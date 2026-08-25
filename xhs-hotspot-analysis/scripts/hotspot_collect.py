#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""热点采集脚本：把用户的品类筛选条件翻译成 Spider_XHS 搜索参数，抓回候选爆文。

用法（建议通过 Claude Code skill 调用，也可单独运行）：

    python hotspot_collect.py --query "AI工具" --count 30 \
        --sort popularity --days 7 --min-likes 500 --min-comments 50 \
        --cookies "...完整PC Cookie..."

输出：data/<YYYY-MM-DD>-<关键词>/sources.jsonl
每行一条候选爆文，统一字段（标题/正文/互动/标签/时间/IP/URL）。
详情与评论在 --detail 开启时逐条补齐（网络慢，默认关）。

说明：本脚本不实现任何反爬对抗，登录态（Cookie）由用户在浏览器里正常登录后
复制得到，仅采集公开内容，仅供学习交流，请遵守小红书用户协议。
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # Spider_XHS 仓库根
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _resolve_cookies(cli_cookies: str) -> str:
    """Cookie 优先级：--cookies > 环境变量 COOKIES > 项目 .env 里的 COOKIES。"""
    if cli_cookies.strip():
        return cli_cookies.strip()
    env_cookies = os.environ.get("COOKIES", "").strip()
    if env_cookies:
        return env_cookies
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        try:
            from dotenv import dotenv_values
            return (dotenv_values(env_file).get("COOKIES") or "").strip()
        except Exception:
            pass
    return ""

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth

SORT_MAP = {"general": 0, "latest": 1, "popularity": 2, "comment": 3, "collect": 4}
DAYS_MAP = {"day": 1, "week": 2, "half_year": 3}
NOTE_TYPE_MAP = {"all": 0, "video": 1, "note": 2}

ENGAGEMENT_KEY = "engagement"
SUPPORTED_METRICS = {"liked_count", "collected_count", "comment_count", "share_count", "engagement"}


def parse_metric(expr: str):
    """解析形如 'liked_count>=500' 的指标门槛，返回 (字段, 比较符, 数值)。"""
    m = re.fullmatch(r"\s*([a-z_]+)\s*(>=|<=|>|<|==)\s*(\d+)\s*", expr, flags=re.IGNORECASE)
    if not m:
        raise ValueError(
            f"无法解析门槛 '{expr}'，格式应为 字段 比较符 数值，如 liked_count>=500 或 engagement>=1000"
        )
    field, op, num = m.group(1).lower(), m.group(2), int(m.group(3))
    if field not in SUPPORTED_METRICS:
        raise ValueError(f"不支持的指标字段 '{field}'，可选：{', '.join(sorted(SUPPORTED_METRICS))}")
    return field, op, num


def parse_filters(raw: str | None) -> list:
    """把逗号分隔的门槛串解析成规则列表。"""
    if not raw:
        return []
    return [parse_metric(part) for part in raw.split(",") if part.strip()]


def norm_int(value) -> int:
    """把 '1.2万' / '3.4k' / 123 归一成 int，无法解析返回 0。"""
    if isinstance(value, int):
        return value
    if not value:
        return 0
    text = str(value).strip()
    m = re.fullmatch(r"([\d.]+)\s*(万|w|k)?", text, flags=re.IGNORECASE)
    if not m:
        return 0
    number = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit == "万":
        number *= 10000
    elif unit == "w":
        number *= 10000
    elif unit == "k":
        number *= 1000
    return int(number)


def make_engine(notes: list[dict]) -> dict:
    """把互动指标拼成可写表达式，避免 eval 一个未知用户字符串。"""
    def _value(note: dict, field: str) -> int:
        if field == ENGAGEMENT_KEY:
            return (
                note.get("liked_count", 0)
                + note.get("collected_count", 0)
                + note.get("comment_count", 0)
                + note.get("share_count", 0)
            )
        return note.get(field, 0)

    def engine(note: dict, field: str, op: str, num: int) -> bool:
        value = _value(note, field)
        if op == ">=":
            return value >= num
        if op == "<=":
            return value <= num
        if op == ">":
            return value > num
        if op == "<":
            return value < num
        if op == "==":
            return value == num
        return False

    return engine


def build_config(args) -> dict:
    """把命令行参数翻译成底层接口参数。"""
    sort_choice = SORT_MAP[args.sort]
    time_choice = DAYS_MAP[args.days]
    note_type = NOTE_TYPE_MAP[args.note_type]
    detail = bool(args.detail) and not args.no_detail
    config = {
        "query": args.query,
        "require_num": args.count,
        "sort_type_choice": sort_choice,
        "note_type": note_type,
        "note_time": time_choice,
        "geo": "",
        "detail": detail,
        "detail_count": args.detail_count,
        "comments_count": args.comments_count,
        "max_results": args.max_results,
    }
    if args.exclude:
        config["exclude_words"] = [word.strip() for word in args.exclude.split(",") if word.strip()]
    return config


def normalize_note(raw: dict) -> dict:
    """把搜索返回的原始笔记卡片归一化成统一字段。

    搜索 item 结构：{id, model_type, note_card, xsec_token}
    note_card 内：{user, interact_info, cover, image_list, display_title, ...}
    """
    note_card = raw.get("note_card", raw)
    note_id = raw.get("id") or note_card.get("note_id") or ""
    interact = note_card.get("interact_info", {}) or {}
    user = note_card.get("user", {}) or {}
    return {
        "note_id": note_id,
        "url": f"https://www.xiaohongshu.com/explore/{note_id}",
        "title": note_card.get("display_title") or note_card.get("title") or "",
        "desc": note_card.get("desc") or note_card.get("title") or "",
        "type": note_card.get("type", ""),
        "liked_count": norm_int(interact.get("liked_count", 0)),
        "collected_count": norm_int(interact.get("collected_count", 0)),
        "comment_count": norm_int(interact.get("comment_count", 0)),
        "share_count": norm_int(interact.get("shared_count", 0)),
        "user": user.get("nickname", ""),
        "user_id": user.get("user_id", ""),
        "tags": _extract_topics(note_card),
        "upload_time": note_card.get("upload_time", ""),
        "time_desc": note_card.get("time_desc", ""),
        "ip_location": note_card.get("ip_location", ""),
        "xsec_token": raw.get("xsec_token") or user.get("xsec_token", ""),
        "xsec_source": raw.get("xsec_source", ""),
        "image_count": len(note_card.get("image_list", []) or []),
    }


def _extract_topics(note_card: dict) -> list[str]:
    topics: list[str] = []
    tags = note_card.get("tags", []) or []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str):
                topics.append(tag.lstrip("#"))
            elif isinstance(tag, dict):
                name = tag.get("name") or tag.get("tag") or tag.get("text")
                if name:
                    topics.append(str(name).lstrip("#"))
    return topics


def short_title(title: str, limit: int = 20) -> str:
    return title if len(title) <= limit else title[:limit] + "…"


def log(msg: str) -> None:
    print(f"[hotspot] {msg}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="抓取某品类/关键词下的小红书热点候选笔记，按用户条件筛选",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--query", required=True, help="品类/关键词，如 'AI工具'")
    parser.add_argument("--count", type=int, default=30, help="抓取数量")
    parser.add_argument(
        "--sort",
        choices=list(SORT_MAP),
        default="popularity",
        help="排序：general综合 / latest最新 / popularity最多点赞 / comment最多评论 / collect最多收藏",
    )
    parser.add_argument(
        "--days",
        choices=list(DAYS_MAP),
        default="week",
        help="时间范围：day一天内 / week一周内 / half_year半年内",
    )
    parser.add_argument(
        "--note-type",
        choices=list(NOTE_TYPE_MAP),
        default="all",
        help="笔记类型：all不限 / video视频 / note图文",
    )
    parser.add_argument(
        "--min",
        dest="filters",
        default="",
        help="互动门槛，逗号分隔，如 'liked_count>=500,collected_count>=100'，字段可选 "
        f"{', '.join(sorted(SUPPORTED_METRICS))}",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="标题/正文中出现的排除词，逗号分隔（广告、引流等你想过滤的内容）",
    )
    parser.add_argument(
        "--detail", action="store_true", help="对 Top N 逐条补齐详情与评论（较慢）"
    )
    parser.add_argument("--no-detail", action="store_true", help="强制不抓详情（默认不抓）")
    parser.add_argument("--detail-count", type=int, default=10, help="补齐详情的笔记条数")
    parser.add_argument("--comments-count", type=int, default=5, help="每条笔记保留的一级评论数")
    parser.add_argument("--max-results", type=int, default=20, help="筛选后最多保留的条数")
    parser.add_argument(
        "--cookies",
        default="",
        help="完整 PC Cookie（含 a1 与 web_session）。不传则从 COOKIES 环境变量读取",
    )
    args = parser.parse_args()

    config = build_config(args)
    filters = parse_filters(args.filters)
    engine = make_engine([])

    try:
        auth = XHSPcAuth.from_cookie(_resolve_cookies(args.cookies))
        api = XHS_Apis(auth).bootstrap()
    except Exception as exc:
        print(f"[hotspot] ❌ 登录态无效或缺少 Cookie：{exc}", file=sys.stderr)
        print(
            "[hotspot]    请在浏览器登录 xiaohongshu.com 后，把完整 Cookie（含 a1 与 web_session）"
            "通过 --cookies 或环境变量 COOKIES 传入。",
            file=sys.stderr,
        )
        return 2

    out_dir = Path("data") / f"{datetime.now():%Y-%m-%d}-{args.query}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "sources.jsonl"

    # 1) 搜索
    log(f"搜索「{config['query']}」 count={config['require_num']} sort={args.sort} days={args.days}")
    success, msg, raw_notes = api.search_some_note(
        query=config["query"],
        require_num=config["require_num"],
        sort_type_choice=config["sort_type_choice"],
        note_type=config["note_type"],
        note_time=config["note_time"],
        geo=config["geo"],
    )
    if not success:
        print(f"[hotspot] ❌ 搜索失败：{msg}", file=sys.stderr)
        return 1
    if not raw_notes:
        print("[hotspot] ⚠️ 搜索无结果", file=sys.stderr)
        return 1
    log(f"搜索返回 {len(raw_notes)} 条")

    notes = [normalize_note(item) for item in raw_notes]

    # 2) 本地筛选（排除词 + 互动门槛）
    before = len(notes)
    if config.get("exclude_words"):
        words = config["exclude_words"]
        notes = [
            n
            for n in notes
            if not any(w.lower() in (n["title"] + n["desc"]).lower() for w in words)
        ]
        log(f"排除词过滤：{before} -> {len(notes)}")
    before = len(notes)
    if filters:
        notes = [n for n in notes if all(engine(n, f, op, num) for f, op, num in filters)]
        log(f"互动门槛过滤：{before} -> {len(notes)}")

    notes = notes[: config["max_results"]]
    log(f"最终保留 {len(notes)} 条")

    # 3) 评论 + 详情（可选）。评论是"为什么爆"的直接证据，优先抓。
    if config["detail"]:
        for idx, note in enumerate(notes[: config["detail_count"]], start=1):
            log(f"补齐 {idx}/{min(config['detail_count'], len(notes))}: {short_title(note['title'])}")
            if note["xsec_token"]:
                try:
                    ok, msg, comments = api.get_note_all_out_comment(
                        note["note_id"], note["xsec_token"]
                    )
                    if ok:
                        note["comments"] = [
                            {
                                "content": c.get("content", ""),
                                "like_count": norm_int(c.get("like_count", 0)),
                                "nickname": (c.get("user_info", {}) or {}).get("nickname", ""),
                            }
                            for c in comments[: config["comments_count"]]
                        ]
                    else:
                        note["comment_error"] = msg
                except Exception as exc:
                    note["comment_error"] = str(exc)
            else:
                note["comment_error"] = "无 xsec_token，跳过评论"
            note_url = note["url"]
            # 详情接口需带 xsec_token 的完整 URL，否则被风控
            if note.get("xsec_token"):
                note_url = (
                    f"https://www.xiaohongshu.com/explore/{note['note_id']}"
                    f"?xsec_token={note['xsec_token']}&xsec_source=pc_search"
                )
            try:
                ok, msg, detail = api.get_note_info(note_url)
                if ok:
                    note["detail"] = _extract_detail(detail)
                else:
                    note["detail_error"] = msg
            except Exception as exc:
                note["detail_error"] = str(exc)
            time.sleep(0.5)

    with out_file.open("w", encoding="utf-8") as fh:
        for note in notes:
            fh.write(json.dumps(note, ensure_ascii=False) + "\n")

    log(f"✅ 完成：{out_file}（{len(notes)} 条）")
    return 0


def _extract_detail(detail: dict) -> dict:
    """从 get_note_info 返回里提取对爆因分析有用的字段，尽量容错。

    注意：详情接口可能被风控（items 为空、返回'当前笔记暂时无法浏览'），
    此时返回 {detail_unavailable: True}，让下游分析知道正文没拿到、不要脑补。
    """
    items = (detail.get("data") or {}).get("items") or []
    if not items:
        return {"detail_unavailable": True, "reason": (detail.get("msg") or "详情接口未返回内容")}
    result: dict = {}
    try:
        note = items[0]
        card = note.get("note_card", note)
        result["title"] = card.get("title", "")
        result["desc"] = card.get("desc", "")
        result["type"] = card.get("type", "")
        result["liked_count"] = norm_int(card.get("interact_info", {}).get("liked_count", 0))
        result["collected_count"] = norm_int(card.get("interact_info", {}).get("collected_count", 0))
        result["comment_count"] = norm_int(card.get("interact_info", {}).get("comment_count", 0))
        result["share_count"] = norm_int(card.get("interact_info", {}).get("share_count", 0))
        result["image_count"] = len(card.get("image_list", []) or [])
        result["ip_location"] = card.get("ip_location", "")
        result["upload_time"] = card.get("upload_time", "")
        result["topics"] = _extract_topics(card)
        video = card.get("video", {})
        result["video_cover"] = video.get("cover", {}).get("url_default", "")
        result["has_video"] = bool(video)
    except Exception:
        result["detail_error"] = "解析失败"
    return result


if __name__ == "__main__":
    sys.exit(main())

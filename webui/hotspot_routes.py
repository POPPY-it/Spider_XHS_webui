# encoding: utf-8
"""热点分析：WebUI 端采集 + 详情 + LLM 分析。

对应 WebUI「热点分析」栏目：
  1. 热点采集：按筛选条件（品类/条数/排序/时间/互动门槛/排除词）抓候选爆文，
     复用 tasks 任务机制，结果存 data/hotspot/<task_id>/sources.jsonl。
  2. 笔记详情：点标题进抽屉，复用 Data_Spider().spider_note 拉正文/评论。
  3. LLM 分析：把 sources.jsonl 交给配置的大模型，产出 analysis.md。
"""

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from webui import tasks
from webui.tasks import AUTH_SEM, _log

router = APIRouter(prefix="/api/hotspot", tags=["hotspot"])

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOTSPOT_ROOT = PROJECT_ROOT / "data" / "hotspot"
ANALYZE_SCRIPT = PROJECT_ROOT / "xhs-hotspot-analysis" / "scripts" / "hotspot_analyze.py"

# LLM 分析只允许一个在跑
_ANALYZE_LOCK = threading.Lock()

SORT_MAP = {"general": 0, "latest": 1, "popularity": 2, "comment": 3, "collect": 4}
DAYS_MAP = {"day": 1, "week": 2, "half_year": 3}
NOTE_TYPE_MAP = {"all": 0, "video": 1, "note": 2}
SUPPORTED_METRICS = {"liked_count", "collected_count", "comment_count", "share_count", "engagement"}


def _json(data: dict, status: int = 200):
    return JSONResponse(content=data, status_code=status)


# ---------------------------------------------------------------------------
# 采集（worker 由 tasks.start_task("hotspot") 调用）
# ---------------------------------------------------------------------------


def _norm_int(value) -> int:
    if isinstance(value, int):
        return value
    if not value:
        return 0
    m = re.fullmatch(r"([\d.]+)\s*(万|w|k)?", str(value).strip(), flags=re.IGNORECASE)
    if not m:
        return 0
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("万", "w"):
        num *= 10000
    elif unit == "k":
        num *= 1000
    return int(num)


def _extract_topics(note_card: dict) -> list[str]:
    topics = []
    for tag in note_card.get("tags", []) or []:
        if isinstance(tag, str):
            topics.append(tag.lstrip("#"))
        elif isinstance(tag, dict):
            name = tag.get("name") or tag.get("tag") or tag.get("text")
            if name:
                topics.append(str(name).lstrip("#"))
    return topics


def _normalize_note(raw: dict) -> dict:
    """搜索 item → 统一字段（与 hotspot_collect.py 保持一致）。"""
    note_card = raw.get("note_card", raw)
    note_id = raw.get("id") or note_card.get("note_id") or ""
    interact = note_card.get("interact_info", {}) or {}
    user = note_card.get("user", {}) or {}
    return {
        "note_id": note_id,
        "url": f"https://www.xiaohongshu.com/explore/{note_id}",
        "title": note_card.get("display_title") or note_card.get("title") or "",
        "desc": note_card.get("desc") or "",
        "type": note_card.get("type", ""),
        "liked_count": _norm_int(interact.get("liked_count")),
        "collected_count": _norm_int(interact.get("collected_count")),
        "comment_count": _norm_int(interact.get("comment_count")),
        "share_count": _norm_int(interact.get("shared_count")),
        "user": user.get("nickname", ""),
        "user_id": user.get("user_id", ""),
        "tags": _extract_topics(note_card),
        "upload_time": note_card.get("upload_time", ""),
        "time_desc": note_card.get("time_desc", ""),
        "ip_location": note_card.get("ip_location", ""),
        "xsec_token": raw.get("xsec_token") or user.get("xsec_token", ""),
        "image_count": len(note_card.get("image_list", []) or []),
    }


def _parse_metric(expr: str):
    m = re.fullmatch(r"\s*([a-z_]+)\s*(>=|<=|>|<|==)\s*(\d+)\s*", expr, flags=re.IGNORECASE)
    if not m:
        raise ValueError(f"无法解析门槛 '{expr}'，格式应为 字段 比较符 数值")
    field, op, num = m.group(1).lower(), m.group(2), int(m.group(3))
    if field not in SUPPORTED_METRICS:
        raise ValueError(f"不支持的指标 '{field}'，可选：{', '.join(sorted(SUPPORTED_METRICS))}")
    return field, op, num


def _metric_value(n: dict, field: str) -> int:
    if field == "engagement":
        return n["liked_count"] + n["collected_count"] + n["comment_count"] + n["share_count"]
    return n.get(field, 0)


def _apply_filters(notes: list[dict], req: dict) -> list[dict]:
    exclude = [w for w in (req.get("exclude_words") or []) if str(w).strip()]
    if exclude:
        notes = [
            n for n in notes
            if not any(w.lower() in (n["title"] + n["desc"]).lower() for w in exclude)
        ]
    min_filters = [str(e).strip() for e in (req.get("min_filters") or []) if str(e).strip()]
    if min_filters:
        rules = [_parse_metric(e) for e in min_filters]
        for n in notes:
            n["_pass"] = True
        for field, op, num in rules:
            for n in notes:
                if n.get("_pass"):
                    v = _metric_value(n, field)
                    ok = {
                        ">=": v >= num, "<=": v <= num, ">": v > num, "<": v < num, "==": v == num,
                    }[op]
                    if not ok:
                        n["_pass"] = False
        notes = [n for n in notes if n.pop("_pass", True)]
    return notes


def _split_queries(query: str) -> list:
    """把多关键词字符串拆成词列表（支持中英文逗号/换行）。"""
    return [q.strip() for q in re.split(r"[,，\n]", query or "") if q.strip()]


def _fetch_author_fans(api, cands: list, log, cap: int = 50) -> None:
    """为候选的唯一作者取粉丝数（best-effort），写回 fans 字段。"""
    targets, seen = [], set()
    for c in cands:
        uid = c.get("user_id") or ""
        if uid and uid not in seen:
            seen.add(uid)
            targets.append(uid)
        if len(targets) >= cap:
            break
    fans_map = {}
    for uid in targets:
        try:
            ok, msg, res = api.get_user_info(uid)
            if ok and res:
                interactions = (res.get("data") or {}).get("interactions") or []
                if len(interactions) > 1:
                    fans_map[uid] = _norm_int(interactions[1].get("count"))
        except Exception:
            pass
        time.sleep(0.5)
    for c in cands:
        uid = c.get("user_id") or ""
        if uid in fans_map:
            c["fans"] = fans_map[uid]


def _score_candidates(cands: list, lowfan: bool) -> list:
    """按互动数或互动/粉丝比排序，并打标低粉爆款（is_lowfan）。"""
    for c in cands:
        interact = (c.get("liked_count", 0) + c.get("collected_count", 0)
                    + c.get("comment_count", 0) + c.get("share_count", 0))
        c["_interact"] = interact
        fans = c.get("fans") or 0
        c["ratio"] = round(interact / max(fans, 1), 2) if fans else None
        c["is_lowfan"] = bool(fans and fans < 10000 and interact >= 500 and (c["ratio"] or 0) >= 1.0)
    if lowfan:
        cands.sort(key=lambda c: (1 if c.get("is_lowfan") else 0, c.get("ratio") or 0, c.get("_interact")), reverse=True)
    else:
        cands.sort(key=lambda c: c.get("_interact", 0), reverse=True)
    for c in cands:
        c.pop("_interact", None)
    return cands


def _hotspot_worker(task_id: str, req: dict) -> None:
    """热点采集后台任务：搜索 + 过滤 + 存 sources.jsonl。"""
    auth = None
    try:
        from webui.login_bridge import _build_authed_api

        auth, api = _build_authed_api()
        queries = _split_queries(req.get("query", ""))
        if not queries:
            raise RuntimeError("品类/关键词不能为空（多个词用逗号分隔）")
        count = int(req.get("count", 30) or 30)
        sort = SORT_MAP.get(req.get("sort", "popularity"), 2)
        days = DAYS_MAP.get(req.get("days", "week"), 2)
        note_type = NOTE_TYPE_MAP.get(req.get("note_type", "all"), 0)
        max_results = int(req.get("max_results", 20) or 20)
        lowfan = bool(req.get("lowfan", True))

        # 多词下钻：逐词搜索，聚合去重
        all_notes = []
        seen_ids = set()
        for qi, query in enumerate(queries, 1):
            _log(task_id, f"[{qi}/{len(queries)}] 搜索「{query}」 目标 {count} 条…")
            ok, msg, raw_notes = api.search_some_note(
                query=query,
                require_num=count,
                sort_type_choice=sort,
                note_type=note_type,
                note_time=days,
            )
            if not ok:
                _log(task_id, f"  搜索「{query}」失败：{msg}")
                continue
            for item in raw_notes or []:
                n = _normalize_note(item)
                if n["note_id"] and n["note_id"] not in seen_ids:
                    seen_ids.add(n["note_id"])
                    n["keyword"] = query
                    all_notes.append(n)
        if not all_notes:
            raise RuntimeError("搜索无结果，请换词或放宽条件")
        _log(task_id, f"共聚合 {len(all_notes)} 条（{len(queries)} 个词，去重后），开始本地筛选…")

        notes = _apply_filters(all_notes, req)
        if not notes:
            raise RuntimeError("筛选后无结果，请放宽条件")

        # 低粉爆款：取作者粉丝，按互动/粉丝比排序
        if lowfan:
            _log(task_id, "获取作者粉丝数，识别低粉爆款…")
            _fetch_author_fans(api, notes, _log)
        notes = _score_candidates(notes, lowfan)[:max_results]
        if not notes:
            raise RuntimeError("排序后无结果")

        # 爆款潜力评分卡：特征工程 + 批次百分位 → 可解释的爆款分
        from webui.viral_score import score_notes
        score_notes(notes)
        _log(task_id, f"已计算爆款潜力分（{len(notes)} 条）")

        # 抓评论 + 正文：用带 xsec_token 的完整 URL 拉详情（裸 ID URL 会被风控）
        comments_limit = int(req.get("comments_count", 5) or 5)
        _log(task_id, f"抓取正文与评论区（每条最多 {comments_limit} 条评论）…")
        for idx, n in enumerate(notes, start=1):
            token = n.get("xsec_token") or ""
            if not token:
                n["comment_error"] = "缺少 xsec_token"
                continue
            # 正文：详情接口需带 xsec_token 的完整 URL，否则被风控
            try:
                detail_url = f"https://www.xiaohongshu.com/explore/{n['note_id']}?xsec_token={token}&xsec_source=pc_search"
                ok3, msg3, detail = api.get_note_info(detail_url)
                if ok3:
                    d_items = ((detail or {}).get("data") or {}).get("items") or []
                    if d_items:
                        d_card = d_items[0].get("note_card", d_items[0])
                        desc = d_card.get("desc", "") or ""
                        if desc:
                            n["detail"] = {"desc": desc}
                else:
                    n["detail_error"] = msg3
            except Exception as exc:
                n["detail_error"] = str(exc)
            try:
                ok2, msg2, raw = api.get_note_all_out_comment(n["note_id"], token)
                if ok2:
                    n["comments"] = [
                        {
                            "content": c.get("content", ""),
                            "like_count": _norm_int(c.get("like_count")),
                            "nickname": (c.get("user_info", {}) or {}).get("nickname", ""),
                        }
                        for c in raw[:comments_limit]
                    ]
                else:
                    n["comment_error"] = msg2
            except Exception as exc:
                n["comment_error"] = str(exc)
            time.sleep(0.3)
        _log(task_id, f"正文与评论抓取完成")

        out_dir = HOTSPOT_ROOT / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "sources.jsonl"
        with out_file.open("w", encoding="utf-8") as fh:
            for n in notes:
                fh.write(json.dumps(n, ensure_ascii=False) + "\n")
        # 记录品类等元信息，供历史 tab 展示
        with (out_dir / "meta.json").open("w", encoding="utf-8") as fh:
            json.dump({
                "query": "，".join(queries),
                "queries": queries,
                "count": len(notes),
                "sort": req.get("sort", "popularity"),
                "days": req.get("days", "week"),
                "target_category": (req.get("target_category") or "").strip(),
                "lowfan": lowfan,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, fh, ensure_ascii=False, indent=2)

        _log(task_id, f"完成：{len(notes)} 条已保存")
        _finish(task_id, "done", result={"query": "，".join(queries), "notes": len(notes)})
    except Exception as exc:
        _log(task_id, f"任务失败：{exc}")
        _finish(task_id, "error", error=str(exc))
    finally:
        if auth is not None:
            try:
                auth.close()
            except Exception:
                pass


def _finish(task_id, status, result=None, error=""):
    tasks._finish(task_id, status, result=result, error=error)


def _notes_from_dir(out_dir: Path) -> list[dict]:
    f = out_dir / "sources.jsonl"
    if not f.exists():
        return []
    notes = []
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                notes.append(json.loads(line))
    return notes


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("/run")
def hotspot_run(payload: dict):
    query = (payload or {}).get("query") or ""
    if not str(query).strip():
        return _json({"success": False, "error": "请输入品类/关键词"}, 400)
    try:
        task_id = tasks.start_task("hotspot", payload or {})
    except RuntimeError as exc:
        return _json(
            {"success": False, "error": "已有任务正在运行，请稍后再试", "running_task_id": str(exc)},
            409,
        )
    return _json({"success": True, "task_id": task_id})


@router.get("/tasks/{task_id}")
def hotspot_task(task_id: str):
    task = tasks.get_task(task_id)
    if not task:
        return _json({"success": False, "error": "任务不存在"}, 404)
    return _json({"success": True, "task": task})


@router.get("/tasks/{task_id}/notes")
def hotspot_notes(task_id: str):
    out_dir = HOTSPOT_ROOT / task_id
    notes = _notes_from_dir(out_dir)
    return _json({"success": True, "notes": notes, "count": len(notes)})


@router.get("/notes/{note_id}")
def hotspot_note_detail(note_id: str, task_id: str = "", with_comments: int = Query(1)):
    """单条笔记详情：点标题进抽屉时调用。

    优先用 Data_Spider().spider_note 拉完整详情；若详情接口被风控（可能抛
    KeyError/IndexError 等），降级为 sources.jsonl 里的基础信息，并单独抓评论。
    """
    from spider.spider import Data_Spider

    url = f"https://www.xiaohongshu.com/explore/{note_id}"
    basic = {}
    if task_id:
        for n in _notes_from_dir(HOTSPOT_ROOT / task_id):
            if n.get("note_id") == note_id:
                basic = n
                break
    result = {"note": basic, "detail_unavailable": False}
    # 详情接口需带 xsec_token 的完整 URL，否则被风控
    token = (basic or {}).get("xsec_token") or ""
    if token:
        url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_search"
    try:
        with AUTH_SEM:
            from webui.login_bridge import _build_authed_api

            auth, api = _build_authed_api()
            try:
                success, msg, info = Data_Spider(auth).spider_note(url)
                # 评论与详情用同一会话抓（会话关闭后无法再请求）
                if with_comments:
                    xsec = token or basic.get("xsec_token") or ""
                    if xsec:
                        ok2, msg2, raw = api.get_note_all_out_comment(note_id, xsec)
                        if ok2:
                            comments = []
                            for c in raw:
                                try:
                                    comments.append({
                                        "content": c.get("content", ""),
                                        "like_count": _norm_int(c.get("like_count")),
                                        "nickname": (c.get("user_info", {}) or {}).get("nickname", ""),
                                    })
                                except Exception:
                                    continue
                            result["comments"] = comments[:30]
                        else:
                            result["comment_error"] = msg2
                    else:
                        result["comment_error"] = "缺少 xsec_token，无法抓评论"
            finally:
                auth.close()
        if success and info:
            result["note"] = info
        else:
            # 详情被风控时降级：用基础信息，不报硬错误
            if not basic:
                return _json({"success": False, "error": str(msg) or "获取笔记失败"}, 400)
            result["detail_unavailable"] = True
            result["detail_error"] = str(msg)
        return _json({"success": True, **result})
    except Exception as exc:
        if basic:
            return _json({"success": True, **result, "detail_error": str(exc)})
        return _json({"success": False, "error": str(exc)}, 400)


@router.post("/tasks/{task_id}/analyze")
def hotspot_analyze(task_id: str, payload: dict = None):
    """触发 LLM 分析 sources.jsonl → analysis.md（后台线程）。"""
    out_dir = HOTSPOT_ROOT / task_id
    if not _notes_from_dir(out_dir):
        return _json({"success": False, "error": "该任务没有已采集的笔记"}, 400)
    if not _ANALYZE_LOCK.acquire(blocking=False):
        return _json({"success": False, "error": "已有分析任务在运行"}, 409)

    payload = payload or {}
    provider = (payload.get("provider") or "").strip()
    context = (payload.get("context") or "").strip()
    target_category = (payload.get("target_category") or "").strip()
    threading.Thread(target=_analyze_worker, args=(task_id, provider, context, target_category), daemon=True).start()
    return _json({"success": True, "message": "分析已开始，完成后可查看报告"})


def _analyze_worker(task_id: str, provider: str, context: str, target_category: str = "") -> None:
    """后台执行 LLM 分析，调用 hotspot_analyze.py。"""
    try:
        sources = HOTSPOT_ROOT / task_id / "sources.jsonl"
        cmd = [sys.executable, str(ANALYZE_SCRIPT), "--sources", str(sources)]
        if provider:
            cmd += ["--provider", provider]
        if context:
            cmd += ["--context", context]
        if target_category:
            cmd += ["--target-category", target_category]
        _log(task_id, f"开始 AI 分析（provider={provider or '默认'}）…")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT))
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "分析失败")
        _log(task_id, "AI 分析完成，报告已生成")
    except Exception as exc:
        _log(task_id, f"分析失败：{exc}")
    finally:
        _ANALYZE_LOCK.release()


@router.get("/tasks/{task_id}/analysis")
def hotspot_analysis_result(task_id: str):
    out_dir = HOTSPOT_ROOT / task_id
    md = out_dir / "analysis.md"
    if not md.exists():
        return _json({"success": True, "ready": False})
    return _json({"success": True, "ready": True, "content": md.read_text(encoding="utf-8")})

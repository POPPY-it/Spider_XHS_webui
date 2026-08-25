# encoding: utf-8
"""数据仪表盘聚合：笔记 / 评论 / 达人数据的统计汇总（纯函数，无 FastAPI）。"""

import glob
import json
import os
import re
from collections import Counter
from datetime import datetime

DATAS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "datas"))
EXPORT_DIR = os.path.join(DATAS_DIR, "exports")
EXCEL_DIR = os.path.join(DATAS_DIR, "excel_datas")

# 评论行格式：- **用户名**（YYYY-MM-DD HH:MM:SS，赞 N）内容（楼中楼缩进 2 空格）
_COMMENT_PAT = re.compile(
    r'^- \*\*(.+?)\*\*（(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})，赞 (\d+)）(.*)$'
)


def _parse_dt(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _month_key(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _fill_months(pairs: list, start: datetime, end: datetime) -> list:
    """把 {(year,month): count} 展开成连续月份列表（补 0）。"""
    out = []
    ym = (start.year, start.month)
    end_ym = (end.year, end.month)
    while ym <= end_ym:
        out.append({"month": f"{ym[0]:04d}-{ym[1]:02d}", "count": pairs.get(ym, 0)})
        if ym[1] == 12:
            ym = (ym[0] + 1, 1)
        else:
            ym = (ym[0], ym[1] + 1)
    return out


def _load_notes(jsonl_path: str) -> list:
    """读 notes.jsonl，返回笔记 dict 列表。"""
    notes = []
    if not os.path.isfile(jsonl_path):
        return notes
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except ValueError:
                continue
    return notes


def _iter_comments(collection_path: str):
    """遍历集合内所有 note.md，产出 (datetime, username)。"""
    for md_path in glob.glob(os.path.join(collection_path, "*", "*", "note.md")):
        in_comments = False
        try:
            f = open(md_path, encoding="utf-8")
        except OSError:
            continue
        with f:
            for line in f:
                s = line.strip()
                if s == "## 评论":
                    in_comments = True
                    continue
                if not in_comments or not s.startswith("- **"):
                    continue
                m = _COMMENT_PAT.match(s)
                if not m:
                    continue
                user, y, mo, d, h, mi, sec = m.groups()[:7]
                dt = _parse_dt(f"{y}-{mo}-{d} {h}:{mi}:{sec}")
                if dt:
                    yield dt, user


def _load_newest_talents() -> list:
    """读最新的蒲公英达人完整数据 JSON。"""
    files = glob.glob(os.path.join(EXCEL_DIR, "蒲公英达人_*_完整数据.json"))
    if not files:
        return []
    files.sort(key=os.path.getmtime, reverse=True)
    try:
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _talent_bands(talents: list) -> dict:
    gender = Counter()
    location = Counter()
    fans = Counter()
    price = Counter()
    for t in talents:
        g = (t.get("gender") or "").strip()
        if g:
            gender[g] += 1
        loc = (t.get("location") or "").strip()
        if loc:
            location[loc] += 1
        try:
            fans_num = int(t.get("fansNum") or 0)
        except (TypeError, ValueError):
            fans_num = 0
        if fans_num < 1000:
            fans["<1千"] += 1
        elif fans_num < 10000:
            fans["1千-1万"] += 1
        elif fans_num < 100000:
            fans["1万-10万"] += 1
        else:
            fans["10万+"] += 1
        try:
            lower = int(t.get("lowerPrice") or 0) / 100.0  # 分 → 元
        except (TypeError, ValueError):
            lower = 0
        if lower < 100:
            price["<100元"] += 1
        elif lower < 500:
            price["100-500元"] += 1
        elif lower < 1000:
            price["500-1000元"] += 1
        else:
            price["1000元+"] += 1
    return {
        "gender": [{"name": k, "value": v} for k, v in gender.items()],
        "location_top": [{"name": k, "value": v} for k, v in location.most_common(10)],
        "fans_bands": [{"name": k, "value": v} for k, v in fans.items()],
        "price_bands": [{"name": k, "value": v} for k, v in price.items()],
    }


def aggregate_export_collection(collection_path: str) -> dict:
    """聚合一个导出集合的笔记/评论数据，返回仪表盘用 dict。"""
    jsonl_path = os.path.join(collection_path, "notes.jsonl")
    notes = _load_notes(jsonl_path)

    kpi = {"note_count": len(notes), "comment_count": 0,
           "total_likes": 0, "total_collects": 0, "total_shares": 0}
    note_trend_pairs = Counter()
    type_dist = Counter()
    interact = []

    for n in notes:
        for key, tkey in (("liked_count", "total_likes"),
                          ("collected_count", "total_collects"),
                          ("share_count", "total_shares")):
            try:
                kpi[tkey] += int(n.get(key) or 0)
            except (TypeError, ValueError):
                pass
        dt = _parse_dt(n.get("upload_time") or "")
        if dt:
            note_trend_pairs[_month_key(dt)] += 1
        type_dist[n.get("type") or "未知"] += 1
        try:
            score = int(n.get("liked_count") or 0) + int(n.get("collected_count") or 0) + int(n.get("comment_count") or 0)
        except (TypeError, ValueError):
            score = 0
        interact.append({
            "title": n.get("title") or "",
            "type": n.get("type") or "",
            "likes": int(n.get("liked_count") or 0),
            "comments": int(n.get("comment_count") or 0),
            "url": n.get("note_url") or "",
            "_score": score,
        })

    # 评论：解析 note.md 全量
    comment_dt_pairs = Counter()
    user_counter = Counter()
    all_comment_dts = []
    for dt, user in _iter_comments(collection_path):
        comment_dt_pairs[_month_key(dt)] += 1
        user_counter[user] += 1
        all_comment_dts.append(dt)
    kpi["comment_count"] = len(all_comment_dts)

    # 时间范围（补连续月份）
    all_note_dts = [_parse_dt(n.get("upload_time") or "") for n in notes]
    all_note_dts = [dt for dt in all_note_dts if dt]
    all_dts = all_note_dts + all_comment_dts
    if all_dts:
        start, end = min(all_dts), max(all_dts)
    else:
        start = end = datetime.now()
    note_trend = _fill_months({(int(m[:4]), int(m[5:])): c for m, c in note_trend_pairs.items()}, start, end)
    comment_trend = _fill_months({(int(m[:4]), int(m[5:])): c for m, c in comment_dt_pairs.items()}, start, end)

    interact.sort(key=lambda x: x.pop("_score", 0), reverse=True)
    top10 = interact[:10]

    return {
        "kpi": kpi,
        "note_trend": note_trend,
        "comment_trend": comment_trend,
        "note_interact_top": top10,
        "user_comment_top": [{"name": k, "value": v} for k, v in user_counter.most_common(10)],
        "note_type_dist": [{"name": k, "value": v} for k, v in type_dist.items()],
        "talent": _talent_bands(_load_newest_talents()),
    }


def resolve_collection(name: str) -> str:
    """把集合名解析为绝对路径，越界（非 exports 下）抛 ValueError。"""
    base = os.path.abspath(EXPORT_DIR)
    real = os.path.abspath(os.path.join(base, name or ""))
    if not real.startswith(base + os.sep):
        raise ValueError("集合名不合法")
    return real


def default_collection() -> str:
    """返回最新导出集合名。"""
    if not os.path.isdir(EXPORT_DIR):
        return ""
    dirs = [d for d in os.listdir(EXPORT_DIR) if os.path.isdir(os.path.join(EXPORT_DIR, d))]
    if not dirs:
        return ""
    return max(dirs, key=lambda d: os.path.getmtime(os.path.join(EXPORT_DIR, d)))

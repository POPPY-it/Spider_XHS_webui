# encoding: utf-8
"""把蒲公英原始导出 JSON（1000 条达人）转换成数据库需要的格式。

输入：datas/excel_datas/蒲公英达人_*.json（完整数据导出）
输出：datas/excel_datas/数据库格式_<时间>.json

输出结构（对齐 SocialCreator / SocialNote 表）：
    {
      "creators": [ {达人映射字段...}, ... ],
      "notes":    [ {笔记映射字段...}, ... ]
    }

达人/笔记字段只保留数据库需要的，其余多余参数丢弃。
"""

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "datas", "excel_datas"))
PLATFORM = "xiaohongshu"
PARSER_VERSION = "2026-07-29.2"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _gender(g):
    if g == "女":
        return "female"
    if g == "男":
        return "male"
    return None


def map_creator(t: dict) -> dict:
    """把蒲公英达人 dict 映射成 SocialCreator 行（只保留数据库字段）。"""
    uid = t.get("userId") or ""
    now = datetime.now().isoformat()
    return {
        "id": uid,                      # 用 platformUserId 作主键
        "platform": PLATFORM,
        "platformUserId": uid,
        "handle": t.get("redId"),
        "nickname": t.get("name") or "",
        "bio": None,
        "gender": _gender(t.get("gender")),
        "ipLocation": t.get("location"),
        "avatarUrl": t.get("headPhoto"),
        "profileUrl": f"https://www.xiaohongshu.com/user/profile/{uid}" if uid else None,
        "fans": _int(t.get("fansNum") or t.get("fansCount") or 0) or None,
        "follows": None,
        "interaction": None,
        "tags": t.get("personalTags") or [],
        "entryMode": "pgy_export",
        "sourceKeywords": [],
        "acquisitionMethods": ["pugongying"],
        # 报价与中位数（蒲公英特色字段，也保留）
        "picturePrice": _int(t.get("picturePrice") or 0) or None,
        "videoPrice": _int(t.get("videoPrice") or 0) or None,
        "median_read": t.get("median_read"),
        "median_interaction": t.get("median_interaction"),
        "median_note": t.get("median_note"),
        "raw": json.dumps(t, ensure_ascii=False, default=str),
        "parserVersion": PARSER_VERSION,
        "firstSeenAt": now,
        "lastSeenAt": now,
    }


def map_note(creator: dict, n: dict) -> dict:
    """把蒲公英笔记 dict 映射成 SocialNote 行。"""
    note_id = n.get("noteId") or ""
    now = datetime.now().isoformat()
    full_detail = n.get("full_detail") or {}
    published_at = None
    if full_detail.get("createTime"):
        try:
            published_at = datetime.fromtimestamp(int(full_detail["createTime"]) / 1000).isoformat()
        except Exception:
            published_at = None
    return {
        "id": note_id,
        "platform": PLATFORM,
        "platformNoteId": note_id,
        "platformUserId": creator.get("platformUserId"),
        "creatorId": creator.get("platformUserId"),
        "authorNickname": creator.get("nickname"),
        "type": "video" if _int(n.get("type")) == 2 else "image",
        "title": n.get("title"),
        "body": full_detail.get("content"),
        "publishedAt": published_at,
        "likedCount": _int(n.get("likeNum") or 0) or None,
        "collectedCount": _int(n.get("collectNum") or 0) or None,
        "commentCount": _int(n.get("interactionNum") or 0) or None,
        "shareCount": None,
        "countsRaw": json.dumps({
            "readNum": n.get("readNum"),
            "impNum": n.get("impNum"),
            "likeNum": n.get("likeNum"),
            "collectNum": n.get("collectNum"),
            "interactionNum": n.get("interactionNum"),
        }, ensure_ascii=False, default=str),
        "countPrecision": "exact",
        "tags": [],
        "noteUrl": full_detail.get("noteLink"),
        "videoUrls": [str(full_detail["videoInfo"].get("videoKey"))] if full_detail.get("videoInfo") else [],
        "videoDuration": None,
        "atUsers": None,
        "sourceKeywords": [],
        "acquisitionMethods": ["pugongying"],
        "raw": json.dumps(n, ensure_ascii=False, default=str),
        "parserVersion": PARSER_VERSION,
        "firstSeenAt": now,
        "lastSeenAt": now,
    }


def build_db_format(talents: list, on_progress=None) -> dict:
    """纯转换：把蒲公英达人列表转成数据库格式 dict（{creators, notes}），不写文件。"""
    creators = []
    notes = []
    total = len(talents)
    for i, t in enumerate(talents, 1):
        creator = map_creator(t)
        creators.append(creator)
        detail = t.get("detail") or {}
        notes_data = ((detail.get("notes") or {}).get("data") or {})
        for n in notes_data.get("notes") or []:
            notes.append(map_note(creator, n))
        if on_progress:
            on_progress(i, total, t.get("name", ""))
    return {"creators": creators, "notes": notes}


def convert(source_path: str, out_path: str = None, on_progress=None) -> dict:
    """转换主函数：读原始 JSON，生成数据库格式 JSON。"""
    with open(source_path, "r", encoding="utf-8") as f:
        talents = json.load(f)

    data = build_db_format(talents, on_progress=on_progress)
    if out_path is None:
        out_path = os.path.join(BASE_DIR, f"数据库格式_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    return {
        "out_path": out_path,
        "creators": len(data["creators"]),
        "notes": len(data["notes"]),
        "source": source_path,
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        # 默认取最大的完整数据文件
        files = sorted(
            [os.path.join(BASE_DIR, f) for f in os.listdir(BASE_DIR)
             if f.startswith("蒲公英达人_") and f.endswith("_完整数据.json")],
            key=os.path.getsize, reverse=True,
        )
        if not files:
            print("没有找到原始 JSON 文件")
            sys.exit(1)
        src = files[0]
        print(f"自动选择: {os.path.basename(src)} ({os.path.getsize(src)/1024/1024:.1f} MB)")
    result = convert(src)
    print(f"转换完成:")
    print(f"  达人 {result['creators']} 条")
    print(f"  笔记 {result['notes']} 条")
    print(f"  输出: {result['out_path']}")

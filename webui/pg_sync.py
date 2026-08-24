# encoding: utf-8
"""达人数据同步到 PostgreSQL（SocialCreator / SocialNote 表）。

写入逻辑：
- SocialCreator：按 (platform, platformUserId) 去重，已存在则更新，否则插入
- SocialNote：按 (platform, platformNoteId) 去重，已存在则更新，否则插入
- 不抓评论（按用户需求）
"""

import json
import os
import re
import uuid
from datetime import datetime

import psycopg2
import psycopg2.extras

# DATABASE_URL 从 .env 读取（.env 已被 gitignore，不会上传）
DEFAULT_DATABASE_URL = os.getenv("DATABASE_URL", "")

PLATFORM = "xiaohongshu"
PARSER_VERSION = "2026-07-29.2"


def _connect(db_url: str = None):
    if not db_url:
        # 运行时动态加载 .env，确保 DATABASE_URL 生效
        from dotenv import load_dotenv
        load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")), override=True)
        db_url = os.getenv("DATABASE_URL", "")
    url = db_url or DEFAULT_DATABASE_URL
    if not url:
        raise RuntimeError(
            "未配置 DATABASE_URL，请在项目根目录 .env 中添加：DATABASE_URL='postgresql://...'"
        )
    return _connect_from_url(url)


def _connect_from_url(url: str):
    """解析 postgresql://user:pass@host:port/db 形式的 URL，用关键字参数连接。

    URL 里密码等已做 percent-encoding（%25 表示 %），这里统一解码。
    """
    from urllib.parse import unquote, urlparse
    p = urlparse(url)
    kwargs = {
        "host": p.hostname,
        "port": p.port or 5432,
        "user": unquote(p.username) if p.username else None,
        "password": unquote(p.password) if p.password else None,
        "dbname": p.path.lstrip("/"),
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    return psycopg2.connect(**kwargs)


def _now():
    return datetime.now()


def sync_talents_to_db(talents: list, db_url: str = None, on_progress=None) -> dict:
    """把蒲公英原始格式达人列表写入数据库（兼容旧流程）。"""
    conn = _connect(db_url)
    stats = {
        "creators_inserted": 0,
        "creators_updated": 0,
        "notes_inserted": 0,
        "notes_updated": 0,
        "failed": 0,
    }
    try:
        cur = conn.cursor()
        total = len(talents)
        for i, t in enumerate(talents, 1):
            try:
                uid = t.get("userId")
                if not uid:
                    stats["failed"] += 1
                    continue
                # 1) upsert creator
                creator_id, c_op = _upsert_creator(cur, t)
                if c_op == "inserted":
                    stats["creators_inserted"] += 1
                else:
                    stats["creators_updated"] += 1
                # 2) upsert notes（含正文标题，不含评论）
                detail = t.get("detail") or {}
                notes_data = ((detail.get("notes") or {}).get("data") or {})
                note_list = notes_data.get("notes") or []
                # 若导出时笔记为空/缺正文，蒲公英接口偶发空，这里补拉详情
                if not note_list:
                    try:
                        from webui import pgy_talents
                        fresh = pgy_talents.get_talent_detail(uid)
                        fdata = ((fresh.get("notes") or {}).get("data") or {})
                        note_list = fdata.get("notes") or []
                    except Exception:
                        note_list = []
                # 给每篇笔记补拉正文（full_detail）
                full_list = []
                for n in note_list:
                    if not n.get("full_detail"):
                        try:
                            from webui import pgy_talents
                            note_id = n.get("noteId")
                            if note_id:
                                nd = pgy_talents.get_note_full_detail(note_id, with_comments=False)
                                if nd.get("detail"):
                                    n = dict(n)
                                    n["full_detail"] = nd["detail"]
                        except Exception:
                            pass
                    full_list.append(n)
                for n in full_list:
                    op = _upsert_note(cur, creator_id, t, n)
                    if op == "inserted":
                        stats["notes_inserted"] += 1
                    elif op == "updated":
                        stats["notes_updated"] += 1
                conn.commit()
            except Exception:
                conn.rollback()
                stats["failed"] += 1
            if on_progress:
                on_progress(i, total, t.get("name", ""))
    finally:
        conn.close()
    return stats


# 数据库格式（{creators, notes}）的插入列定义
_CREATOR_COLS = [
    "id", "platform", "platformUserId", "handle", "nickname", "bio", "gender",
    "ipLocation", "avatarUrl", "profileUrl", "fans", "follows", "interaction",
    "tags", "entryMode", "sourceKeywords", "acquisitionMethods", "raw",
    "parserVersion", "firstSeenAt", "lastSeenAt",
]
_NOTE_COLS = [
    "id", "platform", "platformNoteId", "platformUserId", "creatorId",
    "authorNickname", "type", "title", "body", "publishedAt", "likedCount",
    "collectedCount", "commentCount", "shareCount", "countsRaw", "countPrecision",
    "tags", "noteUrl", "videoUrls", "atUsers", "sourceKeywords",
    "acquisitionMethods", "raw", "parserVersion", "firstSeenAt", "lastSeenAt",
]


def sync_db_format(db_data: dict, db_url: str = None, on_progress=None) -> dict:
    """把数据库格式数据（{creators, notes}，来自导出的 JSON）写入数据库。

    与 sync_talents_to_db 不同：这里直接接收转换后的字段，不再做格式映射。
    返回 {creators_inserted, creators_updated, notes_inserted, notes_updated, failed}
    """
    creators = db_data.get("creators") or []
    notes = db_data.get("notes") or []
    conn = _connect(db_url)
    stats = {
        "creators_inserted": 0, "creators_updated": 0,
        "notes_inserted": 0, "notes_updated": 0, "failed": 0,
    }
    try:
        cur = conn.cursor()
        total = len(creators)
        for i, c in enumerate(creators, 1):
            try:
                pid = c.get("platformUserId")
                if not pid:
                    stats["failed"] += 1
                    continue
                op = _upsert_creator_db(cur, c)
                if op == "inserted":
                    stats["creators_inserted"] += 1
                else:
                    stats["creators_updated"] += 1
                conn.commit()
            except Exception:
                conn.rollback()
                stats["failed"] += 1
            if on_progress:
                on_progress(i, total, c.get("nickname", ""))
        # 笔记
        total = len(notes)
        for i, n in enumerate(notes, 1):
            try:
                op = _upsert_note_db(cur, n)
                if op == "inserted":
                    stats["notes_inserted"] += 1
                elif op == "updated":
                    stats["notes_updated"] += 1
                conn.commit()
            except Exception:
                conn.rollback()
                stats["failed"] += 1
    finally:
        conn.close()
    return stats


def _exists_creator(cur, platform_user_id) -> bool:
    cur.execute(
        'SELECT "platformUserId" FROM "SocialCreator" WHERE platform=%s AND "platformUserId"=%s',
        (PLATFORM, platform_user_id),
    )
    return cur.fetchone() is not None


def _upsert_creator_db(cur, c: dict) -> str:
    """按数据库格式 upsert SocialCreator（先查存在再更新/插入）。"""
    pid = c.get("platformUserId")
    exists = _exists_creator(cur, pid)
    now = _now()
    if exists:
        cur.execute(
            """UPDATE "SocialCreator" SET
                handle=%s, nickname=%s, bio=%s, gender=%s, "ipLocation"=%s,
                "avatarUrl"=%s, "profileUrl"=%s, fans=%s, tags=%s, raw=%s,
                "parserVersion"=%s, "lastSeenAt"=%s
               WHERE platform=%s AND "platformUserId"=%s""",
            (c.get("handle"), c.get("nickname"), c.get("bio"), c.get("gender"),
             c.get("ipLocation"), c.get("avatarUrl"), c.get("profileUrl"),
             c.get("fans"), c.get("tags") or [], c.get("raw") or "",
             c.get("parserVersion") or PARSER_VERSION, now, PLATFORM, pid),
        )
        return "updated"
    else:
        cur.execute(
            """INSERT INTO "SocialCreator" (%s) VALUES (%s)""" % (
                ", ".join(f'"{c2}"' for c2 in _CREATOR_COLS),
                ", ".join(["%s"] * len(_CREATOR_COLS)),
            ),
            tuple(c.get(c2) for c2 in _CREATOR_COLS),
        )
        return "inserted"


def _upsert_note_db(cur, n: dict) -> None:
    """按数据库格式 upsert SocialNote。"""
    note_id = n.get("platformNoteId")
    if not note_id:
        return
    cur.execute(
        'SELECT "platformNoteId" FROM "SocialNote" WHERE platform=%s AND "platformNoteId"=%s',
        (PLATFORM, note_id),
    )
    exists = cur.fetchone() is not None
    now = _now()
    if exists:
        cur.execute(
            """UPDATE "SocialNote" SET
                title=%s, body=%s, "likedCount"=%s, "collectedCount"=%s,
                "commentCount"=%s, "shareCount"=%s, "countsRaw"=%s, tags=%s,
                "noteUrl"=%s, "videoUrls"=%s, raw=%s, "parserVersion"=%s, "lastSeenAt"=%s
               WHERE platform=%s AND "platformNoteId"=%s""",
            (n.get("title"), n.get("body"), n.get("likedCount"), n.get("collectedCount"),
             n.get("commentCount"), n.get("shareCount"), n.get("countsRaw"),
             n.get("tags") or [], n.get("noteUrl"), n.get("videoUrls") or [],
             n.get("raw") or "", n.get("parserVersion") or PARSER_VERSION, now,
             PLATFORM, note_id),
        )
    else:
        cur.execute(
            """INSERT INTO "SocialNote" (%s) VALUES (%s)""" % (
                ", ".join(f'"{c2}"' for c2 in _NOTE_COLS),
                ", ".join(["%s"] * len(_NOTE_COLS)),
            ),
            tuple(n.get(c2) for c2 in _NOTE_COLS),
        )
        return "inserted"
    return "updated"


def _upsert_creator(cur, t: dict) -> str:
    """插入或更新 SocialCreator，返回 creator id（即 platformUserId）。"""
    uid = t.get("userId")
    platform_user_id = uid
    nickname = t.get("name") or ""
    handle = t.get("redId") or None
    bio = None
    gender = t.get("gender") or None
    if gender == "女":
        gender = "female"
    elif gender == "男":
        gender = "male"
    ip_location = t.get("location") or None
    avatar_url = t.get("headPhoto") or None
    profile_url = f"https://www.xiaohongshu.com/user/profile/{uid}" if uid else None
    fans = int(t.get("fansNum") or t.get("fansCount") or 0) or None
    follows = None
    interaction = None
    tags = t.get("personalTags") or []
    entry_mode = "pgy_export"
    source_keywords = []
    acquisition_methods = ["pugongying"]
    raw = json.dumps(t, ensure_ascii=False, default=str)
    now = _now()

    # 用 platformUserId 判断是否已存在
    cur.execute(
        'SELECT "platformUserId" FROM "SocialCreator" WHERE platform=%s AND "platformUserId"=%s',
        (PLATFORM, platform_user_id),
    )
    exists = cur.fetchone()
    if exists:
        cur.execute(
            """UPDATE "SocialCreator" SET
                handle=%s, nickname=%s, bio=%s, gender=%s, "ipLocation"=%s,
                "avatarUrl"=%s, "profileUrl"=%s, fans=%s, tags=%s, raw=%s,
                "parserVersion"=%s, "lastSeenAt"=%s
               WHERE platform=%s AND "platformUserId"=%s""",
            (handle, nickname, bio, gender, ip_location, avatar_url, profile_url,
             fans, tags, raw, PARSER_VERSION, now, PLATFORM, platform_user_id),
        )
        return platform_user_id, "updated"
    # 插入：用 platformUserId 作为 id（小红书用户 id 全局唯一，天然去重）
    _id = platform_user_id
    cur.execute(
        """INSERT INTO "SocialCreator"
           (id, platform, "platformUserId", handle, nickname, bio, gender, "ipLocation",
            "avatarUrl", "profileUrl", fans, follows, interaction, tags, "entryMode",
            "sourceKeywords", "acquisitionMethods", raw, "parserVersion",
            "firstSeenAt", "lastSeenAt")
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (_id, PLATFORM, platform_user_id, handle, nickname, bio, gender, ip_location,
         avatar_url, profile_url, fans, follows, interaction, tags, entry_mode,
         source_keywords, acquisition_methods, raw, PARSER_VERSION, now, now),
    )
    return platform_user_id, "inserted"


def _upsert_note(cur, creator_id: str, t: dict, n: dict) -> None:
    """插入或更新 SocialNote（含正文标题，不含评论）。"""
    note_id = n.get("noteId")
    if not note_id:
        return
    platform_user_id = creator_id
    author_nickname = t.get("name") or ""
    note_type = "video" if _int(n.get("type")) == 2 else "image"
    title = n.get("title") or None
    body = None
    # 从 full_detail 拿正文
    full_detail = n.get("full_detail") or {}
    if full_detail.get("content"):
        body = full_detail["content"]
    published_at = None
    if full_detail.get("createTime"):
        try:
            published_at = datetime.fromtimestamp(int(full_detail["createTime"]) / 1000)
        except Exception:
            published_at = None
    liked_count = int(n.get("likeNum") or 0) or None
    collected_count = int(n.get("collectNum") or 0) or None
    comment_count = int(n.get("interactionNum") or 0) or None
    share_count = None
    counts_raw = json.dumps({
        "readNum": n.get("readNum"),
        "impNum": n.get("impNum"),
        "likeNum": n.get("likeNum"),
        "collectNum": n.get("collectNum"),
        "interactionNum": n.get("interactionNum"),
    }, ensure_ascii=False, default=str)
    count_precision = "exact"
    tags = []
    note_url = None
    if full_detail.get("noteLink"):
        note_url = full_detail["noteLink"]
    video_urls = []
    if full_detail.get("videoInfo"):
        video_urls = [str(full_detail["videoInfo"].get("videoKey") or "")]
    video_duration = None
    at_users = None
    source_keywords = []
    acquisition_methods = ["pugongying"]
    raw = json.dumps(n, ensure_ascii=False, default=str)
    now = _now()

    cur.execute(
        'SELECT "platformNoteId" FROM "SocialNote" WHERE platform=%s AND "platformNoteId"=%s',
        (PLATFORM, note_id),
    )
    exists = cur.fetchone()
    if exists:
        cur.execute(
            """UPDATE "SocialNote" SET
                title=%s, body=%s, "likedCount"=%s, "collectedCount"=%s,
                "commentCount"=%s, "shareCount"=%s, "countsRaw"=%s, tags=%s,
                "noteUrl"=%s, "videoUrls"=%s, raw=%s, "parserVersion"=%s, "lastSeenAt"=%s
               WHERE platform=%s AND "platformNoteId"=%s""",
            (title, body, liked_count, collected_count, comment_count, share_count,
             counts_raw, tags, note_url, video_urls, raw, PARSER_VERSION, now,
             PLATFORM, note_id),
        )
        return "updated"
    _id = note_id
    cur.execute(
        """INSERT INTO "SocialNote"
           (id, platform, "platformNoteId", "platformUserId", "creatorId", "authorNickname",
            type, title, body, "publishedAt", "likedCount", "collectedCount",
            "commentCount", "shareCount", "countsRaw", "countPrecision", tags,
            "noteUrl", "videoUrls", "atUsers", "sourceKeywords", "acquisitionMethods",
            raw, "parserVersion", "firstSeenAt", "lastSeenAt")
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (_id, PLATFORM, note_id, platform_user_id, creator_id, author_nickname,
         note_type, title, body, published_at, liked_count, collected_count,
         comment_count, share_count, counts_raw, count_precision, tags,
         note_url, video_urls, at_users, source_keywords, acquisition_methods,
         raw, PARSER_VERSION, now, now),
    )
    return "inserted"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

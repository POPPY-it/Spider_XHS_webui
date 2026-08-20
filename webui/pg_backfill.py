# encoding: utf-8
"""为数据库里缺少笔记的达人补拉笔记正文并写入。

逻辑：
1. 从 SocialCreator 找出没有笔记的达人（或指定 platformUserId 列表）
2. 对每个达人调蒲公英 get_talent_detail 拿笔记列表
3. 每篇笔记调 get_note_full_detail 拿正文
4. 写入 SocialNote（更新已有 / 插入新的）

用法：
    python -m webui.pg_backfill                # 补全部缺笔记的达人
    python -m webui.pg_backfill uid1 uid2      # 只补指定达人
"""

import sys
import time

from webui import pg_sync, pgy_talents


def backfill_creators(uid_list=None, on_progress=None) -> dict:
    """补拉指定/全部缺笔记达人的笔记正文。返回统计。"""
    stats = {
        "creators_processed": 0,
        "notes_fetched": 0,
        "notes_inserted": 0,
        "notes_updated": 0,
        "failed": 0,
    }

    if uid_list is None:
        # 查数据库里缺笔记的达人
        conn = pg_sync._connect()
        cur = conn.cursor()
        cur.execute(
            """SELECT c."platformUserId" FROM "SocialCreator" c
               WHERE c.platform=%s
               AND NOT EXISTS (SELECT 1 FROM "SocialNote" n
                               WHERE n."platformUserId"=c."platformUserId")
            """, (pg_sync.PLATFORM,))
        uid_list = [r[0] for r in cur.fetchall()]
        conn.close()

    total = len(uid_list)
    for i, uid in enumerate(uid_list, 1):
        try:
            # 1) 拉达人详情（笔记列表）
            detail = pgy_talents.get_talent_detail(uid)
            notes_data = ((detail.get("notes") or {}).get("data") or {})
            note_list = notes_data.get("notes") or []
            if not note_list:
                stats["creators_processed"] += 1
                if on_progress:
                    on_progress(i, total, f"{uid}（无笔记）")
                continue

            # 2) 拉每篇笔记正文
            creator_row = {"platformUserId": uid, "nickname": ""}
            conn = pg_sync._connect()
            cur = conn.cursor()
            for n in note_list:
                note_id = n.get("noteId")
                if not note_id:
                    continue
                # 拉正文
                try:
                    nd = pgy_talents.get_note_full_detail(note_id, with_comments=False)
                    if nd.get("detail"):
                        n = dict(n)
                        n["full_detail"] = nd["detail"]
                except Exception:
                    pass
                # 构造数据库格式笔记行
                db_note = _to_db_note(creator_row, n)
                try:
                    op = pg_sync._upsert_note_db(cur, db_note)
                    if op == "inserted":
                        stats["notes_inserted"] += 1
                    elif op == "updated":
                        stats["notes_updated"] += 1
                    stats["notes_fetched"] += 1
                except Exception:
                    stats["failed"] += 1
                time.sleep(0.3)
            conn.commit()
            conn.close()
            stats["creators_processed"] += 1
            if on_progress:
                on_progress(i, total, f"{uid}（{len(note_list)}篇）")
        except Exception as e:
            stats["failed"] += 1
            if on_progress:
                on_progress(i, total, f"{uid}（失败:{str(e)[:30]}）")
        time.sleep(0.5)

    return stats


def _to_db_note(creator_row: dict, n: dict) -> dict:
    """把蒲公英笔记 dict 转成数据库格式（复用 pg_convert 的 map_note 逻辑）。"""
    from webui.pg_convert import map_note
    # map_note 需要 creator 有 platformUserId/nickname
    return map_note(creator_row, n)


if __name__ == "__main__":
    uids = sys.argv[1:] if len(sys.argv) > 1 else None
    print("开始补拉达人笔记正文…")
    s = backfill_creators(uids, on_progress=lambda i, t, n: print(f"  [{i}/{t}] {n}"))
    print("补全完成:", s)

# encoding: utf-8
"""补抓评论：对已导出但评论为空的笔记，只补评论（不重复下载图片/视频）。

用法（风控解除后运行）：
    python -m webui.backfill_comments

逻辑：
1. 扫描 datas/exports/<集合>/ 下所有 info.json，找 comment_count > 0 但 note.md 无评论的笔记
2. 对每篇用 info.json 里的 note_url 重新抓评论
3. 只更新 note.md 的「## 评论」章节，不动图片/视频/info.json
"""

import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from webui.login_bridge import _build_authed_api
from webui.exporters import _fmt_comment


def find_missing_comment_notes(base: str) -> list:
    """找出 comment_count > 0 但 note.md 没有评论的笔记，返回 [(md_path, info, note_url)]。"""
    missing = []
    for md_path in glob.glob(os.path.join(base, "*", "*", "note.md")):
        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read()
        if "## 评论" in md:
            continue  # 已有评论，跳过
        info_path = os.path.join(os.path.dirname(md_path), "info.json")
        if not os.path.exists(info_path):
            continue
        with open(info_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        try:
            cc = int(info.get("comment_count", 0))
        except (TypeError, ValueError):
            cc = 0
        if cc > 0:
            missing.append((md_path, info, info.get("note_url", "")))
    return missing


def backfill_comments(base: str, on_progress=None) -> dict:
    """补抓评论。返回统计。"""
    missing = find_missing_comment_notes(base)
    if not missing:
        return {"total": 0, "fixed": 0, "failed": 0}

    auth, api = _build_authed_api()
    stats = {"total": len(missing), "fixed": 0, "failed": 0}
    try:
        for i, (md_path, info, note_url) in enumerate(missing, 1):
            title = info.get("title", "")[:20]
            if not note_url:
                stats["failed"] += 1
                if on_progress:
                    on_progress(i, len(missing), f"{title}（无 note_url）")
                continue
            try:
                success, msg, raw = api.get_note_all_comment(note_url)
                if not success or not raw:
                    stats["failed"] += 1
                    if on_progress:
                        on_progress(i, len(missing), f"{title}（{msg or '空'}）")
                    continue
                # 标准化评论（含二级）
                comments = []
                for c in raw:
                    try:
                        c = dict(c)
                        c["note_id"] = info.get("note_id", "")
                        c["note_url"] = note_url
                        c["parent_comment_id"] = ""
                        comments.append(_std_comment(c))
                        for sc in (c.get("sub_comments") or []):
                            try:
                                sc = dict(sc)
                                sc["note_id"] = info.get("note_id", "")
                                sc["note_url"] = note_url
                                sc["parent_comment_id"] = c.get("id", "")
                                comments.append(_std_comment(sc))
                            except Exception:
                                continue
                    except Exception:
                        continue
                # 更新 note.md：追加「## 评论」章节
                _append_comments_to_md(md_path, comments)
                stats["fixed"] += 1
                if on_progress:
                    on_progress(i, len(missing), f"✓ {title}（补 {len(comments)} 条）")
            except Exception as exc:
                stats["failed"] += 1
                if on_progress:
                    on_progress(i, len(missing), f"{title}（异常 {str(exc)[:20]}）")
            time.sleep(1.5)
    finally:
        auth.close()
    return stats


def _std_comment(c: dict) -> dict:
    """把原始评论 dict 转成标准化 dict（对齐 handle_comment_info 的输出字段）。"""
    from xhs_utils.data_util import handle_comment_info
    return handle_comment_info(c)


def _append_comments_to_md(md_path: str, comments: list) -> None:
    """在 note.md 末尾追加「## 评论」章节（不重写其他内容）。"""
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()
    if "## 评论" in md:
        return  # 已有评论，不重复
    lines = md.rstrip("\n").split("\n")
    lines.append("")
    lines.append("## 评论")
    lines.append("")
    for c in comments:
        lines.append(_fmt_comment(c))
    lines.append("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "datas/exports/Friso美素佳儿香港版"
    print(f"扫描 {base} 中评论为空的笔记...")
    missing = find_missing_comment_notes(base)
    print(f"需补评论的笔记: {len(missing)} 篇")
    if missing:
        stats = backfill_comments(base, on_progress=lambda i, t, n: print(f"  [{i}/{t}] {n}"))
        print("补抓完成:", stats)

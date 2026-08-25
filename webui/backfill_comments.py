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
import sys

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
            log = (lambda m: on_progress(i, len(missing), f"{title} {m}")) if on_progress else None
            comments = _fetch_comments_with_retry(api, note_url, log, auth=auth)
            if not comments:
                stats["failed"] += 1
                if on_progress:
                    on_progress(i, len(missing), f"{title}（空/限频）")
                # 会话可能已过期：快速检测，过期则中止，避免剩余笔记全部白重试
                try:
                    s_ok, s_msg, _ = api.get_user_me()
                    if not s_ok and "过期" in (s_msg or ""):
                        stats["failed"] += len(missing) - i
                        if on_progress:
                            on_progress(i, len(missing), f"会话失效（{s_msg}），中止补抓，需重新登录")
                        return stats
                except Exception:
                    pass
                continue
            for c in comments:
                c["note_id"] = info.get("note_id", "")
                c["note_url"] = note_url
            _append_comments_to_md(md_path, comments)
            stats["fixed"] += 1
            if on_progress:
                on_progress(i, len(missing), f"✓ {title}（补 {len(comments)} 条）")
    finally:
        auth.close()
    return stats


def _fetch_comments_with_retry(api, note_url, log, auth=None, retries=4) -> list:
    """带退避重试 + 新 token 兜底的评论抓取；仍失败返回空列表。

    复用 webui.tasks._fetch_comments 的自适应间隔（限频自动拉大、成功回落），
    空结果再额外重试，最后尝试换新 token 抓一次。
    """
    import time as _t

    from webui.tasks import _fetch_comments

    noop = log or (lambda m: None)
    for attempt in range(retries):
        comments = _fetch_comments(api, note_url, noop)
        if comments:
            return comments
        if attempt < retries - 1:
            backoff = 6 * (attempt + 1)
            noop(f"（第{attempt + 1}次空，退避 {backoff}s 重试）")
            _t.sleep(backoff)
    # 兜底：换新 token 再抓一次
    if auth:
        try:
            from spider.spider import Data_Spider
            s, m, info = Data_Spider(auth).spider_note(note_url)
            if s and info and info.get("note_url"):
                comments = _fetch_comments(api, info["note_url"], noop)
                if comments:
                    return comments
        except Exception:
            pass
    return []


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

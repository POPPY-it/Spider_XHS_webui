# encoding: utf-8
"""AI / 知识库友好导出：Markdown 单篇 + JSONL 聚合。

输出根目录：``datas/exports/{collection}/``。
"""

import json
import os
from datetime import datetime

from xhs_utils.data_util import norm_str


def _export_dir(collection: str) -> str:
    safe = norm_str(collection) or "notes"
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "../datas/exports"))
    path = os.path.join(base, safe)
    os.makedirs(path, exist_ok=True)
    return path


def _fmt_comment(comment: dict) -> str:
    nickname = comment.get("nickname", "")
    time = comment.get("upload_time", "")
    likes = comment.get("like_count", 0)
    content = (comment.get("content", "") or "").replace("\n", " ")
    parent_id = comment.get("parent_comment_id", "")
    target_user = comment.get("target_user", "")
    prefix = "  " if parent_id else ""   # 二级评论缩进
    at = f"回复 @{target_user}：" if target_user else ""
    return f"{prefix}- **{nickname}**（{time}，赞 {likes}）{at}{content}"


def build_markdown(note: dict, comments: list, collection: str) -> str:
    """生成单篇笔记的 Markdown 内容（不写文件）。"""
    def q(value):
        return json.dumps(str(value), ensure_ascii=False)

    frontmatter = "\n".join([
        "---",
        f"title: {q(note.get('title', ''))}",
        f"author: {q(note.get('nickname', ''))}",
        f"note_id: {q(note.get('note_id', ''))}",
        f"note_url: {q(note.get('note_url', ''))}",
        f"type: {q(note.get('note_type', ''))}",
        f"liked_count: {note.get('liked_count', 0)}",
        f"collected_count: {note.get('collected_count', 0)}",
        f"comment_count: {note.get('comment_count', 0)}",
        f"share_count: {note.get('share_count', 0)}",
        f"tags: {json.dumps(note.get('tags', []) or [], ensure_ascii=False)}",
        f"upload_time: {q(note.get('upload_time', ''))}",
        f"ip_location: {q(note.get('ip_location', ''))}",
        'source: "xiaohongshu"',
        f"collection: {q(collection)}",
        "---",
    ])

    body = [frontmatter, "", f"# {note.get('title', '')}", ""]
    desc = note.get("desc", "") or ""
    if desc:
        body += [desc, ""]
    if note.get("note_type") == "视频" and note.get("video_addr"):
        body += ["## 视频", "", f"[video]({note['video_addr']})", ""]
    else:
        images = note.get("image_list") or []
        if images:
            body += ["## 图片", ""]
            for i, url in enumerate(images):
                body.append(f"![image-{i}]({url})")
            body.append("")
    if comments:
        body += ["## 评论", ""]
        for c in comments:
            body.append(_fmt_comment(c))
        body.append("")
    return "\n".join(body)


def write_note(note: dict, comments: list, collection: str) -> str:
    """写单篇 Markdown，返回文件路径。``comments`` 为已标准化的评论列表。"""
    path = _export_dir(collection)
    note_id = note.get("note_id", "note")
    file_path = os.path.join(path, f"note_{note_id}.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(build_markdown(note, comments, collection))
    return file_path


def export_note_folder(note: dict, comments: list, collection: str) -> str:
    """采集式存储：每篇笔记一个文件夹（<昵称_用户id>/<标题_笔记id>），
    含 note.md + 下载的图片/视频 + info.json。返回文件夹路径。"""
    from xhs_utils.data_util import norm_str, check_and_create_path, download_media

    note_id = note.get("note_id", "note")
    user_id = note.get("user_id", "")
    title = norm_str(note.get("title", ""))[:40]
    nickname = norm_str(note.get("nickname", ""))[:20]
    if not title.strip():
        title = "无标题"

    base = _export_dir(collection)
    folder = os.path.join(base, f"{nickname}_{user_id}", f"{title}_{note_id}")
    check_and_create_path(folder)

    # 下载媒体（复用采集逻辑）
    note_type = note.get("note_type", "")
    if note_type == "图集":
        for i, url in enumerate(note.get("image_list") or []):
            try:
                download_media(folder, f"image_{i}", url, "image")
            except Exception:
                pass
    elif note_type == "视频":
        if note.get("video_cover"):
            try:
                download_media(folder, "cover", note["video_cover"], "image")
            except Exception:
                pass
        if note.get("video_addr"):
            try:
                download_media(folder, "video", note["video_addr"], "video")
            except Exception:
                pass

    # 写 info.json
    with open(os.path.join(folder, "info.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False, default=str) + "\n")

    # 写 note.md
    with open(os.path.join(folder, "note.md"), "w", encoding="utf-8") as f:
        f.write(build_markdown(note, comments, collection))

    return folder


def append_jsonl(note: dict, comments: list, collection: str) -> None:
    """把单篇追加进 notes.jsonl（每行一个紧凑 JSON 对象）。"""
    path = _export_dir(collection)
    comments_out = []
    for c in comments:
        item = {
            "comment_id": c.get("comment_id", ""),
            "parent_comment_id": c.get("parent_comment_id", ""),
            "target_comment_id": c.get("target_comment_id", ""),
            "target_user": c.get("target_user", ""),
            "user_id": c.get("user_id", ""),
            "nickname": c.get("nickname", ""),
            "content": c.get("content", ""),
            "like_count": c.get("like_count", 0),
            "upload_time": c.get("upload_time", ""),
            "ip_location": c.get("ip_location", ""),
        }
        comments_out.append(item)

    line = {
        "note_id": note.get("note_id", ""),
        "title": note.get("title", ""),
        "desc": note.get("desc", ""),
        "author": note.get("nickname", ""),
        "user_id": note.get("user_id", ""),
        "home_url": note.get("home_url", ""),
        "note_url": note.get("note_url", ""),
        "type": note.get("note_type", ""),
        "liked_count": note.get("liked_count", 0),
        "collected_count": note.get("collected_count", 0),
        "comment_count": note.get("comment_count", 0),
        "share_count": note.get("share_count", 0),
        "tags": note.get("tags", []) or [],
        "upload_time": note.get("upload_time", ""),
        "ip_location": note.get("ip_location", ""),
        "image_urls": note.get("image_list", []) or [],
        "video_url": note.get("video_addr", ""),
        "comments": comments_out,
        "collection": collection,
        "source": "xiaohongshu",
        "exported_at": datetime.now().astimezone().isoformat(),
    }
    file_path = os.path.join(path, "notes.jsonl")
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")

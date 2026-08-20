# encoding: utf-8
"""蒲公英（KOL 达人）路由：Cookie 管理、类目、筛选搜索、详情、导出。"""

import os
import time

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from webui import pgy_talents

router = APIRouter(prefix="/api/pgy", tags=["pgy"])

EXCEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "datas", "excel_datas"))


def _json(data: dict, status: int = 200):
    return JSONResponse(content=data, status_code=status)


# ---------------------------------------------------------------------------
# Cookie 管理
# ---------------------------------------------------------------------------


@router.get("/status")
def pgy_status():
    """蒲公英 Cookie 保存状态 + 有效性校验。"""
    info = pgy_talents.pgy_cookie_info()
    valid = pgy_talents.check_pgy_status()
    return _json({"success": True, **info, **valid})


@router.post("/cookie")
def pgy_save_cookie(payload: dict):
    """保存蒲公英 Cookie 并校验。先校验成功才落盘。"""
    cookie = (payload or {}).get("cookie", "").strip()
    if not cookie:
        return _json({"success": False, "error": "Cookie 不能为空"}, 400)
    result = pgy_talents.verify_pgy_cookie(cookie)
    if not result.get("valid"):
        return _json({"success": False, "error": result.get("error", "Cookie 无效")}, 400)
    pgy_talents.save_pgy_cookie(cookie)
    return _json({"success": True, "nickname": result.get("nickname")})


# ---------------------------------------------------------------------------
# 类目树
# ---------------------------------------------------------------------------


@router.get("/categories")
def pgy_categories():
    """获取蒲公英内容类目树。"""
    try:
        tree = pgy_talents.get_categories()
        return _json({"success": True, "tree": tree})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


# ---------------------------------------------------------------------------
# 达人搜索
# ---------------------------------------------------------------------------


@router.get("/search")
def pgy_search(
    fans_min: int = Query(None),
    fans_max: int = Query(None),
    gender: str = Query(None),
    location: str = Query(None),
    trade_type: str = Query("不限"),
    note_type: int = Query(0),
    page_size: int = Query(20),
    max_pages: int = Query(10),
    content_tags: str = Query(None),
    personal_tags: str = Query(None),
    feature_tags: str = Query(None),
):
    """按筛选条件搜索达人。

    content_tags / personal_tags / feature_tags 是逗号分隔的字符串。
    content_tags 里的元素是类目 key：``"1"`` 表示一级类目，``"1-2"`` 表示
    一级下的二级类目；后端会先用类目树解析成实际的 taxonomy 标签。
    """
    content_tags_list = _split_tags(content_tags)
    resolved_tags = []
    if content_tags_list:
        try:
            tree = pgy_talents.get_categories()
            resolved_tags = pgy_talents.build_content_tag(content_tags_list, tree)
        except Exception:
            # 类目解析失败时回退到原样传入，交由接口侧判断
            resolved_tags = content_tags_list
    personal_tags_list = _split_tags(personal_tags)
    feature_tags_list = _split_tags(feature_tags)
    try:
        result = pgy_talents.search_talents(
            content_tags=resolved_tags,
            fans_min=fans_min,
            fans_max=fans_max,
            gender=gender,
            location=location,
            personal_tags=personal_tags_list,
            feature_tags=feature_tags_list,
            trade_type=trade_type,
            note_type=note_type,
            page_size=page_size,
            max_pages=max_pages,
        )
        return _json({"success": True, **result})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


def _split_tags(s: str) -> list:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# 已下载达人（去重）
# ---------------------------------------------------------------------------


@router.get("/downloaded")
def pgy_downloaded():
    """返回已下载达人列表（含 userId），供管理/勾选删除。"""
    items = pgy_talents.list_downloaded()
    return _json({"success": True, "count": len(items), "items": items})


@router.post("/downloaded/remove")
def pgy_downloaded_remove(payload: dict):
    """删除指定 userId 的已下载记录（可多个）。"""
    user_ids = (payload or {}).get("user_ids", [])
    if not user_ids:
        return _json({"success": False, "error": "没有选择要删除的记录"}, 400)
    removed = pgy_talents.remove_downloaded(user_ids)
    return _json({"success": True, "removed": removed})


@router.post("/downloaded/reset")
def pgy_downloaded_reset():
    """清空全部已下载记录（从头开始记录）。"""
    import os as _os
    if _os.path.exists(pgy_talents.DOWNLOADED_FILE):
        _os.remove(pgy_talents.DOWNLOADED_FILE)
    return _json({"success": True})


# ---------------------------------------------------------------------------
# 达人详情
# ---------------------------------------------------------------------------


@router.post("/enrich-median")
def pgy_enrich_median(payload: dict):
    """后台批量拉取达人阅读/互动中位数，返回 task_id 供前端轮询进度。

    前端传入 talents（搜索结果），worker 逐个调详情接口补全 median_* 字段。
    """
    from webui.tasks import start_task
    talents = (payload or {}).get("talents", [])
    if not talents:
        return _json({"success": False, "error": "没有可处理的达人"}, 400)
    try:
        task_id = start_task("median", {"talents": talents})
        return _json({"success": True, "task_id": task_id, "total": len(talents)})
    except RuntimeError as exc:
        return _json({"success": False, "error": "已有任务正在运行，请稍后再试", "running_task_id": str(exc)}, 409)


@router.get("/note-detail")
def pgy_note_detail(note_id: str = Query(...), with_comments: int = Query(1), top_liked: int = Query(0)):
    """获取蒲公英笔记完整详情（标题/正文/图片/视频/评论）。"""
    try:
        result = pgy_talents.get_note_full_detail(
            note_id,
            with_comments=bool(with_comments),
            top_liked=bool(top_liked),
            comment_limit=20,
        )
        return _json({"success": True, **result})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


@router.get("/detail")
def pgy_detail(user_id: str = Query(...)):
    """获取单个达人详情（数据总览 + 粉丝画像 + 笔记数据）。"""
    try:
        result = pgy_talents.get_talent_detail(user_id)
        return _json({"success": True, **result})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------


@router.post("/export")
def pgy_export(payload: dict):
    """后台导出达人完整数据：Excel 汇总 + JSON 完整备份（含详情页数据）。"""
    from webui.tasks import start_task
    talents = (payload or {}).get("talents", [])
    if not talents:
        return _json({"success": False, "error": "没有可导出的达人"}, 400)
    base_name = (payload or {}).get("base_name") or time.strftime("蒲公英达人_%Y%m%d_%H%M%S")
    with_comments = bool((payload or {}).get("with_comments"))
    sync_db = bool((payload or {}).get("sync_db"))
    db_only = bool((payload or {}).get("db_only"))
    try:
        task_id = start_task("full_export", {
            "talents": talents,
            "base_name": base_name,
            "with_comments": with_comments,
            "sync_db": sync_db,
            "db_only": db_only,
        })
        return _json({"success": True, "task_id": task_id, "total": len(talents)})
    except RuntimeError as exc:
        return _json({"success": False, "error": "已有任务正在运行，请稍后再试", "running_task_id": str(exc)}, 409)

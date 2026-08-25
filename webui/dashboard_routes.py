# encoding: utf-8
"""数据仪表盘路由。"""

import os

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from webui import dashboard_api

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _json(data: dict, status: int = 200):
    return JSONResponse(content=data, status_code=status)


@router.get("")
def dashboard(collection: str = Query("", description="导出集合名，默认最新")):
    name = collection.strip() or dashboard_api.default_collection()
    if not name:
        return _json({"success": False, "error": "没有可用导出集合"}, 400)
    try:
        path = dashboard_api.resolve_collection(name)
    except ValueError:
        return _json({"success": False, "error": "集合名不合法"}, 400)
    if not os.path.isdir(path):
        return _json({"success": False, "error": f"集合不存在：{name}"}, 404)
    try:
        data = dashboard_api.aggregate_export_collection(path)
    except Exception as exc:
        return _json({"success": False, "error": f"聚合失败：{exc}"}, 500)
    return _json({
        "success": True,
        "collection": name,
        "collections": dashboard_api.list_collections(),
        **data,
    })

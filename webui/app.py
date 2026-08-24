# encoding: utf-8
"""FastAPI 入口：路由 + 静态页面 + uvicorn 启动。

启动方式（仓库根目录）：
    python -m uvicorn webui.app:app --port 8000
"""

import os

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response

from webui import login_bridge, tasks
from webui.datas_api import read_excel, scan_datas, open_in_finder, delete_path
from webui.hotspot_routes import router as hotspot_router
from webui.pgy_routes import router as pgy_router
from webui.tasks import AUTH_SEM

app = FastAPI(title="Spider_XHS WebUI")
app.include_router(pgy_router)
app.include_router(hotspot_router)

BASE_DIR = os.path.dirname(__file__)
INDEX_HTML = os.path.join(BASE_DIR, "static", "index.html")


def _json(data: dict, status: int = 200):
    return JSONResponse(content=data, status_code=status)


# ---------------------------------------------------------------------------
# 认证 / 账号
# ---------------------------------------------------------------------------


@app.get("/api/auth/status")
def auth_status():
    with AUTH_SEM:
        return login_bridge.check_auth_status()


@app.post("/api/auth/cookie")
def auth_save_cookie(payload: dict):
    cookie = (payload or {}).get("cookie", "")
    with AUTH_SEM:
        result = login_bridge.save_cookie_and_verify(cookie)
    if not result.get("success"):
        return _json({"success": False, "error": result.get("error", "保存失败")}, 400)
    return _json({"success": True, "nickname": result.get("nickname")})


@app.post("/api/auth/qr/start")
def auth_qr_start():
    try:
        login_bridge.start_qr_login()
    except RuntimeError as exc:
        return _json({"success": False, "error": str(exc)}, 409)
    return _json({"started": True})


@app.post("/api/auth/browser-login/start")
def auth_browser_login_start():
    try:
        login_bridge.start_browser_login()
    except RuntimeError as exc:
        return _json({"success": False, "error": str(exc)}, 409)
    return _json({"started": True})


@app.get("/api/auth/browser-login/status")
def auth_browser_login_status():
    return login_bridge.browser_login_state()


@app.get("/api/auth/qr/image")
def auth_qr_image():
    try:
        png = login_bridge.qr_image_png()
    except ValueError as exc:
        if "没有进行中" in str(exc):
            return _json({"success": False, "error": str(exc)}, 404)
        return _json({"success": False, "error": "二维码尚未生成，请稍候…"}, 202)
    return Response(content=png, media_type="image/png")


@app.get("/api/auth/qr/status")
def auth_qr_status():
    return login_bridge.qr_state()


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


@app.post("/api/tasks/crawl")
def task_crawl(payload: dict):
    try:
        task_id = tasks.start_task("crawl", payload or {})
    except RuntimeError as exc:
        return _json({"success": False, "error": "已有任务正在运行", "running_task_id": str(exc)}, 409)
    return _json({"task_id": task_id})


@app.post("/api/tasks/export")
def task_export(payload: dict):
    try:
        task_id = tasks.start_task("export", payload or {})
    except RuntimeError as exc:
        return _json({"success": False, "error": "已有任务正在运行", "running_task_id": str(exc)}, 409)
    return _json({"task_id": task_id})


@app.get("/api/tasks/{task_id}")
def task_get(task_id: str):
    task = tasks.get_task(task_id)
    if not task:
        return _json({"success": False, "error": "任务不存在"}, 404)
    return _json(task)


@app.post("/api/tasks/{task_id}/cancel")
def task_cancel(task_id: str):
    if not tasks.cancel_task(task_id):
        return _json({"success": False, "error": "任务不存在"}, 404)
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# 浏览
# ---------------------------------------------------------------------------


@app.get("/api/browse/note")
def browse_note(url: str = Query(...)):
    from spider.spider import Data_Spider
    with AUTH_SEM:
        try:
            auth, api = login_bridge._build_authed_api()
            try:
                success, msg, info = Data_Spider(auth).spider_note(url)
            finally:
                auth.close()
        except Exception as exc:
            return _json({"success": False, "error": str(exc)}, 400)
    if not success or not info:
        return _json({"success": False, "error": msg or "获取失败"}, 400)
    return _json({"success": True, "note": info})


@app.get("/api/browse/note/comments")
def browse_note_comments(url: str = Query(...)):
    from webui.tasks import _fetch_comments
    with AUTH_SEM:
        try:
            auth, api = login_bridge._build_authed_api()
            try:
                comments = _fetch_comments(api, url, lambda m: None)
            finally:
                auth.close()
        except Exception as exc:
            return _json({"success": False, "error": str(exc)}, 400)
    return _json({"success": True, "comments": comments})


@app.get("/api/browse/user")
def browse_user(url: str = Query(...)):
    from xhs_utils.data_util import handle_user_info
    import urllib.parse
    with AUTH_SEM:
        try:
            auth, api = login_bridge._build_authed_api()
            try:
                parsed = urllib.parse.urlparse(url)
                user_id = parsed.path.split("/")[-1]
                success, msg, user_info = api.get_user_info(user_id)
                if not success:
                    return _json({"success": False, "error": msg or "获取用户失败"}, 400)
                s2, m2, raw_notes = api.get_user_all_notes(url)
                if not s2:
                    return _json({"success": False, "error": m2 or "获取笔记失败"}, 400)
            finally:
                auth.close()
        except Exception as exc:
            return _json({"success": False, "error": str(exc)}, 400)
    user = handle_user_info(user_info["data"], user_id)
    notes = []
    for n in raw_notes:
        note_id = n.get("note_id") or n.get("id") or ""
        cover = ""
        try:
            cover = n["note_card"]["cover"]["url_default"]
        except Exception:
            pass
        notes.append({
            "note_id": note_id,
            "title": (n.get("note_card") or {}).get("title", ""),
            "url": f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={n.get('xsec_token','')}",
            "cover": cover,
            "type": "视频" if ((n.get("note_card") or {}).get("type") == "video") else "图集",
            "liked_count": ((n.get("note_card") or {}).get("interact_info") or {}).get("liked_count", 0),
        })
    return _json({"success": True, "user": user, "notes": notes})


# ---------------------------------------------------------------------------
# 数据目录
# ---------------------------------------------------------------------------


@app.get("/api/datas")
def datas_list():
    return _json({"success": True, **scan_datas()})


@app.get("/api/datas/excel")
def datas_excel(path: str = Query(...)):
    try:
        return _json({"success": True, **read_excel(path)})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


@app.get("/api/datas/json")
def datas_json(path: str = Query(...)):
    import json as jsonlib, os as _os
    from webui.datas_api import DATAS_DIR
    real = _os.path.abspath(path)
    if not real.startswith(_os.path.abspath(DATAS_DIR) + _os.sep) or not real.endswith(".json"):
        return _json({"success": False, "error": "路径不合法"}, 400)
    if not _os.path.isfile(real):
        return _json({"success": False, "error": "文件不存在"}, 404)
    try:
        with open(real, "r", encoding="utf-8") as f:
            data = jsonlib.load(f)
        return _json({"success": True, "data": data})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


@app.post("/api/datas/open")
def datas_open(payload: dict):
    path = (payload or {}).get("path", "")
    if not path:
        return _json({"success": False, "error": "缺少 path"}, 400)
    try:
        return _json({"success": True, **open_in_finder(path)})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


@app.post("/api/datas/delete")
def datas_delete(payload: dict):
    path = (payload or {}).get("path", "")
    if not path:
        return _json({"success": False, "error": "缺少 path"}, 400)
    try:
        return _json({"success": True, **delete_path(path)})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 400)


# ---------------------------------------------------------------------------
# 静态
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(INDEX_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

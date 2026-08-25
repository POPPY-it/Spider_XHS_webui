# encoding: utf-8
"""后台任务：爬取 / 导出 + 进度注册表。

线程模型：全局只允许一个后台任务运行（防风控与签名器并发）。每个任务
线程内部构建独立的 auth（非线程安全，不能跨线程共享），任务结束 close()。
"""

import os
import threading
import time
import uuid

from spider.spider import Data_Spider
from xhs_utils.common_util import init
from xhs_utils.data_util import (
    handle_comment_info,
    download_note,
    save_to_xlsx,
)

from webui import exporters
from webui.login_bridge import _build_authed_api

_TASK_LOCK = threading.Lock()
TASKS: dict = {}
_current_task_id = None

# 同步请求（浏览/认证）也可用 auth，这里做轻量并发护栏。
AUTH_SEM = threading.Semaphore(3)


def _default_excel_name(req: dict) -> str:
    mode = req.get("mode")
    if mode == "search":
        return req.get("query", "搜索") or "搜索"
    if mode == "user":
        url = req.get("user_url", "") or ""
        name = url.rstrip("/").split("/")[-1].split("?")[0]
        return name or "用户"
    if mode == "note":
        url = req.get("note_url", "") or ""
        return url.rstrip("/").split("/")[-1].split("?")[0] or "笔记"
    return "笔记"


def _discover_notes(api, req: dict, log) -> list:
    """复刻 spider.py 的发现逻辑，返回笔记 URL 列表。"""
    mode = req.get("mode", "note")
    if mode == "note":
        return [req.get("note_url", "")]
    if mode == "user":
        user_url = req.get("user_url", "")
        success, msg, raw_notes = api.get_user_all_notes(user_url)
        if not success:
            raise RuntimeError(f"获取用户笔记失败：{msg}")
        log(f"发现用户笔记 {len(raw_notes)} 篇")
        urls = []
        for note in raw_notes:
            note_id = note.get("note_id") or note.get("id") or ""
            token = note.get("xsec_token", "")
            if not note_id:
                continue
            urls.append(f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}")
        return urls
    if mode == "search":
        query = req.get("query", "")
        require_num = int(req.get("require_num", 10) or 10)
        success, msg, notes = api.search_some_note(
            query,
            require_num,
            req.get("sort_type_choice", 0),
            req.get("note_type", 0),
            req.get("note_time", 0),
            req.get("note_range", 0),
            req.get("pos_distance", 0),
            req.get("geo", ""),
        )
        if not success:
            raise RuntimeError(f"搜索失败：{msg}")
        notes = [n for n in notes if n.get("model_type") == "note"]
        log(f"搜索「{query}」发现笔记 {len(notes)} 篇")
        urls = []
        for note in notes:
            note_id = note.get("id") or ""
            token = note.get("xsec_token", "")
            if not note_id:
                continue
            urls.append(f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}")
        return urls
    raise RuntimeError(f"未知模式：{mode}")


# 评论抓取的自适应间隔（秒）：限频时拉大，成功时回落，平衡速度与风控
_COMMENT_INTERVAL = 2.0
_COMMENT_INTERVAL_MIN = 2.0
_COMMENT_INTERVAL_MAX = 60.0


def _fetch_comments(api, note_url: str, log) -> list:
    """抓取笔记全部评论（一级 + 二级/楼中楼）并标准化；失败时返回空列表。

    评论接口有频率限制，采用自适应退避：遇到「访问频繁」拉大间隔重试，
    连续成功则逐步回落到最小间隔。
    """
    global _COMMENT_INTERVAL
    import time as _t
    _t.sleep(_COMMENT_INTERVAL)
    for attempt in range(3):
        try:
            success, msg, raw_comments = api.get_note_all_comment(note_url)
            if not success:
                if "频繁" in (msg or "") or "稍后再试" in (msg or ""):
                    _COMMENT_INTERVAL = min(_COMMENT_INTERVAL * 2, _COMMENT_INTERVAL_MAX)
                    log(f"  评论接口限频，间隔提升到 {_COMMENT_INTERVAL:.0f} 秒，重试（第{attempt + 1}次）...")
                    _t.sleep(_COMMENT_INTERVAL)
                    continue
                log(f"  评论抓取失败：{msg}")
                return []
            # 成功：逐步回落间隔
            _COMMENT_INTERVAL = max(_COMMENT_INTERVAL - 1.0, _COMMENT_INTERVAL_MIN)
            comments = []
            for c in raw_comments:
                try:
                    c = dict(c)
                    c["note_id"] = (c.get("note_id") or "")
                    c["note_url"] = note_url
                    c["parent_comment_id"] = ""   # 一级评论无父评论
                    comments.append(handle_comment_info(c))
                    # 展开二级评论（楼中楼回复）
                    sub_comments = c.get("sub_comments") or []
                    for sc in sub_comments:
                        try:
                            sc = dict(sc)
                            sc["note_id"] = (c.get("note_id") or "")
                            sc["note_url"] = note_url
                            sc["parent_comment_id"] = (c.get("id") or "")   # 父评论是一级评论
                            comments.append(handle_comment_info(sc))
                        except Exception:
                            continue
                except Exception:
                    continue
            return comments
        except Exception as exc:
            log(f"  评论抓取异常：{exc}")
            return []
    return []


# ---------------------------------------------------------------------------
# 进度注册表
# ---------------------------------------------------------------------------


def start_task(kind: str, req: dict) -> str:
    """创建任务并启动后台线程。已有运行中任务则抛 RuntimeError。"""
    global _current_task_id
    with _TASK_LOCK:
        if _current_task_id and TASKS.get(_current_task_id, {}).get("status") == "running":
            raise RuntimeError(_current_task_id)
        task_id = uuid.uuid4().hex[:12]
        TASKS[task_id] = {
            "id": task_id,
            "kind": kind,
            "status": "running",
            "phase": "discover",
            "progress": 0,
            "total": 0,
            "log": [],
            "result": None,
            "error": "",
            "cancel": False,
            "created_at": time.time(),
        }
        _current_task_id = task_id
    if kind == "crawl":
        target = _crawl_worker
    elif kind == "export":
        target = _export_worker
    elif kind == "median":
        target = _median_worker
    elif kind == "full_export":
        target = _full_export_worker
    elif kind == "hotspot":
        from webui.hotspot_routes import _hotspot_worker
        target = _hotspot_worker
    elif kind == "comment_analyze":
        target = _comment_analyze_worker
    else:
        raise RuntimeError(f"未知任务类型：{kind}")
    threading.Thread(target=target, args=(task_id, req), daemon=True).start()
    return task_id


def _comment_analyze_worker(task_id: str, req: dict) -> None:
    try:
        import os as _os

        from webui import comment_analyze
        from webui.dashboard_api import resolve_collection

        name = (req or {}).get("collection", "")
        if not name:
            raise RuntimeError("缺少 collection 参数")
        path = resolve_collection(name)
        if not _os.path.isdir(path):
            raise RuntimeError(f"集合不存在：{name}")
        _log(task_id, f"开始分析 {name} 的评论…")

        def on_progress(done, total):
            t = _task(task_id)
            t["progress"] = done
            t["total"] = total
            if done % 20 == 0 or done == total:
                _log(task_id, f"分析进度 {done}/{total}")

        result = comment_analyze.analyze_collection(path, on_progress)
        comment_analyze.save_cache(name, result)
        _log(task_id, f"分析完成：{result['kpi']['analyzed']} 条评论")
        _finish(task_id, "success", result)
    except Exception as exc:
        _finish(task_id, "failed", error=str(exc))


def get_task(task_id: str) -> dict:
    return TASKS.get(task_id)


def running_task_id() -> str:
    return _current_task_id


def cancel_task(task_id: str) -> bool:
    task = TASKS.get(task_id)
    if not task:
        return False
    task["cancel"] = True
    return True


def _task(task_id):
    return TASKS[task_id]


def _log(task_id, message: str) -> None:
    ts = time.strftime("%H:%M:%S", time.localtime())
    _task(task_id)["log"].append(f"[{ts}] {message}")


def _set_total(task_id, total: int) -> None:
    _task(task_id)["total"] = total
    _task(task_id)["phase"] = "process"


def _bump(task_id) -> None:
    task = _task(task_id)
    task["progress"] = task.get("progress", 0) + 1


def _cancelled(task_id) -> bool:
    return bool(_task(task_id).get("cancel"))


def _finish(task_id, status: str, result=None, error="") -> None:
    task = _task(task_id)
    task["status"] = status
    task["result"] = result
    task["error"] = error
    task["cancel"] = False
    with _TASK_LOCK:
        global _current_task_id
        if _current_task_id == task_id:
            _current_task_id = None


# ---------------------------------------------------------------------------
# 任务 worker
# ---------------------------------------------------------------------------


def _crawl_worker(task_id: str, req: dict) -> None:
    auth = None
    try:
        auth, api = _build_authed_api()
        _, base_path = init()

        urls = _discover_notes(api, req, lambda m: _log(task_id, m))
        if not urls:
            raise RuntimeError("未发现任何笔记")
        _set_total(task_id, len(urls))
        _log(task_id, f"开始处理 {len(urls)} 篇笔记…")

        save_choice = req.get("save_choice", "all")
        collected = []
        for url in urls:
            if _cancelled(task_id):
                _finish(task_id, "cancelled", error="已取消")
                return
            try:
                success, msg, info = Data_Spider(auth).spider_note(url)
            except Exception as exc:
                success, msg = False, str(exc)
                info = None
            _log(task_id, f"{'✓' if success else '✗'} {url}")
            if success and info:
                collected.append(info)
            if info and ("media" in save_choice or save_choice == "all"):
                try:
                    download_note(info, base_path["media"], save_choice)
                except Exception as exc:
                    _log(task_id, f"  媒体下载失败：{exc}")
            _bump(task_id)

        if save_choice in ("all", "excel"):
            excel_name = req.get("excel_name") or _default_excel_name(req)
            file_path = os.path.abspath(os.path.join(base_path["excel"], f"{excel_name}.xlsx"))
            try:
                save_to_xlsx(collected, file_path)
                _log(task_id, f"Excel 已保存：{file_path}")
            except Exception as exc:
                _log(task_id, f"Excel 保存失败：{exc}")

        _finish(task_id, "done", result={
            "note_count": len(collected),
            "success_count": len(collected),
            "total": len(urls),
        })
    except Exception as exc:
        _log(task_id, f"任务失败：{exc}")
        _finish(task_id, "error", error=str(exc))
    finally:
        if auth:
            try:
                auth.close()
            except Exception:
                pass


def _note_id_from_url(url: str) -> str:
    """从笔记 URL 提取 note_id。"""
    import urllib.parse
    path = urllib.parse.urlparse(url).path
    return path.rstrip("/").split("/")[-1]


def _completed_note_ids(collection: str) -> set:
    """从已导出的 notes.jsonl 提取已完成的 note_id 集合（用于断点续传）。"""
    import json as _json
    path = os.path.join(exporters._export_dir(collection), "notes.jsonl")
    if not os.path.exists(path):
        return set()
    ids = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = _json.loads(line)
                if d.get("note_id"):
                    ids.add(d["note_id"])
            except Exception:
                continue
    return ids


def _export_worker(task_id: str, req: dict) -> None:
    auth = None
    try:
        auth, api = _build_authed_api()
        init()

        collection = req.get("collection") or _default_excel_name(req)
        include_comments = bool(req.get("include_comments"))
        urls = _discover_notes(api, req, lambda m: _log(task_id, m))
        if not urls:
            raise RuntimeError("未发现任何笔记")

        # 断点续传：跳过已完成的笔记
        completed = _completed_note_ids(collection)
        if completed:
            remaining = [u for u in urls if _note_id_from_url(u) not in completed]
            skipped = len(urls) - len(remaining)
            if skipped > 0:
                _log(task_id, f"断点续传：跳过已完成的 {skipped} 篇，剩余 {len(remaining)} 篇")
            urls = remaining
            if not urls:
                _finish(task_id, "done", result={
                    "note_count": len(completed),
                    "total": len(completed),
                    "collection": collection,
                })
                return

        _set_total(task_id, len(urls))
        _log(task_id, f"开始导出 {len(urls)} 篇笔记到 datas/exports/{collection}/ …")

        spider = Data_Spider(auth)
        count = 0
        for url in urls:
            if _cancelled(task_id):
                _finish(task_id, "cancelled", error="已取消")
                return
            try:
                success, msg, info = spider.spider_note(url)
            except Exception as exc:
                success, msg = False, str(exc)
                info = None
            if success and info:
                comments = _fetch_comments(api, url, lambda m: _log(task_id, m)) if include_comments else []
                try:
                    folder = exporters.export_note_folder(info, comments, collection)
                    exporters.append_jsonl(info, comments, collection)
                    count += 1
                    _log(task_id, f"  ✓ 已保存：{folder}")
                except Exception as exc:
                    _log(task_id, f"  写入失败：{exc}")
            else:
                _log(task_id, f"✗ {url}（{msg}）")
            _bump(task_id)

        _finish(task_id, "done", result={
            "note_count": count,
            "total": len(urls),
            "collection": collection,
            "dir": os.path.abspath(os.path.join(
                os.path.dirname(__file__), "../datas/exports", collection)),
        })
    except Exception as exc:
        _log(task_id, f"任务失败：{exc}")
        _finish(task_id, "error", error=str(exc))
    finally:
        if auth:
            try:
                auth.close()
            except Exception:
                pass


def _median_worker(task_id: str, req: dict) -> None:
    """后台批量抓取达人阅读/互动中位数（走蒲公英 Cookie）。"""
    from webui import pgy_talents
    try:
        talents = req.get("talents", [])
        if not talents:
            raise RuntimeError("没有可处理的达人")
        if len(talents) > 1000:
            talents = talents[:1000]
        _set_total(task_id, len(talents))
        _log(task_id, f"开始抓取 {len(talents)} 位达人的阅读/互动中位数…")

        def progress(i, total, name):
            _task(task_id)["progress"] = i
            _log(task_id, f"({i}/{total}) {name}")

        pgy_talents.enrich_talents_median(talents, on_progress=progress)
        got = sum(1 for t in talents if t.get("median_read") is not None)
        _log(task_id, f"完成：{got}/{len(talents)} 位达人已获取中位数")
        _finish(task_id, "done", result={
            "talents": talents,
            "got": got,
            "total": len(talents),
        })
    except Exception as exc:
        _log(task_id, f"任务失败：{exc}")
        _finish(task_id, "error", error=str(exc))


def _full_export_worker(task_id: str, req: dict) -> None:
    """后台导出达人完整数据：Excel 汇总 + JSON 完整备份（含详情页数据）。

    db_only=True 时只抓详情写入数据库，不生成 Excel/JSON 文件。
    """
    from webui import pgy_talents
    try:
        talents = req.get("talents", [])
        base_name = req.get("base_name", "蒲公英达人")
        if not talents:
            raise RuntimeError("没有可导出的达人")
        if len(talents) > 1000:
            talents = talents[:1000]
        db_only = bool(req.get("db_only"))
        sync_db = bool(req.get("sync_db")) or db_only
        total_units = len(talents) * (3 if sync_db else 2)
        _set_total(task_id, total_units)
        _log(task_id, f"开始{'写入数据库' if db_only else '导出'} {len(talents)} 位达人的完整数据…")

        def progress(i, total, name):
            _task(task_id)["progress"] = i
            _log(task_id, f"({i}/{total}) {name}")

        result = pgy_talents.export_talents_full(
            talents, base_name, on_progress=progress,
            with_comments=bool(req.get("with_comments")),
            write_files=not db_only,
        )
        if not db_only:
            _log(task_id, f"Excel 已保存：{result['excel_path']}")
            _log(task_id, f"完整数据已保存：{result['json_path']}")

        # 同步到数据库
        db_stats = None
        if sync_db:
            from webui import pg_sync
            _log(task_id, f"正在写入数据库 {len(talents)} 位达人…")
            def db_progress(i, total, name):
                _task(task_id)["progress"] = i + len(talents)
                _log(task_id, f"[数据库] ({i}/{total}) {name}")
            # 用导出结果里的数据库格式直接写入
            db_data = (result or {}).get("db_format") or {"creators": talents, "notes": []}
            db_stats = pg_sync.sync_db_format(db_data, on_progress=db_progress)
            _log(task_id, f"数据库写入完成：新增达人 {db_stats['creators_inserted']}，更新 {db_stats['creators_updated']}，笔记新增 {db_stats['notes_inserted']}，更新 {db_stats['notes_updated']}，失败 {db_stats['failed']}")

        _finish(task_id, "done", result={
            **result,
            "total": len(talents),
            "db_stats": db_stats,
        })
    except Exception as exc:
        _log(task_id, f"任务失败：{exc}")
        _finish(task_id, "error", error=str(exc))

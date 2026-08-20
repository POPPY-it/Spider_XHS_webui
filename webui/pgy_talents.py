# encoding: utf-8
"""蒲公英（KOL 数据）模块：达人筛选、详情、缓存与导出。

蒲公英平台（pgy.xiaohongshu.com）是小红书品牌方找达人做推广的合作平台。
这里封装了达人筛选的完整流程，供 WebUI「达人」页面调用。

蒲公英 Cookie 由用户在浏览器登录后复制，保存在单独的 pgy_cookie 配置文件中，
与 PC 端 COOKIES（.env）分开，互不影响。
"""

import json
import os
import time
from datetime import datetime

import requests
from loguru import logger

from apis.xhs_pugongying_apis import PuGongYingAPI
from xhs_utils.data_util import check_and_create_path
from xhs_utils.xhs_pc.state import PcDeviceProfile, parse_cookie_kv
from xhs_utils.xhs_pugongying_util import generate_pugongying_headers

PGY_COOKIE_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "datas", "pgy_cookie.json")
)
DOWNLOADED_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "datas", "downloaded_talents.json")
)


# ---------------------------------------------------------------------------
# 已下载达人记录（用于去重）
# ---------------------------------------------------------------------------


def load_downloaded() -> dict:
    """读取已下载达人记录，返回 ``{userId: {name, downloaded_at, ...}}``。"""
    try:
        with open(DOWNLOADED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_downloaded(talents: list) -> None:
    """把导出的达人标记为已下载（以 userId 去重）。"""
    rec = load_downloaded()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for t in talents:
        uid = t.get("userId")
        if not uid:
            continue
        rec[uid] = {
            "name": t.get("name", ""),
            "downloaded_at": now,
        }
    check_and_create_path(os.path.dirname(DOWNLOADED_FILE))
    with open(DOWNLOADED_FILE, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)


def annotate_downloaded(talents: list) -> list:
    """给每个达人标记是否已下载过：``t["downloaded"] = True/False``。"""
    rec = load_downloaded()
    for t in talents:
        uid = t.get("userId")
        t["downloaded"] = bool(uid and uid in rec)
    return talents


def remove_downloaded(user_ids: list) -> int:
    """删除指定 userId 的已下载记录，返回删除条数。"""
    rec = load_downloaded()
    removed = 0
    for uid in user_ids:
        if uid in rec:
            del rec[uid]
            removed += 1
    with open(DOWNLOADED_FILE, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return removed


def list_downloaded() -> list:
    """返回已下载记录列表（含 userId），按时间倒序。"""
    rec = load_downloaded()
    items = [{"user_id": uid, **info} for uid, info in rec.items()]
    items.sort(key=lambda x: x.get("downloaded_at", ""), reverse=True)
    return items


# ---------------------------------------------------------------------------
# Cookie 管理
# ---------------------------------------------------------------------------


def get_pgy_cookie() -> str:
    """读取保存的蒲公英 Cookie 字符串；未保存返回空串。"""
    try:
        with open(PGY_COOKIE_FILE, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("cookie", "")
    except (OSError, ValueError):
        return ""


def save_pgy_cookie(cookie: str) -> None:
    """保存蒲公英 Cookie 到配置文件。"""
    check_and_create_path(os.path.dirname(PGY_COOKIE_FILE))
    with open(PGY_COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump({"cookie": cookie, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)


def pgy_cookie_info() -> dict:
    """返回蒲公英 Cookie 的保存状态与摘要（不泄露完整内容）。"""
    cookie = get_pgy_cookie()
    if not cookie:
        return {"saved": False, "has_a1": False, "keys": []}
    keys = list(parse_cookie_kv(cookie).keys())
    return {
        "saved": True,
        "has_a1": "a1" in keys,
        "keys": keys,
        "saved_at": _saved_at(),
    }


def _saved_at() -> str:
    try:
        with open(PGY_COOKIE_FILE, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("saved_at", "")
    except (OSError, ValueError):
        return ""


def check_pgy_status() -> dict:
    """校验蒲公英 Cookie 是否有效（读取已保存的 Cookie）。"""
    cookie = get_pgy_cookie()
    if not cookie:
        return {"valid": False, "error": "未保存蒲公英 Cookie"}
    return verify_pgy_cookie(cookie)


def _cookie_dict() -> dict:
    """读取已保存的蒲公英 Cookie 并解析成 dict（蒲公英 API 需要 dict）。"""
    cookie = get_pgy_cookie()
    if not cookie:
        raise RuntimeError("未保存蒲公英 Cookie")
    return parse_cookie_kv(cookie)


def verify_pgy_cookie(cookie: str) -> dict:
    """校验给定的蒲公英 Cookie 是否有效。"""
    if not cookie:
        return {"valid": False, "error": "Cookie 不能为空"}
    cookies = parse_cookie_kv(cookie)
    try:
        api = PuGongYingAPI()
        res = api.get_self_info(cookies)
        if not isinstance(res, dict):
            return {"valid": False, "error": f"蒲公英返回异常：{res!r}"}
        data = res.get("data")
        if isinstance(data, dict) and data.get("userId"):
            return {"valid": True, "nickname": data.get("nickName", ""), "userId": data["userId"]}
        msg = res.get("msg") or "蒲公英 Cookie 无效，请重新登录复制"
        code = res.get("code")
        if code is not None:
            msg = f"蒲公英返回 code={code}，{msg}"
        return {"valid": False, "error": msg}
    except Exception as e:
        return {"valid": False, "error": f"校验失败：{e}"}


# ---------------------------------------------------------------------------
# 类目树
# ---------------------------------------------------------------------------


def get_categories() -> dict:
    """获取蒲公英内容类目树，供前端下拉选择。"""
    cookies = _cookie_dict()
    api = PuGongYingAPI()
    tree = api.get_all_categories(cookies)
    # 结构：[{taxonomy1Tag, taxonomy2Tags:[...]}, ...]
    return tree


# ---------------------------------------------------------------------------
# 达人搜索
# ---------------------------------------------------------------------------


def build_content_tag(selection: list, tree: list) -> list:
    """根据前端选中的类目节点构造 contentTag 数组。

    selection 元素形如 ``"1"``（一级类目）或 ``"1-2"``（一级下的二级类目）。
    """
    if not selection:
        return []
    content_tag = []
    for sel in selection:
        parts = sel.split("-")
        try:
            first_idx = int(parts[0])
            first = tree[first_idx]
            if len(parts) == 1:
                content_tag.append(first["taxonomy1Tag"])
            else:
                second_idx = int(parts[1])
                content_tag.append(first["taxonomy2Tags"][second_idx])
        except (IndexError, ValueError, KeyError, TypeError):
            continue
    return content_tag


def search_talents(
    *,
    categories=None,
    content_tags=None,
    fans_min=None,
    fans_max=None,
    gender=None,
    location=None,
    personal_tags=None,
    feature_tags=None,
    fans_age=0,
    fans_gender=0,
    trade_type="不限",
    note_type=0,
    page_size=20,
    max_pages=10,
    sort_col="comprehensiverank",
) -> dict:
    """按筛选条件搜索蒲公英达人，返回 ``{talents, total, truncated}``。

    所有筛选字段直接映射到蒲公英接口的请求体（见
    ``xhs_utils/xhs_pugongying_util.get_pugongying_bozhu_data``）。
    """
    cookies = _cookie_dict()
    api = PuGongYingAPI()
    # brandUserId 从当前蒲公英账号信息获取
    self_info = api.get_self_info(cookies)
    brand_user_id = (self_info.get("data") or {}).get("userId")
    if not brand_user_id:
        raise RuntimeError("无法获取蒲公英账号信息，Cookie 可能无效")

    # 构造与前端字段对应的请求体
    payload = {
        "searchType": 1,
        "column": sort_col or "comprehensiverank",
        "sort": "desc",
        "pageSize": page_size,
        "brandUserId": brand_user_id,
        "personalTags": personal_tags or [],
        "featureTags": feature_tags or [],
        "estimatePicReadPrice": [],
        "estimateVideoReadPrice": [],
        "fansNumberLower": fans_min,
        "fansNumberUpper": fans_max,
        "noteType": note_type or 0,
        "gender": gender,
        "location": location,
        "tradeType": trade_type or "不限",
        "fansAge": fans_age or 0,
        "fansGender": fans_gender or 0,
        "fansNumUp": 0,
        "cpc": False,
        "excludeLowActive": False,
        "newHighQuality": 0,
        "efficiencyValid": 0,
        "clothingIndustry": 0,
        "firstIndustry": "",
        "secondIndustry": "",
        "activityCodes": [],
    }
    if content_tags:
        payload["contentTag"] = content_tags

    talents = []
    total = 0
    truncated = False
    for page in range(1, max_pages + 1):
        # 走原生分页接口，页面字段通过 trackId 关联
        page_payload = dict(payload)
        page_payload["pageNum"] = page
        track_id = _get_track_id(api, page_payload, cookies)
        page_payload["trackId"] = track_id
        user_list, total = _fetch_page(api, page_payload, cookies)
        if not user_list:
            break
        talents.extend(user_list)
        if len(talents) >= page_size * max_pages or (total and page * page_size >= total):
            break
        time.sleep(0.5)
    if len(talents) > page_size * max_pages:
        talents = talents[: page_size * max_pages]
        truncated = True
    annotate_downloaded(talents)
    return {"talents": talents, "total": total, "truncated": truncated}


def _get_track_id(api: PuGongYingAPI, payload, cookies) -> str:
    """调用蒲公英 track 接口获取本次搜索的 trackId。"""
    data = json.dumps(payload, separators=(",", ":"))
    res = api.get_track(data, cookies)
    return (res.get("data") or {}).get("trackId", "")


def _fetch_page(api: PuGongYingAPI, payload, cookies):
    """单页请求蒲公英博主列表（模拟 get_user_by_page）。"""
    data = json.dumps(payload, separators=(",", ":"))
    headers = api._signed_headers(cookies, "/api/solar/cooperator/blogger/v2", data)
    response = requests.post(
        api.base_url + "/api/solar/cooperator/blogger/v2",
        headers=headers, cookies=cookies, data=data, timeout=15,
    )
    res_json = response.json()
    total = (res_json.get("data") or {}).get("total", 0)
    user_list = (res_json.get("data") or {}).get("kols", []) or []
    return user_list, total


# ---------------------------------------------------------------------------
# 达人详情
# ---------------------------------------------------------------------------


def get_talent_detail(user_id: str) -> dict:
    """获取单个达人的详细数据：数据总览 + 粉丝画像 + 笔记数据。"""
    cookies = _cookie_dict()
    api = PuGongYingAPI()
    result = {"user_id": user_id}
    try:
        summary = api.get_user_detail(user_id, cookies)
        result["summary"] = summary
    except Exception as e:
        result["summary_error"] = str(e)
    try:
        fans = api.get_user_fans_detail(user_id, cookies)
        result["fans"] = fans
    except Exception as e:
        result["fans_error"] = str(e)
    try:
        notes = api.get_user_notes_detail(user_id, cookies)
        result["notes"] = notes
    except Exception as e:
        result["notes_error"] = str(e)
    return result


def get_note_full_detail(
    note_id: str,
    with_comments: bool = True,
    top_liked: bool = False,
    comment_limit: int = 20,
    max_pages: int = 10,
) -> dict:
    """获取蒲公英笔记的完整详情（标题/正文/图片/视频）+ 评论。

    接口：GET /api/solar/note/{noteId}/detail（正文等）
         GET /api/solar/note/{noteId}/l1_comments（评论，offset 翻页）

    top_liked=True 时：翻页收集评论后按点赞数降序取前 comment_limit 条
    （高赞评论优先）；否则取前 comment_limit 条（接口默认顺序）。
    """
    cookies = _cookie_dict()
    profile = PcDeviceProfile(cookies=cookies)
    base = "https://pgy.xiaohongshu.com"
    result = {"note_id": note_id}

    # 笔记详情
    try:
        splice = f"/api/solar/note/{note_id}/detail"
        headers = generate_pugongying_headers(cookies, splice, profile=profile)
        resp = requests.get(base + splice, headers=headers, cookies=cookies, timeout=15)
        d = resp.json()
        if isinstance(d, dict) and d.get("success"):
            result["detail"] = d.get("data")
        else:
            result["detail_error"] = (d or {}).get("msg", "获取失败")
    except Exception as e:
        result["detail_error"] = str(e)

    # 评论（一级，支持翻页 + 高赞排序）
    if with_comments:
        try:
            all_comments = []
            offset = ""
            total = 0
            for _ in range(max_pages):
                splice = (
                    f"/api/solar/note/{note_id}/l1_comments"
                    f"?offset={offset}&pageSize=20&l2PageSize=3"
                )
                headers = generate_pugongying_headers(cookies, splice, profile=profile)
                resp = requests.get(base + splice, headers=headers, cookies=cookies, timeout=15)
                d = resp.json()
                if not (isinstance(d, dict) and d.get("success")):
                    break
                data = d.get("data") or {}
                total = data.get("l1CommentTotal") or total
                batch = data.get("l1Comments") or []
                if not batch:
                    break
                all_comments.extend(batch)
                # offset 用本页最后一条评论 id 翻页
                last = batch[-1].get("comment") or {}
                offset = str(last.get("idStr") or last.get("id") or "")
                if not offset or len(all_comments) >= total:
                    break
            # 高赞排序取前 N
            if top_liked:
                all_comments.sort(
                    key=lambda c: ((c.get("comment") or {}).get("likeCount") or 0),
                    reverse=True,
                )
            kept = all_comments[:comment_limit]
            result["comments"] = {
                "l1CommentTotal": total,
                "l1Comments": kept,
                "fetched": len(all_comments),
            }
        except Exception as e:
            result["comments_error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# 数据中位数补全
# ---------------------------------------------------------------------------


def enrich_talents_median(talents: list, on_progress=None) -> list:
    """批量拉取每个达人的数据中位数，合并进列表。

    从 ``get_user_detail`` 的 summary 里提取 readMedian / interactionMedian /
    noteNumber，原地写入每个达人 dict 的 ``median_*`` 字段。
    on_progress(n, total, name) 可选回调，供前端显示进度。
    """
    cookies = _cookie_dict()
    api = PuGongYingAPI()
    total = len(talents)
    for i, t in enumerate(talents, 1):
        uid = t.get("userId")
        if not uid:
            t["median_read"] = None
            t["median_interaction"] = None
            t["median_note"] = None
            continue
        try:
            d = api.get_user_detail(uid, cookies)
            data = (d.get("data") or {}) if isinstance(d, dict) else {}
            t["median_read"] = data.get("readMedian")
            t["median_interaction"] = data.get("interactionMedian")
            t["median_note"] = data.get("noteNumber")
        except Exception as e:
            t["median_read"] = None
            t["median_interaction"] = None
            t["median_note"] = None
        if on_progress:
            on_progress(i, total, t.get("name", ""))
    return talents


def _median_display(v):
    """把中位数转成可读的字符串（万）。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return ""
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------


def export_talents_to_excel(talents: list, excel_path: str) -> str:
    """把达人列表写入 Excel，返回文件路径。"""
    import openpyxl

    headers = [
        "昵称", "小红书号", "粉丝数", "达人标签", "内容类目",
        "图文报价(元)", "视频报价(元)", "地区", "性别", "达人ID", "蒲公英主页",
        "阅读中位数", "互动中位数", "笔记数",
    ]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "达人"
    ws.append(headers)
    for t in talents:
        content_tags = []
        for ct in t.get("contentTags") or []:
            content_tags.append(ct.get("taxonomy1Tag", ""))
            for sub in ct.get("taxonomy2Tags") or []:
                content_tags.append(f"{ct.get('taxonomy1Tag','')}/{sub}")
        ws.append([
            t.get("name", ""),
            t.get("redId", ""),
            t.get("fansNum", t.get("fansCount", "")),
            "、".join(t.get("personalTags") or []),
            "、".join(content_tags),
            _fmt_price(t.get("picturePrice")),
            _fmt_price(t.get("videoPrice")),
            t.get("location", ""),
            t.get("gender", ""),
            t.get("userId", ""),
            f"https://www.xiaohongshu.com/user/profile/{t.get('userId','')}" if t.get("userId") else "",
            _median_display(t.get("median_read")),
            _median_display(t.get("median_interaction")),
            t.get("median_note") if t.get("median_note") is not None else "",
        ])
    check_and_create_path(os.path.dirname(excel_path))
    wb.save(excel_path)
    return excel_path


def export_talents_full(
    talents: list,
    base_name: str,
    on_progress=None,
    with_comments: bool = True,
    write_files: bool = True,
) -> dict:
    """导出完整达人数据：逐个拉详情，生成 Excel + JSON 完整备份。

    write_files=False 时只抓详情不写文件（用于只写数据库）。
    返回 ``{excel_path, json_path, count, failed}``。
    每位达人抓取 summary / fans / notes 三块详情，和列表字段一起保存。
    """
    import json
    from webui.pgy_talents import enrich_talents_median

    # 1. 先批量补中位数（详情接口已包含 summary/fans/notes，这里一并拉）
    enrich_talents_median(talents, on_progress=on_progress)

    # 2. 再拉完整详情（fans / notes 等中位数没覆盖的）+ 每篇笔记正文和评论
    cookies = _cookie_dict()
    api = PuGongYingAPI()
    failed = 0
    for i, t in enumerate(talents, 1):
        uid = t.get("userId")
        if not uid:
            failed += 1
            continue
        try:
            summary = api.get_user_detail(uid, cookies)
            fans = api.get_user_fans_detail(uid, cookies)
            notes = api.get_user_notes_detail(uid, cookies)
            # 每篇笔记抓正文 + 评论
            notes_data = (notes.get("data") or {}) if isinstance(notes, dict) else {}
            note_list = notes_data.get("notes") or []
            full_notes = []
            for n in note_list:
                note_id = n.get("noteId")
                if not note_id:
                    full_notes.append(n)
                    continue
                try:
                    nd = get_note_full_detail(
                        note_id,
                        with_comments=with_comments,
                        top_liked=True,
                        comment_limit=20,
                    )
                    merged = dict(n)
                    if nd.get("detail"):
                        merged["full_detail"] = nd["detail"]
                    if nd.get("comments"):
                        merged["comments"] = nd["comments"]
                    full_notes.append(merged)
                except Exception:
                    full_notes.append(n)
                import time as _t
                _t.sleep(0.3)
            if full_notes:
                notes_data = dict(notes_data)
                notes_data["notes"] = full_notes
            t["detail"] = {
                "summary": summary,
                "fans": fans,
                "notes": notes_data,
            }
        except Exception:
            t["detail"] = None
            failed += 1
        if on_progress:
            on_progress(i, len(talents), t.get("name", ""))
        import time as _t
        _t.sleep(0.3)

    # 3. 写 Excel（列表字段）到 datas/excel_datas/（write_files=False 时跳过）
    excel_path = ""
    json_path = ""
    if write_files:
        excel_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "../datas/excel_datas"))
        check_and_create_path(excel_dir)
        excel_path = os.path.join(excel_dir, f"{os.path.basename(base_name)}.xlsx")
        export_talents_to_excel(talents, excel_path)

        # 标记导出过的达人为"已下载"，避免下次重复
        mark_downloaded(talents)

        # 4. 写 JSON 完整数据（数据库格式：只保留 SocialCreator / SocialNote 需要的字段）
        json_path = os.path.join(excel_dir, f"{os.path.basename(base_name)}_完整数据.json")
        from webui.pg_convert import build_db_format
        _db_json = build_db_format(talents)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(_db_json, f, ensure_ascii=False, indent=1)

    return {
        "excel_path": excel_path,
        "json_path": json_path,
        "count": len(talents),
        "failed": failed,
        "db_format": _db_json,
    }


def _fmt_price(v):
    """报价单位是分，转成元展示。"""
    try:
        return round(float(v) / 100)
    except (TypeError, ValueError):
        return ""

# encoding: utf-8
"""登录桥接：账号状态、Cookie 保存、网页内二维码登录。

二维码登录复用了项目内完整的 ``XHSLoginApi.qrcode_login`` 流程，只对该
单个实例做实例级方法遮蔽：

- ``show_qrcode_image`` 换成"捕获 qr_url"而不是弹系统窗口；
- ``check_qrcode_status`` 包一层，把 请扫描/请确认/已过期 状态记录下来。

属性查找规则：实例属性优先于类属性，且实例上的普通函数按普通函数返回，
不绑定 self，因此可以安全遮蔽 staticmethod，无需改类、无全局副作用。
"""

import io
import os
import threading

import qrcode
from dotenv import load_dotenv, set_key

from apis.xhs_pc_login_apis import XHSLoginApi
from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc.auth import XHSPcAuth

ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))

_QR_LOCK = threading.Lock()
_qr_state = None  # {active, state, message, qr_url, nickname, error}


def read_cookies() -> str:
    """从 .env 读取 COOKIES；override=True 保证拿到磁盘最新值。"""
    load_dotenv(ENV_PATH, override=True)
    return os.getenv("COOKIES", "")


def save_cookie_to_env(cookie: str) -> None:
    set_key(ENV_PATH, "COOKIES", cookie)


def _build_authed_api(cookie: str = None):
    """构造一个独立的已登录 XHS_Apis，调用方负责 close()。"""
    cookie = cookie or read_cookies()
    if not cookie:
        raise RuntimeError("未配置 COOKIES，请先在 .env 中填写或扫码登录")
    auth = XHSPcAuth.from_cookie(cookie)
    api = XHS_Apis(auth).bootstrap()
    return auth, api


def check_auth_status() -> dict:
    """校验 .env 中当前 Cookie，返回 ``{valid, user?, error?}``。"""
    try:
        auth, api = _build_authed_api()
        try:
            success, msg, res = api.get_user_me()
            if not success:
                return {"valid": False, "error": f"登录态无效：{msg}"}
            data = (res or {}).get("data") or {}
            nickname = data.get("nickname") or ""
            red_id = data.get("red_id") or ""
            avatar = ""
            basic = data.get("basic_info") or {}
            if basic.get("imageb"):
                avatar = basic["imageb"]
            elif basic.get("images"):
                avatar = basic["images"]
            return {
                "valid": True,
                "user": {"nickname": nickname, "red_id": red_id, "avatar": avatar},
            }
        finally:
            auth.close()
    except Exception as e:
        return {"valid": False, "error": str(e)}


def save_cookie_and_verify(cookie: str) -> dict:
    """校验并保存新 Cookie；校验失败不落盘。返回 ``{success, nickname?, error?}``。"""
    cookie = (cookie or "").strip()
    if not cookie:
        return {"success": False, "error": "Cookie 不能为空"}
    try:
        auth, api = _build_authed_api(cookie)
        try:
            success, msg, res = api.get_user_me()
            if not success:
                return {"success": False, "error": f"Cookie 无效：{msg}"}
            data = (res or {}).get("data") or {}
            nickname = data.get("nickname") or "未知用户"
        finally:
            auth.close()
        save_cookie_to_env(cookie)
        return {"success": True, "nickname": nickname}
    except Exception as e:
        return {"success": False, "error": f"Cookie 解析失败：{e}"}


# ---------------------------------------------------------------------------
# 二维码登录
# ---------------------------------------------------------------------------


def start_qr_login() -> None:
    """启动二维码登录后台线程。若已有登录进行中则抛 RuntimeError。"""
    global _qr_state
    with _QR_LOCK:
        if _qr_state and _qr_state.get("active"):
            raise RuntimeError("已有扫码登录进行中")
        _qr_state = {
            "active": True,
            "state": "preparing",
            "message": "正在初始化匿名设备…",
            "qr_url": None,
            "nickname": None,
            "error": None,
        }
    threading.Thread(target=_qr_worker, daemon=True).start()


def qr_state() -> dict:
    """供 HTTP 层返回当前二维码登录状态。"""
    st = _qr_state
    if not st or not st.get("active"):
        return {"state": "idle"}
    out = {
        "state": st.get("state", "preparing"),
        "message": st.get("message", ""),
        "nickname": st.get("nickname"),
    }
    if st.get("state") == "failed":
        out["error"] = st.get("error", "")
    return out


def qr_image_png() -> bytes:
    """把捕获到的 qr_url 渲染成 PNG；未就绪抛 ValueError。"""
    st = _qr_state
    if not st or not st.get("active"):
        raise ValueError("没有进行中的扫码登录")
    url = st.get("qr_url")
    if not url:
        raise ValueError("二维码尚未生成")
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _qr_worker() -> None:
    global _qr_state
    login = XHSLoginApi()
    captured: dict = {"qr_url": None, "status": "", "expired": False}
    real_check = login.check_qrcode_status

    def _capture_qr(url: str) -> None:
        captured["qr_url"] = url
        _qr_state["qr_url"] = url

    def _wrapped_check(qr_id, code, cookies):
        success, msg, cookies = real_check(qr_id, code, cookies)
        captured["status"] = msg or ""
        if "过期" in captured["status"]:
            captured["expired"] = True
        _qr_state["message"] = msg or ""
        if "过期" in _qr_state["message"]:
            _qr_state["state"] = "expired"
        elif "确认" in _qr_state["message"]:
            _qr_state["state"] = "waiting_confirm"
        elif "扫描" in _qr_state["message"]:
            if _qr_state.get("qr_url"):
                _qr_state["state"] = "waiting_scan"
        return success, msg, cookies

    # 实例级遮蔽：这两个方法在 qrcode_login 内部通过 self.xxx 调用。
    login.show_qrcode_image = _capture_qr
    login.check_qrcode_status = _wrapped_check

    try:
        cookie_str = login.qrcode_login(
            show_in_terminal=False, timeout_seconds=300, poll_interval=2.0
        )
        if not cookie_str:
            if captured.get("expired"):
                _qr_state.update(state="failed", error="二维码已过期，请重新生成")
            else:
                _qr_state.update(state="failed", error="扫码登录未完成（未扫描或已取消）")
            return
        save_cookie_to_env(cookie_str)
        nickname = ""
        try:
            auth = XHSPcAuth.from_cookie(cookie_str)
            api = XHS_Apis(auth).bootstrap()
            ok, _, res = api.get_user_me()
            if ok:
                data = (res or {}).get("data") or {}
                nickname = data.get("nickname") or ""
            auth.close()
        except Exception:
            pass
        _qr_state.update(
            state="success",
            nickname=nickname or None,
            message=f"登录成功：{nickname}".strip() or "登录成功",
        )
    except Exception as exc:
        _qr_state.update(state="failed", error=str(exc), message=str(exc))
    finally:
        login.close()
        _qr_state["active"] = False


# ---------------------------------------------------------------------------
# Playwright 真实浏览器扫码登录（绕过 verifyType=120 设备安全验证风控）
# ---------------------------------------------------------------------------

_browser_login_state = None
_BROWSER_LOGIN_LOCK = threading.Lock()


def start_browser_login() -> None:
    """启动 Playwright 浏览器扫码登录后台线程；已有进行中则抛 RuntimeError。"""
    global _browser_login_state
    with _BROWSER_LOGIN_LOCK:
        if _browser_login_state and _browser_login_state.get("active"):
            raise RuntimeError("已有浏览器扫码登录进行中")
        _browser_login_state = {
            "active": True,
            "state": "running",
            "message": "浏览器已打开，请扫码登录",
        }
    threading.Thread(target=_browser_login_worker, daemon=True).start()


def browser_login_state() -> dict:
    st = _browser_login_state
    if not st:
        return {"state": "idle"}
    out = {"state": st.get("state", "running"), "message": st.get("message", "")}
    if st.get("state") == "failed":
        out["error"] = st.get("message", "")
    return out


def _browser_login_worker() -> None:
    global _browser_login_state
    try:
        from webui.playwright_login import browser_login
        cookie = browser_login()
        save_cookie_to_env(cookie)
        # 拿昵称
        nickname = ""
        try:
            auth, api = _build_authed_api(cookie)
            ok, _, res = api.get_user_me()
            if ok:
                data = (res or {}).get("data") or {}
                nickname = data.get("nickname") or ""
            auth.close()
        except Exception:
            pass
        _browser_login_state.update(
            state="success",
            message=f"登录成功：{nickname}".strip() or "登录成功",
            nickname=nickname or None,
        )
    except Exception as exc:
        _browser_login_state.update(state="failed", message=str(exc))
    finally:
        _browser_login_state["active"] = False

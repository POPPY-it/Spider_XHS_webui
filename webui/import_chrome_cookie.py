# encoding: utf-8
"""从本机 Chrome 读取小红书 Cookie，验证真实登录后写入 .env。

依赖：browser_cookie3（处理 Chrome 新版加密/密钥派生）。
"""
import os
import sys

PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT)

from webui.login_bridge import _me_from_cookie, save_cookie_to_env  # noqa: E402


def load_chrome_cookies() -> str:
    import browser_cookie3

    cj = browser_cookie3.chrome(domain_name=".xiaohongshu.com")
    parts = []
    for c in cj:
        parts.append(f"{c.name}={c.value}")
    return "; ".join(parts)


def import_from_chrome() -> dict:
    """从本机 Chrome 读取小红书 Cookie，验证真实登录后写入 .env。

    返回 ``{success, nickname?, red_id?, error?}``。
    """
    try:
        cookie_str = load_chrome_cookies()
    except Exception as exc:
        return {"success": False, "error": f"读取 Chrome Cookie 失败：{exc}"}
    if not cookie_str:
        return {"success": False, "error": "Chrome 里没有小红书 Cookie，请先在 Chrome 登录 xiaohongshu.com"}
    user = _me_from_cookie(cookie_str)
    if not user:
        return {"success": False, "error": "Chrome 中的会话无效或为游客，请先在 Chrome 重新登录"}
    save_cookie_to_env(cookie_str)
    return {"success": True, "nickname": user.get("nickname"), "red_id": user.get("red_id")}


def main():
    os.chdir(PROJECT)
    result = import_from_chrome()
    if not result.get("success"):
        print("FAILED:", result.get("error"))
        return 1
    print(f"OK: 已写入 .env，账号昵称 = {result.get('nickname')!r} red_id = {result.get('red_id')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

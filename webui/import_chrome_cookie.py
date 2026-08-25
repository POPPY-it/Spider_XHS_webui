# encoding: utf-8
"""从本机 Chrome 读取小红书 Cookie，验证真实登录后写入 .env。

依赖：browser_cookie3（处理 Chrome 新版加密/密钥派生）。
"""
import os
import sys

PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from webui.login_bridge import _me_from_cookie, save_cookie_to_env  # noqa: E402


def load_chrome_cookies() -> str:
    import browser_cookie3

    cj = browser_cookie3.chrome(domain_name=".xiaohongshu.com")
    parts = []
    for c in cj:
        parts.append(f"{c.name}={c.value}")
    return "; ".join(parts)


def main():
    cookie_str = load_chrome_cookies()
    print(f"从 Chrome 读到 xiaohongshu Cookie，长度: {len(cookie_str)}")
    user = _me_from_cookie(cookie_str)
    if not user:
        print("FAILED: 该 Cookie 是游客会话或无效，未写入 .env")
        return 1
    save_cookie_to_env(cookie_str)
    print(f"OK: 已写入 .env，账号昵称 = {user.get('nickname')!r} red_id = {user.get('red_id')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

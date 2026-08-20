# encoding: utf-8
"""扫码登录并把完整 Cookie 保存到 .env，下次可直接用 cookie 模式免扫码。

用法：
    source venv/bin/activate
    python save_login_cookie.py
"""

from dotenv import set_key
from xhs_utils.xhs_pc import XHSPcAuth

ENV_PATH = ".env"


def main() -> None:
    print("=" * 60)
    print("1) 将弹出二维码窗口，请用小红书 App 扫码并确认登录")
    print("2) 登录成功后自动把 Cookie 写入 .env 的 COOKIES 字段")
    print("=" * 60)

    auth = XHSPcAuth.from_qrcode_login(show_in_terminal=False)
    if not auth.cookies:
        raise RuntimeError("登录失败，未获取到 Cookie")

    cookie_str = auth.cookies
    set_key(ENV_PATH, "COOKIES", cookie_str)
    print(f"✅ 登录成功，Cookie 已保存到 {ENV_PATH}")
    print(f"   Cookie 长度: {len(cookie_str)} 字符")
    print("   之后在 spider.py 里把 login_type 设为 'cookie' 即可免扫码运行")
    auth.close()


if __name__ == "__main__":
    main()

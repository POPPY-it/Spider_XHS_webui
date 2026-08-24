# encoding: utf-8
"""Playwright 真实浏览器扫码登录，绕过 verifyType=120 设备安全验证风控。

小红书对非浏览器环境（curl_cffi 模拟指纹）会触发设备安全验证（二次扫码）。
用 Playwright 真实浏览器登录，指纹真实，不会触发该风控。

用法：
    from webui.playwright_login import browser_login
    cookie_str = browser_login()   # 弹出浏览器窗口，用户扫码后返回完整 Cookie
"""

import time

from dotenv import set_key
from playwright.sync_api import sync_playwright

# 防检测：浏览器启动参数
BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-web-security',
    '--disable-features=IsolateOrigins,site-per-process',
]

# 防检测：额外请求头
EXTRA_HEADERS = {
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

# 防检测：反自动化 JS
ANTI_DETECTION_JS = '''
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
    window.chrome = {runtime: {}};
'''

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')


def browser_login(timeout: int = 180) -> str:
    """弹出浏览器窗口让用户扫码登录，成功后返回完整 Cookie 字符串。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=BROWSER_ARGS)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent=USER_AGENT,
            extra_http_headers=EXTRA_HEADERS,
        )
        context.add_init_script(ANTI_DETECTION_JS)
        page = context.new_page()

        # 监听 qrcode/status 响应，检测登录成功
        login_ok = {'flag': False}

        def on_response(response):
            try:
                if 'login/qrcode/status' in response.url:
                    d = response.json()
                    data = d.get('data') or {}
                    if data.get('code_status') == 2:
                        login_ok['flag'] = True
            except Exception:
                pass

        page.on('response', on_response)

        print('正在打开小红书登录页，请在浏览器窗口扫码...')
        page.goto('https://www.xiaohongshu.com/explore', wait_until='domcontentloaded')

        deadline = time.time() + timeout
        while time.time() < deadline:
            if login_ok['flag']:
                break
            # 备选检测：URL 跳转到用户主页，或登录弹窗消失
            if '/user/profile' in page.url or page.locator('.user .reds').count() > 0:
                login_ok['flag'] = True
                break
            time.sleep(1)

        # 无论 XHR 是否捕获到，等 2 秒让 Cookie 稳定
        time.sleep(2)

        cookies = context.cookies()
        cookie_str = '; '.join(f"{c['name']}={c['value']}" for c in cookies)
        browser.close()

        if not login_ok['flag']:
            raise RuntimeError('登录超时：未检测到登录成功')

        if 'web_session' not in cookie_str:
            raise RuntimeError('登录未完成：Cookie 中缺少 web_session')

        return cookie_str


def save_login_cookie() -> str:
    """扫码登录并把 Cookie 写入 .env，返回 Cookie 字符串。"""
    cookie_str = browser_login()
    set_key('.env', 'COOKIES', cookie_str)
    print('✅ 登录成功，Cookie 已保存到 .env')
    return cookie_str


if __name__ == '__main__':
    save_login_cookie()

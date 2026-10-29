import os
"""U8：真实服务器上的三引擎探针（补充 LiveServerTestCase 的引擎盲区）。

背景：WebKit 在 Django `LiveServerTestCase`（WSGI 线程服务器）下登录时，
`/r21/login/` 会因 `Save with update_fields did not affect any rows` 返回 500；
该现象在**真实 runserver** 上不复现。本脚本用真实服务器验证三引擎，
为 E2E 报告提供 WebKit 的证据。

用法（先启动 runserver，再执行）：
    conda run -n smass python scripts/r10_browser_probe.py
"""
import json
import sys

BASE = 'http://127.0.0.1:8000'
LOGIN = 'admin'
PASSWORD = os.environ.get('SMASS_DEMO_PASSWORD', 'Demo#2024')

PAGES = ['/r10/', '/r4/units/', '/r5/years/', '/r6/definitions/',
         '/r7/dashboard/', '/r8/docs/', '/r9/status/']


def probe(engine_name, launcher):
    from playwright.sync_api import sync_playwright  # noqa: F401

    result = {'engine': engine_name, 'ok': False, 'steps': []}

    try:
        browser = launcher.launch(headless=True)
    except Exception as exc:  # noqa: BLE001
        result['error'] = 'launch failed: {}'.format(str(exc)[:160])
        return result

    try:
        ctx = browser.new_context(viewport={'width': 1280, 'height': 860})
        page = ctx.new_page()
        page.set_default_timeout(20000)

        # 1) 登录页
        resp = page.goto(BASE + '/r21/login/')
        result['steps'].append({'step': 'login_page', 'status': resp.status})

        # 2) 真实表单登录
        page.fill('#id_login_name', LOGIN)
        page.fill('#id_password', PASSWORD)
        page.click('#btnLogin')
        page.wait_for_load_state('load')
        result['steps'].append({'step': 'login', 'url': page.url,
                                'ok': page.url.endswith('/r10/')})

        # 3) 逐页可达 + 无溢出
        pages_ok = True
        for path in PAGES:
            resp = page.goto(BASE + path)
            page.wait_for_load_state('load')
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth"
                " > document.documentElement.clientWidth + 1")
            has_sidebar = page.evaluate(
                "() => !!document.getElementById('sm-sidebar')")
            ok = resp.status == 200 and not overflow and has_sidebar
            pages_ok = pages_ok and ok
            result['steps'].append({
                'step': 'page', 'path': path, 'status': resp.status,
                'overflow': overflow, 'sidebar': has_sidebar, 'ok': ok,
            })

        # 4) 移动端抽屉（复用已登录的 cookies，否则会落到 403 页）
        cookies = ctx.cookies()
        mctx = browser.new_context(viewport={'width': 390, 'height': 844},
                                   is_mobile=True, has_touch=True)
        mctx.add_cookies(cookies)
        mp = mctx.new_page()
        mp.set_default_timeout(20000)
        mp.goto(BASE + '/r5/years/')
        mp.wait_for_load_state('load')
        mp.click('#sm-drawer-toggle')
        mp.wait_for_timeout(400)
        drawer_open = mp.evaluate(
            "() => document.getElementById('sm-sidebar').classList.contains('is-open')")
        mp.keyboard.press('Escape')
        mp.wait_for_timeout(300)
        drawer_closed = mp.evaluate(
            "() => !document.getElementById('sm-sidebar').classList.contains('is-open')")
        mctx.close()

        result['steps'].append({
            'step': 'mobile_drawer', 'open': drawer_open,
            'close_on_escape': drawer_closed,
            'ok': drawer_open and drawer_closed,
        })

        result['ok'] = pages_ok and drawer_open and drawer_closed
    except Exception as exc:  # noqa: BLE001
        result['error'] = '{}: {}'.format(type(exc).__name__, str(exc)[:200])
    finally:
        browser.close()

    return result


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        results = []
        for name in ('chromium', 'firefox', 'webkit'):
            launcher = getattr(pw, name, None)
            if launcher is None:
                results.append({'engine': name, 'ok': False,
                                'error': 'engine unavailable'})
                continue
            results.append(probe(name, launcher))

    payload = {
        'ok': all(r['ok'] for r in results),
        'engines': results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

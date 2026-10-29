"""H4：可访问性加固验证。

覆盖：
- skip-to-content 链接
- 每页恰好一个 h1
- 表单错误 aria-describedby / aria-invalid 关联
- 200% 缩放（等效 640x430 视口）无横向溢出
- 高对比 / 强制颜色模式（若引擎支持）
- 键盘可达与焦点可见

未覆盖项（如实标注，见 docs/SMASS_R10_Accessibility_Audit.md）：
- 屏幕阅读器实机（NVDA/JAWS/VoiceOver）
- axe-core 自动扫描（本机无离线包）
"""
import os
import re
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.test import TestCase
from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

PASSWORD = 'H4Pass#2024'
ENGINE = os.environ.get('H4_BROWSER', 'chromium').strip().lower()

PAGES = ['/r10/', '/r4/units/', '/r4/students/', '/r4/import/',
         '/r5/years/', '/r5/courses/', '/r5/sections/',
         '/r6/definitions/', '/r6/tasks/', '/r6/notifications/',
         '/r7/dashboard/', '/r7/metrics/', '/r8/docs/', '/r9/status/']

FORM_PAGES = ['/r4/units/new/', '/r5/years/new/', '/r6/definitions/new/']


def make_account(login, role=RoleCode.SYSTEM_ADMIN):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin')
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    core_services.grant_role(account, role, granted_by='h4')
    return Account.objects.get(pk=account.pk)


class SkipLinkAndHeadingTests(TestCase):
    """不依赖浏览器即可断言的静态结构。"""

    def setUp(self):
        self.account = make_account('H4STATIC')
        self.client.force_login(self.account)

    def test_skip_link_present_and_targets_main(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        self.assertIn('class="sm-skip"', body)
        self.assertIn('href="#sm-content"', body)
        # 跳转目标必须存在
        self.assertIn('id="sm-content"', body)

    def test_skip_link_is_first_focusable(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        skip_pos = body.find('sm-skip')
        nav_pos = body.find('sm-nav-link')
        self.assertGreater(skip_pos, -1)
        self.assertGreater(nav_pos, -1)
        self.assertLess(skip_pos, nav_pos, 'skip link 不在导航之前')

    def test_each_page_has_exactly_one_h1(self):
        offenders = []
        for url in PAGES:
            body = self.client.get(url).content.decode('utf-8')
            # 只统计 <body> 内的 h1（排除注释/脚本）
            count = len(re.findall(r'<h1\b', body))
            if count != 1:
                offenders.append((url, count))
        self.assertEqual(offenders, [], 'h1 数量异常: {}'.format(offenders))

    def test_form_pages_have_one_h1(self):
        for url in FORM_PAGES:
            body = self.client.get(url).content.decode('utf-8')
            self.assertEqual(
                len(re.findall(r'<h1\b', body)), 1, url)

    def test_login_page_has_h1(self):
        self.client.logout()
        body = self.client.get('/r21/login/').content.decode('utf-8')
        self.assertIn('<h1', body)


class FormErrorAssociationTests(TestCase):
    """错误消息必须通过 aria-describedby 与字段关联。"""

    def setUp(self):
        self.account = make_account('H4FORM')
        self.client.force_login(self.account)

    def test_unit_form_invalid_field_has_aria(self):
        resp = self.client.post('/r4/units/new/', {
            'code': '', 'name': '缺编码', 'unit_type': 'college', 'parent': '',
        })
        body = resp.content.decode('utf-8')

        self.assertIn('aria-describedby="err-code"', body)
        self.assertIn('aria-invalid="true"', body)
        # 被引用的 id 必须存在
        self.assertIn('id="err-code"', body)

    def test_all_error_ids_are_referenced(self):
        resp = self.client.post('/r4/units/new/', {
            'code': '', 'name': '', 'unit_type': '', 'parent': '',
        })
        body = resp.content.decode('utf-8')

        ids = set(re.findall(r'id="(err-\w+)"', body))
        referenced = set(re.findall(r'aria-describedby="(err-\w+)"', body))
        self.assertTrue(ids, '没有错误元素')
        orphan = ids - referenced
        self.assertEqual(orphan, set(), '这些错误 id 未被任何字段引用: {}'.format(orphan))

    def test_valid_submit_has_no_aria_invalid(self):
        resp = self.client.post('/r4/units/new/', {
            'code': 'H4OK', 'name': '可访问学院', 'unit_type': 'college',
            'parent': '', 'sort_order': '0',
        })
        # 成功后重定向，不应停留在含 aria-invalid 的表单
        self.assertEqual(resp.status_code, 302)


@unittest.skipIf(sync_playwright is None, 'playwright unavailable')
class BrowserA11yTests(StaticLiveServerTestCase):
    host = '127.0.0.1'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        launcher = getattr(cls._pw, ENGINE, None)
        if launcher is None:
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('engine {} unavailable'.format(ENGINE))
        cls.browser = launcher.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.account = make_account('H4BROWSER')
        self.context = self.browser.new_context(
            viewport={'width': 1280, 'height': 860})
        self.page = self.context.new_page()
        self.page.set_default_timeout(20000)
        # 真实表单登录
        self.page.goto(self.live_server_url + '/r21/login/')
        self.page.fill('#id_login_name', 'H4BROWSER')
        self.page.fill('#id_password', PASSWORD)
        self.page.click('#btnLogin')
        self.page.wait_for_load_state('load')

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    def _no_overflow(self, page):
        return page.evaluate(
            "() => document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth + 1")

    def test_skip_link_visible_on_focus(self):
        page = self.page
        page.goto(self.live_server_url + '/r5/years/')
        page.wait_for_load_state('load')

        # 初始在视口外
        initial = page.evaluate("""
            () => {
              const el = document.querySelector('.sm-skip');
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return {left: r.left, visible: r.left >= 0 && r.width > 0};
            }
        """)
        self.assertIsNotNone(initial, 'skip link 不存在')
        self.assertFalse(initial['visible'], 'skip link 初始就可见')

        # 聚焦后进入视口
        focused = page.evaluate("""
            () => {
              const el = document.querySelector('.sm-skip');
              el.focus();
              const r = el.getBoundingClientRect();
              return {left: r.left, visible: r.left >= 0 && r.width > 0,
                      focused: document.activeElement === el};
            }
        """)
        self.assertTrue(focused['focused'])
        self.assertTrue(focused['visible'], '聚焦后 skip link 仍不可见')

    def test_200_percent_zoom_no_overflow(self):
        """200% 缩放等效布局视口 640x430，不应出现横向溢出。"""
        page = self.context.new_page()
        page.set_viewport_size({'width': 640, 'height': 430})

        offenders = []
        for path in ('/r10/', '/r4/units/', '/r5/years/', '/r7/dashboard/',
                     '/r8/docs/', '/r9/status/'):
            page.goto(self.live_server_url + path)
            page.wait_for_load_state('load')
            if not self._no_overflow(page):
                offenders.append(path)

        page.close()
        self.assertEqual(offenders, [], '200% 缩放下溢出: {}'.format(offenders))

    def test_forced_colors_media_rule_exists(self):
        page = self.page
        page.goto(self.live_server_url + '/r10/')
        page.wait_for_load_state('load')

        found = page.evaluate("""
            () => {
              for (const sheet of document.styleSheets) {
                try {
                  for (const rule of sheet.cssRules) {
                    if (rule.conditionText &&
                        rule.conditionText.includes('forced-colors')) {
                      return true;
                    }
                  }
                } catch (e) {}
              }
              return false;
            }
        """)
        self.assertTrue(found, 'CSS 缺少 forced-colors 规则')

    def test_forced_colors_emulation(self):
        """若引擎支持 forced_colors 模拟则验证，否则跳过并记录。"""
        page = self.page
        try:
            page.emulate_media(forced_colors='active')
        except Exception:  # noqa: BLE001
            self.skipTest('{} 不支持 forced_colors 模拟'.format(ENGINE))

        page.goto(self.live_server_url + '/r5/years/')
        page.wait_for_load_state('load')

        # 强制颜色下仍应无溢出，且侧边栏可见
        self.assertTrue(self._no_overflow(page))
        self.assertTrue(page.evaluate(
            "() => !!document.getElementById('sm-sidebar')"))

    def test_keyboard_reaches_skip_then_nav(self):
        """Tab 顺序：skip link 应先于导航（Chromium/Firefox）。"""
        if ENGINE not in ('chromium', 'firefox'):
            self.skipTest('WebKit 默认 Tab 只停表单控件')

        page = self.page
        page.goto(self.live_server_url + '/r10/')
        page.wait_for_load_state('load')
        page.evaluate("() => document.body.focus()")

        page.keyboard.press('Tab')
        first = page.evaluate("""
            () => {
              const el = document.activeElement;
              return {cls: el.className || '', text: (el.textContent || '').trim()};
            }
        """)
        self.assertIn('sm-skip', first['cls'],
                      '第一个 Tab 应落在 skip link，实际: {}'.format(first))
        self.assertIn('跳到主要内容', first['text'])

    def test_aria_live_regions_present(self):
        page = self.page
        page.goto(self.live_server_url + '/r10/')
        page.wait_for_load_state('load')
        count = page.evaluate(
            "() => document.querySelectorAll('[aria-live=\"polite\"]').length")
        self.assertGreater(count, 0, '缺少 aria-live 区域')

    def test_table_headers_have_scope_or_theads(self):
        page = self.page
        page.goto(self.live_server_url + '/r5/years/')
        page.wait_for_load_state('load')
        ok = page.evaluate("""
            () => {
              const tables = Array.from(document.querySelectorAll('table.sm-table'));
              if (!tables.length) return false;
              return tables.every(t => t.querySelector('thead'));
            }
        """)
        self.assertTrue(ok, '存在没有 thead 的表格')

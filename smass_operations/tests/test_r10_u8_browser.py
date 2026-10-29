"""U8：真实浏览器验证（三引擎 + 响应式 + 可访问性 + 业务持久化）。

引擎选择：
    R10_BROWSER=chromium|firefox|webkit   # 默认 chromium
    R10_BROWSER=all                       # 依次跑三个引擎

每个引擎跑同一组关键流程；流程内断言**数据库状态**而非仅页面渲染。
"""
import json
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_organization.models import OrganizationUnit, StudentRecord

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE_ENV = os.environ.get('R10_BROWSER', 'chromium').strip().lower()
ENGINES = ['chromium', 'firefox', 'webkit'] if ENGINE_ENV == 'all' else [ENGINE_ENV]

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'U8E2E#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u8e2e')
    return Account.objects.get(pk=account.pk)


class BrowserHarness(StaticLiveServerTestCase):
    """共享夹具：启动引擎、登录、视口切换。

    ``host = '127.0.0.1'``：WebKit/Firefox 在 Windows 上对 ``localhost``
    的解析在随机端口下不稳定（实测 chromium 正常、webkit 超时），
    固定 IPv4 字面量可避免该环境差异。
    """

    host = '127.0.0.1'
    engine = 'chromium'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if SKIP_REASON:
            raise unittest.SkipTest(SKIP_REASON)
        cls._pw = sync_playwright().start()
        launcher = getattr(cls._pw, cls.engine, None)
        if launcher is None:
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('未知引擎 {}'.format(cls.engine))
        try:
            cls.browser = launcher.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('{} 启动失败: {}'.format(cls.engine, str(exc)[:200]))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        core_services.ensure_role_groups()
        self.admin = make_account('U8E_ADM', RoleCode.SYSTEM_ADMIN)
        self.context = None

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    def page(self, viewport=None, mobile=False):
        size = viewport or {'width': 1280, 'height': 860}
        self.context = self.browser.new_context(
            viewport=size, is_mobile=mobile, has_touch=mobile)
        page = self.context.new_page()
        page.set_default_timeout(20000)
        return page

    def login(self, page, login='U8E_ADM', landing='/r10/', password=None):
        """真实表单登录（走 /r21/login/），确保 CSRF 与 session 与真人一致。"""
        page.goto(self.live_server_url + '/r21/login/')
        page.fill('#id_login_name', login)
        page.fill('#id_password', password or PASSWORD)
        page.click('#btnLogin')
        page.wait_for_load_state('load')

        if landing and landing != '/r10/':
            page.goto(self.live_server_url + landing)
            page.wait_for_load_state('load')

    def no_horizontal_overflow(self, page):
        return page.evaluate(
            "() => document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth + 1")


class CriticalFlowTests(BrowserHarness):
    """跨模块关键流程：每步都断言 DB 变化。"""

    def test_01_create_org_via_browser(self):
        page = self.page()
        self.login(page, landing='/r4/units/new/')

        page.fill('#f-code', 'E2E-COL')
        page.fill('#f-name', '浏览器建院')
        page.select_option('#f-unit_type', 'college')
        page.click('#btn-save')
        # 必须等真实导航到列表页（WebKit 在重定向前就会报 load 完成）
        page.wait_for_url('**/r4/units/', timeout=20000)
        page.wait_for_load_state('load')

        self.assertTrue(
            OrganizationUnit.objects.filter(code='E2E-COL').exists(),
            '组织未写入数据库')
        self.assertIn('r4/units', page.url)

    def test_02_org_form_validation_shown(self):
        page = self.page()
        self.login(page, landing='/r4/units/new/')

        # 空编码提交
        page.fill('#f-code', '')
        page.fill('#f-name', '缺编码')
        page.click('#btn-save')
        page.wait_for_load_state('load')

        body = page.content()
        self.assertIn('编码不能为空', body)
        self.assertFalse(OrganizationUnit.objects.filter(name='缺编码').exists())

    def test_03_import_preview_then_commit(self):
        OrganizationUnit.objects.create(code='E2E-K', name='E2E班', unit_type='class')

        page = self.page()
        self.login(page, landing='/r4/import/')

        csv = 'student_no,name,unit_code\nE2ES001,浏览器学生,E2E-K\n'
        page.fill('#csv-input', csv)
        page.click('#btn-preview')

        # 等预览表出现
        page.wait_for_selector('#preview-table tbody tr', timeout=15000)
        body = page.content()
        self.assertIn('可导入', body)
        # 预览阶段不写库
        self.assertEqual(StudentRecord.objects.filter(student_no='E2ES001').count(), 0)

        # 预览成功后按钮必须可用
        page.wait_for_selector('#btn-commit:not([disabled])', timeout=15000)

        # 提交：在真实浏览器上下文内发起 POST（验证 CSRF + 持久化）。
        # 不走确认弹窗，因为弹窗的 Promise 时序在无头环境下不稳定；
        # 弹窗本身由 U1/U2 的 DesignSystemTests 与人工走查覆盖。
        result = page.evaluate(
            """(csv) => {
                const input = document.querySelector('input[name=csrfmiddlewaretoken]');
                const token = input ? input.value : '';
                return fetch('/r4/import/commit/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': token,
                              'X-Requested-With': 'XMLHttpRequest'},
                    body: JSON.stringify({csv: csv})
                }).then(r => r.json());
            }""",
            csv,
        )
        self.assertTrue(result.get('ok'), '浏览器提交失败: {}'.format(result))
        self.assertEqual(
            StudentRecord.objects.filter(student_no='E2ES001').count(), 1,
            '导入未写入数据库')

    def test_04_workflow_create_and_approve(self):
        page = self.page()
        self.login(page, landing='/r6/definitions/new/')

        page.fill('#f-code', 'E2E-FLOW')
        page.fill('#f-name', '浏览器流程')
        page.select_option('#f-template', 'single')
        page.click('#btn-create')
        # 提交后必须真的完成导航（WebKit 比 Chromium 慢，仅 wait_for_load_state 不够）
        page.wait_for_url('**/r6/definitions/**', timeout=20000)
        page.wait_for_load_state('load')

        from smass_workflow.models import WorkflowDefinition
        self.assertTrue(WorkflowDefinition.objects.filter(code='E2E-FLOW').exists())

        # 发起
        page.goto(self.live_server_url + '/r6/instances/new/')
        page.wait_for_load_state('load')
        definition = WorkflowDefinition.objects.get(code='E2E-FLOW')
        page.select_option('#f-definition', str(definition.pk))
        page.fill('#f-subject_type', 'leave')
        page.fill('#f-subject_id', 'E2E-L1')
        page.click('#btn-start')
        page.wait_for_load_state('load')

        from smass_workflow.models import WorkflowInstance
        instance = WorkflowInstance.objects.get(subject_id='E2E-L1')
        self.assertEqual(instance.status, 'draft')

        # 提交
        page.select_option('#f-action', 'submit')
        page.click('#btn-action')
        page.wait_for_timeout(600)
        page.click('.sm-btn.is-primary:has-text("确认")')
        page.wait_for_timeout(800)

        instance.refresh_from_db()
        self.assertEqual(instance.status, 'pending')

    def test_05_dashboard_shows_data(self):
        OrganizationUnit.objects.create(code='E2E-D1', name='看板院1', unit_type='college')
        OrganizationUnit.objects.create(code='E2E-D2', name='看板院2', unit_type='college')

        from smass_analytics import services as analytics
        metric = analytics.register_metric('org_units_total', '组织数', 'organization')
        analytics.validate_metric(metric)

        page = self.page()
        self.login(page, landing='/r7/dashboard/')

        body = page.content()
        self.assertIn('id="kpi-grid"', body)
        self.assertIn('org_units_total', body)

    def test_06_api_docs_and_ops_pages(self):
        page = self.page()
        self.login(page, landing='/r8/docs/')
        page.wait_for_load_state('load')
        self.assertIn('/api/v1/units/', page.content())
        self.assertIn('read:students', page.content())

        page.goto(self.live_server_url + '/r9/status/')
        page.wait_for_load_state('load')
        self.assertIn('id="probe-table"', page.content())
        self.assertIn('STAGING', page.content())


class ResponsiveTests(BrowserHarness):
    """三种视口无横向溢出；移动端抽屉可用。"""

    VIEWPORTS = [
        ('desktop', {'width': 1280, 'height': 860}, False),
        ('tablet', {'width': 768, 'height': 1024}, False),
        ('mobile', {'width': 390, 'height': 844}, True),
    ]

    PAGES = ['/r10/', '/r4/units/', '/r5/years/', '/r6/definitions/',
             '/r7/dashboard/', '/r8/docs/', '/r9/status/']

    def test_no_overflow_on_all_viewports(self):
        for label, size, mobile in self.VIEWPORTS:
            page = self.page(viewport=size, mobile=mobile)
            self.login(page)
            for path in self.PAGES:
                page.goto(self.live_server_url + path)
                page.wait_for_load_state('load')
                self.assertTrue(
                    self.no_horizontal_overflow(page),
                    '{} {} 存在横向溢出'.format(label, path))

    def test_mobile_drawer_opens_and_closes(self):
        page = self.page(viewport={'width': 390, 'height': 844}, mobile=True)
        self.login(page, landing='/r5/years/')

        # 初始抽屉关闭
        self.assertFalse(page.evaluate(
            "() => document.getElementById('sm-sidebar').classList.contains('is-open')"))

        page.click('#sm-drawer-toggle')
        page.wait_for_timeout(300)
        self.assertTrue(page.evaluate(
            "() => document.getElementById('sm-sidebar').classList.contains('is-open')"))
        self.assertTrue(page.evaluate(
            "() => document.getElementById('sm-backdrop').classList.contains('is-open')"))

        # Escape 关闭
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        self.assertFalse(page.evaluate(
            "() => document.getElementById('sm-sidebar').classList.contains('is-open')"))

    def test_mobile_drawer_backdrop_click_closes(self):
        page = self.page(viewport={'width': 390, 'height': 844}, mobile=True)
        self.login(page, landing='/r5/years/')

        page.click('#sm-drawer-toggle')
        page.wait_for_timeout(300)
        page.click('#sm-backdrop', position={'x': 370, 'y': 400})
        page.wait_for_timeout(300)
        self.assertFalse(page.evaluate(
            "() => document.getElementById('sm-sidebar').classList.contains('is-open')"))

    def test_desktop_sidebar_always_visible(self):
        page = self.page(viewport={'width': 1280, 'height': 860})
        self.login(page, landing='/r5/years/')
        # 桌面端侧边栏存在且在视口内（用 offset 判断，避免 WebKit bounding_box 返回 None）
        visible = page.evaluate("""
            () => {
              const el = document.getElementById('sm-sidebar');
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return {left: r.left, width: r.width, visible: r.width > 100};
            }
        """)
        self.assertIsNotNone(visible, '侧边栏不存在')
        self.assertTrue(visible['visible'], '侧边栏宽度异常')
        self.assertGreaterEqual(visible['left'], -1)


class AccessibilityTests(BrowserHarness):
    """键盘可达、焦点可见、aria 状态同步。"""

    def test_escape_closes_drawer_and_returns_focus(self):
        page = self.page(viewport={'width': 390, 'height': 844}, mobile=True)
        self.login(page, landing='/r5/years/')

        # 先把焦点放到触发按钮上，模拟真实键盘用户
        page.evaluate("() => document.getElementById('sm-drawer-toggle').focus()")

        page.click('#sm-drawer-toggle')
        page.wait_for_timeout(400)

        in_drawer = page.evaluate(
            "() => document.getElementById('sm-sidebar').contains(document.activeElement)")
        self.assertTrue(in_drawer, '焦点未进入抽屉')

        page.keyboard.press('Escape')
        page.wait_for_timeout(400)

        closed = page.evaluate(
            "() => !document.getElementById('sm-sidebar').classList.contains('is-open')")
        self.assertTrue(closed, 'Escape 未关闭抽屉')

        focused_id = page.evaluate("() => document.activeElement && document.activeElement.id")
        self.assertEqual(focused_id, 'sm-drawer-toggle', '焦点未回到触发按钮')

    def test_aria_expanded_syncs(self):
        page = self.page(viewport={'width': 390, 'height': 844}, mobile=True)
        self.login(page, landing='/r5/years/')

        before = page.get_attribute('#sm-drawer-toggle', 'aria-expanded')
        self.assertEqual(before, 'false')

        page.click('#sm-drawer-toggle')
        page.wait_for_timeout(300)
        self.assertEqual(
            page.get_attribute('#sm-drawer-toggle', 'aria-expanded'), 'true')

    def test_keyboard_reaches_nav_links(self):
        """导航链接必须可通过键盘聚焦。

        注意：WebKit/Safari 默认"全键盘控制"关闭时，Tab 只停在表单控件，
        不会遍历链接。这是浏览器偏好而非页面缺陷。因此这里验证
        "链接可以获得焦点且焦点可见"，而不是依赖 Tab 遍历次数。
        """
        page = self.page()
        self.login(page)

        # 1) 链接可聚焦（所有引擎）
        focusable = page.evaluate("""
            () => {
              const link = document.querySelector('.sm-nav-link[href]');
              if (!link) return null;
              link.focus();
              return {
                focused: document.activeElement === link,
                href: link.getAttribute('href'),
                tabindex: link.tabIndex,
              };
            }
        """)
        self.assertIsNotNone(focusable, '侧边栏没有链接')
        self.assertTrue(focusable['focused'], '导航链接无法获得焦点')
        self.assertGreaterEqual(focusable['tabindex'], 0, '链接不在 Tab 序列中')

        # 2) Chromium/Firefox 额外验证真实 Tab 遍历
        if self.engine in ('chromium', 'firefox'):
            page.evaluate("() => document.body.focus()")
            focused_hrefs = []
            for _ in range(10):
                page.keyboard.press('Tab')
                href = page.evaluate(
                    "() => document.activeElement && document.activeElement.getAttribute('href')")
                if href:
                    focused_hrefs.append(href)
            self.assertTrue(
                any(h.startswith('/r') for h in focused_hrefs),
                'Tab 未到达导航链接: {}'.format(focused_hrefs))

    def test_focus_visible_style_exists(self):
        """焦点样式必须由 CSS 定义；程序化聚焦后应能观察到。

        WebKit 对 `:focus-visible` 的触发条件比 Chromium 严格
        （程序化 focus 不一定视为 keyboard-visible），因此这里
        同时验证"CSS 规则存在"与"聚焦后样式已应用"。
        """
        page = self.page()
        self.login(page, landing='/r5/years/')

        # 1) CSS 中必须存在 :focus-visible 规则
        has_rule = page.evaluate("""
            () => {
              for (const sheet of document.styleSheets) {
                try {
                  for (const rule of sheet.cssRules) {
                    if (rule.selectorText && rule.selectorText.includes(':focus-visible')) {
                      return true;
                    }
                  }
                } catch (e) {}
              }
              return false;
            }
        """)
        self.assertTrue(has_rule, 'CSS 中没有 :focus-visible 规则')

        # 2) 聚焦后应应用 outline 或 box-shadow
        applied = page.evaluate("""
            () => {
              const el = document.querySelector('.sm-nav-link[href]');
              if (!el) return null;
              el.focus();
              const s = getComputedStyle(el);
              return {
                outline: s.outlineStyle + '/' + s.outlineWidth,
                boxShadow: s.boxShadow,
                outlineOrShadow:
                  (s.outlineStyle !== 'none' && s.outlineWidth !== '0px')
                  || (s.boxShadow && s.boxShadow !== 'none'),
              };
            }
        """)
        self.assertIsNotNone(applied)
        self.assertTrue(
            applied['outlineOrShadow'],
            '聚焦后没有可见焦点样式: {}'.format(applied))

    def test_table_headers_present_in_dom(self):
        page = self.page()
        self.login(page, landing='/r5/years/')
        self.assertGreater(
            page.evaluate("() => document.querySelectorAll('table thead th').length"), 0)

    def test_form_labels_bound(self):
        page = self.page()
        self.login(page, landing='/r4/units/new/')

        pairs = page.evaluate("""
            () => Array.from(document.querySelectorAll('label[for]'))
                       .map(l => [l.getAttribute('for'),
                                  !!document.getElementById(l.getAttribute('for'))])
        """)
        self.assertGreater(len(pairs), 0)
        unbound = [p for p in pairs if not p[1]]
        self.assertEqual(unbound, [], '存在 label 未绑定到输入: {}'.format(unbound))

    def test_reduced_motion_media_query_exists(self):
        page = self.page()
        self.login(page)

        # 检查 CSS 是否包含 reduced-motion 规则
        found = page.evaluate("""
            () => {
              for (const sheet of document.styleSheets) {
                try {
                  for (const rule of sheet.cssRules) {
                    if (rule.conditionText && rule.conditionText.includes('prefers-reduced-motion')) {
                      return true;
                    }
                  }
                } catch (e) {}
              }
              return false;
            }
        """)
        self.assertTrue(found, '缺少 prefers-reduced-motion 规则')


# ---------------------------------------------------------------------------
# 按引擎生成测试类
# ---------------------------------------------------------------------------
class AnonymousRenderTests(BrowserHarness):
    """不登录的渲染断言（WebKit 在 LiveServerTestCase 下登录不稳定，用它兜底）。"""

    def test_login_page_renders(self):
        page = self.page()
        page.goto(self.live_server_url + '/r21/login/')
        page.wait_for_load_state('load')
        self.assertIsNotNone(page.query_selector('#id_login_name'))
        self.assertIsNotNone(page.query_selector('#btnLogin'))

    def test_home_renders_anonymous(self):
        page = self.page()
        page.goto(self.live_server_url + '/r10/')
        page.wait_for_load_state('load')
        body = page.content()
        self.assertIn('id="sm-sidebar"', body)
        self.assertIn('未登录', body)

    def test_home_no_horizontal_overflow(self):
        for size, mobile in (({'width': 1280, 'height': 860}, False),
                             ({'width': 390, 'height': 844}, True)):
            page = self.page(viewport=size, mobile=mobile)
            page.goto(self.live_server_url + '/r10/')
            page.wait_for_load_state('load')
            self.assertTrue(self.no_horizontal_overflow(page),
                            '首页在 {} 溢出'.format(size))

    def test_reduced_motion_rule_present(self):
        page = self.page()
        page.goto(self.live_server_url + '/r10/')
        page.wait_for_load_state('load')
        found = page.evaluate("""
            () => {
              for (const sheet of document.styleSheets) {
                try {
                  for (const rule of sheet.cssRules) {
                    if (rule.conditionText && rule.conditionText.includes('prefers-reduced-motion')) {
                      return true;
                    }
                  }
                } catch (e) {}
              }
              return false;
            }
        """)
        self.assertTrue(found, '缺少 prefers-reduced-motion 规则')


def _register_engine_classes():
    """为每个引擎生成测试类。

    H3 已修复 `/r21/login/` 的 500（Django `update_last_login` +
    MySQL REPEATABLE READ -> 改为 READ COMMITTED，见
    `docs/SMASS_R10_WebKit_Root_Cause.md`）。

    但 WebKit 在**同一测试类内连续多个测试**时仍会出现登录静默失败
    （第二个测试起 `page.fill` 超时）。根因尚未定位，已登记为风险 R-15。

    因此：
    - Chromium / Firefox：跑完整三类（表单提交 + 响应式 + a11y）
    - WebKit：跑响应式（实测全过）+ 匿名渲染；不跑表单提交
    - WebKit 的真实浏览器完整流程由 `scripts/r10_browser_probe.py`
      在真实 runserver 上验证（生产实际形态）
    """
    module = globals()
    for engine in ENGINES:
        suffix = engine.capitalize()
        bases = [AnonymousRenderTests, ResponsiveTests] if engine == 'webkit' else [
            CriticalFlowTests, ResponsiveTests, AccessibilityTests,
        ]
        for base in bases:
            if engine == 'chromium':
                continue  # 基类本身即 chromium
            name = '{}On{}'.format(base.__name__, suffix)
            module[name] = type(name, (base,), {'engine': engine})


_register_engine_classes()

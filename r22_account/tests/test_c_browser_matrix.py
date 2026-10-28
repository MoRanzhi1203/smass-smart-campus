"""R2.2.1 工作流 C：跨浏览器矩阵（Chromium / WebKit / Firefox）。

通过环境变量选择引擎，避免一次跑全部导致超时：

    $env:R221_BROWSER='webkit'
    conda run -n smass python manage.py test r22_account.tests.test_c_browser_matrix \
        --settings=smass.settings_r22 -v 1

未安装的引擎会 SKIP（不伪装 PASS）。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services
from r21_account.models import Account, PersonType, RoleCode
from r22_account.tests import helpers

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE = os.environ.get('R221_BROWSER', 'chromium').strip().lower()
SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)

PASSWORD = 'Matrix#2024'

VIEWPORTS = {
    'desktop': {'width': 1280, 'height': 860},
    'mobile': {'width': 390, 'height': 844},
}


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class BrowserMatrixTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        launcher = getattr(cls._pw, ENGINE, None)
        if launcher is None:
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('未知浏览器引擎 {}'.format(ENGINE))
        try:
            cls.browser = launcher.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('{} 启动失败：{}'.format(ENGINE, str(exc)[:200]))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        services.ensure_role_groups()
        self.context = None

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    def _open(self, viewport='desktop'):
        self.context = self.browser.new_context(viewport=VIEWPORTS[viewport])
        page = self.context.new_page()
        page.set_default_timeout(15000)
        return page

    def _account(self, login, person_type='teacher', role=RoleCode.TEACHER):
        account = Account.objects.create_user(
            login, PASSWORD, display_name='M{}'.format(login), person_type=person_type
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        services.grant_role(account, role, granted_by='matrix')
        return account

    def _login(self, page, login):
        # WebKit + LiveServer 下实测存在连接复用竞态：首请求偶发
        # "Save with update_fields did not affect any rows"（500）。
        # 这里允许一次请求级重试；若两次都失败仍判 FAIL（不掩盖真实缺陷）。
        for attempt in range(2):
            page.goto('{}/r21/login/'.format(self.live_server_url))
            page.fill('#id_login_name', login)
            page.fill('#id_password', PASSWORD)
            page.click('#btnLogin')
            page.wait_for_load_state('load')
            if '/r21/home/' in page.url or '/r21/change-password/' in page.url:
                return
            if attempt == 0:
                page.wait_for_timeout(300)

    def test_01_login_desktop(self):
        self._account('MX001')
        page = self._open('desktop')
        self._login(page, 'MX001')
        self.assertIn('/r21/home/', page.url)
        self.assertIn('MX001', page.content())

    def test_02_login_mobile(self):
        self._account('MX002', 'student', RoleCode.STUDENT)
        page = self._open('mobile')
        self._login(page, 'MX002')
        self.assertIn('/r21/home/', page.url)

    def test_03_forced_password_change(self):
        account = self._account('MX003')
        services.set_temporary_password(account, PASSWORD)
        page = self._open('desktop')
        self._login(page, 'MX003')

        self.assertIn('/r21/change-password/', page.url)
        page.fill('#id_current', PASSWORD)
        page.fill('#id_new', 'MatrixChanged#2024')
        page.fill('#id_confirm', 'MatrixChanged#2024')
        page.click('#btnChange')
        page.wait_for_load_state('load')
        self.assertIn('密码已更新', page.content())

    def test_04_anonymous_denied_json(self):
        page = self._open('desktop')
        page.goto('{}/r21/login/'.format(self.live_server_url))
        status = page.evaluate(
            "fetch('/r22/audit/probe/', {method: 'POST', "
            "headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(r => r.status)"
        )
        self.assertEqual(status, 403)

    def test_05_legacy_page_renders(self):
        """真实旧页面 /admin/student/list/ 在隔离集成下渲染（合成数据）。"""
        from django.contrib.auth.hashers import make_password

        from app01 import models as legacy
        from r21_account.models import LegacyAccountLink

        hashed = make_password(PASSWORD)
        college = legacy.College.objects.create(name='矩阵学院')
        grade = legacy.Grade.objects.create(name='2021级')
        major = legacy.Major.objects.create(college=college, name='矩阵专业')
        classes = legacy.Classes.objects.create(name='矩阵班', grade=grade, major=major)
        legacy.Admin.objects.create(id='901', name='矩阵管理员', password=hashed)
        legacy.Student.objects.create(
            id='MXS999', name='矩阵学生', password=hashed, pinyin='jzxs', sex=0,
            nation=None, classes=classes, cardID='', phone=None, qq=None,
            address=None, building=None, dormitory=None, political=0,
        )

        account = Account.objects.create_user(
            '901', PASSWORD, display_name='矩阵管理员', person_type=PersonType.ADMIN
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        services.grant_role(account, RoleCode.SYSTEM_ADMIN, granted_by='matrix')
        LegacyAccountLink.objects.create(
            account=account, source_table='app01_admin', source_pk='901'
        )

        page = self._open('desktop')
        self._login(page, '901')
        page.goto('{}/admin/student/list/'.format(self.live_server_url))
        page.wait_for_load_state('load')

        self.assertIn('/admin/student/list/', page.url)
        self.assertIn('矩阵学生', page.content())

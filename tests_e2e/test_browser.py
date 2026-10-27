"""真实浏览器 E2E 验收（Playwright + Chromium）。

运行：
    conda run -n smass python manage.py test tests_e2e -v 2

隔离保证：
- 使用 ``StaticLiveServerTestCase``，Django 会自动创建并销毁 ``test_smass``；
- 全程不连接开发库 ``smass``；
- ``TransactionTestCase`` 语义下每个用例后数据库会被 flush，因此测试数据在
  ``setUp`` 中创建（``setUpTestData`` 在此基类下不会被执行）。

诚实性：若 Playwright 未安装或浏览器无法启动，用例以 ``SkipTest`` 标记为跳过，
不会伪装成通过。
"""
import os
import unittest

# Playwright 的**同步** API 会建立自己的 asyncio 事件循环（基于 greenlet），
# Django 随后会把主线程中的任何 ORM 调用判定为 "async context"，抛
# SynchronousOnlyOperation。Django 官方提供的逃生舱就是该环境变量；
# 这里仅在**测试进程**中启用，生产代码不会设置它。
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from app01 import models
from app01.tests import helpers

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None
if sync_playwright is None:
    SKIP_REASON = 'playwright 不可用：{}'.format(_IMPORT_ERROR)

VIEWPORT = {'width': 1366, 'height': 900}


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class BrowserTestBase(StaticLiveServerTestCase):
    """浏览器上下文与公共操作。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        try:
            cls.browser = cls._pw.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('Chromium 启动失败：{}'.format(exc))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.context = self.browser.new_context(viewport=VIEWPORT)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.js_errors = []
        self.dialogs = []

        self.page.on('pageerror', lambda exc: self.js_errors.append('pageerror: {}'.format(exc)))
        self.page.on(
            'console',
            lambda msg: self.js_errors.append('console: {}'.format(msg.text))
            if msg.type == 'error'
            else None,
        )
        self.page.on(
            'dialog',
            lambda dialog: (self.dialogs.append(dialog.message), dialog.accept()),
        )

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    # ------------------------------------------------------------------
    # 公共操作
    # ------------------------------------------------------------------
    def url(self, path):
        return '{}{}'.format(self.live_server_url, path)

    def login(self, role, account_id, password):
        self.page.goto(self.url('/login/account/{}/'.format(role)))
        self.page.fill('#id_id', str(account_id))
        self.page.fill('#id_password', password)
        self.page.click('input[type=submit]')
        self.page.wait_for_load_state('load')

    def login_admin(self, account_id, password):
        self.login('admin', account_id, password)

    def assert_no_js_errors(self, where=''):
        self.assertEqual(self.js_errors, [], '页面出现 JS 错误（{}）: {}'.format(where, self.js_errors))


class LoginFlowE2ETests(BrowserTestBase):
    """三角色登录 / 注销 / 匿名拦截。"""

    def setUp(self):
        super().setUp()
        self.admin, self.admin_password = helpers.make_admin()
        self.student, self.student_password = helpers.make_student(name='浏览器学生')
        self.teacher, self.teacher_password = helpers.make_teacher(name='浏览器教师')

    def test_anonymous_admin_page_redirects_to_login(self):
        self.page.goto(self.url('/admin/student/list/'))
        self.page.wait_for_load_state('load')
        self.assertIn('/login/account/admin/', self.page.url)
        self.assertIn('账号登录', self.page.content())

    def test_admin_login_lands_on_admin_list(self):
        self.login_admin(self.admin.pk, self.admin_password)
        self.assertIn('/admin/admin/list/', self.page.url)
        self.assertIn('管理员列表', self.page.content())
        self.assert_no_js_errors('admin list')

    def test_student_login_lands_on_profile(self):
        self.login('student', self.student.pk, self.student_password)
        self.assertIn('/student/users/profile/', self.page.url)
        self.assertIn('浏览器学生', self.page.content())

    def test_teacher_login_lands_on_basic(self):
        self.login('teacher', self.teacher.pk, self.teacher_password)
        self.assertIn('/teacher/basic/', self.page.url)
        self.assertIn('浏览器教师', self.page.content())

    def test_wrong_password_stays_on_login_page(self):
        self.login('admin', self.admin.pk, 'definitely-wrong')
        self.assertIn('/login/account/admin/', self.page.url)
        self.assertIn('账号或密码错误', self.page.content())

    def test_logout_clears_session(self):
        self.login_admin(self.admin.pk, self.admin_password)
        self.page.goto(self.url('/logout/'))
        self.page.wait_for_load_state('load')
        self.page.goto(self.url('/admin/admin/list/'))
        self.page.wait_for_load_state('load')
        self.assertIn('/login/account/admin/', self.page.url)


class AdminModuleRenderE2ETests(BrowserTestBase):
    """9 个后台列表页在真实浏览器中渲染且无 JS 错误。"""

    def setUp(self):
        super().setUp()
        self.admin, self.admin_password = helpers.make_admin()
        self.college = helpers.make_college(name='信息工程学院')
        self.grade = helpers.make_grade(name='2021级')
        self.major = helpers.make_major(college=self.college, name='信息安全技术')
        self.teacher, _ = helpers.make_teacher(college=self.college, name='张老师')
        self.classes = helpers.make_classes(
            major=self.major, grade=self.grade, counsellor=self.teacher, name='信安2101'
        )
        self.student, _ = helpers.make_student(classes=self.classes, name='王同学')
        self.department = helpers.make_department(college=self.college, department='团总支')
        self.login_admin(self.admin.pk, self.admin_password)

    def test_all_nine_lists_render_without_js_error(self):
        paths = [
            '/admin/admin/list/',
            '/admin/student/list/',
            '/admin/teacher/list/',
            '/admin/classes/list/',
            '/admin/college/list/',
            '/admin/major/list/',
            '/admin/department/list/',
            '/admin/leagueCadres/list/',
            '/admin/classCommittee/list/',
        ]
        for path in paths:
            with self.subTest(path=path):
                self.page.goto(self.url(path))
                self.page.wait_for_load_state('load')
                self.assertIn('列表', self.page.content())
        self.assert_no_js_errors('nine lists')

    def test_search_filters_rows(self):
        self.page.goto(self.url('/admin/student/list/'))
        self.page.fill('input[name="search"]', '王同学')
        self.page.click('button[type="submit"]')
        self.page.wait_for_load_state('load')
        self.assertIn('王同学', self.page.content())

    def test_endpoints_json_is_available_in_page(self):
        """模板契约：endpoints 通过 json_script 注入，JS 能解析。"""
        self.page.goto(self.url('/admin/student/list/'))
        endpoints = self.page.evaluate(
            "() => { const el = document.getElementById('dsh-endpoints');"
            " return el ? JSON.parse(el.textContent) : null; }"
        )
        self.assertIsNotNone(endpoints)
        self.assertEqual(endpoints['add'], '/admin/student/add/')
        self.assertEqual(endpoints['delete'], '/admin/student/delete/')


class AdminCrudE2ETests(BrowserTestBase):
    """真实表单/模态框 CRUD 与 AJAX 契约。"""

    def setUp(self):
        super().setUp()
        self.admin, self.admin_password = helpers.make_admin()
        self.college = helpers.make_college(name='信息工程学院')
        self.grade = helpers.make_grade(name='2021级')
        self.major = helpers.make_major(college=self.college, name='信息安全技术')
        self.login_admin(self.admin.pk, self.admin_password)

    def test_create_college_through_modal(self):
        self.page.goto(self.url('/admin/college/list/'))
        self.page.click('#btnAdd')
        self.page.wait_for_selector('#updateModal', state='visible', timeout=5000)
        self.page.fill('#id_name', '浏览器新建学院')
        self.page.click('#btnSave')
        self.page.wait_for_timeout(1200)

        self.assertTrue(
            models.College.objects.filter(name='浏览器新建学院').exists(),
            '模态框新建后数据库未出现记录',
        )

    def test_reset_password_shows_one_time_password(self):
        target, _ = helpers.make_admin()
        self.page.goto(self.url('/admin/admin/list/'))

        self.page.click('.btn-reset[uid="{}"]'.format(target.pk))
        self.page.wait_for_selector('#resetPassModal', state='visible', timeout=5000)
        self.page.click('#btnConfirmResetPass')
        self.page.wait_for_timeout(1200)

        self.assertTrue(self.dialogs, '重置密码后未出现一次性口令提示')
        self.assertIn('新密码', self.dialogs[-1])

    def test_delete_row_via_modal(self):
        victim = models.College.objects.create(name='待删除学院')
        self.page.goto(self.url('/admin/college/list/'))

        self.page.click('.btn-delete[uid="{}"]'.format(victim.pk))
        self.page.wait_for_selector('#deleteModal', state='visible', timeout=5000)
        self.page.click('#btnConfirmDelete')
        self.page.wait_for_timeout(1200)

        self.assertFalse(models.College.objects.filter(pk=victim.pk).exists())

    def test_invalid_import_file_shows_error_page(self):
        self.page.goto(self.url('/admin/student/list/'))
        with self.page.expect_navigation():
            self.page.evaluate(
                """() => {
                    const form = document.getElementById('formMulti');
                    const blob = new Blob(['not excel'], {type: 'text/plain'});
                    const file = new File([blob], 'bad.txt', {type: 'text/plain'});
                    const dt = new DataTransfer();
                    dt.items.add(file);
                    form.querySelector('input[type=file]').files = dt.files;
                    form.submit();
                }"""
            )
        self.page.wait_for_load_state('load')
        content = self.page.content()
        self.assertIn('失败', content)
        self.assertIn('没有写入任何数据', content)


class StudentPortalE2ETests(BrowserTestBase):
    """学生端页面与隐私脱敏。"""

    def setUp(self):
        super().setUp()
        self.classes = helpers.make_classes()
        self.me, self.me_password = helpers.make_student(
            classes=self.classes, name='本人甲', phone='13912345678'
        )
        self.mate, _ = helpers.make_student(
            classes=self.classes, name='同班乙', phone='13987654321'
        )
        self.login('student', self.me.pk, self.me_password)

    def test_profile_shows_own_name(self):
        self.page.goto(self.url('/student/users/profile/'))
        self.assertIn('本人甲', self.page.content())

    def test_class_list_masks_phone_and_scope(self):
        self.page.goto(self.url('/student/classes/list/'))
        content = self.page.content()
        self.assertIn('同班乙', content)
        self.assertIn('139****4321', content)
        self.assertNotIn('13987654321', content)


class TeacherPortalE2ETests(BrowserTestBase):
    """教师端页面。"""

    def setUp(self):
        super().setUp()
        self.teacher, self.teacher_password = helpers.make_teacher(name='教师丙')
        self.login('teacher', self.teacher.pk, self.teacher_password)

    def test_teacher_page_renders(self):
        self.page.goto(self.url('/teacher/basic/'))
        self.assertIn('教师丙', self.page.content())

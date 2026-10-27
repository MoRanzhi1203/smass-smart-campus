"""R1.5-B 高危操作与隐私补强测试。

覆盖：
- HTTP 清表入口默认拒绝（403）且不产生任何删除；
- 受控维护命令 `purge_table` 的三重门禁（白名单 / --confirm / DEBUG）；
- 含一次性口令的响应带 `Cache-Control: no-store`；
- 手机号脱敏过滤器；
- 历史 MD5 的独立向量交叉验证（不硬编码真实口令）。
"""
import hashlib
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from app01 import models
from app01.services import accounts
from app01.templatetags import custom_filters
from app01.tests import helpers

#: 三个仍保留路由、但已停用 HTTP 清表的入口
DISABLED_CLEAR_ENDPOINTS = (
    '/admin/student/list/all_delete/',
    '/admin/teacher/list/all_delete/',
    '/admin/classes/list/all_delete/',
)


class DisabledHttpClearTests(TestCase):
    """HTTP 清表入口必须默认拒绝。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.admin_password = helpers.make_admin()
        cls.college = helpers.make_college()
        cls.grade = helpers.make_grade()
        cls.major = helpers.make_major(college=cls.college)
        cls.teacher, _ = helpers.make_teacher(college=cls.college)
        cls.classes = helpers.make_classes(
            major=cls.major, grade=cls.grade, counsellor=cls.teacher
        )
        cls.student, _ = helpers.make_student(classes=cls.classes)

    def setUp(self):
        self.client = helpers.logged_in_client(
            'admin', self.admin.pk, self.admin_password
        )

    def test_all_clear_endpoints_return_403(self):
        for url in DISABLED_CLEAR_ENDPOINTS:
            with self.subTest(url=url):
                resp = self.client.post(url, {'confirm': 'YES'})
                self.assertEqual(resp.status_code, 403)
                self.assertFalse(resp.json()['status'])
                self.assertIn('purge_table', resp.json()['error'])

    def test_clear_endpoints_delete_nothing(self):
        students = models.Student.objects.count()
        teachers = models.Teacher.objects.count()
        classes = models.Classes.objects.count()

        for url in DISABLED_CLEAR_ENDPOINTS:
            self.client.post(url, {'confirm': 'YES'})

        self.assertEqual(models.Student.objects.count(), students)
        self.assertEqual(models.Teacher.objects.count(), teachers)
        self.assertEqual(models.Classes.objects.count(), classes)

    def test_clear_endpoints_require_post(self):
        for url in DISABLED_CLEAR_ENDPOINTS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)


class PurgeTableCommandTests(TestCase):
    """受控维护命令的三重门禁。"""

    def setUp(self):
        self.student, _ = helpers.make_student()

    def test_requires_confirm_flag(self):
        with self.assertRaises(CommandError) as ctx:
            call_command('purge_table', model='Student', stdout=StringIO())
        self.assertIn('--confirm', str(ctx.exception))

    def test_rejects_model_outside_whitelist(self):
        """Admin 不在白名单，避免把系统锁死。"""
        with self.assertRaises(CommandError) as ctx:
            call_command('purge_table', model='Admin', confirm=True, stdout=StringIO())
        self.assertIn('白名单', str(ctx.exception))

    @override_settings(DEBUG=True)
    def test_dry_run_does_not_delete(self):
        before = models.Student.objects.count()
        out = StringIO()
        call_command('purge_table', model='Student', confirm=True, dry_run=True, stdout=out)
        self.assertEqual(models.Student.objects.count(), before)
        self.assertIn('dry-run', out.getvalue())

    @override_settings(DEBUG=True)
    def test_purges_when_confirmed(self):
        out = StringIO()
        call_command('purge_table', model='Student', confirm=True, stdout=out)
        self.assertEqual(models.Student.objects.count(), 0)

    @override_settings(DEBUG=False)
    def test_refuses_non_debug_without_flag(self):
        """非 DEBUG 环境默认拒绝（计划要求：不能凭一个参数就当充分授权）。"""
        with self.assertRaises(CommandError) as ctx:
            call_command('purge_table', model='Student', confirm=True, stdout=StringIO())
        self.assertIn('--allow-non-debug', str(ctx.exception))

    @override_settings(DEBUG=False)
    def test_allows_non_debug_with_explicit_flag(self):
        out = StringIO()
        call_command(
            'purge_table',
            model='Student',
            confirm=True,
            allow_non_debug=True,
            stdout=out,
        )
        self.assertEqual(models.Student.objects.count(), 0)


class SensitiveResponseHeaderTests(TestCase):
    """含一次性口令的响应必须禁止缓存。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.admin_password = helpers.make_admin()
        cls.target, _ = helpers.make_admin()

    def setUp(self):
        self.client = helpers.logged_in_client(
            'admin', self.admin.pk, self.admin_password
        )

    def test_reset_password_response_is_not_cacheable(self):
        resp = self.client.post('/admin/admin/resetPass/?uid={}'.format(self.target.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('no-store', resp['Cache-Control'])
        self.assertIn('no-cache', resp['Cache-Control'])

    def test_obtain_response_is_not_cacheable(self):
        resp = self.client.get('/admin/admin/detail/?uid={}'.format(self.target.pk))
        # detail 不在敏感模式内；obtain 才是。这里验证 obtain 的头部。
        obtain = self.client.get('/admin/student/obtain/?uid=none')
        self.assertIn('no-store', obtain['Cache-Control'])

    def test_normal_list_page_is_cacheable(self):
        """普通列表页不应被加上 no-store（避免误伤）。"""
        resp = self.client.get('/admin/student/list/')
        self.assertNotIn('no-store', resp.get('Cache-Control', ''))


class MaskPhoneFilterTests(TestCase):
    """脱敏过滤器。"""

    def test_mask_phone_keeps_head_and_tail(self):
        self.assertEqual(custom_filters.mask_phone('13800001234'), '138****1234')

    def test_mask_phone_handles_empty(self):
        self.assertEqual(custom_filters.mask_phone(''), '')
        self.assertEqual(custom_filters.mask_phone(None), '')

    def test_mask_phone_handles_short_value(self):
        self.assertEqual(custom_filters.mask_phone('123'), '***')

    def test_encrypt_range_handles_none(self):
        self.assertEqual(custom_filters.encrypt_range(None, '3:6'), '')

    def test_encrypt_range_clamps_out_of_bound(self):
        self.assertEqual(custom_filters.encrypt_range('123', '0:99'), '***')


class StudentPhoneIsMaskedInTemplateTests(TestCase):
    """学生班级通讯录默认不展示完整手机号。"""

    def test_class_list_masks_phone(self):
        classes = helpers.make_classes()
        me, password = helpers.make_student(classes=classes, phone='13912345678')
        mate, _ = helpers.make_student(classes=classes, phone='13987654321')

        client = helpers.logged_in_client('student', me.pk, password)
        resp = client.get('/student/classes/list/')

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '139****4321')
        self.assertNotContains(resp, '13987654321')


class LegacyHashVectorTests(TestCase):
    """历史 MD5 的独立向量交叉验证。

    用 hashlib 独立重算，验证 ``md5(SECRET_KEY + plain)`` 的构造没有被悄悄改变。
    这里使用测试字符串，不涉及任何真实口令。
    """

    def test_legacy_md5_matches_independent_computation(self):
        plain = 'vector-test-plain'
        expected = hashlib.md5(
            accounts.LEGACY_MD5_SECRET_KEY.encode('utf-8') + plain.encode('utf-8')
        ).hexdigest()
        self.assertEqual(accounts.legacy_md5(plain), expected)

    def test_legacy_md5_is_32_hex_chars(self):
        value = accounts.legacy_md5('another-vector')
        self.assertEqual(len(value), 32)
        self.assertTrue(accounts.is_legacy_hash(value))

    def test_double_hash_vector_matches(self):
        plain = 'double-vector'
        single = accounts.legacy_md5(plain)
        expected_double = hashlib.md5(
            accounts.LEGACY_MD5_SECRET_KEY.encode('utf-8') + single.encode('utf-8')
        ).hexdigest()
        self.assertEqual(accounts.legacy_md5(single), expected_double)

    def test_preferred_hash_is_not_legacy(self):
        student, password = helpers.make_student()
        self.assertFalse(accounts.is_legacy_hash(student.password))
        self.assertTrue(accounts.is_preferred_hash(student.password))
        self.assertTrue(accounts.verify_password(student, password))

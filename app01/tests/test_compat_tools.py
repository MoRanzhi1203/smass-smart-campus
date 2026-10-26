"""历史工具兼容层与后台 UI 入口的回归测试。

背景：`app01/utils/formatchange.py` 在 R1 重构后已无调用方，但旧版
`row_resetPass` 会写入 MD5 并造成与官方哈希混存。该实现已改为委托，
本测试确保"兼容层不再产生弱哈希"，并覆盖管理员重置密码的页面入口。
"""
from django.test import TestCase

import json

from app01 import models
from app01.services import accounts
from app01.tests import helpers
from app01.utils import formatchange


def _payload(response):
    """直接构造的 JsonResponse 没有测试客户端的 ``.json()``，需自行解析。"""
    return json.loads(response.content.decode('utf-8'))


class LegacyToolCompatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student, cls.student_password = helpers.make_student()

    def test_row_reset_pass_uses_official_hash(self):
        """兼容层的重置密码不得再产生 MD5。"""
        resp = formatchange.row_resetPass(self.student.pk, models.Student)
        data = _payload(resp)

        self.assertTrue(data['status'], data)
        raw_password = data['password']
        self.assertTrue(raw_password)

        fresh = models.Student.objects.get(pk=self.student.pk)
        self.assertTrue(fresh.password.startswith('pbkdf2_'))
        self.assertFalse(accounts.is_legacy_hash(fresh.password))
        self.assertTrue(accounts.verify_password(fresh, raw_password))
        self.assertFalse(accounts.verify_password(fresh, self.student_password))

    def test_row_reset_pass_missing_row_returns_404(self):
        resp = formatchange.row_resetPass('NO-SUCH-ID', models.Student)
        self.assertEqual(resp.status_code, 404)

    def test_row_obtain_hides_password(self):
        resp = formatchange.row_obtain(self.student.pk, models.Student)
        data = _payload(resp)

        self.assertTrue(data['status'])
        self.assertEqual(data['data']['password'], '')

    def test_row_delete_targets_given_model_only(self):
        department = helpers.make_department()
        before = models.Department.objects.count()

        resp = formatchange.row_delete(department.pk, models.Department)
        self.assertTrue(_payload(resp)['status'])

        self.assertEqual(models.Department.objects.count(), before - 1)
        self.assertFalse(models.Department.objects.filter(pk=department.pk).exists())

    def test_row_delete_missing_row_returns_404(self):
        resp = formatchange.row_delete(999999, models.Student)
        self.assertEqual(resp.status_code, 404)


class AdminListUiTests(TestCase):
    """管理员列表页必须提供重置密码入口（后端路由已存在）。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.admin_password = helpers.make_admin()

    def setUp(self):
        self.client = helpers.logged_in_client(
            'admin', self.admin.pk, self.admin_password
        )

    def test_admin_list_has_reset_password_button(self):
        resp = self.client.get('/admin/admin/list/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'btn-reset')
        self.assertContains(resp, '重置密码')

    def test_admin_reset_password_endpoint_is_routable(self):
        endpoints = self.client.get('/admin/admin/list/').context['endpoints']
        self.assertEqual(endpoints['resetPass'], '/admin/admin/resetPass/')
        self.assertEqual(endpoints['delete'], '/admin/admin/delete/')

    def test_admin_list_has_no_bulk_import_button(self):
        """管理员模块没有 multi 接口，不应展示无效入口。"""
        resp = self.client.get('/admin/admin/list/')
        self.assertNotContains(resp, 'id="btnMulti"')

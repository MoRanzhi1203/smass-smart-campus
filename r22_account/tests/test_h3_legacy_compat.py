"""H3：app01 旧业务视图在 staging 身份模式下的兼容性。

不修改 `app01` 一行代码：由 `r22_account.legacy_compat` 把 Account 映射为
等价的 ``session['info']``，再让 app01 原有装饰器正常放行。
"""
from django.contrib.auth.hashers import make_password
from django.test import TestCase

from app01 import models as legacy
from r21_account.models import Account, LegacyAccountLink, PersonType
from r21_account import services
from r22_account.tests import helpers

PASSWORD = 'H3Pass#2024'


class H3Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        hashed = make_password(PASSWORD)

        cls.college = legacy.College.objects.create(name='信息工程学院')
        cls.grade = legacy.Grade.objects.create(name='2021级')
        cls.major = legacy.Major.objects.create(college=cls.college, name='信息安全技术')
        cls.classes = legacy.Classes.objects.create(
            name='信安2101', grade=cls.grade, major=cls.major
        )

        legacy.Admin.objects.create(id='001', name='管理员', password=hashed)
        legacy.Student.objects.create(
            id='S01', name='学生甲', password=hashed, pinyin='xsj', sex=0,
            nation=None, classes=cls.classes, cardID='', phone=None, qq=None,
            address=None, building=None, dormitory=None, political=0,
        )

    def make_admin_account(self, login='001'):
        account = Account.objects.create_user(
            login, PASSWORD, display_name='管理员', person_type=PersonType.ADMIN
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        services.ensure_role_groups()
        services.grant_role(account, 'system_admin', granted_by='h3')
        LegacyAccountLink.objects.create(
            account=account, source_table='app01_admin', source_pk=login
        )
        return account


class LegacyBridgeTests(H3Fixture):
    def test_account_identity_reaches_real_admin_page(self):
        self.make_admin_account('001')
        helpers.login_account(self.client, '001', PASSWORD)

        resp = self.client.get('/admin/student/list/')

        self.assertEqual(resp.status_code, 200, 'app01 真实页面应可用')
        self.assertIn('学生甲', resp.content.decode('utf-8'))

    def test_account_without_link_cannot_reach_admin_page(self):
        account = Account.objects.create_user(
            'NOLINK01', PASSWORD, display_name='无映射', person_type=PersonType.ADMIN
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        helpers.login_account(self.client, 'NOLINK01', PASSWORD)

        resp = self.client.get('/admin/student/list/', follow=False)
        self.assertIn(resp.status_code, (302, 403))

    def test_legacy_session_still_works(self):
        helpers.set_legacy_session(self.client, 'admin', '001')

        resp = self.client.get('/admin/student/list/')

        self.assertEqual(resp.status_code, 200)

    def test_conflict_denied_on_admin_page(self):
        self.make_admin_account('001')
        helpers.login_account(self.client, '001', PASSWORD)
        # 旧 session 指向另一个人 -> 冲突
        helpers.set_legacy_session(self.client, 'admin', '999')

        resp = self.client.get('/admin/student/list/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(resp.status_code, 403)

    def test_student_identity_cannot_reach_admin_page(self):
        account = Account.objects.create_user(
            'S01', PASSWORD, display_name='学生甲', person_type=PersonType.STUDENT
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        LegacyAccountLink.objects.create(
            account=account, source_table='app01_student', source_pk='S01'
        )
        helpers.login_account(self.client, 'S01', PASSWORD)

        resp = self.client.get('/admin/student/list/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        # 桥接后的 role=student，admin 装饰器应拒绝
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_cannot_reach_admin_page(self):
        resp = self.client.get('/admin/student/list/', follow=False)
        self.assertIn(resp.status_code, (302, 403))

    def test_client_supplied_identity_params_ignored(self):
        self.make_admin_account('001')
        helpers.login_account(self.client, '001', PASSWORD)

        resp = self.client.get(
            '/admin/student/list/?id=999&type=admin&info={"id":"999"}'
        )

        self.assertEqual(resp.status_code, 200)
        # 服务端身份仍来自 LegacyAccountLink（001 是 admin）
        self.assertEqual(self.client.session['info']['id'], '001')

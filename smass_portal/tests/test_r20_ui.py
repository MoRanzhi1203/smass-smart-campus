"""R20 页面层：多角色门户与配置后台的页面流程。

运行::

    python manage.py test smass_portal.tests.test_r20_ui --settings=smass.settings_r20
"""
from __future__ import annotations

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_portal.models import PortalNotice, PortalSection

PASSWORD = 'R20Ui#2026'
LOGIN = '/r21/login/'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def login(client, login_name):
    return client.post(LOGIN, {'login_name': login_name, 'password': PASSWORD})


class PortalUiTests(TestCase):
    def setUp(self):
        self.admin = make_account('r20uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.teacher = make_account('r20uiteacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('r20uistu', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/r20/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_admin(self):
        login(self.client, 'r20uistu')
        self.assertEqual(403, self.client.get('/r20/admin/').status_code)

    def test_admin_bootstrap_then_student_sees_portal(self):
        admin = Client()
        login(admin, 'r20uiadmin')
        response = admin.post('/r20/admin/bootstrap/')
        self.assertEqual(302, response.status_code)
        self.assertTrue(PortalSection.objects.filter(code='student').exists())

        login(self.client, 'r20uistu')
        response = self.client.get('/r20/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '学生门户')
        self.assertNotContains(response, '管理人员门户')

    def test_teacher_sees_teacher_portal(self):
        login(self.client, 'r20uiadmin')
        self.client.post('/r20/admin/bootstrap/')

        teacher = Client()
        login(teacher, 'r20uiteacher')
        response = teacher.get('/r20/')
        self.assertContains(response, '教师/辅导员门户')
        self.assertNotContains(response, '学生门户')

    def test_admin_creates_notice_and_student_reads_it(self):
        admin = Client()
        login(admin, 'r20uiadmin')
        admin.post('/r20/admin/bootstrap/')
        response = admin.post('/r20/admin/notice/', {
            'title': '门户公告', 'body': '公告内容', 'roles': 'student',
        })
        self.assertEqual(302, response.status_code)
        notice = PortalNotice.objects.get(title='门户公告')
        admin.post('/r20/admin/notice/{}/publish/'.format(notice.pk))

        login(self.client, 'r20uistu')
        response = self.client.get('/r20/')
        self.assertContains(response, '门户公告')

    def test_admin_creates_section_and_link(self):
        admin = Client()
        login(admin, 'r20uiadmin')
        response = admin.post('/r20/admin/section/', {
            'code': 'extra', 'title': '扩展区块', 'roles': 'student', 'sort_order': '99',
        })
        self.assertEqual(302, response.status_code)
        section = PortalSection.objects.get(code='extra')

        response = admin.post('/r20/admin/link/', {
            'section': section.pk, 'label': '扩展入口',
            'fallback_url': '/r13/sessions/', 'roles': 'student',
        })
        self.assertEqual(302, response.status_code)

        student = Client()
        login(student, 'r20uistu')
        response = student.get('/r20/')
        self.assertContains(response, '扩展区块')
        self.assertContains(response, '扩展入口')

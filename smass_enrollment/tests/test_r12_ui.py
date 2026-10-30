"""R12 页面层：分班/转专业/学籍异动的真实页面流程与权限负向。

运行::

    python manage.py test smass_enrollment.tests.test_r12_ui --settings=smass.settings_r12
"""
from __future__ import annotations

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_enrollment.models import (
    MajorTransferRequest,
    PlacementRule,
    StudentStatusChange,
)

PASSWORD = 'R12Ui#2026'
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


def make_unit(code, name, unit_type, parent=None):
    return OrganizationUnit.objects.create(
        code=code, name=name, unit_type=unit_type, parent=parent)


class EnrollmentUiTests(TestCase):
    def setUp(self):
        self.college = make_unit('C01', '计算机学院', UNIT_TYPE_COLLEGE)
        self.major_cs = make_unit('M01', '计算机科学与技术', UNIT_TYPE_MAJOR, self.college)
        self.major_se = make_unit('M02', '软件工程', UNIT_TYPE_MAJOR, self.college)
        self.class_cs1 = make_unit('CL01', '计科一班', UNIT_TYPE_CLASS, self.major_cs)
        self.class_se1 = make_unit('CL11', '软工一班', UNIT_TYPE_CLASS, self.major_se)

        self.admin = make_account('r12uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('r12uistu', [RoleCode.STUDENT])
        self.student2 = make_account('r12uistu2', [RoleCode.STUDENT])

        self.record = StudentRecord.objects.create(
            student_no='S5001', name='页面学生', unit=self.class_cs1,
            account=self.student)
        self.record2 = StudentRecord.objects.create(
            student_no='S5002', name='页面学生二', unit=self.class_cs1,
            account=self.student2)

        self.rule = PlacementRule.objects.create(
            name='页面分班规则', major=self.major_cs, capacity_per_class=0,
            strategy='round_robin')

    # ---- 登录与权限 ----
    def test_requires_login(self):
        response = self.client.get('/r12/transfers/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_placement_pages(self):
        login(self.client, 'r12uistu')
        response = self.client.get('/r12/placement/')
        self.assertEqual(403, response.status_code)

    def test_manager_sees_placement_page(self):
        login(self.client, 'r12uiadmin')
        response = self.client.get('/r12/placement/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '页面分班规则')

    # ---- 分班页面流程 ----
    def test_preview_and_apply_through_pages(self):
        # 分班候选：在读且尚未编班的学生
        StudentRecord.objects.create(
            student_no='S5101', name='待分班一', unit=self.major_cs)
        StudentRecord.objects.create(
            student_no='S5102', name='待分班二', unit=self.major_cs)

        login(self.client, 'r12uiadmin')
        response = self.client.post(
            '/r12/placement/preview/{}/'.format(self.rule.pk))
        self.assertEqual(302, response.status_code)

        from smass_enrollment.models import PlacementBatch
        batch = PlacementBatch.objects.latest('pk')
        self.assertEqual(batch.status, 'preview')

        detail = self.client.get('/r12/placement/{}/'.format(batch.pk))
        self.assertEqual(200, detail.status_code)

        response = self.client.post('/r12/placement/{}/apply/'.format(batch.pk))
        self.assertEqual(302, response.status_code)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'applied')
        placed = StudentRecord.objects.get(student_no='S5101')
        self.assertEqual(placed.unit.unit_type, UNIT_TYPE_CLASS)

    # ---- 转专业页面 ----
    def test_student_submits_transfer_via_page(self):
        login(self.client, 'r12uistu')
        response = self.client.post('/r12/transfers/submit/', {
            'to_major': self.major_se.pk,
            'reason': '兴趣方向调整',
        })
        self.assertEqual(302, response.status_code)
        transfer = MajorTransferRequest.objects.get(record=self.record)
        self.assertEqual(transfer.status, 'submitted')

    def test_student_only_sees_own_transfers(self):
        MajorTransferRequest.objects.create(
            record=self.record2, from_unit=self.class_cs1,
            to_major=self.major_se, reason='他人申请', status='submitted')
        MajorTransferRequest.objects.create(
            record=self.record, from_unit=self.class_cs1,
            to_major=self.major_se, reason='我的申请', status='submitted')

        login(self.client, 'r12uistu')
        response = self.client.get('/r12/transfers/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '我的申请')
        self.assertNotContains(response, '他人申请')

    def test_manager_approves_and_applies_via_page(self):
        transfer = MajorTransferRequest.objects.create(
            record=self.record, from_unit=self.class_cs1,
            to_major=self.major_se, reason='理由', status='submitted')

        login(self.client, 'r12uiadmin')
        response = self.client.post(
            '/r12/transfers/{}/approve/'.format(transfer.pk))
        self.assertEqual(302, response.status_code)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'approved')

        response = self.client.post(
            '/r12/transfers/{}/apply/'.format(transfer.pk),
            {'target_class': self.class_se1.pk})
        self.assertEqual(302, response.status_code)
        transfer.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(transfer.status, 'effective')
        self.assertEqual(self.record.unit_id, self.class_se1.pk)

    def test_student_cannot_approve(self):
        transfer = MajorTransferRequest.objects.create(
            record=self.record, from_unit=self.class_cs1,
            to_major=self.major_se, reason='理由', status='submitted')
        login(self.client, 'r12uistu')
        response = self.client.post(
            '/r12/transfers/{}/approve/'.format(transfer.pk))
        self.assertEqual(403, response.status_code)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'submitted')

    # ---- 学籍异动页面 ----
    def test_student_submits_status_change(self):
        login(self.client, 'r12uistu')
        response = self.client.post('/r12/status/submit/', {
            'change_type': 'suspend',
            'reason': '病假',
        })
        self.assertEqual(302, response.status_code)
        change = StudentStatusChange.objects.get(record=self.record)
        self.assertEqual(change.status, 'submitted')

    def test_manager_sees_status_page(self):
        login(self.client, 'r12uiadmin')
        response = self.client.get('/r12/status/')
        self.assertEqual(200, response.status_code)

    def test_manager_approves_status_change(self):
        change = StudentStatusChange.objects.create(
            record=self.record, change_type='suspend',
            from_status='enrolled', to_status='suspended',
            reason='病假', status='submitted')
        login(self.client, 'r12uiadmin')
        response = self.client.post('/r12/status/{}/approve/'.format(change.pk))
        self.assertEqual(302, response.status_code)
        change.refresh_from_db()
        self.assertEqual(change.status, 'approved')

        response = self.client.post('/r12/status/{}/apply/'.format(change.pk))
        self.assertEqual(302, response.status_code)
        change.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(change.status, 'effective')
        self.assertEqual(self.record.status, 'suspended')

"""U3：R4 组织与学生垂直切片。

覆盖：新建组织（成功/校验失败/层级非法）、编辑与移动、学生详情与字段级权限、
学生编辑的乐观锁冲突（409）、导入预览零写入与提交持久化。
"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_organization import services
from smass_organization.models import (
    DataImportJob,
    OrganizationMembership,
    OrganizationUnit,
    StudentRecord,
)

PASSWORD = 'U3Pass#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u3')
    return Account.objects.get(pk=account.pk)


class U3Fixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.admin = make_account('U3ADM', RoleCode.SYSTEM_ADMIN)
        self.college = org_unit('U3C', 'U3学院', 'college')
        self.major = org_unit('U3M', 'U3专业', 'major', self.college)
        self.klass = org_unit('U3K', 'U3班级', 'class', self.major)
        self.client.force_login(self.admin)


def org_unit(code, name, unit_type, parent=None):
    return OrganizationUnit.objects.create(
        code=code, name=name, unit_type=unit_type, parent=parent
    )


class UnitFormTests(U3Fixture):
    def test_new_unit_page_renders(self):
        resp = self.client.get('/r4/units/new/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="unit-form"', body)
        self.assertIn('id="f-code"', body)

    def test_create_unit_persists(self):
        resp = self.client.post('/r4/units/new/', {
            'code': 'U3NEW', 'name': '新建学院', 'unit_type': 'college',
            'parent': '', 'sort_order': '0',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(OrganizationUnit.objects.filter(code='U3NEW').exists())

    def test_create_unit_missing_code_rejected(self):
        resp = self.client.post('/r4/units/new/', {
            'code': '', 'name': '缺编码', 'unit_type': 'college', 'parent': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '编码不能为空')
        self.assertFalse(OrganizationUnit.objects.filter(name='缺编码').exists())

    def test_create_unit_invalid_hierarchy_rejected(self):
        """college 不能挂在 class 下。"""
        resp = self.client.post('/r4/units/new/', {
            'code': 'U3BAD', 'name': '非法层级', 'unit_type': 'college',
            'parent': str(self.klass.pk),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')
        self.assertFalse(OrganizationUnit.objects.filter(code='U3BAD').exists())

    def test_duplicate_code_rejected(self):
        resp = self.client.post('/r4/units/new/', {
            'code': 'U3C', 'name': '重复编码', 'unit_type': 'college', 'parent': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')
        self.assertEqual(OrganizationUnit.objects.filter(code='U3C').count(), 1)

    def test_edit_unit_name(self):
        resp = self.client.post('/r4/units/{}/edit/'.format(self.major.pk), {
            'name': 'U3专业改名', 'parent': str(self.college.pk), 'sort_order': '0',
        })
        self.assertEqual(resp.status_code, 302)
        self.major.refresh_from_db()
        self.assertEqual(self.major.name, 'U3专业改名')

    def test_move_unit_cycle_rejected(self):
        """把祖先移到自己的后代下应被拒绝。"""
        resp = self.client.post('/r4/units/{}/edit/'.format(self.college.pk), {
            'name': 'U3学院', 'parent': str(self.klass.pk), 'sort_order': '0',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')
        self.college.refresh_from_db()
        self.assertIsNone(self.college.parent_id)

    def test_anonymous_denied(self):
        self.client.logout()
        self.assertEqual(self.client.get('/r4/units/new/').status_code, 403)

    def test_teacher_cannot_open_unit_form(self):
        teacher = make_account('U3T', RoleCode.TEACHER, 'teacher')
        self.client.force_login(teacher)
        self.assertEqual(self.client.get('/r4/units/new/').status_code, 403)


class StudentDetailTests(U3Fixture):
    def setUp(self):
        super().setUp()
        self.record = StudentRecord.objects.create(
            student_no='U3S001', name='U3学生', unit=self.klass
        )

    def test_detail_page_renders(self):
        resp = self.client.get('/r4/students/U3S001/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('U3学生', body)
        self.assertIn('id="student-detail-table"', body)

    def test_detail_404_for_unknown(self):
        self.assertEqual(self.client.get('/r4/students/NOPE/').status_code, 404)

    def test_detail_denied_for_other_college(self):
        other = org_unit('U3OTHER', '他院', 'college')
        record = StudentRecord.objects.create(
            student_no='U3S999', name='他院学生', unit=other
        )
        college_admin = make_account('U3CA', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=college_admin, unit=self.college)
        self.client.force_login(college_admin)

        # 本院学生可见
        self.assertEqual(self.client.get('/r4/students/U3S001/').status_code, 200)
        # 他院学生 404（不泄露存在性）
        self.assertEqual(self.client.get('/r4/students/U3S999/').status_code, 404)

    def test_student_sees_own_detail_only(self):
        student_account = make_account('U3S', RoleCode.STUDENT, 'student')
        self.record.account = student_account
        self.record.save(update_fields=['account'])
        other = StudentRecord.objects.create(
            student_no='U3S002', name='别人', unit=self.klass
        )
        self.client.force_login(student_account)

        self.assertEqual(self.client.get('/r4/students/U3S001/').status_code, 200)
        self.assertEqual(self.client.get('/r4/students/U3S002/').status_code, 404)


class StudentEditTests(U3Fixture):
    def setUp(self):
        super().setUp()
        self.record = StudentRecord.objects.create(
            student_no='U3E001', name='编辑前', unit=self.klass
        )

    def test_edit_form_renders(self):
        resp = self.client.get('/r4/students/U3E001/edit/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="student-form"', body)
        self.assertIn('name="version"', body)

    def test_edit_persists_and_bumps_version(self):
        old_version = self.record.version
        resp = self.client.post('/r4/students/U3E001/edit/', {
            'name': '编辑后', 'status': 'active',
            'unit': str(self.klass.pk), 'version': str(old_version),
        })
        self.assertEqual(resp.status_code, 302)

        self.record.refresh_from_db()
        self.assertEqual(self.record.name, '编辑后')
        self.assertEqual(self.record.version, old_version + 1)

    def test_version_conflict_returns_409(self):
        """用过期版本号提交 -> 409 + 明确提示。"""
        stale = self.record.version
        # 先被别人改一次
        services.update_student(self.record, name='别人改的',
                                expected_version=stale, actor='other')

        resp = self.client.post('/r4/students/U3E001/edit/', {
            'name': '我的修改', 'status': 'active',
            'unit': str(self.klass.pk), 'version': str(stale),
        })
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, '已被他人修改', status_code=409)

        self.record.refresh_from_db()
        self.assertEqual(self.record.name, '别人改的')

    def test_empty_name_rejected(self):
        resp = self.client.post('/r4/students/U3E001/edit/', {
            'name': '', 'status': 'active',
            'unit': str(self.klass.pk), 'version': str(self.record.version),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '姓名不能为空')

    def test_teacher_cannot_edit(self):
        teacher = make_account('U3ET', RoleCode.TEACHER, 'teacher')
        self.client.force_login(teacher)
        self.assertEqual(
            self.client.get('/r4/students/U3E001/edit/').status_code, 403)


class ImportFlowTests(U3Fixture):
    CSV = 'student_no,name,unit_code\nU3I001,导入甲,U3K\nU3I002,导入乙,U3K\n'

    BAD_CSV = 'student_no,name,unit_code\nU3I003,,U3K\n,NONAME,U3K\n'

    def test_preview_does_not_write(self):
        before = StudentRecord.objects.count()
        resp = self.client.post(
            '/r4/import/preview/', data='{"csv": %s}'
            % _json_str(self.CSV), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['preview']['valid'], 2)
        # 关键：预览不写学生
        self.assertEqual(StudentRecord.objects.count(), before)

    def test_preview_reports_row_errors(self):
        resp = self.client.post(
            '/r4/import/preview/', data='{"csv": %s}'
            % _json_str(self.BAD_CSV), content_type='application/json')
        payload = resp.json()
        self.assertEqual(payload['preview']['invalid'], 2)
        messages = ' '.join(r.get('error', '') for r in payload['preview']['rows'])
        self.assertIn('姓名不能为空', messages)

    def test_commit_persists_students(self):
        resp = self.client.post(
            '/r4/import/commit/', data='{"csv": %s}'
            % _json_str(self.CSV), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload['ok'])
        self.assertTrue(StudentRecord.objects.filter(student_no='U3I001').exists())
        self.assertTrue(StudentRecord.objects.filter(student_no='U3I002').exists())

    def test_commit_creates_import_job(self):
        before = DataImportJob.objects.count()
        self.client.post('/r4/import/commit/', data='{"csv": %s}'
                         % _json_str(self.CSV), content_type='application/json')
        self.assertEqual(DataImportJob.objects.count(), before + 1)

    def test_empty_csv_rejected(self):
        resp = self.client.post('/r4/import/preview/', data='{"csv": "  "}',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_teacher_cannot_import(self):
        teacher = make_account('U3IT', RoleCode.TEACHER, 'teacher')
        self.client.force_login(teacher)
        self.assertEqual(
            self.client.get('/r4/import/').status_code, 403)


def _json_str(text):
    import json
    return json.dumps(text)

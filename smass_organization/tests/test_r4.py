"""R4 测试：组织树约束、字段级权限、导入流程、视图越权。"""
import json

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_organization import services
from smass_organization.models import (
    DataImportJob,
    OrganizationUnit,
    StudentFieldDefinition,
    StudentRecord,
    StudentRecordChange,
)

PASSWORD = 'R4Pass#2024'


def make_account(login, role=None, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='r4_test')
    return Account.objects.get(pk=account.pk)


class OrganizationTreeTests(TestCase):
    def setUp(self):
        self.college = services.create_unit(
            code='C01', name='信息工程学院', unit_type='college'
        )

    def test_create_child_of_allowed_type(self):
        major = services.create_unit(
            code='M01', name='信息安全', unit_type='major', parent=self.college
        )
        self.assertEqual(major.parent, self.college)

    def test_invalid_hierarchy_rejected(self):
        with self.assertRaises(services.InvalidHierarchyError):
            services.create_unit(code='X1', name='非法', unit_type='class',
                                 parent=self.college)

    def test_cycle_rejected_on_move(self):
        major = services.create_unit(code='M01', name='信安', unit_type='major',
                                     parent=self.college)
        klass = services.create_unit(code='K01', name='信安2101', unit_type='class',
                                     parent=major)

        with self.assertRaises(services.CycleError):
            services.move_unit(self.college, klass)

    def test_move_to_self_rejected(self):
        with self.assertRaises(services.CycleError):
            services.move_unit(self.college, self.college)

    def test_valid_move(self):
        major = services.create_unit(code='M01', name='信安', unit_type='major',
                                     parent=self.college)
        grade = services.create_unit(code='G21', name='2021级', unit_type='grade',
                                     parent=self.college)
        klass = services.create_unit(code='K01', name='信安2101', unit_type='class',
                                     parent=major)

        services.move_unit(klass, grade)
        klass.refresh_from_db()
        self.assertEqual(klass.parent, grade)

    def test_duplicate_code_rejected(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            services.create_unit(code='C01', name='重复', unit_type='college')


class FieldPermissionTests(TestCase):
    def setUp(self):
        StudentFieldDefinition.objects.create(
            code='phone', label='手机号', is_sensitive=True,
            visible_roles=['system_admin'], editable_roles=['system_admin'],
        )
        StudentFieldDefinition.objects.create(
            code='note', label='备注', visible_roles=[], editable_roles=[],
        )
        self.admin = make_account('R4A001', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('R4T001', RoleCode.TEACHER, 'teacher')

    def test_admin_sees_sensitive_field(self):
        self.assertTrue(services.can_view_field(self.admin, 'phone'))

    def test_teacher_cannot_see_sensitive_field(self):
        self.assertFalse(services.can_view_field(self.teacher, 'phone'))

    def test_public_field_visible_to_all(self):
        self.assertTrue(services.can_view_field(self.teacher, 'note'))

    def test_filtered_extra_excludes_unauthorized(self):
        record = StudentRecord.objects.create(
            student_no='R4S001', name='合成学生',
            extra={'phone': '00000000000', 'note': 'ok'},
        )

        self.assertEqual(services.filtered_extra(record, self.teacher), {'note': 'ok'})
        self.assertEqual(
            set(services.filtered_extra(record, self.admin)), {'phone', 'note'}
        )

    def test_anonymous_sees_only_public(self):
        record = StudentRecord.objects.create(
            student_no='R4S002', name='合成学生', extra={'phone': 'x', 'note': 'y'}
        )
        self.assertEqual(services.filtered_extra(record, None), {'note': 'y'})


class ImportTests(TestCase):
    def setUp(self):
        self.college = services.create_unit(
            code='C01', name='信息工程学院', unit_type='college'
        )

    def _csv(self, rows):
        lines = ['student_no,name,unit_code,status']
        lines.extend(rows)
        return '\n'.join(lines)

    def test_preview_reports_errors_without_writing(self):
        text = self._csv([
            'S001,张三,C01,enrolled',
            ',,C01,enrolled',            # 缺学号/姓名
            'S001,重复,C01,enrolled',     # 文件内重复
            'S002,李四,NOPE,enrolled',    # 组织不存在
        ])
        job, preview = services.import_preview(text, actor='tester')

        self.assertEqual(job.total_rows, 4)
        self.assertEqual(job.error_rows, 3)
        self.assertEqual(job.success_rows, 1)
        self.assertEqual(StudentRecord.objects.count(), 0)
        self.assertEqual(job.errors.count(), 4)

        codes = set(job.errors.values_list('error_code', flat=True))
        self.assertIn('EMPTY_STUDENT_NO', codes)
        self.assertIn('DUPLICATE_IN_FILE', codes)
        self.assertIn('UNKNOWN_UNIT', codes)

    def test_commit_creates_records_and_history(self):
        text = self._csv([
            'S001,张三,C01,enrolled',
            'S002,李四,C01,enrolled',
        ])
        job, stats = services.import_commit(text, actor='tester')

        self.assertEqual(stats['created'], 2)
        self.assertEqual(StudentRecord.objects.count(), 2)
        self.assertEqual(StudentRecordChange.objects.count(), 2)
        self.assertEqual(job.status, 'committed')

    def test_commit_updates_and_records_change(self):
        StudentRecord.objects.create(student_no='S001', name='旧名', unit=self.college)
        text = self._csv(['S001,新名,C01,enrolled'])

        job, stats = services.import_commit(text, actor='tester')

        self.assertEqual(stats['updated'], 1)
        record = StudentRecord.objects.get(student_no='S001')
        self.assertEqual(record.name, '新名')
        self.assertEqual(record.version, 2)
        self.assertTrue(
            StudentRecordChange.objects.filter(record=record, field_name='name').exists()
        )

    def test_missing_column_fails_fast(self):
        job, preview = services.import_preview('foo,bar\n1,2', actor='tester')
        self.assertEqual(job.status, 'failed')
        self.assertTrue(job.errors.filter(error_code='MISSING_COLUMN').exists())

    def test_duplicate_student_no_in_db_is_updated_not_duplicated(self):
        text = self._csv(['S009,原名,C01,enrolled'])
        services.import_commit(text, actor='tester')
        services.import_commit(text, actor='tester')

        self.assertEqual(StudentRecord.objects.filter(student_no='S009').count(), 1)


class ViewPermissionTests(TestCase):
    def setUp(self):
        services.create_unit(code='C01', name='学院', unit_type='college')
        StudentRecord.objects.create(student_no='S001', name='学生甲',
                                     extra={'x': 1})
        self.admin = make_account('R4V001', RoleCode.SYSTEM_ADMIN)
        self.nobody = make_account('R4V002', None)

    def test_anonymous_denied(self):
        resp = self.client.get('/r4/units/')
        self.assertEqual(resp.status_code, 403)

    def test_account_without_required_role_denied(self):
        self.client.force_login(self.nobody)
        resp = self.client.get('/r4/units/')
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_list_units_and_students(self):
        self.client.force_login(self.admin)

        resp = self.client.get('/r4/units/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('学院', resp.content.decode('utf-8'))

        resp = self.client.get('/r4/students/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('学生甲', resp.content.decode('utf-8'))

    def test_student_detail_json(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/r4/students/S001/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['student']['student_no'], 'S001')

    def test_create_unit_via_api(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            '/r4/units/create/',
            data=json.dumps({'code': 'C02', 'name': '新学院', 'unit_type': 'college'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(OrganizationUnit.objects.filter(code='C02').exists())

    def test_move_cycle_returns_400(self):
        college = OrganizationUnit.objects.get(code='C01')
        major = services.create_unit(code='M01', name='专业', unit_type='major',
                                     parent=college)
        klass = services.create_unit(code='K01', name='班级', unit_type='class',
                                     parent=major)

        self.client.force_login(self.admin)
        resp = self.client.post(
            '/r4/units/{}/move/'.format(college.pk),
            data=json.dumps({'parent': klass.pk}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'CYCLE')

    def test_health_endpoint(self):
        resp = self.client.get('/r4/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

"""R4-03：受限导出的安全与正确性。"""
import csv
import io

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_organization import export, services
from smass_organization.models import (
    OrganizationMembership,
    StudentFieldDefinition,
    StudentRecord,
)

PASSWORD = 'R4Exp#2024'


def make_account(login, role):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin'
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    core_services.grant_role(account, role, granted_by='r4_export')
    return Account.objects.get(pk=account.pk)


def rows_of(text):
    return list(csv.reader(io.StringIO(text)))


class ExportScopeTests(TestCase):
    def setUp(self):
        self.college_a = services.create_unit(code='CA', name='A院', unit_type='college')
        self.college_b = services.create_unit(code='CB', name='B院', unit_type='college')

        self.sys = make_account('E_SYS', RoleCode.SYSTEM_ADMIN)
        self.admin_a = make_account('E_ADMA', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)

        StudentRecord.objects.create(student_no='SA1', name='A学生', unit=self.college_a)
        StudentRecord.objects.create(student_no='SB1', name='B学生', unit=self.college_b)

    def test_admin_export_only_own_college(self):
        text, meta = export.export_students_csv(self.admin_a)
        body = text

        self.assertIn('SA1', body)
        self.assertNotIn('SB1', body)
        self.assertEqual(meta['exported'], 1)
        self.assertEqual(meta['total'], 1)

    def test_system_admin_export_all(self):
        text, meta = export.export_students_csv(self.sys)
        self.assertEqual(meta['exported'], 2)
        self.assertIn('SA1', text)
        self.assertIn('SB1', text)

    def test_no_role_exports_empty(self):
        account = Account.objects.create_user(
            'E_NOROLE', PASSWORD, display_name='无角色', person_type='admin'
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])

        text, meta = export.export_students_csv(account)
        self.assertEqual(meta['exported'], 0)
        self.assertEqual(len(rows_of(text)), 1)  # 只有表头


class ExportFieldScopeTests(TestCase):
    def setUp(self):
        StudentFieldDefinition.objects.create(
            code='phone', label='手机号', is_sensitive=True,
            visible_roles=['system_admin'],
        )
        self.college = services.create_unit(code='C1', name='学院', unit_type='college')
        StudentRecord.objects.create(
            student_no='S1', name='学生', unit=self.college,
            extra={'phone': '13900000000'},
        )
        self.sys = make_account('F_SYS', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('F_T', RoleCode.TEACHER)
        OrganizationMembership.objects.create(account=self.teacher, unit=self.college)

    def test_sensitive_column_absent_for_teacher(self):
        text, meta = export.export_students_csv(self.teacher)
        self.assertNotIn('phone', meta['columns'])
        self.assertNotIn('13900000000', text)

    def test_sensitive_column_present_for_admin(self):
        text, meta = export.export_students_csv(self.sys)
        self.assertIn('phone', meta['columns'])
        self.assertIn('13900000000', text)


class CsvInjectionTests(TestCase):
    def setUp(self):
        self.college = services.create_unit(code='C1', name='学院', unit_type='college')
        StudentRecord.objects.create(
            student_no='S1', name='=cmd|calc', unit=self.college
        )
        self.sys = make_account('I_SYS', RoleCode.SYSTEM_ADMIN)

    def test_formula_prefixed_cell_is_neutralized(self):
        text, _meta = export.export_students_csv(self.sys)
        rows = rows_of(text)
        header, row = rows[0], rows[1]

        name_index = header.index('name')
        self.assertTrue(row[name_index].startswith("'="))

    def test_sanitize_cell_handles_all_prefixes(self):
        for prefix in ('=', '+', '-', '@'):
            self.assertTrue(export.sanitize_cell(prefix + 'x').startswith("'"))

    def test_newlines_replaced(self):
        self.assertEqual(export.sanitize_cell('a\nb'), 'a b')


class ExportPaginationTests(TestCase):
    def setUp(self):
        self.college = services.create_unit(code='C1', name='学院', unit_type='college')
        for index in range(10):
            StudentRecord.objects.create(
                student_no='P{:03d}'.format(index), name='学生{}'.format(index),
                unit=self.college,
            )
        self.sys = make_account('P_SYS', RoleCode.SYSTEM_ADMIN)

    def test_limit_and_offset(self):
        text, meta = export.export_students_csv(self.sys, limit=4, offset=0)
        self.assertEqual(meta['exported'], 4)
        self.assertTrue(meta['truncated'])

        text2, meta2 = export.export_students_csv(self.sys, limit=4, offset=4)
        self.assertEqual(meta2['exported'], 4)
        self.assertNotEqual(text, text2)

        _text3, meta3 = export.export_students_csv(self.sys, limit=4, offset=8)
        self.assertEqual(meta3['exported'], 2)
        self.assertFalse(meta3['truncated'])

    def test_total_reflects_scope_not_page(self):
        _text, meta = export.export_students_csv(self.sys, limit=1)
        self.assertEqual(meta['total'], 10)
        self.assertEqual(meta['exported'], 1)

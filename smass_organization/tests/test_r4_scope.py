"""R4-01：组织级数据 scope（P0 安全）。"""
from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_organization import services
from smass_organization.models import (
    OrganizationMembership,
    OrganizationUnit,
    StudentRecord,
)

PASSWORD = 'R4Scope#2024'


def make_account(login, role=None, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='r4_scope')
    return Account.objects.get(pk=account.pk)


class ScopeFixture(TestCase):
    def setUp(self):
        self.college_a = services.create_unit(code='CA', name='学院A', unit_type='college')
        self.college_b = services.create_unit(code='CB', name='学院B', unit_type='college')
        self.major_a = services.create_unit(code='MA', name='专业A', unit_type='major',
                                            parent=self.college_a)
        self.major_b = services.create_unit(code='MB', name='专业B', unit_type='major',
                                            parent=self.college_b)
        self.class_a = services.create_unit(code='KA', name='班级A', unit_type='class',
                                            parent=self.major_a)
        self.class_b = services.create_unit(code='KB', name='班级B', unit_type='class',
                                            parent=self.major_b)

        self.stu_a = StudentRecord.objects.create(
            student_no='SA01', name='A院学生', unit=self.class_a
        )
        self.stu_b = StudentRecord.objects.create(
            student_no='SB01', name='B院学生', unit=self.class_b
        )

        self.sys = make_account('SYS001', RoleCode.SYSTEM_ADMIN)
        self.admin_a = make_account('ADMA', RoleCode.COLLEGE_ADMIN)
        self.admin_b = make_account('ADMB', RoleCode.COLLEGE_ADMIN)
        self.teacher_a = make_account('TCHA', RoleCode.TEACHER, 'teacher')
        self.student_a = make_account('STUA', RoleCode.STUDENT, 'student')
        self.nobody = make_account('NOBODY', None)

        # 绑定成员关系
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)
        OrganizationMembership.objects.create(account=self.admin_b, unit=self.college_b)
        OrganizationMembership.objects.create(account=self.teacher_a, unit=self.major_a)
        # 学生档案与账号关联（用于"学生只看自己"）
        self.stu_a.account = self.student_a
        self.stu_a.save(update_fields=['account'])


class ScopedStudentsTests(ScopeFixture):
    def test_system_admin_sees_all(self):
        self.assertEqual(services.scoped_students(self.sys).count(), 2)

    def test_college_admin_sees_only_own_college_subtree(self):
        ids = set(services.scoped_students(self.admin_a).values_list('student_no', flat=True))
        self.assertEqual(ids, {'SA01'})

    def test_college_admin_cannot_see_other_college(self):
        ids = set(services.scoped_students(self.admin_b).values_list('student_no', flat=True))
        self.assertEqual(ids, {'SB01'})

    def test_teacher_scoped_to_own_major(self):
        ids = set(services.scoped_students(self.teacher_a).values_list('student_no', flat=True))
        self.assertEqual(ids, {'SA01'})

    def test_student_sees_only_self(self):
        ids = set(services.scoped_students(self.student_a).values_list('student_no', flat=True))
        self.assertEqual(ids, {'SA01'})

    def test_account_without_role_gets_empty(self):
        self.assertEqual(services.scoped_students(self.nobody).count(), 0)

    def test_anonymous_gets_empty(self):
        self.assertEqual(services.scoped_students(None).count(), 0)

    def test_disabled_account_gets_empty(self):
        self.admin_a.is_active = False
        self.admin_a.save(update_fields=['is_active'])
        self.assertEqual(services.scoped_students(self.admin_a).count(), 0)

    def test_no_membership_gets_empty_not_all(self):
        """关键：无成员关系绝不可回退为"全部"。"""
        admin = make_account('ADMNOORG', RoleCode.COLLEGE_ADMIN)
        self.assertEqual(services.scoped_students(admin).count(), 0)

    def test_revoked_membership_loses_scope(self):
        membership = OrganizationMembership.objects.filter(account=self.admin_a).first()
        membership.ended_at = membership.started_at
        from django.utils import timezone
        membership.ended_at = timezone.now().date()
        membership.save(update_fields=['ended_at'])

        self.assertEqual(services.scoped_students(self.admin_a).count(), 0)

    def test_node_relocation_recomputes_scope(self):
        """把班级A移到学院B的专业下，A院管理员应看不到它。"""
        # 注意：class 不能直接挂 college（层级约束），必须挂到 major 下
        services.move_unit(self.class_a, self.major_b)

        ids = set(services.scoped_students(self.admin_a).values_list('student_no', flat=True))
        self.assertEqual(ids, set())

        ids_b = set(services.scoped_students(self.admin_b).values_list('student_no', flat=True))
        self.assertEqual(ids_b, {'SA01', 'SB01'})


class ScopedUnitsTests(ScopeFixture):
    def test_system_admin_sees_all_units(self):
        self.assertEqual(services.scoped_units(self.sys).count(), 6)

    def test_college_admin_sees_subtree_only(self):
        codes = set(services.scoped_units(self.admin_a).values_list('code', flat=True))
        self.assertEqual(codes, {'CA', 'MA', 'KA'})

    def test_can_access_unit_denied_for_other_college(self):
        self.assertFalse(services.can_access_unit(self.admin_a, self.college_b))
        self.assertTrue(services.can_access_unit(self.admin_a, self.college_a))


class IdorTests(ScopeFixture):
    def test_can_access_student_respects_scope(self):
        self.assertTrue(services.can_access_student(self.admin_a, self.stu_a))
        self.assertFalse(services.can_access_student(self.admin_a, self.stu_b))

    def test_view_list_only_shows_scoped_students(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/r4/students/')
        body = resp.content.decode('utf-8')

        self.assertIn('A院学生', body)
        self.assertNotIn('B院学生', body)

    def test_view_detail_returns_403_for_other_college(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/r4/students/SB01/')
        self.assertEqual(resp.status_code, 403)

    def test_view_detail_ok_for_own_college(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/r4/students/SA01/')
        self.assertEqual(resp.status_code, 200)

    def test_search_cannot_cross_scope(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/r4/students/?q=B院')
        self.assertNotIn('B院学生', resp.content.decode('utf-8'))

    def test_forged_query_params_do_not_expand_scope(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/r4/students/?unit=KB&scope=all&account=1')
        self.assertNotIn('B院学生', resp.content.decode('utf-8'))

    def test_unit_tree_scoped(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/r4/units/tree/')
        codes = {unit['code'] for unit in resp.json()['units']}
        self.assertEqual(codes, {'CA', 'MA', 'KA'})

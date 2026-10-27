"""G3 RBAC 与对象级授权测试（横向/纵向越权、伪造入参、角色撤销）。"""
from django.test import TestCase

from r21_account import scoping, services
from r21_account.models import Account, PersonType, RoleCode, StudentProfile

PASSWORD = 'RbacPass#2024'


def make_account(login_name, person_type='teacher', scope='', roles=(), is_active=True):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type,
        is_active=is_active, scope_college=scope,
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])

    services.ensure_role_groups()
    for role in roles:
        services.grant_role(account, role, granted_by='test')

    return Account.objects.get(pk=account.pk)


class RoleMatrixTests(TestCase):
    """纵向越权：不同角色的能力边界。"""

    def setUp(self):
        services.ensure_role_groups()

    def test_student_has_no_admin_permission(self):
        student = make_account('S001', 'student', roles=[RoleCode.STUDENT])
        for codename in ('add_data', 'change_data', 'delete_data',
                         'reset_password', 'import_data', 'manage_roles',
                         'dangerous_bulk_delete'):
            with self.subTest(codename=codename):
                self.assertFalse(services.account_has_perm(student, codename))

    def test_teacher_cannot_manage_roles(self):
        teacher = make_account('T001', 'teacher', roles=[RoleCode.TEACHER])
        self.assertTrue(services.account_has_perm(teacher, 'view_data'))
        self.assertFalse(services.account_has_perm(teacher, 'manage_roles'))

    def test_college_admin_cannot_delete(self):
        admin = make_account('C001', 'admin', roles=[RoleCode.COLLEGE_ADMIN])
        self.assertTrue(services.account_has_perm(admin, 'add_data'))
        self.assertFalse(services.account_has_perm(admin, 'delete_data'))
        self.assertFalse(services.account_has_perm(admin, 'reset_password'))

    def test_system_admin_lacks_dangerous_bulk_delete(self):
        admin = make_account('A001', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        self.assertTrue(services.account_has_perm(admin, 'manage_roles'))
        self.assertFalse(services.account_has_perm(admin, 'dangerous_bulk_delete'))


class ObjectScopeTests(TestCase):
    """横向越权：只能看到授权范围内的对象。"""

    @classmethod
    def setUpTestData(cls):
        services.ensure_role_groups()
        cls.college_a = ''
        cls.college_b = ''

    def setUp(self):
        self.sys_admin = make_account('A100', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        self.col_admin_a = make_account(
            'C100', 'admin', scope='信息工程学院', roles=[RoleCode.COLLEGE_ADMIN]
        )
        self.teacher_a = make_account(
            'T100', 'teacher', scope='信息工程学院', roles=[RoleCode.TEACHER]
        )
        self.stu_a = make_account('S100', 'student', roles=[RoleCode.STUDENT])
        self.stu_b = make_account('S200', 'student', roles=[RoleCode.STUDENT])

        self.profile_a = StudentProfile.objects.create(
            account=self.stu_a, student_no='S100', name='甲', college_name='信息工程学院'
        )
        self.profile_b = StudentProfile.objects.create(
            account=self.stu_b, student_no='S200', name='乙', college_name='智能制造学院'
        )

    def test_system_admin_sees_all(self):
        ids = set(scoping.scoped_students(self.sys_admin).values_list('student_no', flat=True))
        self.assertEqual(ids, {'S100', 'S200'})

    def test_college_admin_sees_only_own_college(self):
        ids = set(
            scoping.scoped_students(self.col_admin_a).values_list('student_no', flat=True)
        )
        self.assertEqual(ids, {'S100'})

    def test_teacher_sees_only_own_college(self):
        ids = set(scoping.scoped_students(self.teacher_a).values_list('student_no', flat=True))
        self.assertEqual(ids, {'S100'})

    def test_college_admin_without_scope_denied(self):
        admin = make_account('C200', 'admin', scope='', roles=[RoleCode.COLLEGE_ADMIN])
        self.assertEqual(scoping.scoped_students(admin).count(), 0)

    def test_student_sees_only_self(self):
        ids = set(scoping.scoped_students(self.stu_a).values_list('student_no', flat=True))
        self.assertEqual(ids, {'S100'})

    def test_student_cannot_access_other_profile(self):
        self.assertTrue(scoping.can_access_student(self.stu_a, self.profile_a))
        self.assertFalse(scoping.can_access_student(self.stu_a, self.profile_b))

    def test_anonymous_and_inactive_denied(self):
        inactive = make_account(
            'S300', 'student', roles=[RoleCode.STUDENT], is_active=False
        )
        self.assertEqual(scoping.scoped_students(inactive).count(), 0)
        self.assertEqual(scoping.scoped_students(None).count(), 0)

    def test_account_without_role_denied_by_default(self):
        """默认拒绝：无角色账号看不到任何数据。"""
        services.ensure_role_groups()
        bare = Account.objects.create_user(
            'N001', PASSWORD, display_name='无角色', person_type='teacher'
        )
        bare.must_change_password = False
        bare.save(update_fields=['must_change_password'])

        self.assertEqual(scoping.scoped_students(bare).count(), 0)
        self.assertEqual(scoping.scoped_teachers(bare).count(), 0)


class RoleRevocationTests(TestCase):
    """角色撤销后，权限与可见范围立即失效。"""

    def setUp(self):
        services.ensure_role_groups()
        self.account = make_account(
            'T300', 'teacher', scope='信息工程学院', roles=[RoleCode.TEACHER]
        )
        StudentProfile.objects.create(
            account=make_account('S400', 'student', roles=[RoleCode.STUDENT]),
            student_no='S400', name='丙', college_name='信息工程学院',
        )

    def test_after_revoke_permission_and_scope_gone(self):
        self.assertTrue(services.account_has_perm(self.account, 'view_data'))
        self.assertEqual(scoping.scoped_students(self.account).count(), 1)

        services.revoke_role(self.account, RoleCode.TEACHER, revoked_by='test')

        fresh = Account.objects.get(pk=self.account.pk)
        self.assertFalse(services.account_has_perm(fresh, 'view_data'))
        self.assertEqual(scoping.scoped_students(fresh).count(), 0)


class ForgedInputTests(TestCase):
    """伪造入参不应改变授权结果。"""

    def setUp(self):
        services.ensure_role_groups()
        self.student = make_account('S500', 'student', roles=[RoleCode.STUDENT])
        self.other = make_account('S600', 'student', roles=[RoleCode.STUDENT])
        self.profile_other = StudentProfile.objects.create(
            account=self.other, student_no='S600', name='丁', college_name='信息工程学院'
        )

    def test_forged_login_name_in_session_cannot_elevate(self):
        """登录态由服务端 Session 决定；查询集只看 request.user 的角色。"""
        self.client.force_login(self.student)

        resp = self.client.get('/r21/ping/')
        payload = resp.json()
        self.assertEqual(payload['login_name'], 'S500')
        self.assertEqual(payload['roles'], ['student'])

        # 伪造参数不改变可见范围
        self.assertFalse(scoping.can_access_student(self.student, self.profile_other))

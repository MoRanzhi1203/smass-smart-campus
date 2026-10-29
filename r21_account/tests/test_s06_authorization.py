"""S06 授权门面验收测试：默认拒绝的五维授权。

覆盖主任务书 S06：
- RBAC（动作 -> permission）；
- 组织域（college 收窄，空 scope 不等于全部）；
- 对象级（IDOR：跨院/跨人访问必须拒绝）；
- 字段级（允许列表，新增字段默认不可见；敏感字段脱敏）；
- 业务状态（状态转换表，未知转换默认拒绝）；
- 默认拒绝（匿名、无角色、未知资源、未知动作）。
"""
from django.test import TestCase, override_settings

from r21_account import authorization as authz
from r21_account import services
from r21_account.models import Account, RoleCode, StudentProfile


def make_account(login_name, person_type='teacher', scope='', roles=(), is_active=True):
    account = Account.objects.create_user(
        login_name, 'S06Pass#2024', display_name=login_name, person_type=person_type,
        is_active=is_active, scope_college=scope,
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    services.ensure_role_groups()
    for role in roles:
        services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def make_profile(account, no='S100001', college='计算机学院', phone='13900001111',
                 card='500000199001010011'):
    return StudentProfile.objects.create(
        account=account, student_no=no, name='测试学生{}'.format(no),
        college_name=college, classes_name='软工2101', phone=phone, card_id=card,
    )


class DefaultDenyTests(TestCase):
    """验收点：无角色 / 匿名 / 未知资源 / 未知动作，一律拒绝。"""

    def test_anonymous_denied_everywhere(self):
        for action in authz.ACTION_PERMISSIONS:
            with self.subTest(action=action):
                self.assertFalse(authz.has_action(None, action))

    def test_account_without_roles_is_denied(self):
        account = make_account('S06001', 'teacher', roles=[])
        for action in authz.ACTION_PERMISSIONS:
            with self.subTest(action=action):
                self.assertFalse(authz.has_action(account, action))
        self.assertEqual(list(authz.scope_queryset(account, 'student')), [])

    def test_inactive_account_is_denied(self):
        account = make_account('S06002', 'teacher', roles=[RoleCode.TEACHER],
                               is_active=False)
        self.assertFalse(authz.has_action(account, 'view'))
        self.assertEqual(list(authz.scope_queryset(account, 'student')), [])

    def test_unknown_action_is_denied(self):
        admin = make_account('S06003', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        self.assertFalse(authz.has_action(admin, 'not_an_action'))

    def test_unknown_resource_raises(self):
        admin = make_account('S06004', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        with self.assertRaises(authz.AuthzDenied):
            authz.scope_queryset(admin, 'not_a_resource')


class RbacMatrixTests(TestCase):
    """验收点：动作矩阵。"""

    def test_system_admin_can_view_create_update_but_not_bulk_delete(self):
        admin = make_account('S06101', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        self.assertTrue(authz.has_action(admin, 'view'))
        self.assertTrue(authz.has_action(admin, 'create'))
        self.assertTrue(authz.has_action(admin, 'update'))
        self.assertTrue(authz.has_action(admin, 'import'))
        self.assertTrue(authz.has_action(admin, 'manage_roles'))
        self.assertFalse(authz.has_action(admin, 'bulk_delete'),
                         'dangerous_bulk_delete 不应默认授予')

    def test_college_admin_cannot_delete_or_reset(self):
        admin = make_account('S06102', 'admin', scope='计算机学院',
                             roles=[RoleCode.COLLEGE_ADMIN])
        self.assertTrue(authz.has_action(admin, 'view'))
        self.assertTrue(authz.has_action(admin, 'update'))
        self.assertFalse(authz.has_action(admin, 'delete'))
        self.assertFalse(authz.has_action(admin, 'reset_password'))

    def test_student_has_no_write(self):
        student = make_account('S06103', 'student', roles=[RoleCode.STUDENT])
        self.assertFalse(authz.has_action(student, 'create'))
        self.assertFalse(authz.has_action(student, 'update'))
        self.assertFalse(authz.has_action(student, 'delete'))

    def test_require_action_raises(self):
        student = make_account('S06104', 'student', roles=[RoleCode.STUDENT])
        with self.assertRaises(authz.AuthzDenied) as ctx:
            authz.require_action(student, 'delete')
        self.assertEqual(ctx.exception.reason, 'action_forbidden')


class ScopeTests(TestCase):
    """验收点：组织域收窄。"""

    @classmethod
    def setUpTestData(cls):
        cls.cs = make_account('S06201', 'admin', scope='计算机学院',
                              roles=[RoleCode.COLLEGE_ADMIN])
        cls.art = make_account('S06202', 'admin', scope='艺术学院',
                               roles=[RoleCode.COLLEGE_ADMIN])
        cls.root = make_account('S06203', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        cls.empty = make_account('S06204', 'admin', scope='',
                                 roles=[RoleCode.COLLEGE_ADMIN])

        cls.s1 = make_profile(cls.cs, no='S100001', college='计算机学院')
        cls.s2 = make_profile(cls.art, no='S100002', college='艺术学院')

    def test_college_admin_sees_only_own_college(self):
        ids = set(authz.scope_queryset(self.cs, 'student').values_list('pk', flat=True))
        self.assertIn(self.s1.pk, ids)
        self.assertNotIn(self.s2.pk, ids)

    def test_empty_scope_sees_nothing(self):
        self.assertEqual(list(authz.scope_queryset(self.empty, 'student')), [],
                         '空 scope 不得被当作"全部"')

    def test_system_admin_sees_all(self):
        ids = set(authz.scope_queryset(self.root, 'student').values_list('pk', flat=True))
        self.assertEqual(ids, {self.s1.pk, self.s2.pk})

    def test_student_sees_self_only(self):
        student_account = make_account('S06205', 'student', roles=[RoleCode.STUDENT])
        mine = make_profile(student_account, no='S100003', college='计算机学院')
        ids = set(authz.scope_queryset(student_account, 'student').values_list('pk', flat=True))
        self.assertEqual(ids, {mine.pk})


class ObjectLevelIdorTests(TestCase):
    """验收点：对象级（横向越权）。"""

    @classmethod
    def setUpTestData(cls):
        cls.art_admin = make_account('S06301', 'admin', scope='艺术学院',
                                     roles=[RoleCode.COLLEGE_ADMIN])
        cls.cs_admin = make_account('S06302', 'admin', scope='计算机学院',
                                    roles=[RoleCode.COLLEGE_ADMIN])
        cls.teacher = make_account('S06303', 'teacher', scope='计算机学院',
                                   roles=[RoleCode.TEACHER])
        cls.cs_student = make_profile(cls.cs_admin, no='S100011', college='计算机学院')
        cls.art_student = make_profile(cls.art_admin, no='S100012', college='艺术学院')

    def test_cross_college_access_denied(self):
        self.assertFalse(
            authz.can_access_object(self.art_admin, 'student', self.cs_student))
        with self.assertRaises(authz.AuthzDenied) as ctx:
            authz.require_object(self.art_admin, 'student', self.cs_student)
        self.assertEqual(ctx.exception.reason, 'object_out_of_scope')

    def test_same_college_access_allowed(self):
        self.assertTrue(
            authz.can_access_object(self.cs_admin, 'student', self.cs_student))

    def test_teacher_view_allowed_but_update_denied(self):
        self.assertTrue(authz.can_access_object(self.teacher, 'student', self.cs_student))
        with self.assertRaises(authz.AuthzDenied):
            authz.require_object(self.teacher, 'student', self.cs_student, action='update')

    def test_missing_object_denied(self):
        with self.assertRaises(authz.AuthzDenied) as ctx:
            authz.require_object(self.cs_admin, 'student', None)
        self.assertEqual(ctx.exception.reason, 'object_missing')


class FieldLevelTests(TestCase):
    """验收点：字段级允许列表与脱敏。"""

    @classmethod
    def setUpTestData(cls):
        cls.root = make_account('S06401', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        cls.college = make_account('S06402', 'admin', scope='计算机学院',
                                   roles=[RoleCode.COLLEGE_ADMIN])
        cls.teacher = make_account('S06403', 'teacher', scope='计算机学院',
                                   roles=[RoleCode.TEACHER])
        cls.owner = make_account('S06404', 'student', roles=[RoleCode.STUDENT])
        cls.student = make_profile(cls.owner, no='S100021', college='计算机学院',
                                   phone='13900002222', card='500000199001010011')

    def test_system_admin_sees_all_fields(self):
        self.assertEqual(authz.visible_fields(self.root, 'student'), authz.ALL_FIELDS)

    def test_teacher_cannot_see_phone_or_card(self):
        fields = authz.visible_fields(self.teacher, 'student')
        self.assertNotIn('phone', fields)
        self.assertNotIn('card_id', fields)
        self.assertIn('name', fields)

    def test_student_sees_own_phone_but_not_card(self):
        fields = authz.visible_fields(self.owner, 'student')
        self.assertIn('phone', fields)
        self.assertNotIn('card_id', fields)

    def test_redact_drops_disallowed_keys(self):
        data = {'student_no': 'S100021', 'name': 'X', 'phone': '13900002222',
                'card_id': '500000199001010011', 'college_name': '计算机学院'}
        out = authz.redact(self.teacher, 'student', data)
        self.assertNotIn('phone', out)
        self.assertNotIn('card_id', out)
        self.assertIn('student_no', out)

    def test_redact_masks_sensitive_for_non_privileged(self):
        data = {'phone': '13900002222', 'card_id': '500000199001010011',
                'student_no': 'S100021', 'name': 'X'}
        out = authz.redact(self.owner, 'student', data)
        self.assertEqual(out['phone'], '139******22')
        self.assertNotIn('card_id', out)

    def test_redact_keeps_raw_for_system_admin(self):
        data = {'phone': '13900002222', 'card_id': '500000199001010011'}
        out = authz.redact(self.root, 'student', data)
        self.assertEqual(out['phone'], '13900002222')
        self.assertEqual(out['card_id'], '500000199001010011')

    def test_anonymous_gets_empty_dict(self):
        self.assertEqual(authz.redact(None, 'student', {'name': 'X'}), {})

    def test_write_fields_denied_for_teacher(self):
        """教师对 student 只有 view，没有 update -> 任何字段都不可写。"""
        denied = authz.check_write_fields(self.teacher, 'student', ['name', 'card_id'])
        self.assertEqual(sorted(denied), ['card_id', 'name'])

    def test_no_update_permission_blocks_all_fields(self):
        student_denied = authz.check_write_fields(
            self.owner, 'student', ['name', 'phone', 'card_id'])
        self.assertEqual(sorted(student_denied), ['card_id', 'name', 'phone'])
        self.assertFalse(authz.has_action(self.owner, 'update'))

    def test_require_write_fields_raises(self):
        with self.assertRaises(authz.AuthzDenied) as ctx:
            authz.require_write_fields(self.teacher, 'student', ['phone'])
        self.assertEqual(ctx.exception.reason, 'field_forbidden')

    def test_student_cannot_write_anything(self):
        denied = authz.check_write_fields(self.owner, 'student', ['name'])
        self.assertEqual(denied, ['name'], '学生没有 update 权限，任何字段都不可写')


class StateMachineTests(TestCase):
    """验收点：业务状态转换（引擎级；业务模型接入后用真实字段）。"""

    class _Stub:
        def __init__(self, status):
            self.status = status
            self.pk = 1

    @classmethod
    def setUpTestData(cls):
        cls.root = make_account('S06501', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        cls.college = make_account('S06502', 'admin', scope='计算机学院',
                                   roles=[RoleCode.COLLEGE_ADMIN])

    def test_active_can_be_suspended_by_admin(self):
        self.assertTrue(authz.can_transition(self.root, 'student',
                                             self._Stub('active'), 'suspend'))
        self.assertTrue(authz.can_transition(self.college, 'student',
                                             self._Stub('active'), 'suspend'))

    def test_terminal_state_denies_all(self):
        for stub_state in ('graduated', 'withdrawn'):
            with self.subTest(state=stub_state):
                self.assertFalse(authz.can_transition(
                    self.root, 'student', self._Stub(stub_state), 'suspend'))

    def test_unknown_action_denied(self):
        self.assertFalse(authz.can_transition(
            self.root, 'student', self._Stub('active'), 'teleport'))

    def test_unknown_state_denied(self):
        self.assertFalse(authz.can_transition(
            self.root, 'student', self._Stub('nonexistent'), 'suspend'))

    def test_inactive_account_cannot_transition(self):
        student = make_account('S06503', 'student', roles=[RoleCode.STUDENT])
        self.assertFalse(authz.can_transition(
            student, 'student', self._Stub('active'), 'suspend'))

    def test_require_transition_raises(self):
        with self.assertRaises(authz.AuthzDenied) as ctx:
            authz.require_transition(self.root, 'student', self._Stub('graduated'), 'suspend')
        self.assertEqual(ctx.exception.reason, 'transition_forbidden')

    @override_settings(AUTHORIZATION_TRANSITIONS={
        'student': {'active': {'archive_self': {RoleCode.STUDENT}}},
    })
    def test_settings_can_extend_transitions(self):
        student = make_account('S06504', 'student', roles=[RoleCode.STUDENT])
        self.assertTrue(authz.can_transition(
            student, 'student', self._Stub('active'), 'archive_self'))


class DescribeTests(TestCase):
    """验收点：诊断输出不泄露字段值。"""

    def test_describe_contains_capabilities_not_values(self):
        admin = make_account('S06601', 'admin', roles=[RoleCode.SYSTEM_ADMIN])
        payload = authz.describe(admin)
        self.assertTrue(payload['authenticated'])
        self.assertIn(RoleCode.SYSTEM_ADMIN, payload['roles'])
        self.assertTrue(payload['actions']['view'])
        self.assertEqual(payload['visible_fields']['student'], ['*'])
        flat = str(payload)
        self.assertNotIn('500000199001010011', flat)
        self.assertNotIn('139', flat)

    def test_describe_anonymous(self):
        payload = authz.describe(None)
        self.assertFalse(payload['authenticated'])
        self.assertEqual(payload['roles'], [])
        self.assertEqual(payload['visible_fields']['student'], [])

    def test_denied_message_has_no_sensitive_value(self):
        teacher = make_account('S06602', 'teacher', scope='计算机学院',
                               roles=[RoleCode.TEACHER])
        try:
            authz.require_write_fields(teacher, 'student', ['card_id'])
        except authz.AuthzDenied as exc:
            self.assertNotIn('500000', str(exc))
            self.assertIn('card_id', str(exc))
        else:
            self.fail('应当抛出 AuthzDenied')

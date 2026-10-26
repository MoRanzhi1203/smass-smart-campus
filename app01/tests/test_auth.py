"""认证回归测试（对应计划 9.2）。

覆盖：
- 三类角色正确/错误登录；
- 编辑资料不改密码（历史 P0 缺陷）；
- 修改密码 / 管理员重置密码后新旧密码行为；
- 历史 MD5（含"双重哈希"坏数据）兼容与自动升级；
- 会话轮换、登出失效、登录失败锁定、开放重定向防护。
"""
from django.test import Client, TestCase

from app01 import models
from app01.services import accounts
from app01.tests import helpers


class LoginTests(TestCase):
    """登录流程。"""

    def test_admin_login_success(self):
        admin, password = helpers.make_admin()
        resp = helpers.login(self.client, 'admin', admin.pk, password)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/admin/admin/list/')
        self.assertEqual(self.client.session['info']['type'], 'admin')
        self.assertEqual(self.client.session['info']['id'], admin.pk)

    def test_admin_login_wrong_password_rejected(self):
        admin, _ = helpers.make_admin()
        resp = helpers.login(self.client, 'admin', admin.pk, 'definitely-wrong')

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('info', self.client.session)
        self.assertContains(resp, '账号或密码错误')

    def test_unknown_account_does_not_leak_existence(self):
        """账号不存在与密码错误返回同样的提示，避免账号枚举。"""
        resp = helpers.login(self.client, 'admin', '999', 'whatever')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '账号或密码错误')

    def test_student_cannot_login_via_admin_endpoint(self):
        """身份表隔离：学生账号在管理员入口无法通过认证。"""
        student, password = helpers.make_student()
        resp = helpers.login(self.client, 'admin', student.pk, password)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('info', self.client.session)

    def test_student_login_success(self):
        student, password = helpers.make_student()
        resp = helpers.login(self.client, 'student', student.pk, password)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/student/users/profile/')
        self.assertEqual(self.client.session['info']['type'], 'student')

    def test_teacher_login_success(self):
        """教师登录入口在历史版本被注释掉，本用例保证它真的存在且可用。"""
        teacher, password = helpers.make_teacher()
        resp = helpers.login(self.client, 'teacher', teacher.pk, password)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/teacher/basic/')
        self.assertEqual(self.client.session['info']['type'], 'teacher')

    def test_session_key_rotated_on_login(self):
        """登录成功后 Session ID 必须变化（防会话固定）。"""
        admin, password = helpers.make_admin()

        self.client.get('/login/account/admin/')
        old_key = self.client.session.session_key

        helpers.login(self.client, 'admin', admin.pk, password)
        self.assertNotEqual(old_key, self.client.session.session_key)

    def test_logout_invalidates_session(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)
        self.assertEqual(client.get('/admin/admin/list/').status_code, 200)

        resp = client.get('/logout/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/login/')

        # 旧会话已失效
        follow_up = client.get('/admin/admin/list/')
        self.assertEqual(follow_up.status_code, 302)
        self.assertIn('/login/account/admin/', follow_up['Location'])

    def test_open_redirect_is_blocked(self):
        """next 指向站外时必须回落到默认首页。"""
        admin, password = helpers.make_admin()
        resp = self.client.post(
            '/login/account/admin/?next=https://evil.example.com/steal',
            {'id': admin.pk, 'password': password},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/admin/admin/list/')

    def test_login_lockout_after_repeated_failures(self):
        """连续失败达到阈值后返回 429，阻断暴力破解。"""
        admin, _ = helpers.make_admin()

        for _ in range(accounts.LOGIN_MAX_FAILURES):
            helpers.login(self.client, 'admin', admin.pk, 'wrong-password')

        resp = helpers.login(self.client, 'admin', admin.pk, 'wrong-password')
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, '登录失败次数过多', status_code=429)


class PasswordIntegrityTests(TestCase):
    """密码写入路径一致性（历史 P0：编辑/重置会把密码二次哈希）。"""

    def setUp(self):
        self.admin, self.admin_password = helpers.make_admin()
        self.client = helpers.logged_in_client('admin', self.admin.pk, self.admin_password)

    def test_edit_profile_without_password_keeps_hash(self):
        before = models.Admin.objects.get(pk=self.admin.pk).password

        resp = self.client.post(
            '/admin/admin/edit/?uid={}'.format(self.admin.pk),
            {'id': self.admin.pk, 'name': '改名后的管理员', 'password': ''},
        )
        self.assertTrue(resp.json()['status'])

        after = models.Admin.objects.get(pk=self.admin.pk)
        self.assertEqual(after.password, before, '留空密码时不得改动密码哈希')
        self.assertEqual(after.name, '改名后的管理员')

        # 原密码仍然可用
        fresh_client = Client()
        resp2 = helpers.login(fresh_client, 'admin', self.admin.pk, self.admin_password)
        self.assertEqual(resp2.status_code, 302)

    def test_edit_profile_with_password_sets_new_password(self):
        self.client.post(
            '/admin/admin/edit/?uid={}'.format(self.admin.pk),
            {'id': self.admin.pk, 'name': self.admin.name, 'password': 'AdminNew1'},
        )

        fresh = models.Admin.objects.get(pk=self.admin.pk)
        self.assertTrue(accounts.verify_password(fresh, 'AdminNew1'))
        self.assertFalse(accounts.verify_password(fresh, self.admin_password))

    def test_create_account_without_password_generates_one(self):
        resp = self.client.post(
            '/admin/admin/add/',
            {'id': '777', 'name': '随机密码管理员', 'password': ''},
        )
        data = resp.json()

        self.assertTrue(data['status'], data)
        self.assertIn('initial_password', data)

        created = models.Admin.objects.get(pk='777')
        self.assertTrue(created.password.startswith('pbkdf2_'))
        self.assertTrue(accounts.verify_password(created, data['initial_password']))

    def test_password_never_stored_in_plaintext(self):
        """任何创建路径都不得把明文直接写入 password 字段。"""
        self.client.post(
            '/admin/admin/add/',
            {'id': '778', 'name': '明文检查', 'password': 'PlainText1'},
        )
        created = models.Admin.objects.get(pk='778')
        self.assertNotEqual(created.password, 'PlainText1')
        self.assertTrue(created.password.startswith('pbkdf2_'))

    def test_admin_reset_password_returns_working_password(self):
        """Admin 模型没有 cardID，重置逻辑不得依赖它。"""
        target, _ = helpers.make_admin()

        resp = self.client.post('/admin/admin/resetPass/?uid={}'.format(target.pk))
        data = resp.json()

        self.assertTrue(data['status'], data)
        new_password = data['password']
        self.assertTrue(new_password)

        fresh = models.Admin.objects.get(pk=target.pk)
        self.assertTrue(accounts.verify_password(fresh, new_password))

    def test_student_reset_password_returns_working_password(self):
        student, old_password = helpers.make_student()

        resp = self.client.post('/admin/student/resetPass/?uid={}'.format(student.pk))
        data = resp.json()
        self.assertTrue(data['status'], data)

        fresh = models.Student.objects.get(pk=student.pk)
        self.assertTrue(accounts.verify_password(fresh, data['password']))
        self.assertFalse(accounts.verify_password(fresh, old_password))


class StudentChangePasswordTests(TestCase):
    """学生自助改密。"""

    def test_change_password_flow(self):
        student, old_password = helpers.make_student()
        client = helpers.logged_in_client('student', student.pk, old_password)

        resp = client.post('/student/users/change/password/', {
            'past_password': old_password,
            'new_password': 'NewPass12',
            'confirm_password': 'NewPass12',
        })
        self.assertTrue(resp.json()['status'], resp.json())

        fresh = models.Student.objects.get(pk=student.pk)
        self.assertTrue(accounts.verify_password(fresh, 'NewPass12'))
        self.assertFalse(accounts.verify_password(fresh, old_password))

    def test_wrong_old_password_rejected(self):
        student, old_password = helpers.make_student()
        client = helpers.logged_in_client('student', student.pk, old_password)

        resp = client.post('/student/users/change/password/', {
            'past_password': 'not-the-old-one',
            'new_password': 'NewPass12',
            'confirm_password': 'NewPass12',
        })
        data = resp.json()
        self.assertFalse(data['status'])
        self.assertEqual(data['tips'], 1)

        fresh = models.Student.objects.get(pk=student.pk)
        self.assertTrue(accounts.verify_password(fresh, old_password))

    def test_requires_post(self):
        student, old_password = helpers.make_student()
        client = helpers.logged_in_client('student', student.pk, old_password)

        resp = client.get('/student/users/change/password/')
        self.assertEqual(resp.status_code, 405)


class LegacyHashTests(TestCase):
    """历史 MD5 数据的兼容与升级。"""

    def test_legacy_md5_login_upgrades_hash(self):
        legacy = accounts.legacy_md5('Legacy#2019')
        models.Admin.objects.create(id='900', name='旧账号', password=legacy)

        resp = helpers.login(self.client, 'admin', '900', 'Legacy#2019')
        self.assertEqual(resp.status_code, 302)

        fresh = models.Admin.objects.get(pk='900')
        self.assertNotEqual(fresh.password, legacy)
        self.assertTrue(fresh.password.startswith('pbkdf2_'))

    def test_double_hashed_legacy_login_is_recovered(self):
        """曾被 save() 二次哈希的坏数据也能登录，并被修好。"""
        double = accounts.legacy_md5(accounts.legacy_md5('Double#2018'))
        models.Admin.objects.create(id='901', name='双哈希账号', password=double)

        resp = helpers.login(self.client, 'admin', '901', 'Double#2018')
        self.assertEqual(resp.status_code, 302)

        fresh = models.Admin.objects.get(pk='901')
        self.assertTrue(accounts.verify_password(fresh, 'Double#2018'))
        self.assertFalse(accounts.is_legacy_hash(fresh.password))

"""授权与 CSRF 回归测试（对应计划 9.3）。

覆盖：
- 匿名访问三类受保护路径均被拒绝（历史缺陷：``/teacher/*`` 曾直接放行）；
- 跨角色访问被拒绝；
- AJAX 未登录返回 403 JSON 而非重定向；
- 写接口必须 POST + CSRF；
- 学生只能看到自己的资料与本班同学。
"""
from django.test import Client, TestCase

from app01 import models
from app01.services import accounts
from app01.tests import helpers


class AnonymousAccessTests(TestCase):
    """匿名访问。"""

    def test_login_pages_are_public(self):
        for url in ('/login/', '/login/account/admin/', '/login/account/student/', '/login/account/teacher/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_pages_require_login(self):
        for url in ('/admin/admin/list/', '/admin/student/list/', '/admin/classes/list/'):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn('/login/account/admin/', resp['Location'])

    def test_student_pages_require_login(self):
        for url in ('/student/users/profile/', '/student/classes/list/'):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn('/login/account/student/', resp['Location'])

    def test_teacher_pages_require_login(self):
        """历史 P0：中间件对 /teacher/* 是 pass，匿名可直接进入。"""
        resp = self.client.get('/teacher/basic/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/account/teacher/', resp['Location'])

    def test_ajax_denied_returns_json_403(self):
        resp = self.client.get(
            '/admin/student/detail/',
            {'uid': '2021000001'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()['status'])


class CrossRoleTests(TestCase):
    """跨角色访问。"""

    def test_student_cannot_touch_admin_area(self):
        student, password = helpers.make_student()
        client = helpers.logged_in_client('student', student.pk, password)

        resp = client.get('/admin/admin/list/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/account/admin/', resp['Location'])

    def test_student_ajax_into_admin_area_gets_403(self):
        student, password = helpers.make_student()
        client = helpers.logged_in_client('student', student.pk, password)

        resp = client.post(
            '/admin/student/add/',
            {'id': 'X1', 'name': '越权', 'password': 'Abcdef12'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(models.Student.objects.filter(pk='X1').exists())

    def test_teacher_cannot_touch_admin_area(self):
        teacher, password = helpers.make_teacher()
        client = helpers.logged_in_client('teacher', teacher.pk, password)

        resp = client.get('/admin/teacher/list/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/account/admin/', resp['Location'])

    def test_admin_cannot_enter_student_area(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)

        resp = client.get('/student/users/profile/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/account/student/', resp['Location'])

    def test_teacher_page_renders_for_teacher(self):
        teacher, password = helpers.make_teacher(name='王老师')
        client = helpers.logged_in_client('teacher', teacher.pk, password)

        resp = client.get('/teacher/basic/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '王老师')


class CsrfTests(TestCase):
    """写接口的 CSRF 约束。"""

    def setUp(self):
        self.admin, self.admin_password = helpers.make_admin()
        self.target, _ = helpers.make_admin()

        self.csrf_client = Client(enforce_csrf_checks=True)
        self.csrf_client.get('/login/account/admin/')
        self.token = self.csrf_client.cookies['csrftoken'].value
        self.csrf_client.post('/login/account/admin/', {
            'id': self.admin.pk,
            'password': self.admin_password,
            'csrfmiddlewaretoken': self.token,
        })

    def test_post_without_csrf_is_rejected(self):
        resp = self.csrf_client.post(
            '/admin/admin/delete/',
            {'uid': self.target.pk},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(models.Admin.objects.filter(pk=self.target.pk).exists())

    def test_post_with_csrf_succeeds(self):
        resp = self.csrf_client.post(
            '/admin/admin/delete/',
            {'uid': self.target.pk, 'csrfmiddlewaretoken': self.token},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['status'])
        self.assertFalse(models.Admin.objects.filter(pk=self.target.pk).exists())

    def test_delete_via_get_is_not_allowed(self):
        """删除接口只接受 POST（GET 删除可被预取/伪造触发）。"""
        resp = self.csrf_client.get('/admin/admin/delete/?uid={}'.format(self.target.pk))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(models.Admin.objects.filter(pk=self.target.pk).exists())

    def test_admin_cannot_delete_self(self):
        resp = self.csrf_client.post(
            '/admin/admin/delete/',
            {'uid': self.admin.pk, 'csrfmiddlewaretoken': self.token},
        )
        data = resp.json()
        self.assertFalse(data['status'])
        self.assertTrue(models.Admin.objects.filter(pk=self.admin.pk).exists())


class ObjectPermissionTests(TestCase):
    """对象归属：学生只能看自己与本班。"""

    def test_profile_only_shows_self(self):
        classes = helpers.make_classes()
        me, password = helpers.make_student(classes=classes, name='甲同学')
        other, _ = helpers.make_student(classes=classes, name='乙同学')

        client = helpers.logged_in_client('student', me.pk, password)
        resp = client.get('/student/users/profile/')

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '甲同学')
        self.assertNotContains(resp, '乙同学')

    def test_class_list_scoped_to_own_class(self):
        class_a = helpers.make_classes()
        class_b = helpers.make_classes()
        me, password = helpers.make_student(classes=class_a, name='我自己')
        mate, _ = helpers.make_student(classes=class_a, name='同班同学')
        outsider, _ = helpers.make_student(classes=class_b, name='外班同学')

        client = helpers.logged_in_client('student', me.pk, password)
        resp = client.get('/student/classes/list/')

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '同班同学')
        self.assertNotContains(resp, '外班同学')

    def test_student_cannot_change_other_password_via_param(self):
        """改密接口只认会话身份，忽略任何客户端传入的 uid。"""
        me, password = helpers.make_student()
        other, other_password = helpers.make_student()

        client = helpers.logged_in_client('student', me.pk, password)
        resp = client.post('/student/users/change/password/?uid={}'.format(other.pk), {
            'past_password': password,
            'new_password': 'Hacked123',
            'confirm_password': 'Hacked123',
        })
        self.assertTrue(resp.json()['status'])

        # 被改的是自己，而不是 other
        self.assertTrue(accounts.verify_password(
            models.Student.objects.get(pk=other.pk), other_password
        ))
        self.assertTrue(accounts.verify_password(
            models.Student.objects.get(pk=me.pk), 'Hacked123'
        ))

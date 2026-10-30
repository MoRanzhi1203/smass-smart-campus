"""R17 页面层：发帖、评论、举报处理与公告的真实页面流程。

运行::

    python manage.py test smass_forum.tests.test_r17_ui --settings=smass.settings_r17
"""
from __future__ import annotations

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_forum.models import Announcement, Board, Comment, Post, Report

PASSWORD = 'R17Ui#2026'
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


class ForumUiTests(TestCase):
    def setUp(self):
        self.admin = make_account('r17uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('r17uistu', [RoleCode.STUDENT])
        self.student2 = make_account('r17uistu2', [RoleCode.STUDENT])
        self.board = Board.objects.create(code='GENERAL', name='综合讨论')

    def test_requires_login(self):
        response = self.client.get('/r17/forum/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_creates_post_and_comment(self):
        login(self.client, 'r17uistu')
        response = self.client.post('/r17/forum/board/{}/post/'.format(self.board.pk), {
            'title': '界面帖子', 'body': '界面正文',
        })
        self.assertEqual(302, response.status_code)
        post = Post.objects.get(title='界面帖子')
        self.assertEqual(post.status, 'published')

        response = self.client.post('/r17/forum/post/{}/comment/'.format(post.pk), {
            'body': '界面评论',
        })
        self.assertEqual(302, response.status_code)
        self.assertTrue(Comment.objects.filter(post=post, body='界面评论').exists())

    def test_student_reports_and_admin_resolves(self):
        post = Post.objects.create(
            board=self.board, author=self.student2, title='可疑帖子', body='内容')
        login(self.client, 'r17uistu')
        response = self.client.post('/r17/forum/report/', {
            'target_type': 'post', 'target_id': post.pk,
            'reason': '不当内容', 'next': '/r17/forum/post/{}/'.format(post.pk),
        })
        self.assertEqual(302, response.status_code)
        report = Report.objects.get(target_id=post.pk)

        admin = Client()
        login(admin, 'r17uiadmin')
        response = admin.post('/r17/reports/{}/resolve/'.format(report.pk),
                              {'action': 'hide'})
        self.assertEqual(302, response.status_code)
        post.refresh_from_db()
        self.assertEqual(post.status, 'hidden')

    def test_student_forbidden_on_reports(self):
        login(self.client, 'r17uistu')
        self.assertEqual(403, self.client.get('/r17/reports/').status_code)

    def test_moderator_removes_post_via_page(self):
        post = Post.objects.create(
            board=self.board, author=self.student, title='待删', body='内容')
        admin = Client()
        login(admin, 'r17uiadmin')
        response = admin.post('/r17/forum/post/{}/action/'.format(post.pk),
                              {'action': 'remove'})
        self.assertEqual(302, response.status_code)
        post.refresh_from_db()
        self.assertEqual(post.status, 'removed')

    def test_author_hides_own_post(self):
        post = Post.objects.create(
            board=self.board, author=self.student, title='自删', body='内容')
        login(self.client, 'r17uistu')
        response = self.client.post('/r17/forum/post/{}/action/'.format(post.pk),
                                    {'action': 'hide'})
        self.assertEqual(302, response.status_code)
        post.refresh_from_db()
        self.assertEqual(post.status, 'hidden')

    def test_announcement_publish_and_visibility(self):
        admin = Client()
        login(admin, 'r17uiadmin')
        response = admin.post('/r17/announcements/create/', {
            'title': '界面公告', 'body': '公告正文', 'audience': 'all',
        })
        self.assertEqual(302, response.status_code)
        announcement = Announcement.objects.get(title='界面公告')
        self.assertEqual(announcement.status, 'draft')

        response = admin.post('/r17/announcements/{}/publish/'.format(announcement.pk))
        self.assertEqual(302, response.status_code)

        login(self.client, 'r17uistu')
        response = self.client.get('/r17/announcements/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '界面公告')

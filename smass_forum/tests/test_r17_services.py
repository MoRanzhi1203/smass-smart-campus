"""R17 服务层：发帖、评论、举报处理与公告。

运行::

    python manage.py test smass_forum.tests.test_r17_services --settings=smass.settings_r17
"""
from __future__ import annotations

from django.test import TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_forum import services
from smass_forum.models import (
    Announcement,
    Board,
    Comment,
    Post,
    Report,
)

PASSWORD = 'R17Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class ForumBase(TestCase):
    def setUp(self):
        self.admin = make_account('r17admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.teacher = make_account('r17teacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('r17stu', [RoleCode.STUDENT])
        self.student2 = make_account('r17stu2', [RoleCode.STUDENT])

        self.board = services.create_board(self.admin, 'GENERAL', '综合讨论')
        self.post = services.create_post(
            self.board, self.student, '第一条帖子', '正文内容')


class PostTests(ForumBase):
    def test_create_board_permission(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_board(self.student, 'X', '非法')

    def test_duplicate_board_code(self):
        with self.assertRaises(services.ForumError) as ctx:
            services.create_board(self.admin, 'GENERAL', '重复')
        self.assertEqual(ctx.exception.code, 'DUPLICATE_CODE')

    def test_empty_title_rejected(self):
        with self.assertRaises(services.ForumError) as ctx:
            services.create_post(self.board, self.student, '  ', '正文')
        self.assertEqual(ctx.exception.code, 'EMPTY_TITLE')

    def test_empty_body_rejected(self):
        with self.assertRaises(services.ForumError) as ctx:
            services.create_post(self.board, self.student, '标题', '   ')
        self.assertEqual(ctx.exception.code, 'EMPTY_BODY')

    def test_archived_board_rejected(self):
        Board.objects.filter(pk=self.board.pk).update(status='archived')
        self.board.refresh_from_db()
        with self.assertRaises(services.ForumError) as ctx:
            services.create_post(self.board, self.student, '标题', '正文')
        self.assertEqual(ctx.exception.code, 'BOARD_UNAVAILABLE')

    def test_comment_and_hidden_post(self):
        comment = services.create_comment(self.post, self.student2, '评论内容')
        self.assertEqual(comment.status, 'published')

        services.hide_content('post', self.post.pk, self.student)
        self.post.refresh_from_db()
        with self.assertRaises(services.ForumError) as ctx:
            services.create_comment(self.post, self.student2, '再评论')
        self.assertEqual(ctx.exception.code, 'POST_UNAVAILABLE')


class ModerationTests(ForumBase):
    def test_author_can_hide_own_post(self):
        services.hide_content('post', self.post.pk, self.student)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, 'hidden')

    def test_other_cannot_hide(self):
        with self.assertRaises(services.PermissionDenied):
            services.hide_content('post', self.post.pk, self.student2)

    def test_moderator_can_remove(self):
        services.remove_content('post', self.post.pk, self.admin)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, 'removed')

    def test_removed_is_terminal(self):
        services.remove_content('post', self.post.pk, self.admin)
        with self.assertRaises(services.ForumError) as ctx:
            services.hide_content('post', self.post.pk, self.admin)
        self.assertEqual(ctx.exception.code, 'TERMINAL_STATE')

    def test_author_cannot_remove(self):
        with self.assertRaises(services.PermissionDenied):
            services.remove_content('post', self.post.pk, self.student)


class ReportTests(ForumBase):
    def test_report_and_hide(self):
        report = services.report_content('post', self.post.pk, self.student2, '不当内容')
        self.assertEqual(report.status, 'pending')
        services.resolve_report(report, self.admin, 'hide')
        report.refresh_from_db()
        self.post.refresh_from_db()
        self.assertEqual(report.status, 'resolved')
        self.assertEqual(report.action, 'hide')
        self.assertEqual(self.post.status, 'hidden')

    def test_duplicate_report_rejected(self):
        services.report_content('post', self.post.pk, self.student2, '不当')
        with self.assertRaises(services.ForumError) as ctx:
            services.report_content('post', self.post.pk, self.student2, '再举报')
        self.assertEqual(ctx.exception.code, 'DUPLICATE_REPORT')

    def test_empty_reason_rejected(self):
        with self.assertRaises(services.ForumError) as ctx:
            services.report_content('post', self.post.pk, self.student2, '   ')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_dismiss_report_keeps_content(self):
        report = services.report_content('post', self.post.pk, self.student2, '误报')
        services.resolve_report(report, self.admin, 'dismiss')
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, 'published')

    def test_non_moderator_cannot_resolve(self):
        report = services.report_content('post', self.post.pk, self.student2, '不当')
        with self.assertRaises(services.PermissionDenied):
            services.resolve_report(report, self.student2, 'hide')

    def test_resolve_twice_rejected(self):
        report = services.report_content('post', self.post.pk, self.student2, '不当')
        services.resolve_report(report, self.admin, 'dismiss')
        with self.assertRaises(services.ForumError) as ctx:
            services.resolve_report(report, self.admin, 'hide')
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_report_comment(self):
        comment = services.create_comment(self.post, self.student2, '评论')
        report = services.report_content('comment', comment.pk, self.student, '辱骂')
        services.resolve_report(report, self.admin, 'remove')
        comment.refresh_from_db()
        self.assertEqual(comment.status, 'removed')


class VisibilityTests(ForumBase):
    def test_author_sees_hidden_others_do_not(self):
        services.hide_content('post', self.post.pk, self.student)
        self.assertEqual(services.visible_posts(self.student).count(), 1)
        self.assertEqual(services.visible_posts(self.student2).count(), 0)
        self.assertEqual(services.visible_posts(self.admin).count(), 1)

    def test_removed_hidden_even_for_author(self):
        services.remove_content('post', self.post.pk, self.admin)
        self.assertEqual(services.visible_posts(self.student).count(), 0)


class AnnouncementTests(ForumBase):
    def test_draft_not_visible_to_student(self):
        services.create_announcement(self.admin, '停水通知', '明天停水')
        self.assertEqual(services.visible_announcements(self.student).count(), 0)
        self.assertEqual(services.visible_announcements(self.admin).count(), 1)

    def test_published_visible(self):
        announcement = services.create_announcement(self.admin, '停水通知', '明天停水')
        services.publish_announcement(announcement, self.admin)
        self.assertEqual(services.visible_announcements(self.student).count(), 1)

    def test_audience_filter(self):
        announcement = services.create_announcement(
            self.admin, '教师通知', '仅教师', audience='teacher')
        services.publish_announcement(announcement, self.admin)
        self.assertEqual(services.visible_announcements(self.student).count(), 0)
        self.assertEqual(services.visible_announcements(self.teacher).count(), 1)

    def test_student_cannot_create(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_announcement(self.student, '非法', '内容')

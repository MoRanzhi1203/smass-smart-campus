"""R20 服务层：门户区块/链接/公告的角色可见性与初始化。

运行::

    python manage.py test smass_portal.tests.test_r20_services --settings=smass.settings_r20
"""
from __future__ import annotations

from django.test import TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_portal import services
from smass_portal.models import PortalLink, PortalNotice, PortalSection

PASSWORD = 'R20Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class PortalBase(TestCase):
    def setUp(self):
        self.admin = make_account('r20admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.college = make_account('r20college', [RoleCode.COLLEGE_ADMIN],
                                    person_type='admin')
        self.teacher = make_account('r20teacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('r20stu', [RoleCode.STUDENT])
        self.nobody = make_account('r20none', [])
        services.bootstrap_defaults()


class RoleVisibilityTests(PortalBase):
    def test_student_sees_only_student_section(self):
        sections = services.visible_sections(self.student)
        codes = [s.code for s in sections]
        self.assertEqual(codes, ['student'])

    def test_teacher_sees_teacher_section(self):
        codes = [s.code for s in services.visible_sections(self.teacher)]
        self.assertEqual(codes, ['teacher'])

    def test_admin_sees_admin_section(self):
        for account in (self.admin, self.college):
            codes = [s.code for s in services.visible_sections(account)]
            self.assertEqual(codes, ['admin'])

    def test_no_role_sees_nothing(self):
        self.assertEqual(list(services.visible_sections(self.nobody)), [])

    def test_links_filtered_by_role(self):
        section = PortalSection.objects.get(code='admin')
        self.assertEqual(services.visible_links(section, self.student), [])
        self.assertGreater(len(services.visible_links(section, self.admin)), 0)


class LinkResolutionTests(PortalBase):
    def test_reverse_works(self):
        section = PortalSection.objects.get(code='student')
        link = PortalLink.objects.create(
            section=section, label='门户首页', url_name='r20:home')
        self.assertEqual(services.resolve_link(link), '/r20/')

    def test_invalid_name_falls_back(self):
        section = PortalSection.objects.get(code='student')
        link = PortalLink.objects.create(
            section=section, label='不存在', url_name='no:such:name',
            fallback_url='/fallback/')
        self.assertEqual(services.resolve_link(link), '/fallback/')

    def test_no_target_returns_hash(self):
        section = PortalSection.objects.get(code='student')
        link = PortalLink.objects.create(section=section, label='空链接')
        self.assertEqual(services.resolve_link(link), '#')

    def test_default_sections_use_fallback(self):
        section = PortalSection.objects.get(code='student')
        link = section.links.first()
        self.assertTrue(services.resolve_link(link).startswith('/r'))


class NoticeTests(PortalBase):
    def test_draft_hidden_from_student(self):
        notice = services.create_notice(self.admin, '草稿公告', '内容')
        titles = [n.title for n in services.visible_notices(self.student)]
        self.assertNotIn('草稿公告', titles)

        services.publish_notice(notice, self.admin)
        titles = [n.title for n in services.visible_notices(self.student)]
        self.assertIn('草稿公告', titles)

    def test_role_filtered_notice(self):
        notice = services.create_notice(
            self.admin, '教师公告', '仅教师', roles='teacher')
        services.publish_notice(notice, self.admin)
        self.assertNotIn('教师公告',
                         [n.title for n in services.visible_notices(self.student)])
        self.assertIn('教师公告',
                      [n.title for n in services.visible_notices(self.teacher)])

    def test_admin_sees_drafts(self):
        services.create_notice(self.admin, '草稿公告', '内容')
        self.assertIn('草稿公告',
                      [n.title for n in services.visible_notices(self.admin)])


class ConfigPermissionTests(PortalBase):
    def test_student_cannot_create(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_section(self.student, 'X', '非法')
        with self.assertRaises(services.PermissionDenied):
            services.create_notice(self.student, 'X', 'Y')

    def test_duplicate_section_code(self):
        with self.assertRaises(services.PortalError) as ctx:
            services.create_section(self.admin, 'student', '重复')
        self.assertEqual(ctx.exception.code, 'DUPLICATE_CODE')

    def test_create_section_and_link(self):
        section = services.create_section(
            self.admin, 'custom', '自定义', roles='student')
        link = services.create_link(
            section, '入口', fallback_url='/custom/', roles='student',
            actor=self.admin)
        self.assertEqual(services.resolve_link(link), '/custom/')
        self.assertIn(section.code,
                      [s.code for s in services.visible_sections(self.student)])

    def test_link_requires_target(self):
        section = PortalSection.objects.get(code='student')
        with self.assertRaises(services.PortalError) as ctx:
            services.create_link(section, '空', actor=self.admin)
        self.assertEqual(ctx.exception.code, 'EMPTY_TARGET')

    def test_bootstrap_is_idempotent(self):
        before = PortalSection.objects.count()
        services.bootstrap_defaults()
        self.assertEqual(PortalSection.objects.count(), before)


class PortalContextTests(PortalBase):
    def test_portal_context_structure(self):
        context = services.portal_context(self.student)
        self.assertEqual(len(context['sections']), 1)
        self.assertEqual(context['sections'][0]['section'].code, 'student')
        self.assertTrue(context['sections'][0]['links'])
        self.assertTrue(all(item['href'].startswith('/')
                            for item in context['sections'][0]['links']))

    def test_empty_account_context(self):
        context = services.portal_context(self.nobody)
        self.assertEqual(context['sections'], [])
        self.assertEqual(context['notices'], [])

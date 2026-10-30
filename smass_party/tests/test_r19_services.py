"""R19 服务层：组织、成员、活动、受控资料与访问审计。

运行::

    python manage.py test smass_party.tests.test_r19_services --settings=smass.settings_r19
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_party import services
from smass_party.models import (
    AccessGrant,
    AccessLog,
    AccessRequest,
    PartyDocument,
    PartyMember,
    PartyOrg,
)

PASSWORD = 'R19Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class PartyBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.admin = make_account('r19admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.teacher = make_account('r19teacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('r19stu', [RoleCode.STUDENT])
        self.student2 = make_account('r19stu2', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S9401', name='党员学生', unit=self.klass, account=self.student)
        self.other = StudentRecord.objects.create(
            student_no='S9402', name='其他学生', unit=self.klass, account=self.student2)

        self.org = services.create_org(self.admin, 'BR-01', '学生党支部', 'branch')
        services.add_member(self.org, self.me, 'party_member', self.admin)

        self.public_doc = services.create_document(
            self.org, '公开通知', 'public', '公开摘要', self.admin)
        self.internal_doc = services.create_document(
            self.org, '内部纪要', 'internal', '内部摘要', self.admin)
        self.sensitive_doc = services.create_document(
            self.org, '敏感材料', 'sensitive', '敏感摘要（合成）', self.admin)


class OrgTests(PartyBase):
    def test_create_org_requires_party_admin(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_org(self.student, 'BR-99', '非法', 'branch')

    def test_duplicate_org_code(self):
        with self.assertRaises(services.PartyError) as ctx:
            services.create_org(self.admin, 'BR-01', '重复', 'branch')
        self.assertEqual(ctx.exception.code, 'DUPLICATE_CODE')

    def test_add_and_remove_member(self):
        member = services.add_member(self.org, self.other, 'league_member', self.admin)
        self.assertEqual(member.status, 'active')
        services.remove_member(member, self.admin)
        member.refresh_from_db()
        self.assertEqual(member.status, 'left')

    def test_duplicate_member_rejected(self):
        with self.assertRaises(services.PartyError) as ctx:
            services.add_member(self.org, self.me, 'party_member', self.admin)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_MEMBER')

    def test_activity_lifecycle(self):
        activity = services.create_activity(
            self.org, '主题党日', 'theme_party_day',
            timezone.localdate(), self.admin)
        self.assertEqual(activity.status, 'planned')
        services.complete_activity(activity, self.admin, summary='已完成')
        activity.refresh_from_db()
        self.assertEqual(activity.status, 'done')
        self.assertEqual(activity.summary, '已完成')


class DocumentVisibilityTests(PartyBase):
    def test_public_visible_to_all(self):
        self.assertTrue(services.can_view(self.student, self.public_doc))
        self.assertTrue(services.can_view(self.student2, self.public_doc))

    def test_internal_requires_membership(self):
        self.assertTrue(services.can_view(self.student, self.internal_doc))
        self.assertFalse(services.can_view(self.student2, self.internal_doc))

    def test_sensitive_denied_by_default(self):
        self.assertFalse(services.can_view(self.student, self.sensitive_doc))
        self.assertFalse(services.can_view(self.student2, self.sensitive_doc))
        # 党务管理员可看（仍会记审计）
        self.assertTrue(services.can_view(self.admin, self.sensitive_doc))

    def test_view_document_masks_and_audits(self):
        result = services.view_document(self.sensitive_doc, self.student)
        self.assertFalse(result['allowed'])
        self.assertTrue(result['masked'])
        self.assertNotIn('敏感摘要', result['summary'])
        self.assertEqual(AccessLog.objects.filter(
            document=self.sensitive_doc, action='deny').count(), 1)

    def test_view_document_allowed_writes_view_log(self):
        result = services.view_document(self.public_doc, self.student)
        self.assertTrue(result['allowed'])
        self.assertIn('公开摘要', result['summary'])
        self.assertEqual(AccessLog.objects.filter(
            document=self.public_doc, action='view').count(), 1)


class AccessRequestTests(PartyBase):
    def test_request_and_approve(self):
        request = services.request_access(self.sensitive_doc, '写材料', self.student)
        self.assertEqual(request.status, 'submitted')
        services.approve_access(request, self.admin)
        request.refresh_from_db()
        self.assertEqual(request.status, 'approved')
        self.assertIsNotNone(request.valid_until)
        self.assertTrue(services.can_view(self.student, self.sensitive_doc))

    def test_request_requires_sensitive_doc(self):
        with self.assertRaises(services.PartyError) as ctx:
            services.request_access(self.public_doc, '看看', self.student)
        self.assertEqual(ctx.exception.code, 'NOT_SENSITIVE')

    def test_request_empty_purpose(self):
        with self.assertRaises(services.PartyError) as ctx:
            services.request_access(self.sensitive_doc, '  ', self.student)
        self.assertEqual(ctx.exception.code, 'EMPTY_PURPOSE')

    def test_duplicate_request(self):
        services.request_access(self.sensitive_doc, '写材料', self.student)
        with self.assertRaises(services.PartyError) as ctx:
            services.request_access(self.sensitive_doc, '再申请', self.student)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_REQUEST')

    def test_already_allowed_request(self):
        services.request_access(self.sensitive_doc, '写材料', self.student)
        request = AccessRequest.objects.get(document=self.sensitive_doc)
        services.approve_access(request, self.admin)
        with self.assertRaises(services.PartyError) as ctx:
            services.request_access(self.sensitive_doc, '再申请', self.student)
        self.assertEqual(ctx.exception.code, 'ALREADY_ALLOWED')

    def test_student_cannot_approve(self):
        request = services.request_access(self.sensitive_doc, '写材料', self.student)
        with self.assertRaises(services.PermissionDenied):
            services.approve_access(request, self.student)

    def test_reject_requires_reason(self):
        request = services.request_access(self.sensitive_doc, '写材料', self.student)
        with self.assertRaises(services.PartyError) as ctx:
            services.reject_access(request, self.admin, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_expired_request_denied(self):
        request = services.request_access(self.sensitive_doc, '写材料', self.student)
        services.approve_access(request, self.admin)
        AccessRequest.objects.filter(pk=request.pk).update(
            valid_until=timezone.now() - dt.timedelta(minutes=1))
        self.assertFalse(services.can_view(self.student, self.sensitive_doc))
        services.expire_requests()
        request.refresh_from_db()
        self.assertEqual(request.status, 'expired')


class ClearanceTests(PartyBase):
    def test_self_grant_denied(self):
        with self.assertRaises(services.PartyError) as ctx:
            services.grant_clearance(self.admin, self.admin)
        self.assertEqual(ctx.exception.code, 'SELF_GRANT_DENIED')

    def test_grant_and_revoke(self):
        grant = services.grant_clearance(self.student, self.admin)
        self.assertTrue(services.has_clearance(self.student))
        self.assertTrue(services.can_view(self.student, self.sensitive_doc))

        services.revoke_clearance(grant, self.admin)
        self.assertFalse(services.has_clearance(self.student))
        self.assertFalse(services.can_view(self.student, self.sensitive_doc))

    def test_expired_grant(self):
        services.grant_clearance(self.student, self.admin, valid_days=1)
        AccessGrant.objects.filter(account=self.student).update(
            expires_at=timezone.now() - dt.timedelta(minutes=1))
        self.assertFalse(services.has_clearance(self.student))


class AuditImmutabilityTests(PartyBase):
    def test_audit_cannot_be_modified(self):
        services.view_document(self.public_doc, self.student)
        log = AccessLog.objects.first()
        log.purpose = '改一下'
        with self.assertRaises(ValueError):
            log.save()

    def test_audit_cannot_be_deleted(self):
        services.view_document(self.public_doc, self.student)
        log = AccessLog.objects.first()
        with self.assertRaises(ValueError):
            log.delete()

    def test_student_cannot_read_audit(self):
        services.view_document(self.public_doc, self.student)
        self.assertEqual(services.scoped_audit_logs(self.student).count(), 0)
        self.assertGreater(services.scoped_audit_logs(self.admin).count(), 0)


class ScopingTests(PartyBase):
    def test_student_sees_public_and_member_internal(self):
        docs = list(services.scoped_documents(self.student))
        titles = {doc.title for doc in docs}
        self.assertIn('公开通知', titles)
        self.assertIn('内部纪要', titles)
        self.assertNotIn('敏感材料', titles)

    def test_non_member_sees_only_public(self):
        docs = list(services.scoped_documents(self.student2))
        titles = {doc.title for doc in docs}
        self.assertEqual(titles, {'公开通知'})

    def test_admin_sees_all(self):
        docs = list(services.scoped_documents(self.admin))
        self.assertEqual(len(docs), 3)

"""S18 跨模块安全负向测试集。

覆盖：IDOR、越权（管理端 403）、CSRF、XSS 转义、SQL 注入不崩、SSRF（下载不接受
外部 URL）、并发/重复提交幂等。

运行::

    python manage.py test smass_security_tests --settings=smass.settings_security
"""
from __future__ import annotations

import datetime as dt

from django.test import Client, TestCase
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

from smass_activities.models import Activity, ActivityRegistration
from smass_attendance.models import AttendanceRecord, AttendanceSession
from smass_clubs.models import Club, ClubMembership
from smass_enrollment.models import MajorTransferRequest
from smass_finance.models import Bill
from smass_forum.models import Board, Post
from smass_party.models import PartyDocument, PartyOrg

PASSWORD = 'S18Neg#2026'
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


class SecurityBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.class_a = OrganizationUnit.objects.create(
            code='CL-A', name='A 班', unit_type=UNIT_TYPE_CLASS, parent=self.major)
        self.class_b = OrganizationUnit.objects.create(
            code='CL-B', name='B 班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.admin = make_account('s18admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.teacher = make_account('s18teacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student_a = make_account('s18stua', [RoleCode.STUDENT])
        self.student_b = make_account('s18stub', [RoleCode.STUDENT])

        self.record_a = StudentRecord.objects.create(
            student_no='S18A01', name='学生 A', unit=self.class_a,
            account=self.student_a)
        self.record_b = StudentRecord.objects.create(
            student_no='S18B01', name='学生 B', unit=self.class_b,
            account=self.student_b)

        # R13：A 班的考勤会话
        self.session = AttendanceSession.objects.create(
            unit=self.class_a, session_date=timezone.localdate(),
            period='第1-2节', status='open', code='123456',
            code_expires_at=timezone.now() + dt.timedelta(minutes=10))
        AttendanceRecord.objects.create(
            session=self.session, record=self.record_a, status='absent',
            source='teacher')

        # R14：已发布活动 + A 已报名 + B 已报名
        self.activity = Activity.objects.create(
            title='S18 活动', category='volunteer',
            start_at=timezone.now() + dt.timedelta(hours=1),
            end_at=timezone.now() + dt.timedelta(hours=3),
            capacity=10, status='published', checkin_code='654321',
            created_by=str(self.teacher.pk))
        self.reg_a = ActivityRegistration.objects.create(
            activity=self.activity, record=self.record_a, status='registered')
        self.reg_b = ActivityRegistration.objects.create(
            activity=self.activity, record=self.record_b, status='registered')

        # R15：社团 + B 的成员关系
        self.club = Club.objects.create(
            code='S18CLUB', name='S18 社团', category='club', status='active')
        self.member_b = ClubMembership.objects.create(
            club=self.club, record=self.record_b, role='member', status='active')

        # R17：板块 + B 的帖子
        self.board = Board.objects.create(code='S18B', name='S18 板块')
        self.post_b = Post.objects.create(
            board=self.board, author=self.student_b, title='B 的帖子',
            body='B 的正文', status='published')

        # R18：A 与 B 各一张账单
        self.bill_a = Bill.objects.create(
            bill_no='BILL-S18A', record=self.record_a, total=100,
            paid=0, status='unpaid')
        self.bill_b = Bill.objects.create(
            bill_no='BILL-S18B', record=self.record_b, total=200,
            paid=0, status='unpaid')

        # R19：组织 + 敏感资料
        self.party_org = PartyOrg.objects.create(
            code='S18BR', name='S18 支部', org_type='branch', status='active')
        self.sensitive = PartyDocument.objects.create(
            org=self.party_org, title='S18 敏感资料', classification='sensitive',
            summary='S18 合成摘要', status='published')


class IdorTests(SecurityBase):
    def test_cannot_view_other_class_session(self):
        login(self.client, 's18stua')
        # A 属于 A 班，B 班会话应 403
        other_session = AttendanceSession.objects.create(
            unit=self.class_b, session_date=timezone.localdate(),
            period='第3-4节', status='open', code='111111')
        response = self.client.get('/r13/sessions/{}/'.format(other_session.pk))
        self.assertEqual(403, response.status_code)

    def test_cannot_cancel_others_registration(self):
        login(self.client, 's18stua')
        response = self.client.post(
            '/r14/registrations/{}/cancel/'.format(self.reg_b.pk))
        self.assertEqual(403, response.status_code)
        self.reg_b.refresh_from_db()
        self.assertEqual(self.reg_b.status, 'registered')

    def test_cannot_remove_others_post(self):
        login(self.client, 's18stua')
        response = self.client.post(
            '/r17/forum/post/{}/action/'.format(self.post_b.pk),
            {'action': 'remove'})
        self.assertEqual(403, response.status_code)
        self.post_b.refresh_from_db()
        self.assertEqual(self.post_b.status, 'published')

    def test_cannot_read_other_bill(self):
        login(self.client, 's18stua')
        response = self.client.get('/r18/bills/{}/'.format(self.bill_b.pk))
        self.assertEqual(403, response.status_code)

    def test_cannot_leave_others_membership(self):
        login(self.client, 's18stua')
        response = self.client.post(
            '/r15/memberships/{}/leave/'.format(self.member_b.pk))
        self.assertEqual(403, response.status_code)
        self.member_b.refresh_from_db()
        self.assertEqual(self.member_b.status, 'active')

    def test_cannot_read_other_transfer(self):
        transfer = MajorTransferRequest.objects.create(
            record=self.record_b, from_unit=self.class_b,
            to_major=self.major, reason='B 的申请', status='submitted')
        login(self.client, 's18stua')
        response = self.client.post(
            '/r12/transfers/{}/cancel/'.format(transfer.pk))
        self.assertEqual(403, response.status_code)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'submitted')

    def test_sensitive_document_masked(self):
        login(self.client, 's18stua')
        response = self.client.get('/r19/documents/{}/'.format(self.sensitive.pk))
        self.assertEqual(200, response.status_code)
        self.assertNotIn('S18 合成摘要', response.content.decode('utf-8'))


class PrivilegeTests(SecurityBase):
    GET_MANAGE_URLS = [
        '/r12/placement/',
        '/r13/stats/',
        '/r17/reports/',
        '/r18/ledger/',
        '/r19/audit/',
        '/s16/alerts/',
    ]
    POST_MANAGE_URLS = ['/r15/clubs/create/']

    def test_student_forbidden_on_manage_pages(self):
        login(self.client, 's18stua')
        for url in self.GET_MANAGE_URLS:
            with self.subTest(url=url):
                self.assertEqual(403, self.client.get(url).status_code, url)
        for url in self.POST_MANAGE_URLS:
            with self.subTest(url=url):
                self.assertEqual(403, self.client.post(url, {}).status_code, url)

    def test_teacher_allowed_on_attendance_stats(self):
        login(self.client, 's18teacher')
        self.assertEqual(200, self.client.get('/r13/stats/').status_code)

    def test_anonymous_redirected_to_login(self):
        for url in self.GET_MANAGE_URLS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(302, response.status_code, url)
                self.assertIn('/r21/login/', response['Location'])
        for url in self.POST_MANAGE_URLS:
            with self.subTest(url=url):
                response = self.client.post(url, {})
                self.assertEqual(302, response.status_code, url)
                self.assertIn('/r21/login/', response['Location'])


class CsrfTests(SecurityBase):
    def test_post_without_token_rejected(self):
        client = Client(enforce_csrf_checks=True)
        page = client.get('/r21/login/')
        self.assertEqual(200, page.status_code)
        token = client.cookies['csrftoken'].value
        response = client.post(LOGIN, {
            'login_name': 's18stua', 'password': PASSWORD,
            'csrfmiddlewaretoken': token,
        })
        self.assertEqual(302, response.status_code)

        for url, data in [
            ('/r13/leaves/submit/', {'leave_type': 'personal',
                                     'start_date': timezone.localdate().isoformat(),
                                     'end_date': timezone.localdate().isoformat(),
                                     'reason': 'csrf 测试'}),
            ('/r17/forum/post/{}/comment/'.format(self.post_b.pk),
             {'body': 'csrf 评论'}),
            ('/r14/activities/{}/register/'.format(self.activity.pk), {}),
        ]:
            with self.subTest(url=url):
                self.assertEqual(403, client.post(url, data).status_code, url)


class XssTests(SecurityBase):
    def test_post_title_is_escaped(self):
        payload = '<script>alert(1)</script>'
        login(self.client, 's18stua')
        response = self.client.post(
            '/r17/forum/board/{}/post/'.format(self.board.pk),
            {'title': payload, 'body': '正文'})
        self.assertEqual(302, response.status_code)

        post = Post.objects.get(title=payload)
        detail = self.client.get('/r17/forum/post/{}/'.format(post.pk))
        content = detail.content.decode('utf-8')
        self.assertIn('&lt;script&gt;', content)
        self.assertNotIn('<script>alert(1)</script>', content)

    def test_announcement_body_escaped(self):
        login(self.client, 's18admin')
        response = self.client.post('/r17/announcements/create/', {
            'title': 'XSS 公告', 'body': '<img src=x onerror=alert(1)>',
            'audience': 'all',
        })
        self.assertEqual(302, response.status_code)
        login(self.client, 's18stua')
        listing = self.client.get('/r17/announcements/').content.decode('utf-8')
        self.assertNotIn('<img src=x onerror=alert(1)>', listing)


class SqlInjectionTests(SecurityBase):
    PAYLOADS = [
        "' OR 1=1 --",
        "1; DROP TABLE smass_attendance_attendancerecord; --",
        "\" OR \"\"=\"",
        "1' UNION SELECT password FROM r21_account_account --",
    ]

    def test_stats_unit_param_injection_does_not_crash(self):
        login(self.client, 's18teacher')
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.get('/r13/stats/', {'unit': payload})
                self.assertLess(response.status_code, 500, payload)

    def test_session_mark_record_injection_does_not_crash(self):
        login(self.client, 's18teacher')
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.post(
                    '/r13/sessions/{}/mark/'.format(self.session.pk),
                    {'record': payload, 'status': 'present'})
                self.assertLess(response.status_code, 500, payload)

    def test_bill_create_injection_does_not_crash(self):
        login(self.client, 's18admin')
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.post('/r18/bills/create/', {
                    'record': payload, 'fee_item': payload, 'term': payload,
                })
                self.assertLess(response.status_code, 500, payload)


class SsrfTests(SecurityBase):
    def test_download_ignores_external_url_params(self):
        """下载只按主键读取本地私有文件，不接受 URL 参数，不会外发请求。"""
        login(self.client, 's18admin')
        from smass_uploads import services as upload_services
        from django.core.files.uploadedfile import SimpleUploadedFile

        payload = b'%PDF-1.4\ns18-local'
        record = upload_services.store(
            SimpleUploadedFile('local.pdf', payload, content_type='application/pdf'),
            self.admin, 'report')

        response = self.client.get(
            '/uploads/{}/download/'.format(record.pk),
            {'url': 'http://169.254.169.254/latest/meta-data/',
             'next': 'http://evil.example/'})
        self.assertEqual(200, response.status_code)
        self.assertEqual(b''.join(response.streaming_content), payload)


class ConcurrencyTests(SecurityBase):
    def test_duplicate_activity_registration_idempotent(self):
        login(self.client, 's18stua')
        # A 已报名，再报名一次 → 服务层拒绝（302 + error），记录数仍为 1
        response = self.client.post(
            '/r14/activities/{}/register/'.format(self.activity.pk))
        self.assertEqual(302, response.status_code)
        self.assertIn('error=', response['Location'])
        self.assertEqual(
            ActivityRegistration.objects.filter(
                activity=self.activity, record=self.record_a).count(), 1)

    def test_duplicate_sign_in_idempotent(self):
        login(self.client, 's18stua')
        for _ in range(2):
            response = self.client.post(
                '/r13/sessions/{}/sign/'.format(self.session.pk),
                {'code': '123456'})
            self.assertEqual(302, response.status_code)
        self.assertEqual(
            AttendanceRecord.objects.filter(
                session=self.session, record=self.record_a).count(), 1)

    def test_duplicate_leave_submit_rejected(self):
        login(self.client, 's18stua')
        today = timezone.localdate().isoformat()
        first = self.client.post('/r13/leaves/submit/', {
            'leave_type': 'personal', 'start_date': today, 'end_date': today,
            'reason': '第一次'})
        self.assertEqual(302, first.status_code)
        second = self.client.post('/r13/leaves/submit/', {
            'leave_type': 'personal', 'start_date': today, 'end_date': today,
            'reason': '第二次'})
        self.assertEqual(302, second.status_code)
        self.assertIn('error=', second['Location'])

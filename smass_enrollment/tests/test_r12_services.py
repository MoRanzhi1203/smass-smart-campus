"""R12 服务层：自动分班、转专业与学籍异动。

覆盖：预览不写档案、执行/回滚、容量、均衡、候选过滤、权限，
转专业与异动的完整状态机、职责分离、重复申请与终态拒绝。

运行::

    python manage.py test smass_enrollment.tests.test_r12_services --settings=smass.settings_r12
"""
from __future__ import annotations

from django.test import TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
    StudentRecordChange,
)

from smass_enrollment import services
from smass_enrollment.models import (
    CHANGE_SUSPEND,
    CHANGE_WITHDRAW,
    MajorTransferRequest,
    PlacementAssignment,
    PlacementBatch,
    PlacementRule,
    StudentStatusChange,
)

PASSWORD = 'R12Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def make_unit(code, name, unit_type, parent=None):
    return OrganizationUnit.objects.create(
        code=code, name=name, unit_type=unit_type, parent=parent)


def make_record(student_no, name, unit=None, status='enrolled', account=None, extra=None):
    return StudentRecord.objects.create(
        student_no=student_no, name=name, unit=unit, status=status,
        account=account, extra=extra or {})


class EnrollmentBase(TestCase):
    def setUp(self):
        self.college = make_unit('C01', '计算机学院', UNIT_TYPE_COLLEGE)
        self.major_cs = make_unit('M01', '计算机科学与技术', UNIT_TYPE_MAJOR, self.college)
        self.major_se = make_unit('M02', '软件工程', UNIT_TYPE_MAJOR, self.college)
        self.class_cs1 = make_unit('CL01', '计科一班', UNIT_TYPE_CLASS, self.major_cs)
        self.class_cs2 = make_unit('CL02', '计科二班', UNIT_TYPE_CLASS, self.major_cs)
        self.class_se1 = make_unit('CL11', '软工一班', UNIT_TYPE_CLASS, self.major_se)

        self.admin = make_account('r12admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student_account = make_account('r12stu', [RoleCode.STUDENT])
        self.student_account2 = make_account('r12stu2', [RoleCode.STUDENT])

        self.rule = PlacementRule.objects.create(
            name='2026 级计科分班', major=self.major_cs,
            capacity_per_class=0, strategy='balanced', balance_keys=['sex'])


class PlacementTests(EnrollmentBase):
    def _records(self, count, major=None, sex_cycle=('M', 'F')):
        major = major or self.major_cs
        records = []
        for idx in range(count):
            records.append(make_record(
                'S{:04d}'.format(idx + 1), '学生{}'.format(idx + 1),
                unit=major, extra={'sex': sex_cycle[idx % len(sex_cycle)]}))
        return records

    def test_preview_does_not_touch_records(self):
        records = self._records(4)
        batch = services.create_placement_preview(self.rule, self.admin)

        self.assertEqual(PlacementBatch.objects.get(pk=batch.pk).status, 'preview')
        for record in records:
            record.refresh_from_db()
            self.assertEqual(record.unit_id, self.major_cs.pk)
        self.assertEqual(PlacementAssignment.objects.filter(batch=batch).count(), 4)
        self.assertEqual(StudentRecordChange.objects.count(), 0)

    def test_apply_writes_records_and_history(self):
        records = self._records(4)
        batch = services.create_placement_preview(self.rule, self.admin)
        services.apply_placement(batch, self.admin)

        batch.refresh_from_db()
        self.assertEqual(batch.status, 'applied')
        for record in records:
            record.refresh_from_db()
            self.assertEqual(record.unit.unit_type, UNIT_TYPE_CLASS)
        self.assertEqual(StudentRecordChange.objects.filter(field_name='unit').count(), 4)

    def test_apply_is_single_shot(self):
        self._records(2)
        batch = services.create_placement_preview(self.rule, self.admin)
        services.apply_placement(batch, self.admin)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.apply_placement(batch, self.admin)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_rollback_restores_original_unit(self):
        records = self._records(4)
        batch = services.create_placement_preview(self.rule, self.admin)
        services.apply_placement(batch, self.admin)
        services.rollback_placement(batch, self.admin)

        for record in records:
            record.refresh_from_db()
            self.assertEqual(record.unit_id, self.major_cs.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'rolled_back')

    def test_rollback_refused_when_class_changed_after_apply(self):
        records = self._records(2)
        batch = services.create_placement_preview(self.rule, self.admin)
        services.apply_placement(batch, self.admin)

        record = records[0]
        record.refresh_from_db()
        record.unit = self.class_se1
        record.save(update_fields=['unit'])

        with self.assertRaises(services.EnrollmentError) as ctx:
            services.rollback_placement(batch, self.admin)
        self.assertEqual(ctx.exception.code, 'CONCURRENT_MODIFICATION')

    def test_capacity_exceeded_is_rejected_before_any_write(self):
        rule = PlacementRule.objects.create(
            name='小容量', major=self.major_cs, capacity_per_class=1,
            strategy='round_robin')
        self._records(3)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.create_placement_preview(rule, self.admin)
        self.assertEqual(ctx.exception.code, 'CAPACITY_EXCEEDED')
        self.assertEqual(PlacementBatch.objects.count(), 0)

    def test_balanced_strategy_splits_gender_evenly(self):
        self._records(8)
        batch = services.create_placement_preview(self.rule, self.admin)
        per_class = {}
        for assignment in PlacementAssignment.objects.filter(batch=batch):
            per_class.setdefault(assignment.to_unit_id, []).append(assignment.record)
        self.assertEqual(len(per_class), 2)
        for members in per_class.values():
            sexes = [m.extra.get('sex') for m in members]
            self.assertEqual(sexes.count('M'), 2)
            self.assertEqual(sexes.count('F'), 2)

    def test_already_placed_records_are_excluded(self):
        make_record('S100', '已分班', unit=self.class_cs1)
        self._records(2)
        self.assertEqual(len(services.candidate_records(self.rule)), 2)

    def test_other_major_records_are_excluded(self):
        self._records(2)
        make_record('S200', '软工学生', unit=self.major_se)
        records = services.candidate_records(self.rule)
        self.assertEqual([r.student_no for r in records], ['S0001', 'S0002'])

    def test_no_candidate_is_rejected(self):
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.create_placement_preview(self.rule, self.admin)
        self.assertEqual(ctx.exception.code, 'NO_CANDIDATE')

    def test_non_manager_cannot_preview(self):
        self._records(2)
        with self.assertRaises(services.PermissionDenied):
            services.create_placement_preview(self.rule, self.student_account)


class TransferTests(EnrollmentBase):
    def setUp(self):
        super().setUp()
        self.record = make_record(
            'S3001', '转专业学生', unit=self.class_cs1, account=self.student_account)

    def test_student_submits_transfer(self):
        transfer = services.submit_transfer(
            self.record, self.major_se, '兴趣方向', self.student_account)
        self.assertEqual(transfer.status, 'submitted')
        self.assertEqual(transfer.from_unit_id, self.class_cs1.pk)

    def test_same_major_is_rejected(self):
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.submit_transfer(
                self.record, self.major_cs, '同专业', self.student_account)
        self.assertEqual(ctx.exception.code, 'SAME_MAJOR')

    def test_duplicate_active_request_is_rejected(self):
        services.submit_transfer(
            self.record, self.major_se, '第一次', self.student_account)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.submit_transfer(
                self.record, self.major_se, '第二次', self.student_account)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_REQUEST')

    def test_empty_reason_is_rejected(self):
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.submit_transfer(
                self.record, self.major_se, '   ', self.student_account)
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_self_approval_is_denied(self):
        transfer = services.submit_transfer(
            self.record, self.major_se, '理由', self.student_account)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.approve_transfer(transfer, self.student_account)
        # 学生没有审批权，先被权限拒绝
        self.assertIn(ctx.exception.code, {'PERMISSION_DENIED', 'SELF_APPROVAL_DENIED'})

    def test_manager_cannot_approve_own_submission(self):
        transfer = services.submit_transfer(
            self.record, self.major_se, '理由', self.admin)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.approve_transfer(transfer, self.admin)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_full_flow_approve_and_apply(self):
        transfer = services.submit_transfer(
            self.record, self.major_se, '理由', self.student_account)
        services.approve_transfer(transfer, self.admin)
        services.apply_transfer(transfer, self.admin, self.class_se1)

        transfer.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(transfer.status, 'effective')
        self.assertEqual(self.record.unit_id, self.class_se1.pk)
        fields = set(StudentRecordChange.objects.filter(
            record=self.record).values_list('field_name', flat=True))
        self.assertEqual(fields, {'unit', 'major'})

    def test_apply_requires_class_of_target_major(self):
        transfer = services.submit_transfer(
            self.record, self.major_se, '理由', self.student_account)
        services.approve_transfer(transfer, self.admin)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.apply_transfer(transfer, self.admin, self.class_cs2)
        self.assertEqual(ctx.exception.code, 'BAD_CLASS')

    def test_apply_requires_approved_state(self):
        transfer = services.submit_transfer(
            self.record, self.major_se, '理由', self.student_account)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.apply_transfer(transfer, self.admin, self.class_se1)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_reject_requires_reason(self):
        transfer = services.submit_transfer(
            self.record, self.major_se, '理由', self.student_account)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.reject_transfer(transfer, self.admin, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_scoping_hides_other_students_requests(self):
        other = make_record('S3002', '别的学生', unit=self.class_cs1,
                            account=self.student_account2)
        services.submit_transfer(other, self.major_se, '理由', self.student_account2)
        mine = services.scoped_transfers(self.student_account)
        self.assertEqual(list(mine), [])


class StatusChangeTests(EnrollmentBase):
    def setUp(self):
        super().setUp()
        self.record = make_record(
            'S4001', '异动学生', unit=self.class_cs1, account=self.student_account)

    def test_suspend_and_resume(self):
        change = services.submit_status_change(
            self.record, CHANGE_SUSPEND, '病假', self.student_account)
        services.approve_status_change(change, self.admin)
        services.apply_status_change(change, self.admin)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'suspended')

        resume = services.submit_status_change(
            self.record, 'resume', '康复', self.student_account)
        services.approve_status_change(resume, self.admin)
        services.apply_status_change(resume, self.admin)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'enrolled')

    def test_illegal_transition_is_rejected(self):
        self.record.status = 'suspended'
        self.record.save(update_fields=['status'])
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.submit_status_change(
                self.record, 'graduate', '提前毕业', self.admin)
        self.assertEqual(ctx.exception.code, 'ILLEGAL_TRANSITION')

    def test_withdraw_requires_reason(self):
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.submit_status_change(
                self.record, CHANGE_WITHDRAW, '', self.admin)
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_terminal_status_blocks_further_change(self):
        self.record.status = 'withdrawn'
        self.record.save(update_fields=['status'])
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.submit_status_change(
                self.record, 'resume', '想复学', self.admin)
        self.assertEqual(ctx.exception.code, 'TERMINAL_STATUS')

    def test_self_approval_denied(self):
        change = services.submit_status_change(
            self.record, CHANGE_SUSPEND, '病假', self.admin)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.approve_status_change(change, self.admin)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_duplicate_active_change_is_rejected(self):
        services.submit_status_change(
            self.record, CHANGE_SUSPEND, '病假', self.admin)
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.submit_status_change(
                self.record, CHANGE_SUSPEND, '再休学', self.admin)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_REQUEST')

    def test_apply_refused_when_status_drifted(self):
        change = services.submit_status_change(
            self.record, CHANGE_SUSPEND, '病假', self.student_account)
        services.approve_status_change(change, self.admin)
        # 模拟审批后状态被其他流程改写
        self.record.status = 'withdrawn'
        self.record.save(update_fields=['status'])
        with self.assertRaises(services.EnrollmentError) as ctx:
            services.apply_status_change(change, self.admin)
        self.assertEqual(ctx.exception.code, 'CONCURRENT_MODIFICATION')

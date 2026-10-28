"""R6：工作流定义/版本/实例/待办/通知。"""
from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_workflow import services
from smass_workflow.models import (
    ApprovalTask,
    Notification,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowNode,
    WorkflowVersion,
)

PASSWORD = 'R6Pass#2024'


def make_account(login, role):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin'
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='r6_test')
    return Account.objects.get(pk=account.pk)


def build_two_step(definition, *, with_end=True, start=True, reachable=True):
    """构造一个 start -> approve -> end 的最小流程版本（草稿）。"""
    version = services.create_draft_version(definition)

    if start:
        services.add_node(version, 'start', '发起', 'start', order=0)
    services.add_node(version, 'approve', '审批', 'approval', order=1)
    if with_end:
        services.add_node(version, 'end', '完成', 'end', order=2)

    if start:
        services.add_transition(version, 'start', 'approve', 'submit')
    if with_end:
        services.add_transition(version, 'approve', 'end', 'approve')
        services.add_transition(version, 'approve', 'end', 'reject')

    return version


class DefinitionTests(TestCase):
    def test_create_definition_not_active_by_default(self):
        definition = services.create_definition('LEAVE', '请假')
        self.assertFalse(definition.is_active)   # D05：不自动启用

    def test_duplicate_definition_rejected(self):
        services.create_definition('LEAVE', '请假')
        with self.assertRaises(services.SchemaError):
            services.create_definition('LEAVE', '另一个')

    def test_version_numbers_increment(self):
        definition = services.create_definition('D1', '流程1')
        v1 = services.create_draft_version(definition)
        v2 = services.create_draft_version(definition)
        self.assertEqual(v1.version, 1)
        self.assertEqual(v2.version, 2)

    def test_duplicate_node_rejected(self):
        definition = services.create_definition('D1', '流程1')
        version = services.create_draft_version(definition)
        services.add_node(version, 'start', '开始', 'start')
        with self.assertRaises(services.SchemaError):
            services.add_node(version, 'start', '重复', 'start')

    def test_transition_to_missing_node_rejected(self):
        definition = services.create_definition('D1', '流程1')
        version = services.create_draft_version(definition)
        services.add_node(version, 'start', '开始', 'start')
        with self.assertRaises(services.SchemaError):
            services.add_transition(version, 'start', 'nope', 'submit')

    def test_published_version_is_immutable(self):
        definition = services.create_definition('D1', '流程1')
        version = build_two_step(definition)
        services.publish_version(version)

        with self.assertRaises(services.SchemaError):
            services.add_node(version, 'extra', '额外', 'approval')


class SchemaValidationTests(TestCase):
    def setUp(self):
        self.definition = services.create_definition('V', '校验')

    def test_missing_start_rejected(self):
        version = build_two_step(self.definition, start=False)
        with self.assertRaises(services.SchemaError):
            services.validate_version(version)

    def test_missing_end_rejected(self):
        version = build_two_step(self.definition, with_end=False)
        with self.assertRaises(services.SchemaError):
            services.validate_version(version)

    def test_valid_flow_passes(self):
        version = build_two_step(self.definition)
        self.assertTrue(services.validate_version(version))

    def test_end_with_outgoing_rejected(self):
        version = build_two_step(self.definition)
        end_node = version.nodes.get(code='end')
        # 人为造一条从 end 出发的转移（绕过服务层校验）
        from smass_workflow.models import WorkflowTransition

        WorkflowTransition.objects.create(
            version=version, from_node=end_node,
            to_node=version.nodes.get(code='approve'), action='back',
        )
        with self.assertRaises(services.SchemaError):
            services.validate_version(version)

    def test_unreachable_node_rejected(self):
        version = build_two_step(self.definition)
        services.add_node(version, 'orphan', '孤立', 'approval')
        with self.assertRaises(services.SchemaError):
            services.validate_version(version)

    def test_publish_archives_previous(self):
        v1 = build_two_step(self.definition)
        services.publish_version(v1)

        v2 = build_two_step(self.definition)
        services.publish_version(v2)

        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v1.status, 'archived')
        self.assertEqual(v2.status, 'active')
        self.assertEqual(services.active_version(self.definition), v2)


class InstanceTests(TestCase):
    def setUp(self):
        self.definition = services.create_definition('LEAVE', '请假')
        self.version = build_two_step(self.definition)
        services.publish_version(self.version)

    def test_start_instance(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1', created_by='t'
        )
        self.assertEqual(instance.status, 'draft')
        self.assertEqual(instance.current_node.code, 'start')
        self.assertEqual(instance.events.count(), 1)

    def test_cannot_start_on_draft_version(self):
        draft = services.create_draft_version(self.definition)
        with self.assertRaises(services.SchemaError):
            services.start_instance(draft, subject_type='x', subject_id='1')

    def test_submit_moves_to_approval_and_opens_task(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1'
        )
        instance = services.transition(instance, 'submit', actor='alice')

        self.assertEqual(instance.status, 'pending')
        self.assertEqual(instance.current_node.code, 'approve')
        self.assertEqual(ApprovalTask.objects.filter(instance=instance, status='open').count(), 1)

    def test_illegal_action_rejected(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1'
        )
        with self.assertRaises(services.TransitionError):
            services.transition(instance, 'approve')   # start 节点没有 approve 动作

    def test_approve_finishes_instance(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1'
        )
        services.transition(instance, 'submit')
        instance = services.transition(instance, 'approve', actor='boss')

        self.assertEqual(instance.status, 'approved')
        self.assertEqual(instance.current_node.code, 'end')
        self.assertEqual(ApprovalTask.objects.filter(instance=instance, status='open').count(), 0)

    def test_reject_sets_rejected(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1'
        )
        services.transition(instance, 'submit')
        instance = services.transition(instance, 'reject', reason='材料不全')

        self.assertEqual(instance.status, 'rejected')

    def test_terminal_instance_cannot_transition(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1'
        )
        services.transition(instance, 'submit')
        instance = services.transition(instance, 'approve')

        with self.assertRaises(services.TransitionError):
            services.transition(instance, 'submit')

    def test_stale_instance_raises_conflict(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1'
        )
        stale = WorkflowInstance.objects.get(pk=instance.pk)
        services.transition(instance, 'submit')

        with self.assertRaises(services.ConflictError):
            services.transition(stale, 'submit')

    def test_event_history_complete(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L1'
        )
        services.transition(instance, 'submit', actor='alice')
        services.transition(instance, 'approve', actor='boss')

        actions = list(instance.events.order_by('created_at').values_list('action', flat=True))
        self.assertEqual(actions, ['create', 'submit', 'approve'])


class TaskTests(TestCase):
    def setUp(self):
        definition = services.create_definition('F', '流程')
        self.version = build_two_step(definition)
        services.publish_version(self.version)

    def test_complete_task_is_idempotent_guard(self):
        instance = services.start_instance(
            self.version, subject_type='x', subject_id='1'
        )
        services.transition(instance, 'submit')
        task = ApprovalTask.objects.get(instance=instance, status='open')

        services.complete_task(task, actor='boss')
        task.refresh_from_db()
        self.assertEqual(task.status, 'done')

        with self.assertRaises(services.ConflictError):
            services.complete_task(task)


class NotificationTests(TestCase):
    def test_notify_is_idempotent_by_event_key(self):
        first = services.notify('u1', '标题', event_key='e1')
        second = services.notify('u1', '标题', event_key='e1')

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.filter(recipient='u1').count(), 1)

    def test_different_event_keys_create_multiple(self):
        services.notify('u1', '一', event_key='e1')
        services.notify('u1', '二', event_key='e2')
        self.assertEqual(Notification.objects.filter(recipient='u1').count(), 2)

    def test_inbox_and_mark_read(self):
        note = services.notify('u2', '提醒', event_key='x1')
        self.assertEqual(services.inbox('u2', unread_only=True).count(), 1)

        services.mark_read(note)
        self.assertEqual(services.inbox('u2', unread_only=True).count(), 0)


class DemoFlowTests(TestCase):
    """R6-05：两条不同的演示流程，各自走完配置→提交→审批→审计→通知。"""

    def _build(self, code, name, middle='approve'):
        definition = services.create_definition(code, name)
        version = services.create_draft_version(definition)
        services.add_node(version, 'start', '发起', 'start', order=0)
        services.add_node(version, 'approve', '审批', 'approval', order=1)
        if middle == 'two':
            services.add_node(version, 'review', '复核', 'approval', order=2)
        services.add_node(version, 'end', '完成', 'end', order=3)

        services.add_transition(version, 'start', 'approve', 'submit')
        if middle == 'two':
            services.add_transition(version, 'approve', 'review', 'approve')
            services.add_transition(version, 'review', 'end', 'approve')
            services.add_transition(version, 'review', 'end', 'reject')
        else:
            services.add_transition(version, 'approve', 'end', 'approve')
            services.add_transition(version, 'approve', 'end', 'reject')

        services.publish_version(version)
        return definition, version

    def test_flow_a_single_approval(self):
        definition, version = self._build('DEMO_A', '演示流程A（单级）')
        instance = services.start_instance(
            version, subject_type='demo_a', subject_id='A1', created_by='alice'
        )
        services.transition(instance, 'submit', actor='alice')
        services.notify('alice', '待审批', event_key='a-submit')
        instance = services.transition(instance, 'approve', actor='boss')

        self.assertEqual(instance.status, 'approved')
        self.assertEqual(len(definition.versions.all()), 1)
        self.assertEqual(services.inbox('alice').count(), 1)

    def test_flow_b_two_level_approval(self):
        _definition, version = self._build('DEMO_B', '演示流程B（两级）', middle='two')
        instance = services.start_instance(
            version, subject_type='demo_b', subject_id='B1', created_by='bob'
        )
        services.transition(instance, 'submit', actor='bob')
        services.transition(instance, 'approve', actor='boss1')
        self.assertEqual(instance.current_node.code, 'review')

        instance = services.transition(instance, 'approve', actor='boss2')
        self.assertEqual(instance.status, 'approved')

        actions = list(instance.events.order_by('created_at').values_list('action', flat=True))
        self.assertEqual(actions, ['create', 'submit', 'approve', 'approve'])

    def test_demo_definitions_are_explicit_not_default(self):
        """演示流程必须显式发布；不发布则 active_version 为 None。"""
        definition = services.create_definition('DEMO_C', '未发布演示')
        version = services.create_draft_version(definition)
        services.add_node(version, 'start', '开始', 'start')
        services.add_node(version, 'end', '结束', 'end')
        services.add_transition(version, 'start', 'end', 'submit')

        self.assertIsNone(services.active_version(definition))
        self.assertFalse(definition.is_active)


class WorkflowViewTests(TestCase):
    def setUp(self):
        self.admin = make_account('R6ADM', RoleCode.SYSTEM_ADMIN)
        self.nobody = make_account('R6NOB', None)

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get('/r6/definitions/').status_code, 403)

    def test_no_role_denied(self):
        self.client.force_login(self.nobody)
        self.assertEqual(self.client.get('/r6/definitions/').status_code, 403)

    def test_admin_can_list_definitions(self):
        services.create_definition('V1', '流程1')
        self.client.force_login(self.admin)
        resp = self.client.get('/r6/definitions/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('V1', resp.content.decode('utf-8'))

    def test_create_definition_api(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            '/r6/definitions/create/',
            data='{"code":"V2","name":"流程2"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(WorkflowDefinition.objects.filter(code='V2').exists())

    def test_transition_error_returns_400(self):
        definition = services.create_definition('V3', '流程3')
        version = build_two_step(definition)
        services.publish_version(version)
        instance = services.start_instance(version, subject_type='x', subject_id='1')

        self.client.force_login(self.admin)
        resp = self.client.post(
            '/r6/instances/{}/action/'.format(instance.pk),
            data='{"action":"approve"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('code'), 'TRANSITION')

    def test_health(self):
        resp = self.client.get('/r6/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

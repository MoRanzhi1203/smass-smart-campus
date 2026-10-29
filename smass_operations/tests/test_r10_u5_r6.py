"""U5：R6 审批与通知垂直切片。"""
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

PASSWORD = 'U5Pass#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u5')
    return Account.objects.get(pk=account.pk)


def build_published(code='U5-FLOW', name='U5流程', two_level=False):
    definition = services.create_definition(code, name)
    version = services.create_draft_version(definition)
    services.add_node(version, 'start', '发起', 'start', order=0)
    services.add_node(version, 'approve', '审批', 'approval', order=1)
    if two_level:
        services.add_node(version, 'review', '复核', 'approval', order=2)
    services.add_node(version, 'end', '完成', 'end', order=3)
    services.add_transition(version, 'start', 'approve', 'submit')
    if two_level:
        services.add_transition(version, 'approve', 'review', 'approve')
        services.add_transition(version, 'review', 'end', 'approve')
        services.add_transition(version, 'review', 'end', 'reject')
    else:
        services.add_transition(version, 'approve', 'end', 'approve')
        services.add_transition(version, 'approve', 'end', 'reject')
    services.publish_version(version)
    return definition, version


class U5Fixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.admin = make_account('U5ADM', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('U5T', RoleCode.TEACHER, 'teacher')
        self.client.force_login(self.admin)


class DefinitionFormTests(U5Fixture):
    def test_new_page_renders_with_demo_warning(self):
        resp = self.client.get('/r6/definitions/new/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="definition-form"', body)
        self.assertIn('DEMO_ONLY', body)

    def test_create_single_template_publishes(self):
        resp = self.client.post('/r6/definitions/new/', {
            'code': 'U5-A', 'name': '单级流程', 'description': '',
            'template': 'single',
        })
        self.assertEqual(resp.status_code, 302)

        definition = WorkflowDefinition.objects.get(code='U5-A')
        self.assertTrue(definition.is_active)
        active = services.active_version(definition)
        self.assertIsNotNone(active)
        self.assertEqual(active.nodes.count(), 3)
        self.assertEqual(active.transitions.count(), 3)

    def test_create_double_template(self):
        self.client.post('/r6/definitions/new/', {
            'code': 'U5-B', 'name': '两级流程', 'template': 'double',
        })
        definition = WorkflowDefinition.objects.get(code='U5-B')
        active = services.active_version(definition)
        self.assertEqual(active.nodes.count(), 4)
        self.assertEqual(active.transitions.count(), 4)

    def test_duplicate_code_rejected(self):
        build_published('U5-DUP')
        resp = self.client.post('/r6/definitions/new/', {
            'code': 'U5-DUP', 'name': '重复', 'template': 'single',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')

    def test_missing_name_rejected(self):
        resp = self.client.post('/r6/definitions/new/', {
            'code': 'U5-X', 'name': '', 'template': 'single',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '流程名称不能为空')
        self.assertFalse(WorkflowDefinition.objects.filter(code='U5-X').exists())

    def test_definition_detail_shows_nodes_and_transitions(self):
        definition, _ = build_published('U5-DET')
        resp = self.client.get('/r6/definitions/{}/'.format(definition.pk))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="node-table"', body)
        self.assertIn('id="transition-table"', body)
        self.assertIn('id="version-table"', body)

    def test_teacher_cannot_create_definition(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get('/r6/definitions/new/').status_code, 403)


class InstanceFlowTests(U5Fixture):
    def setUp(self):
        super().setUp()
        self.definition, self.version = build_published('U5-FLOW')

    def test_instance_new_page(self):
        resp = self.client.get('/r6/instances/new/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="instance-form"', resp.content.decode('utf-8'))

    def test_start_instance(self):
        resp = self.client.post('/r6/instances/new/', {
            'definition': self.definition.pk,
            'subject_type': 'leave', 'subject_id': 'L-001',
        })
        self.assertEqual(resp.status_code, 302)
        instance = WorkflowInstance.objects.get(subject_id='L-001')
        self.assertEqual(instance.status, 'draft')
        self.assertEqual(instance.created_by, 'U5ADM')

    def test_missing_subject_rejected(self):
        resp = self.client.post('/r6/instances/new/', {
            'definition': self.definition.pk,
            'subject_type': '', 'subject_id': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '业务类型不能为空')

    def test_instance_detail_shows_actions(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L-002',
            created_by='U5ADM')
        resp = self.client.get('/r6/instances/{}/'.format(instance.pk))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="event-table"', body)
        self.assertIn('submit', body)   # start 节点只允许 submit

    def test_submit_then_approve(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L-003',
            created_by='U5ADM')

        self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                         {'action': 'submit'})
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'pending')

        self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                         {'action': 'approve'})
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'approved')

    def test_reject_sets_rejected(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L-004',
            created_by='U5ADM')
        services.transition(instance, 'submit')

        self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                         {'action': 'reject', 'reason': '材料不全'})
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'rejected')

    def test_illegal_action_shows_error(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L-005',
            created_by='U5ADM')

        resp = self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                                {'action': 'approve'}, follow=True)
        self.assertContains(resp, '非法操作')
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'draft')

    def test_terminal_no_action_form(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L-006',
            created_by='U5ADM')
        services.transition(instance, 'submit')
        services.transition(instance, 'approve')

        resp = self.client.get('/r6/instances/{}/'.format(instance.pk))
        body = resp.content.decode('utf-8')
        self.assertNotIn('id="action-form"', body)
        self.assertIn('已结束', body)

    def test_other_user_cannot_view_instance(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L-007',
            created_by='someone-else')
        self.client.force_login(self.teacher)
        self.assertEqual(
            self.client.get('/r6/instances/{}/'.format(instance.pk)).status_code, 403)

    def test_other_user_cannot_act(self):
        instance = services.start_instance(
            self.version, subject_type='leave', subject_id='L-008',
            created_by='someone-else')
        self.client.force_login(self.teacher)
        self.assertEqual(
            self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                             {'action': 'submit'}).status_code, 403)


class TaskAndNotificationTests(U5Fixture):
    def setUp(self):
        super().setUp()
        self.definition, self.version = build_published('U5-TASK')
        self.instance = services.start_instance(
            self.version, subject_type='leave', subject_id='T-001',
            created_by='U5ADM')
        services.transition(self.instance, 'submit')

    def test_task_list_shows_open_task(self):
        resp = self.client.get('/r6/tasks/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="task-table"', body)
        self.assertIn('approve', body)

    def test_complete_task(self):
        task = ApprovalTask.objects.get(instance=self.instance, status='open')
        resp = self.client.post('/r6/tasks/{}/complete/'.format(task.pk))
        self.assertEqual(resp.status_code, 302)

        task.refresh_from_db()
        self.assertEqual(task.status, 'done')

    def test_complete_twice_warns(self):
        task = ApprovalTask.objects.get(instance=self.instance, status='open')
        services.complete_task(task)
        resp = self.client.post('/r6/tasks/{}/complete/'.format(task.pk), follow=True)
        self.assertContains(resp, '任务已处理')

    def test_notification_list_and_read(self):
        note = services.notify('U5ADM', '待审批提醒', event_key='u5-e1')

        resp = self.client.get('/r6/notifications/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('待审批提醒', body)
        self.assertIn('id="notification-table"', body)

        self.client.post('/r6/notifications/{}/read/'.format(note.pk))
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_cannot_read_others_notification(self):
        note = services.notify('someone-else', '别人的消息', event_key='u5-e2')
        resp = self.client.post('/r6/notifications/{}/read/'.format(note.pk))
        self.assertEqual(resp.status_code, 404)


class DemoWorkflowAuditTests(U5Fixture):
    """端到端：配置 -> 发起 -> 审批 -> 审计完整。"""

    def test_full_journey_with_audit(self):
        # 1) 管理员建两级流程
        self.client.post('/r6/definitions/new/', {
            'code': 'U5-E2E', 'name': '端到端流程', 'template': 'double',
        })
        definition = WorkflowDefinition.objects.get(code='U5-E2E')
        version = services.active_version(definition)
        self.assertEqual(version.nodes.count(), 4)

        # 2) 发起
        self.client.post('/r6/instances/new/', {
            'definition': definition.pk,
            'subject_type': 'leave', 'subject_id': 'E2E-001',
        })
        instance = WorkflowInstance.objects.get(subject_id='E2E-001')

        # 3) 提交 -> 初审 -> 复审
        for action in ('submit', 'approve', 'approve'):
            self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                             {'action': action})

        instance.refresh_from_db()
        self.assertEqual(instance.status, 'approved')

        # 4) 审计完整：create + 3 次动作
        actions = list(instance.events.order_by('created_at').values_list('action', flat=True))
        self.assertEqual(actions, ['create', 'submit', 'approve', 'approve'])

        # 5) 每次动作都记录了 actor
        events = instance.events.exclude(actor='').count()
        self.assertEqual(events, 4)

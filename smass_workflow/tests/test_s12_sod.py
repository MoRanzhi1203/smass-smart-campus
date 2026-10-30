"""S12：工作流职责分离（SoD）与不可变审批链。

覆盖：
- 发起人可以 submit/withdraw，但不能审批自己提交的实例；
- 其他审批人可以正常批准；
- 越级动作（当前节点无该转移）被拒绝；
- 审批事件追加写入，修改/删除被模型层阻止。
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from smass_workflow import services
from smass_workflow.models import WorkflowEvent

from .test_r6_workflow import build_two_step


def published_version(code='SOD'):
    definition = services.create_definition(code, '职责分离测试')
    version = build_two_step(definition)
    services.add_transition(version, 'approve', 'end', 'withdraw')
    services.publish_version(version)
    return definition, version


class SeparationOfDutyTests(TestCase):
    def setUp(self):
        self.definition, self.version = published_version()
        self.instance = services.start_instance(
            self.version, subject_type='leave', subject_id='SOD-1',
            created_by='alice')

    def test_submitter_can_submit(self):
        services.transition(self.instance, 'submit', actor='alice')
        self.instance.refresh_from_db()
        self.assertEqual('approve', self.instance.current_node.code)

    def test_submitter_cannot_approve_own_instance(self):
        services.transition(self.instance, 'submit', actor='alice')
        with self.assertRaises(services.TransitionError) as ctx:
            services.transition(self.instance, 'approve', actor='alice')
        self.assertIn('职责分离', str(ctx.exception))
        self.instance.refresh_from_db()
        self.assertEqual('approve', self.instance.current_node.code)

    def test_other_approver_can_approve(self):
        services.transition(self.instance, 'submit', actor='alice')
        services.transition(self.instance, 'approve', actor='bob')
        self.instance.refresh_from_db()
        self.assertEqual('approved', self.instance.status)

    def test_submitter_can_withdraw(self):
        services.transition(self.instance, 'submit', actor='alice')
        services.transition(self.instance, 'withdraw', actor='alice')
        self.instance.refresh_from_db()
        self.assertEqual('withdrawn', self.instance.status)

    def test_skip_level_action_rejected(self):
        # start 节点没有 approve 转移，越级直接审批必须失败
        with self.assertRaises(services.TransitionError):
            services.transition(self.instance, 'approve', actor='bob')

    def test_event_chain_is_append_only(self):
        services.transition(self.instance, 'submit', actor='alice',
                            reason='提交')
        services.transition(self.instance, 'approve', actor='bob',
                            reason='同意')
        events = list(WorkflowEvent.objects.filter(
            instance=self.instance).order_by('created_at', 'pk'))
        self.assertEqual(['create', 'submit', 'approve'],
                         [e.action for e in events])
        self.assertEqual(['alice', 'alice', 'bob'],
                         [e.actor for e in events])

        with self.assertRaises(ValidationError):
            events[0].reason = '被篡改'
            events[0].save()

        with self.assertRaises(ValidationError):
            events[0].delete()

"""流程模板构建器：把常见流程封装为可复用的产品能力。

当前提供"单级审批"模板：开始 → 审批 → 结束。
节点/流转仍走 R6 服务，不复制状态机。
"""
from __future__ import annotations

from smass_workflow import services
from smass_workflow.models import WorkflowNode


class BlueprintError(Exception):
    """流程模板错误。"""


def create_single_approval_flow(code, name, *, description=''):
    code = (code or '').strip()
    name = (name or '').strip()
    if not code or not name:
        raise BlueprintError('流程编码与名称必填')
    definition = services.create_definition(
        code, name, description=description or '')
    version = services.create_draft_version(definition)
    services.add_node(version, 'start', '开始', WorkflowNode.NODE_START, order=0)
    services.add_node(version, 'review', '审批', WorkflowNode.NODE_APPROVAL, order=1)
    services.add_node(version, 'end', '结束', WorkflowNode.NODE_END, order=2)
    services.add_transition(version, 'start', 'review', 'submit')
    services.add_transition(version, 'review', 'end', 'approve')
    services.publish_version(version)
    return definition, version


def start_and_submit(definition, *, subject_id, actor=''):
    version = services.active_version(definition)
    if version is None:
        raise BlueprintError('该流程还没有已发布版本')
    label = (subject_id or '').strip() or '未命名事项'
    instance = services.start_instance(
        version, subject_type='request', subject_id=label[:64],
        created_by=actor)
    services.transition(instance, 'submit', actor=actor)
    instance.refresh_from_db()
    return instance

"""R6 服务层：流程定义版本化、实例状态机、待办与通知。

关键约束：
- 状态转移**只能**沿 version 内配置的 transition 进行；不在配置里的一律拒绝；
- 已启动实例绑定创建时版本，后续定义变更不影响它；
- 审批人身份由调用方传入的可信 actor（服务端会话），不接受客户端自报；
- 通知写库（站内），不做外部发送。
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from smass_workflow.models import (
    ApprovalTask,
    Notification,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowNode,
    WorkflowTransition,
    WorkflowVersion,
)


class WorkflowError(Exception):
    """工作流域错误基类。"""


class SchemaError(WorkflowError):
    """流程定义结构非法。"""


class TransitionError(WorkflowError):
    """不允许的状态转移。"""


class AccessError(WorkflowError):
    """越权。"""


class ConflictError(WorkflowError):
    """并发冲突或重复操作。"""


#: 发起人本人可执行的动作；审批类动作必须由他人执行（S12 职责分离）
SELF_SERVICE_ACTIONS = frozenset({'submit', 'withdraw', 'cancel', 'resubmit'})


# ---------------------------------------------------------------------------
# R6-01 定义与版本
# ---------------------------------------------------------------------------
def create_definition(code, name, *, description=''):
    code = (code or '').strip()
    name = (name or '').strip()
    if not code or not name:
        raise WorkflowError('流程编码与名称不能为空')
    if WorkflowDefinition.objects.filter(code=code).exists():
        raise SchemaError('流程 {} 已存在'.format(code))
    # 默认不启用（D05）
    return WorkflowDefinition.objects.create(
        code=code, name=name, description=description, is_active=False
    )


def create_draft_version(definition):
    """创建一个新的草稿版本（版本号自增）。"""
    last = definition.versions.order_by('-version').first()
    next_version = (last.version + 1) if last else 1
    return WorkflowVersion.objects.create(
        definition=definition, version=next_version, status=WorkflowVersion.STATUS_DRAFT
    )


def add_node(version, code, name, node_type, *, order=0):
    if version.status != WorkflowVersion.STATUS_DRAFT:
        raise SchemaError('只有草稿版本可以修改节点')
    if node_type not in ('start', 'approval', 'end'):
        raise SchemaError('非法节点类型: {}'.format(node_type))
    if WorkflowNode.objects.filter(version=version, code=code).exists():
        raise SchemaError('节点 {} 已存在'.format(code))
    return WorkflowNode.objects.create(
        version=version, code=code, name=name, node_type=node_type, order=order
    )


def add_transition(version, from_code, to_code, action):
    if version.status != WorkflowVersion.STATUS_DRAFT:
        raise SchemaError('只有草稿版本可以修改转移')

    from_node = WorkflowNode.objects.filter(version=version, code=from_code).first()
    to_node = WorkflowNode.objects.filter(version=version, code=to_code).first()
    if from_node is None or to_node is None:
        raise SchemaError('转移引用了不存在的节点')

    if WorkflowTransition.objects.filter(
        version=version, from_node=from_node, action=action
    ).exists():
        raise SchemaError('同一节点同一动作已有转移')

    return WorkflowTransition.objects.create(
        version=version, from_node=from_node, to_node=to_node, action=action
    )


def validate_version(version):
    """结构校验：恰好一个 start、至少一个 end、无离开 end 的转移。"""
    nodes = list(version.nodes.all())
    if not nodes:
        raise SchemaError('流程没有任何节点')

    starts = [n for n in nodes if n.node_type == WorkflowNode.NODE_START]
    ends = [n for n in nodes if n.node_type == WorkflowNode.NODE_END]

    if len(starts) != 1:
        raise SchemaError('必须有且只有一个开始节点（当前 {}）'.format(len(starts)))
    if not ends:
        raise SchemaError('至少需要一个结束节点')

    end_ids = {n.pk for n in ends}
    leaving = version.transitions.filter(from_node_id__in=end_ids).count()
    if leaving:
        raise SchemaError('结束节点不允许再有后续转移')

    reachable = {starts[0].pk}
    changed = True
    guard = 0
    while changed and guard < 200:
        changed = False
        for transition in version.transitions.all():
            if transition.from_node_id in reachable and transition.to_node_id not in reachable:
                reachable.add(transition.to_node_id)
                changed = True
        guard += 1

    unreachable = [n.code for n in nodes if n.pk not in reachable]
    if unreachable:
        raise SchemaError('存在不可达节点: {}'.format(unreachable))

    return True


def publish_version(version):
    """发布版本：校验通过后设为 active，同流程旧 active 归档。"""
    if version.status != WorkflowVersion.STATUS_DRAFT:
        raise SchemaError('只有草稿可以发布')

    validate_version(version)

    with transaction.atomic():
        WorkflowVersion.objects.filter(
            definition=version.definition, status=WorkflowVersion.STATUS_ACTIVE
        ).update(status=WorkflowVersion.STATUS_ARCHIVED)

        version.status = WorkflowVersion.STATUS_ACTIVE
        version.published_at = timezone.now()
        version.save(update_fields=['status', 'published_at'])

        definition = version.definition
        definition.is_active = True
        definition.save(update_fields=['is_active'])

    return version


def active_version(definition):
    return definition.versions.filter(status=WorkflowVersion.STATUS_ACTIVE).first()


# ---------------------------------------------------------------------------
# R6-02 实例状态机
# ---------------------------------------------------------------------------
def start_instance(version, *, subject_type, subject_id, created_by=''):
    if version.status != WorkflowVersion.STATUS_ACTIVE:
        raise SchemaError('只能基于已发布版本启动流程')

    start_node = version.nodes.filter(node_type=WorkflowNode.NODE_START).first()
    if start_node is None:
        raise SchemaError('流程缺少开始节点')

    with transaction.atomic():
        instance = WorkflowInstance.objects.create(
            version=version, subject_type=subject_type, subject_id=subject_id,
            status=WorkflowInstance.STATUS_DRAFT, current_node=start_node,
            created_by=created_by[:32],
        )
        WorkflowEvent.objects.create(
            instance=instance, action='create', to_status=instance.status,
            to_node=start_node.code, actor=created_by[:32],
        )
        _sync_task(instance)
    return instance


def _allowed(version, from_node, action):
    return WorkflowTransition.objects.filter(
        version=version, from_node=from_node, action=action
    ).select_related('to_node').first()


def _sync_task(instance):
    """根据当前节点维护待办：进入 approval 节点开任务，否则关闭。"""
    ApprovalTask.objects.filter(
        instance=instance, status=ApprovalTask.STATUS_OPEN
    ).update(status=ApprovalTask.STATUS_CANCELLED, completed_at=timezone.now())

    node = instance.current_node
    if node is not None and node.node_type == WorkflowNode.NODE_APPROVAL:
        ApprovalTask.objects.create(instance=instance, node=node)


def transition(instance, action, *, actor='', reason=''):
    """执行状态转移（唯一合法入口）。

    **职责分离（S12）**：发起人可以 ``submit`` / ``withdraw`` / ``cancel``，
    但不能审批自己提交的实例；审批动作必须由其他 actor 执行。
    """
    if instance.status in (
        WorkflowInstance.STATUS_APPROVED, WorkflowInstance.STATUS_REJECTED,
        WorkflowInstance.STATUS_WITHDRAWN,
    ):
        raise TransitionError('流程已结束，不能继续转移')

    if (actor and instance.created_by and actor == instance.created_by
            and action not in SELF_SERVICE_ACTIONS):
        raise TransitionError('职责分离：不能审批自己提交的流程')

    current = instance.current_node
    if current is None:
        raise TransitionError('实例没有当前节点')

    allowed = _allowed(instance.version, current, action)
    if allowed is None:
        raise TransitionError(
            '节点 {} 不允许动作 {}（配置中无此转移）'.format(current.code, action)
        )

    target = allowed.to_node
    if target is None:
        raise TransitionError('转移目标不存在')

    old_status = instance.status
    new_status = _status_for(instance, target, action)

    with transaction.atomic():
        affected = WorkflowInstance.objects.filter(
            pk=instance.pk, version_no=instance.version_no
        ).update(
            status=new_status, current_node=target,
            version_no=instance.version_no + 1, updated_at=timezone.now(),
        )
        if affected == 0:
            raise ConflictError('实例已被他人修改，请刷新后重试')

        instance.refresh_from_db()

        WorkflowEvent.objects.create(
            instance=instance, action=action, from_status=old_status,
            to_status=new_status, from_node=current.code, to_node=target.code,
            actor=actor[:32], reason=reason[:255],
        )
        _sync_task(instance)

    return instance


def _status_for(instance, target, action):
    # 撤回优先于目标节点类型：撤回即使指向 end 也应标记 withdrawn
    if action == 'withdraw':
        return WorkflowInstance.STATUS_WITHDRAWN
    if target.node_type == WorkflowNode.NODE_END:
        if action in ('reject', 'refuse'):
            return WorkflowInstance.STATUS_REJECTED
        return WorkflowInstance.STATUS_APPROVED
    return WorkflowInstance.STATUS_PENDING


# ---------------------------------------------------------------------------
# R6-03 待办
# ---------------------------------------------------------------------------
def open_tasks(assignee=None):
    queryset = ApprovalTask.objects.filter(
        status=ApprovalTask.STATUS_OPEN
    ).select_related('instance', 'node')
    if assignee:
        queryset = queryset.filter(assignee=assignee)
    return queryset


def complete_task(task, *, actor=''):
    if task.status != ApprovalTask.STATUS_OPEN:
        raise ConflictError('任务已处理')

    affected = ApprovalTask.objects.filter(
        pk=task.pk, status=ApprovalTask.STATUS_OPEN
    ).update(status=ApprovalTask.STATUS_DONE, completed_at=timezone.now())
    if affected == 0:
        raise ConflictError('任务已被他人处理')
    return task


# ---------------------------------------------------------------------------
# R6-04 通知
# ---------------------------------------------------------------------------
def notify(recipient, title, *, body='', level='info', event_key=''):
    """写站内通知（幂等：同 recipient+event_key 只落一条）。"""
    if not recipient:
        raise WorkflowError('接收人不能为空')

    recipient = recipient[:32]
    event_key = (event_key or '')[:96]

    existing = Notification.objects.filter(
        recipient=recipient, event_key=event_key
    ).first()
    if existing is not None:
        return existing

    try:
        # savepoint：IntegrityError 后事务仍可用，才能回查已有记录
        with transaction.atomic():
            return Notification.objects.create(
                recipient=recipient, title=title[:128], body=body[:512],
                level=level, event_key=event_key,
            )
    except IntegrityError:
        return Notification.objects.filter(
            recipient=recipient, event_key=event_key
        ).first()


def inbox(recipient, unread_only=False):
    queryset = Notification.objects.filter(recipient=recipient).order_by('-created_at')
    if unread_only:
        queryset = queryset.filter(is_read=False)
    return queryset


def mark_read(notification):
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    return notification

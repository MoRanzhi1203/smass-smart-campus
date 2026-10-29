"""U5：R6 审批与通知的浏览器流程。

流程定义采用**模板化生成**（单级/两级审批），避免暴露裸 JSON 编辑器：
管理员选模板 → 自动建节点与转移 → 校验 → 发布。

DEMO_ONLY：这些是演示流程，不作为学校正式规则；正式审批链需 BD-06 输入。
"""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from smass_organization.views import roles_required
from smass_workflow import services
from smass_workflow.models import (
    ApprovalTask,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowNode,
    WorkflowVersion,
)

ADMIN_ROLES = {'system_admin', 'college_admin'}
STAFF_ROLES = {'system_admin', 'college_admin', 'teacher'}

#: 流程模板（DEMO_ONLY）
TEMPLATES = {
    'single': {
        'label': '单级审批',
        'nodes': [('start', '发起', 'start'), ('approve', '审批', 'approval'), ('end', '完成', 'end')],
        'transitions': [
            ('start', 'approve', 'submit'),
            ('approve', 'end', 'approve'),
            ('approve', 'end', 'reject'),
        ],
    },
    'double': {
        'label': '两级审批',
        'nodes': [('start', '发起', 'start'), ('approve', '初审', 'approval'),
                  ('review', '复审', 'approval'), ('end', '完成', 'end')],
        'transitions': [
            ('start', 'approve', 'submit'),
            ('approve', 'review', 'approve'),
            ('review', 'end', 'approve'),
            ('review', 'end', 'reject'),
        ],
    },
}


def _actor(request):
    account = getattr(request, 'user', None)
    return getattr(account, 'login_name', '') if account is not None else ''


# ---------------------------------------------------------------------------
# 定义
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*ADMIN_ROLES)
def definition_new(request):
    errors = {}
    form = {'code': '', 'name': '', 'description': '', 'template': 'single'}

    if request.method == 'POST':
        form.update({
            'code': (request.POST.get('code') or '').strip(),
            'name': (request.POST.get('name') or '').strip(),
            'description': (request.POST.get('description') or '').strip(),
            'template': (request.POST.get('template') or 'single').strip(),
        })

        if not form['code']:
            errors['code'] = '流程编码不能为空'
        if not form['name']:
            errors['name'] = '流程名称不能为空'
        spec = TEMPLATES.get(form['template'])
        if spec is None:
            errors['template'] = '未知模板'

        if not errors:
            try:
                definition = services.create_definition(
                    form['code'], form['name'], description=form['description'])
                version = services.create_draft_version(definition)
                for index, (code, label, node_type) in enumerate(spec['nodes']):
                    services.add_node(version, code, label, node_type, order=index)
                for from_code, to_code, action in spec['transitions']:
                    services.add_transition(version, from_code, to_code, action)
                services.publish_version(version)
            except services.WorkflowError as exc:
                errors['general'] = str(exc)
            else:
                messages.success(
                    request, '流程「{}」已创建并发布（演示模板）'.format(definition.name))
                return redirect('/r6/definitions/{}/'.format(definition.pk))

    return render(request, 'r6/definition_new.html', {
        'form': form,
        'errors': errors,
        'templates': [(k, v['label']) for k, v in TEMPLATES.items()],
    })


@require_http_methods(['GET'])
@roles_required(*ADMIN_ROLES)
def definition_detail(request, pk):
    definition = WorkflowDefinition.objects.filter(pk=pk).first()
    if definition is None:
        return HttpResponse('流程不存在', status=404)

    versions = definition.versions.order_by('-version').prefetch_related('nodes')
    active = services.active_version(definition)

    return render(request, 'r6/definition_detail.html', {
        'definition': definition,
        'versions': versions,
        'active': active,
        'active_nodes': active.nodes.order_by('order') if active else [],
        'active_transitions': (
            active.transitions.select_related('from_node', 'to_node') if active else []
        ),
    })


@require_POST
@roles_required(*ADMIN_ROLES)
def definition_publish(request, pk):
    """发布该定义下最新的草稿版本。"""
    definition = WorkflowDefinition.objects.filter(pk=pk).first()
    if definition is None:
        return HttpResponse('流程不存在', status=404)

    draft = definition.versions.filter(status=WorkflowVersion.STATUS_DRAFT).order_by('-version').first()
    if draft is None:
        messages.warning(request, '没有可发布的草稿版本')
        return redirect('/r6/definitions/{}/'.format(definition.pk))

    try:
        services.publish_version(draft)
    except services.WorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, '版本 v{} 已发布'.format(draft.version))
    return redirect('/r6/definitions/{}/'.format(definition.pk))


# ---------------------------------------------------------------------------
# 实例
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*STAFF_ROLES)
def instance_new(request):
    errors = {}
    form = {'definition': '', 'subject_type': 'demo', 'subject_id': ''}

    publishable = WorkflowDefinition.objects.filter(is_active=True).order_by('code')

    if request.method == 'POST':
        form.update({
            'definition': (request.POST.get('definition') or '').strip(),
            'subject_type': (request.POST.get('subject_type') or '').strip(),
            'subject_id': (request.POST.get('subject_id') or '').strip(),
        })

        definition = WorkflowDefinition.objects.filter(pk=form['definition']).first()
        # 独立校验：一次显示全部问题，而不是只报第一个
        if definition is None:
            errors['definition'] = '请选择流程'
        if not form['subject_type']:
            errors['subject_type'] = '业务类型不能为空'
        if not form['subject_id']:
            errors['subject_id'] = '业务标识不能为空'

        if not errors:
            version = services.active_version(definition)
            if version is None:
                errors['general'] = '该流程没有已发布版本'
            else:
                try:
                    instance = services.start_instance(
                        version, subject_type=form['subject_type'],
                        subject_id=form['subject_id'], created_by=_actor(request))
                except services.WorkflowError as exc:
                    errors['general'] = str(exc)
                else:
                    messages.success(request, '流程已发起')
                    return redirect('/r6/instances/{}/'.format(instance.pk))

    return render(request, 'r6/instance_new.html', {
        'form': form,
        'errors': errors,
        'definitions': publishable,
    })


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def instance_detail(request, pk):
    instance = WorkflowInstance.objects.filter(pk=pk).select_related(
        'version', 'current_node', 'version__definition').first()
    if instance is None:
        return HttpResponse('实例不存在', status=404)

    account = getattr(request, 'user', None)
    roles = set(account.active_roles()) if account and account.is_active else set()
    is_admin = 'system_admin' in roles
    if not is_admin and instance.created_by != getattr(account, 'login_name', ''):
        return HttpResponse('无权查看该实例', status=403)

    # 当前节点允许的动作
    actions = []
    if instance.current_node and instance.status not in (
            WorkflowInstance.STATUS_APPROVED, WorkflowInstance.STATUS_REJECTED,
            WorkflowInstance.STATUS_WITHDRAWN):
        for transition in instance.version.transitions.filter(
                from_node=instance.current_node).select_related('to_node'):
            if transition.action not in actions:
                actions.append(transition.action)

    return render(request, 'r6/instance_detail.html', {
        'instance': instance,
        'events': instance.events.order_by('created_at'),
        'actions': actions,
        'is_admin': is_admin,
    })


@require_POST
@roles_required(*STAFF_ROLES)
def instance_action(request, pk):
    instance = WorkflowInstance.objects.filter(pk=pk).first()
    if instance is None:
        return HttpResponse('实例不存在', status=404)

    account = getattr(request, 'user', None)
    roles = set(account.active_roles()) if account and account.is_active else set()
    is_admin = 'system_admin' in roles
    if not is_admin and instance.created_by != getattr(account, 'login_name', ''):
        return HttpResponse('无权操作该实例', status=403)

    action = (request.POST.get('action') or '').strip()
    reason = (request.POST.get('reason') or '').strip()

    try:
        services.transition(instance, action, actor=_actor(request), reason=reason)
    except services.TransitionError as exc:
        messages.error(request, '非法操作：{}'.format(exc))
    except services.ConflictError as exc:
        messages.warning(request, '操作冲突：{}'.format(exc))
    except services.WorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, '已完成动作「{}」'.format(action))

    return redirect('/r6/instances/{}/'.format(instance.pk))


# ---------------------------------------------------------------------------
# 待办
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def task_list_page(request):
    tasks = services.open_tasks().select_related('instance', 'node').order_by('created_at')
    return render(request, 'r6/task_list.html', {'tasks': tasks[:200]})


@require_POST
@roles_required(*STAFF_ROLES)
def task_complete(request, pk):
    task = ApprovalTask.objects.filter(pk=pk).first()
    if task is None:
        return HttpResponse('任务不存在', status=404)

    try:
        services.complete_task(task, actor=_actor(request))
    except services.ConflictError as exc:
        messages.warning(request, str(exc))
    else:
        messages.success(request, '任务已标记完成')

    return redirect('/r6/tasks/')


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def notification_page(request):
    account = getattr(request, 'user', None)
    login = getattr(account, 'login_name', '')
    return render(request, 'r6/notification_list.html', {
        'rows': services.inbox(login)[:200],
        'unread': services.inbox(login, unread_only=True).count(),
    })


@require_POST
@roles_required(*STAFF_ROLES)
def notification_read(request, pk):
    from smass_workflow.models import Notification

    account = getattr(request, 'user', None)
    login = getattr(account, 'login_name', '')
    note = Notification.objects.filter(pk=pk, recipient=login).first()
    if note is None:
        return HttpResponse('通知不存在', status=404)

    services.mark_read(note)
    messages.success(request, '已标记为已读')
    return redirect('/r6/notifications/')

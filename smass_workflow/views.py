"""R6 视图：流程定义、实例状态转移、待办与站内消息。"""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from smass_organization.views import roles_required
from smass_workflow import services
from smass_workflow.models import (
    ApprovalTask,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowVersion,
)

ADMIN_ROLES = {'system_admin', 'college_admin'}
STAFF_ROLES = {'system_admin', 'college_admin', 'teacher'}


def _body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


def health(request):
    return JsonResponse({
        'ok': True,
        'module': 'smass_workflow',
        'definitions': WorkflowDefinition.objects.count(),
        'instances': WorkflowInstance.objects.count(),
        'open_tasks': ApprovalTask.objects.filter(status='open').count(),
    })


@require_http_methods(['GET'])
@roles_required(*ADMIN_ROLES)
def definition_list(request):
    definitions = WorkflowDefinition.objects.all().order_by('code')
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': [
            {'code': d.code, 'name': d.name, 'is_active': d.is_active,
             'versions': d.versions.count()}
            for d in definitions
        ]})
    return render(request, 'r6/definition_list.html', {'definitions': definitions})


@require_POST
@roles_required(*ADMIN_ROLES)
def definition_create(request):
    data = _body(request)
    try:
        definition = services.create_definition(
            data.get('code', ''), data.get('name', ''),
            description=data.get('description', ''),
        )
    except services.WorkflowError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'id': definition.pk, 'code': definition.code})


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def instance_list(request):
    account = getattr(request, 'user', None)
    instances = WorkflowInstance.objects.select_related('version', 'current_node')
    if account is not None and 'system_admin' not in set(account.active_roles()):
        instances = instances.filter(created_by=account.login_name)
    instances = instances.order_by('-created_at')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': [
            {'id': i.pk, 'subject': '{}:{}'.format(i.subject_type, i.subject_id),
             'status': i.status,
             'node': i.current_node.code if i.current_node else ''}
            for i in instances[:200]
        ]})
    return render(request, 'r6/instance_list.html', {'instances': instances[:200]})


@require_POST
@roles_required(*STAFF_ROLES)
def instance_create(request):
    data = _body(request)
    account = getattr(request, 'user', None)

    definition = WorkflowDefinition.objects.filter(pk=data.get('definition')).first()
    if definition is None:
        return JsonResponse({'ok': False, 'reason': '流程不存在'}, status=400)

    version = services.active_version(definition)
    if version is None:
        return JsonResponse({'ok': False, 'reason': '流程无已发布版本'}, status=400)

    try:
        instance = services.start_instance(
            version,
            subject_type=data.get('subject_type', 'demo'),
            subject_id=data.get('subject_id', ''),
            created_by=getattr(account, 'login_name', ''),
        )
    except services.WorkflowError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'id': instance.pk})


@require_POST
@roles_required(*STAFF_ROLES)
def instance_action(request, pk):
    data = _body(request)
    account = getattr(request, 'user', None)
    instance = WorkflowInstance.objects.filter(pk=pk).first()
    if instance is None:
        return JsonResponse({'ok': False, 'reason': 'not found'}, status=404)

    try:
        instance = services.transition(
            instance, data.get('action', ''),
            actor=getattr(account, 'login_name', ''),
            reason=data.get('reason', ''),
        )
    except services.TransitionError as exc:
        return JsonResponse({'ok': False, 'code': 'TRANSITION', 'reason': str(exc)},
                            status=400)
    except services.ConflictError as exc:
        return JsonResponse({'ok': False, 'code': 'CONFLICT', 'reason': str(exc)},
                            status=409)

    return JsonResponse({'ok': True, 'status': instance.status,
                         'node': instance.current_node.code if instance.current_node else ''})


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def task_list(request):
    tasks = services.open_tasks().order_by('created_at')
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': [
            {'id': t.pk, 'instance': t.instance_id, 'node': t.node.code,
             'assignee': t.assignee}
            for t in tasks[:200]
        ]})
    return render(request, 'r6/task_list.html', {'tasks': tasks[:200]})


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def notification_list(request):
    account = getattr(request, 'user', None)
    login = getattr(account, 'login_name', '')
    rows = services.inbox(login)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': [
            {'id': n.pk, 'title': n.title, 'is_read': n.is_read}
            for n in rows[:200]
        ]})
    return render(request, 'r6/notification_list.html', {'rows': rows[:200]})
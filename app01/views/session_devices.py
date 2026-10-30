"""S17：并发登录设备与会话管理。

安全要点：

1. **身份只来自服务端会话** —— 不读取任何请求参数里的 user_id/role，
   避免通过参数伪造归属；
2. **踢出必须双匹配** —— ``user_id`` + ``role`` + ``revoked_at IS NULL``，
   防止不同角色模型使用相同字符串主键时互相越权（IDOR）；
3. **POST + CSRF** —— 所有破坏性操作只接受 POST，并由 Django CSRF 中间件校验；
4. **不泄露会话键** —— 页面只展示设备标识前 8 位、IP、UA 与时间，
   服务端 Session Key 从不出现在响应里。
"""
import logging

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from app01.services import accounts
from app01.services import session_security
from app01.utils.authz import role_required, wants_json

logger = logging.getLogger('smass.audit')

ROLES = (accounts.ROLE_ADMIN, accounts.ROLE_STUDENT, accounts.ROLE_TEACHER)


def _identity(request):
    """从服务端会话解析当前身份；返回 (role, account_id)。"""
    info = request.session.get('info') or {}
    return info.get('type'), info.get('id')


def _device_rows(role, account_id, current_device_id):
    rows = []
    for device in session_security.list_devices(account_id, role=role):
        rows.append({
            'device_id': device.device_id,
            'short_id': device.device_id[:8],
            'ip': device.ip or '-',
            'user_agent': device.user_agent or '-',
            'last_seen': device.last_seen,
            'current': device.device_id == current_device_id,
        })
    return rows


@role_required(*ROLES)
@require_http_methods(['GET'])
def session_list(request):
    """当前账号的在线设备列表（GET）。"""
    role, account_id = _identity(request)
    if not account_id:
        return redirect('/login/')
    current_device_id = request.session.get('device_id')
    rows = _device_rows(role, account_id, current_device_id)
    return render(request, 'account/sessions.html', {
        'devices': rows,
        'role': role,
        'role_label': accounts.ROLE_LABELS.get(role, ''),
        'account_name': (request.session.get('info') or {}).get('name', ''),
        'idle_enabled': session_security.enabled(),
        'idle_minutes': session_security.idle_timeout_minutes(),
        'notice': request.GET.get('notice', ''),
        'error': request.GET.get('error', ''),
        'home_url': accounts.ROLE_HOME_URLS.get(role, '/'),
    })


@role_required(*ROLES)
@require_POST
def session_revoke(request, device_id):
    """踢出指定设备（仅限本人、本角色）。"""
    role, account_id = _identity(request)
    current_device_id = request.session.get('device_id')

    if device_id == current_device_id:
        payload = {'status': False, 'tips': '不能在此踢出当前设备，请直接退出登录'}
        if wants_json(request):
            return JsonResponse(payload, status=400)
        return redirect('/account/sessions/?error=current')

    revoked = session_security.revoke_device(account_id, device_id, role=role)
    logger.info(
        'session_device_revoked actor=%s role=%s target=%s ok=%s ip=%s',
        account_id, role, device_id[:8], revoked,
        request.META.get('REMOTE_ADDR', '-'),
    )
    payload = {'status': revoked, 'revoked': 1 if revoked else 0}
    if not revoked:
        payload['tips'] = '设备不存在或已失效'
    if wants_json(request):
        return JsonResponse(payload, status=200 if revoked else 404)
    if not revoked:
        return redirect('/account/sessions/?error=notfound')
    return redirect('/account/sessions/?notice=revoked')


@role_required(*ROLES)
@require_POST
def session_revoke_others(request):
    """踢出除当前设备外的所有会话（"退出其他设备"）。"""
    role, account_id = _identity(request)
    current_device_id = request.session.get('device_id')
    revoked = session_security.revoke_other_devices(
        account_id, current_device_id, role=role)
    logger.info(
        'session_devices_revoked_others actor=%s role=%s count=%s ip=%s',
        account_id, role, revoked, request.META.get('REMOTE_ADDR', '-'),
    )
    if wants_json(request):
        return JsonResponse({'status': True, 'revoked': revoked})
    return redirect('/account/sessions/?notice=others&count={}'.format(revoked))

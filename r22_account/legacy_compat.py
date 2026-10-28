"""H3：让 `app01` 旧视图在 staging 身份模式下可用（**不改 app01 一行代码**）。

思路：`app01` 的视图与装饰器都读 ``session['info']``。R2.2 的认证主体是
``Account``（``request.user``）。因此适配层只做一件事：

> 当身份解析为 ``account`` 或 ``dual`` 时，把 Account 映射回它的
> ``LegacyAccountLink``，并在**本次会话**中补齐等价的 ``session['info']``。

安全约束：
1. 映射**只来自** ``LegacyAccountLink``（权威），不做登录名/pk 推测；
2. ``conflict`` / 匿名不写 session（不降级、不伪造）；
3. 只在 ``R22_FLAGS.legacy_bridge`` 开启时生效（默认仅在隔离配置开启）；
4. 已存在 ``session['info']`` 时不覆盖（避免覆盖旧会话的真实身份）。
"""
from r21_account.models import LegacyAccountLink

SOURCE_TABLE_TO_ROLE = {
    'app01_admin': 'admin',
    'app01_teacher': 'teacher',
    'app01_student': 'student',
}


def legacy_info_for(account):
    """把 Account 映射为 ``session['info']`` 结构；无法映射时返回 None。"""
    if account is None:
        return None

    link = LegacyAccountLink.objects.filter(account=account).first()
    if link is None:
        return None

    role = SOURCE_TABLE_TO_ROLE.get(link.source_table)
    if role is None:
        return None

    return {
        'id': str(link.source_pk),
        'type': role,
        'name': getattr(account, 'display_name', '') or '',
    }


def ensure_legacy_session(request):
    """为 app01 旧视图补齐 session['info']（幂等、不覆盖既有身份）。"""
    from r22_account import conf

    if not conf.flags().get('legacy_bridge'):
        return False

    identity = request.r22_identity()
    if identity.kind not in ('account', 'dual'):
        return False

    if request.session.get('info'):
        return False

    info = legacy_info_for(identity.account)
    if info is None:
        return False

    request.session['info'] = info
    # 身份已变化（account -> dual），必须让解析缓存失效，
    # 否则后续 RoutePolicy 仍按旧的 'account' 判定并拒绝旧路由。
    cache = getattr(request, '_r22_identity_cache', None)
    if isinstance(cache, dict):
        cache['identity'] = None
    return True

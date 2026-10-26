"""通用 CRUD 服务。

设计约束（对应 R1-C）：
1. 搜索字段必须由每个业务模块**显式声明**，禁止把用户输入拼进 ORM 字段名；
2. 删除、详情等操作必须显式传入模型类，禁止依据请求参数动态决定操作对象
   （历史上 ``classCommittee_delete`` 误传 ``models.Department`` 即由此而来）；
3. 对外只返回结构化 JSON，不暴露 traceback。
"""
import logging

from django.db.models import Q
from django.http import JsonResponse
from django.urls import NoReverseMatch, reverse

from app01.services.accounts import log_action

logger = logging.getLogger('smass.audit')

#: 后台模块可能用到的接口动作，与命名路由约定 ``admin_<模块>_<动作>`` 对应
DEFAULT_ACTIONS = ('add', 'detail', 'edit', 'delete', 'obtain', 'resetPass', 'multi', 'template')


def build_endpoints(module_prefix, actions=DEFAULT_ACTIONS):
    """按命名路由约定生成接口地址字典。

    模板通过 ``{{ endpoints }}`` / ``json_script`` 消费，不再用
    ``str_dict.name_en`` 拼装 URL —— 历史版本正是这样把班委接口串到团学干部。
    缺失的路由（例如非账号模块没有 obtain/resetPass）会被静默略过。
    """
    endpoints = {}
    for action in actions:
        try:
            endpoints[action] = reverse('admin_{}_{}'.format(module_prefix, action))
        except NoReverseMatch:
            continue
    return endpoints


def apply_search(queryset, search_fields, keyword):
    """按显式声明的字段做 OR 模糊匹配。

    :param queryset: 已过滤的基础查询集
    :param search_fields: 形如 ``('name', 'major__name')`` 的字段路径元组
    :param keyword: 用户输入的关键词
    """
    keyword = (keyword or '').strip()
    if not keyword or not search_fields:
        return queryset

    query = Q()
    for field in search_fields:
        query |= Q(**{'{}__icontains'.format(field): keyword})
    return queryset.filter(query)


def build_search_meta(search_fields, keyword):
    """构造传给模板的搜索上下文（保持 ``search_data`` 回显）。"""
    return {
        'search_data': (keyword or '').strip(),
        'search_fields': tuple(search_fields),
    }


def row_detail_dict(model, pk, exclude=('password',)):
    """返回一行数据的字典。

    - 外键键名由 ``counsellor_id`` 还原为 ``counsellor``（与表单字段名一致）；
    - ``exclude`` 中的敏感字段一律置为空字符串，避免把密码哈希回显到前端。
    """
    row = model.objects.filter(pk=pk).values().first()
    if row is None:
        return None

    for field in model._meta.fields:
        attname = getattr(field, 'attname', None)
        if field.is_relation and attname and attname in row:
            value = row.pop(attname)
            row[field.name] = value

    for name in exclude:
        if name in row:
            row[name] = ''

    return row


def delete_by_pk(model, pk, request=None):
    """按主键删除一行并返回统一 JSON。

    模型类由调用方显式传入，不接受任何来自请求的模型名。
    """
    if not pk:
        return JsonResponse({'status': False, 'error': '缺少必要参数 uid'}, status=400)

    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)

    identifier = str(obj.pk)
    try:
        obj.delete()
    except Exception:  # noqa: BLE001 - 数据完整性错误需要转成可读提示
        logger.exception(
            'delete_failed model=%s pk=%s', model.__name__, identifier
        )
        return JsonResponse(
            {'status': False, 'error': '删除失败：该记录仍被其他数据引用'},
            status=409,
        )

    log_action(request, 'delete', None, detail='model={} pk={}'.format(model.__name__, identifier))
    return JsonResponse({'status': True})

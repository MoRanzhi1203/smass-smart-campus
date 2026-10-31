"""V2.0 通用分页：Queryset 与 list 均可，供管理端/教师端列表复用。"""
from __future__ import annotations

from math import ceil

DEFAULT_PER_PAGE = 20


def paginate(items, page, per_page=DEFAULT_PER_PAGE):
    """返回 ``{'items', 'page', 'page_count', 'total', 'has_prev', 'has_next'}``。

    页码非法（非数字/越界）时回落到合法范围，不抛错。
    """
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    per_page = max(1, per_page)

    from django.db.models import QuerySet

    is_queryset = isinstance(items, QuerySet)
    if is_queryset:
        total = items.count()
    else:
        total = len(items)
    page_count = max(1, ceil(total / per_page))
    page = max(1, min(page, page_count))
    offset = (page - 1) * per_page
    if is_queryset:
        slice_items = list(items[offset:offset + per_page])
    else:
        slice_items = items[offset:offset + per_page]
    return {
        'items': slice_items,
        'page': page,
        'page_count': page_count,
        'total': total,
        'per_page': per_page,
        'has_prev': page > 1,
        'has_next': page < page_count,
    }


def querystring_without_page(request):
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()

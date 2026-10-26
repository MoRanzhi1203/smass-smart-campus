"""历史工具函数的兼容层（**已弃用，仅为避免遗留 import 断裂而保留**）。

R1 重构后，本模块的职责已分别迁到服务层：

| 旧函数 | 新实现 |
|---|---|
| `row_delete` | `app01.services.crud.delete_by_pk` |
| `row_obtain` | `app01.services.crud.row_detail_dict`（且**不再返回密码哈希**） |
| `row_resetPass` | `app01.services.accounts.reset_password`（官方哈希 + 随机一次性口令） |
| `download_template` | 各视图直接用 `openpyxl` + `services.imports.*_HEADERS` |

⚠️ 重要：旧版 `row_resetPass` 会执行 `md5(cardID[-6:])` 并直接写入数据库。
在模型 `save()` 已不再哈希的前提下，那会产生"MD5 与 PBKDF2 混存"的坏数据。
该实现已彻底移除，本模块现在**只做委托**，不包含任何密码哈希代码。

新代码请直接使用 services 层；本文件计划在 R2 清理调用方后整体删除。
"""
import urllib.parse

from django.http import HttpResponse, JsonResponse
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from app01.services import accounts, crud


def Delete_ForeignKey_id(row_dict, data_sheet):
    """把 ``values()`` 结果中的外键键名 ``xxx_id`` 还原为 ``xxx``。

    纯字典操作，无副作用。新代码请用 ``crud.row_detail_dict``。
    """
    row_renew = []
    for key in row_dict.keys():
        # is_relation 判断该字段是否为外键类型
        is_ForeignKey = data_sheet._meta.get_field(key).is_relation
        if is_ForeignKey:
            row_renew.append(key)

    for key in row_renew:
        value = row_dict.pop(key)
        new_key = key[:-3]
        row_dict[new_key] = value

    return row_dict


def row_delete(uid, models_delete, request=None):
    """按主键删除一行（委托 ``crud.delete_by_pk``）。"""
    return crud.delete_by_pk(models_delete, uid, request)


def row_obtain(uid, models_obtain):
    """获取一行详情（**敏感字段已屏蔽**，委托 ``crud.row_detail_dict``）。"""
    row = crud.row_detail_dict(models_obtain, uid, exclude=('password',))
    if row is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)
    return JsonResponse({'status': True, 'data': row})


def row_resetPass(uid, models_reset, request=None):
    """重置密码（委托 ``accounts.reset_password``）。

    :return: ``{'status': True, 'password': <一次性明文>}``
             —— 明文仅供调用方展示一次，不写入日志。
    """
    instance = models_reset.objects.filter(pk=uid).first()
    if instance is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)

    raw_password = accounts.reset_password(instance, request=request)
    return JsonResponse({'status': True, 'password': raw_password})


def download_template(headers, head_txt):
    """生成并下载 xlsx 模版（无副作用，保留原签名）。"""
    workbook = Workbook()
    sheet = workbook.active

    for col_num, header in enumerate(headers, 1):
        col_letter = get_column_letter(col_num)
        sheet['{}1'.format(col_letter)] = header

    filename = '{}信息批量导入模版.xlsx'.format(head_txt)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename*=UTF-8\'\'{}'.format(
        urllib.parse.quote(filename)
    )

    workbook.save(response)
    return response

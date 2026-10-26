import urllib.parse

from django.http import JsonResponse, HttpResponse
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from app01.utils.encrypt import md5


def Delete_ForeignKey_id(row_dict, data_sheet):
    """
    # 对外键字段名最后附加的'_id'进行删除
    :param row_dict: 传参字典
    :param data_sheet: 数据表名
    :return: 删除 外键字段名附加'_id' 后的字典
    """
    row_renew = []
    for key in row_dict.keys():
        # is_relation方法 判断该字段是否为外键类型
        is_ForeignKey = data_sheet._meta.get_field(key).is_relation
        if is_ForeignKey:
            row_renew.append(key)

    for key in row_renew:
        value = row_dict.pop(key)
        new_key = key[:-3]
        row_dict[new_key] = value


def row_delete(uid, models_delete):
    """
    # 删除数据行
    :param uid: 所选数据行
    :param models_delete: 所选数据表
    :return:
    """
    exists = models_delete.objects.filter(id=uid).exists()
    if not exists:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    models_delete.objects.filter(id=uid).delete()
    # 删除成功
    return JsonResponse({'status': True})


def row_obtain(uid, models_obtain):
    """
    # 获取重置数据行信息
    :param uid: 所选数据行
    :param models_obtain: 所选数据表
    :return:
    """
    exists = models_obtain.objects.filter(id=uid).exists()
    if not exists:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    # 获取匹配过滤条件的行数据
    row_name = models_obtain.objects.filter(id=uid).values().first()

    return JsonResponse({'status': True, 'data': row_name})


def row_resetPass(uid, models_reset):
    """
    # 重置该用户密码
    :param uid: 获取用户uid
    :param models_reset: 所选数据表
    :return:
    """
    reset = models_reset.objects.get(id=uid)
    # 重置密码为身份证后六位，并 md5加密
    reset.password = md5(reset.cardID[-6:])
    # 保存至数据库
    reset.save()

    # 密码重置成功
    return JsonResponse({'status': True})


def download_template(headers, head_txt):
    """
    # 创建【批量添加模版】
    :param headers: 表头列表
    :return: 下载模版Excel
    """

    # 创建工作簿
    workbook = Workbook()
    sheet = workbook.active

    # # 表头内容列表
    # headers = ['学院']

    # 批量添加表头
    for col_num, header in enumerate(headers, 1):
        col_letter = get_column_letter(col_num)
        sheet[f'{col_letter}1'] = header

    # 设置响应头以指定文件名和内容类型
    filename = '{}信息批量导入模版.xlsx'.format(head_txt)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename*=UTF-8\'\'{}'.format(urllib.parse.quote(filename))

    # 将工作簿保存到响应对象中
    workbook.save(response)

    return response

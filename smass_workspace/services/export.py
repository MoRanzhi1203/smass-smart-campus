"""E07 受控导出：字段白名单 + 公式注入中和 + CSV（UTF-8 BOM，Excel 友好）。

只导出产品明确允许的列；不导出手机号、身份证、密码等敏感字段。
"""
from __future__ import annotations

import csv
import io

from django.http import HttpResponse

#: 导出种类 → (表头, 取值函数)
def export_records(rows):
    return [[item.student_no, item.name,
             item.unit.name if item.unit_id else '',
             item.get_status_display()] for item in rows]


def export_bills(rows):
    return [[item.bill_no, item.record.student_no, item.record.name,
             item.term, str(item.total), str(item.paid),
             item.get_status_display()] for item in rows]


def export_users(rows):
    return [[item.login_name, item.display_name, item.get_person_type_display(),
             '是' if item.is_active else '否'] for item in rows]


EXPORTS = {
    'records': {
        'headers': ['学号', '姓名', '学院', '学籍状态'],
        'rows': export_records,
        'filename': 'students-records',
    },
    'bills': {
        'headers': ['账单号', '学号', '姓名', '学期', '应缴', '已缴', '状态'],
        'rows': export_bills,
        'filename': 'finance-bills',
    },
    'users': {
        'headers': ['登录名', '姓名', '人员类型', '启用'],
        'rows': export_users,
        'filename': 'accounts',
    },
}

FORMULA_PREFIXES = ('=', '+', '-', '@')


def neutralize(value):
    text = '' if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def csv_response(headers, rows, filename):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([neutralize(value) for value in row])
    payload = '\ufeff' + buffer.getvalue()
    response = HttpResponse(payload, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="{}.csv"'.format(
        filename)
    return response

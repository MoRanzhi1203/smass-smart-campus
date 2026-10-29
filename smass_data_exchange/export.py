"""S25 安全导出。

要求（主任务书 S25）：
- 导出的行必须**只包含调用者有字段权限的列**（字段级裁剪）；
- 单元格文本必须做**公式注入中和**（``= + - @`` 与制表/换行开头加单引号）；
- CSV 用 UTF-8 BOM 并对大结果集分块写出；
- 导出文件名 ASCII，中文只在内容里；
- 不在导出中返回未经授权的敏感字段原值。
"""
from __future__ import annotations

import csv
import io

from .parsing import ParseError
from .schema import DatasetSchema, get
from .templates import CSV_MIME, CSV_ENCODING, XLSX_MIME

#: Excel 公式注入前缀字符
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r', '\n')


def neutralize(text) -> str:
    """中和公式注入，返回可安全写入单元格的文本。"""
    if text is None:
        return ''
    value = str(text)
    if value and value[0] in FORMULA_PREFIXES:
        return "'" + value
    return value


def allowed_columns(schema: DatasetSchema, allowed_codes=None):
    """按字段权限裁剪列；``None`` 表示全部允许。"""
    if allowed_codes is None:
        return tuple(schema.fields)
    allowed = set(allowed_codes)
    return tuple(f for f in schema.fields if f.code in allowed)


def _mask(schema: DatasetSchema, code: str, value):
    """敏感字段在导出时脱敏（保守默认）。"""
    spec = schema.field(code)
    if not spec.sensitive:
        return value
    text = '' if value is None else str(value)
    if len(text) <= 5:
        return '*' * len(text)
    return text[:3] + '*' * (len(text) - 5) + text[-2:]


def export_csv_bytes(schema: DatasetSchema, rows, *, allowed_codes=None,
                     mask_sensitive=True, batch_size=2000) -> bytes:
    fields = allowed_columns(schema, allowed_codes)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\r\n')
    writer.writerow([f.code for f in fields])

    written = 0
    for row in rows:
        values = []
        for f in fields:
            value = row.get(f.code, '')
            if mask_sensitive:
                value = _mask(schema, f.code, value)
            values.append(neutralize(value))
        writer.writerow(values)
        written += 1
        if batch_size and written % batch_size == 0:
            buffer.flush()
    return buffer.getvalue().encode(CSV_ENCODING)


def export_xlsx_bytes(schema: DatasetSchema, rows, *, allowed_codes=None,
                      mask_sensitive=True, sheet_title='Data') -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    fields = allowed_columns(schema, allowed_codes)
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title or 'Data')[:31]

    for col, f in enumerate(fields, start=1):
        cell = ws.cell(row=1, column=col, value=f.code)
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='DCE6F1')

    for index, row in enumerate(rows, start=2):
        for col, f in enumerate(fields, start=1):
            value = row.get(f.code, '')
            if mask_sensitive:
                value = _mask(schema, f.code, value)
            ws.cell(row=index, column=col, value=neutralize(value))

    for col, f in enumerate(fields, start=1):
        from openpyxl.utils import get_column_letter

        ws.column_dimensions[get_column_letter(col)].width = max(12, min(40, len(f.label) * 2 + 6))
    ws.freeze_panes = 'A2'

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export_filename(schema: DatasetSchema, ext: str) -> str:
    return 'smass_export_{}_v{}.{}'.format(
        schema.code.replace('.', '_'), schema.version, ext)


def export_dataset(dataset: str, rows, fmt: str = 'csv', *, allowed_codes=None,
                   mask_sensitive=True) -> tuple[bytes, str, str]:
    """返回 ``(内容, ASCII 文件名, Content-Type)``。"""
    schema = get(dataset)
    fmt = (fmt or 'csv').lower()
    if fmt in ('xlsx', 'excel'):
        return (export_xlsx_bytes(schema, rows, allowed_codes=allowed_codes,
                                  mask_sensitive=mask_sensitive),
                export_filename(schema, 'xlsx'), XLSX_MIME)
    if fmt == 'csv':
        return (export_csv_bytes(schema, rows, allowed_codes=allowed_codes,
                                 mask_sensitive=mask_sensitive),
                export_filename(schema, 'csv'), CSV_MIME)
    raise ParseError('不支持的导出格式: {}'.format(fmt), code='UNSUPPORTED_TYPE')

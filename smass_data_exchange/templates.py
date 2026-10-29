"""S25 模板生成：真实可下载的 .xlsx 与 UTF-8 CSV。

要求（主任务书 S25）：
- 每个受支持的导入能力都要有真实的 Excel 与 CSV 模板；
- Excel 含 ``Data`` / ``Instructions`` / ``Options`` 三张表；
- 模板中的示例行必须是**合成数据**，不得含真实人员；
- 文件名用 ASCII，中文只出现在文件内容里。
"""
from __future__ import annotations

import csv
import io

from .schema import DatasetSchema

#: CSV 用 UTF-8 BOM，避免 Excel 双击打开中文乱码
CSV_ENCODING = 'utf-8-sig'

XLSX_MIME = ('application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet')
CSV_MIME = 'text/csv; charset=utf-8'


def template_filename(schema: DatasetSchema, ext: str) -> str:
    """ASCII 文件名：smass_template_<code>_v<version>.<ext>"""
    safe = schema.code.replace('.', '_')
    return 'smass_template_{}_v{}.{}'.format(safe, schema.version, ext)


#: 示例行标记列名。带下划线双前缀，不会与业务字段冲突；
#: 解析器只在这一列被显式标记时跳过该行，**不再按值猜**——
#: 否则用户数据恰好等于示例值就会被静默丢弃。
EXAMPLE_MARKER = '__example__'


def _header_cells(schema):
    """表头文本：``code``（必填加 ``*``）+ 末尾示例标记列。"""
    cells = []
    for f in schema.fields:
        cells.append('{}*'.format(f.code) if f.required else f.code)
    cells.append(EXAMPLE_MARKER)
    return cells


def build_csv_template(schema: DatasetSchema) -> bytes:
    """UTF-8(BOM) CSV：**只有表头**（不含示例行）。

    CSV 没有可靠的注释机制，若放示例行会让用户必须手工删行；
    因此 CSV 模板保持"表头即用"，示例与说明放在 xlsx 的
    ``Instructions`` 表与页面帮助文本里。
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\r\n')
    writer.writerow([f.code for f in schema.fields])
    return buffer.getvalue().encode(CSV_ENCODING)


def build_xlsx_template(schema: DatasetSchema) -> bytes:
    """三表 xlsx：Data（表头+示例+下拉校验）/ Instructions / Options。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()

    # ---------------- Data ----------------
    ws = wb.active
    ws.title = 'Data'
    header_fill = PatternFill('solid', fgColor='DCE6F1')
    header_font = Font(bold=True)

    for col, text in enumerate(_header_cells(schema), start=1):
        cell = ws.cell(row=1, column=col, value=text)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')

    example = schema.example_row()
    for col, f in enumerate(schema.fields, start=1):
        cell = ws.cell(row=2, column=col, value=example.get(f.code, ''))
        cell.font = Font(italic=True, color='808080')
    # 示例行用显式标记列标识；解析器只认这一列，不按值猜。
    marker_cell = ws.cell(row=2, column=len(schema.fields) + 1, value=1)
    marker_cell.font = Font(italic=True, color='C00000')

    # 列宽
    for col, f in enumerate(schema.fields, start=1):
        width = max(12, min(40, len(f.label) * 2 + 6))
        ws.column_dimensions[get_column_letter(col)].width = width

    ws.freeze_panes = 'A2'

    # 枚举下拉校验（作用到第 3..MAX 行）
    for col, f in enumerate(schema.fields, start=1):
        if f.dtype != 'enum' or not f.choices:
            continue
        options_sheet = 'Options'
        letter = get_column_letter(col)
        dv = DataValidation(
            type='list',
            formula1="'{}'!$A$1:$A${}".format(options_sheet, len(f.choices)),
            allow_blank=not f.required,
            showDropDown=False,
        )
        dv.error = '取值必须是 {} 之一'.format('/'.join(f.choices))
        dv.errorTitle = f.label
        ws.add_data_validation(dv)
        dv.add('{}{}:{}{}'.format(letter, 3, letter, 3 + 1000))

    # ---------------- Instructions ----------------
    ins = wb.create_sheet('Instructions')
    ins.append(['字段', '中文名', '必填', '类型', '长度上限', '可选值', '说明', '示例'])
    for cell in ins[1]:
        cell.font = header_font
        cell.fill = header_fill
    for f in schema.fields:
        ins.append([
            f.code, f.label, '是' if f.required else '否', f.dtype,
            f.max_length or '', '/'.join(f.choices) or '', f.help, f.example,
        ])
    for col, width in zip('ABCDEFGH', (18, 18, 8, 10, 10, 24, 46, 20)):
        ins.column_dimensions[col].width = width
    ins.freeze_panes = 'A2'

    row = ins.max_row + 2
    ins.cell(row=row, column=1, value='数据集').font = header_font
    ins.cell(row=row, column=2, value=schema.title)
    row += 1
    ins.cell(row=row, column=1, value='模板版本').font = header_font
    ins.cell(row=row, column=2, value=schema.version)
    row += 1
    ins.cell(row=row, column=1, value='导入说明').font = header_font
    ins.cell(row=row, column=2, value='；'.join(schema.instructions) or '-')
    row += 1
    if schema.notes:
        ins.cell(row=row, column=1, value='注意事项').font = header_font
        ins.cell(row=row, column=2, value='；'.join(schema.notes))

    # ---------------- Options ----------------
    opt = wb.create_sheet('Options')
    opt.append(['字段', '中文名', '可选值'])
    for cell in opt[1]:
        cell.font = header_font
        cell.fill = header_fill
    for f in schema.fields:
        if f.dtype == 'enum':
            for choice in f.choices:
                opt.append([f.code, f.label, choice])
    # 若没有枚举字段，仍保留表头，保证三表结构稳定
    for col, width in zip('ABC', (18, 20, 24)):
        opt.column_dimensions[col].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_template(schema: DatasetSchema, fmt: str) -> tuple[bytes, str, str]:
    """返回 ``(内容, 文件名, Content-Type)``。"""
    fmt = (fmt or 'xlsx').lower()
    if fmt in ('xlsx', 'excel'):
        return (build_xlsx_template(schema), template_filename(schema, 'xlsx'), XLSX_MIME)
    if fmt == 'csv':
        return (build_csv_template(schema), template_filename(schema, 'csv'), CSV_MIME)
    raise ValueError('不支持的模板格式: {}'.format(fmt))

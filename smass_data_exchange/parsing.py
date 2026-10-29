"""S25 上传解析：.xlsx / .csv 的有界、安全解析。

安全要点
--------
1. **格式白名单**：只接受 .xlsx 与 .csv；其余（.xls/.xlsm/.ods）拒绝，
   避免旧格式的宏与解析器差异。
2. **压缩炸弹防护**：xlsx 是 zip，先检查声明的解压总量与压缩比。
3. **公式不执行**：``openpyxl`` 以 ``data_only=True`` + ``read_only=True`` 打开，
   公式单元格只拿到缓存值；无法计算时按空处理（绝不执行宏或外部链接）。
4. **有界解析**：字节上限 ``MAX_UPLOAD_BYTES``、行数上限 ``MAX_ROWS``、
   单行字段上限由 ``FieldSpec.max_length`` 约束。
5. **编码不静默损坏**：CSV 依次尝试 utf-8-sig / utf-8 / gb18030，
   全部失败则明确报错，不做 replace 静默降级。
"""
from __future__ import annotations

import csv
import io
import zipfile

from .schema import (
    MAX_ROWS,
    MAX_UPLOAD_BYTES,
    DatasetSchema,
    ValidationResult,
)

ALLOWED_EXTENSIONS = ('.xlsx', '.csv')

#: xlsx 解压后的总字节上限（防 zip 炸弹）
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
#: xlsx 允许的最大压缩比
MAX_COMPRESSION_RATIO = 120

#: CSV 编码尝试顺序（gb18030 是 gbk 的超集）
CSV_ENCODINGS = ('utf-8-sig', 'utf-8', 'gb18030')


class ParseError(ValueError):
    """解析阶段的可展示错误。"""

    def __init__(self, message, *, code='PARSE_ERROR', row=0, column=''):
        self.code = code
        self.row = row
        self.column = column
        super().__init__(message)


def detect_format(filename: str, content: bytes) -> str:
    """按扩展名 + 魔数判定格式；两者矛盾时以魔数为准并记录原因。"""
    name = (filename or '').lower()
    is_zip = content[:2] == b'PK'
    if name.endswith('.xlsx'):
        if not is_zip:
            raise ParseError('文件扩展名是 .xlsx 但内容不是有效的 xlsx（zip）')
        return 'xlsx'
    if name.endswith('.csv'):
        if is_zip:
            raise ParseError('文件扩展名是 .csv 但内容看起来是压缩包，已拒绝')
        return 'csv'
    for ext in ALLOWED_EXTENSIONS:
        if name.endswith(ext):
            return ext.lstrip('.')
    raise ParseError(
        '不支持的文件类型：只接受 {}'.format(' / '.join(ALLOWED_EXTENSIONS)),
        code='UNSUPPORTED_TYPE')


def check_size(content: bytes):
    if content is None or len(content) == 0:
        raise ParseError('文件为空', code='EMPTY_FILE')
    if len(content) > MAX_UPLOAD_BYTES:
        raise ParseError(
            '文件过大（{} 字节），上限 {} 字节'.format(len(content), MAX_UPLOAD_BYTES),
            code='TOO_LARGE')


def check_zip_safety(content: bytes):
    """压缩炸弹检查：解压总量与压缩比。"""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            total = sum(info.file_size for info in zf.infolist())
            compressed = sum(max(info.compress_size, 1) for info in zf.infolist())
    except zipfile.BadZipFile:
        raise ParseError('xlsx 文件结构损坏（不是有效 zip）', code='BAD_ZIP')
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ParseError(
            'xlsx 解压后过大（{} 字节），上限 {}'.format(total, MAX_UNCOMPRESSED_BYTES),
            code='ZIP_BOMB')
    if compressed and total / compressed > MAX_COMPRESSION_RATIO:
        raise ParseError(
            'xlsx 压缩比异常（{:.1f}:1），疑似压缩炸弹已拒绝'.format(total / compressed),
            code='ZIP_BOMB')


def _normalize_header(text: str) -> str:
    """表头 ``code*`` / ``code`` -> code。"""
    return str(text or '').strip().rstrip('*').strip().lower()


def _decode_csv(content: bytes) -> tuple[str, str]:
    last_error = None
    for encoding in CSV_ENCODINGS:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    raise ParseError(
        'CSV 编码无法识别（已尝试 {}）：{}'.format('/'.join(CSV_ENCODINGS), last_error),
        code='BAD_ENCODING')


def _read_xlsx_rows(content: bytes) -> list[list]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl 抛的异常类型不稳定
        raise ParseError('xlsx 无法解析：{}'.format(exc), code='BAD_XLSX')

    try:
        if 'Data' not in wb.sheetnames:
            raise ParseError(
                'xlsx 缺少 Data 工作表（必须是模板生成的 .xlsx）', code='MISSING_SHEET')
        ws = wb['Data']
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
            if len(rows) > MAX_ROWS + 5:
                raise ParseError(
                    '数据行超过上限 {}，请拆分后导入'.format(MAX_ROWS),
                    code='TOO_MANY_ROWS')
        return rows
    finally:
        wb.close()


def _read_csv_rows(content: bytes) -> tuple[list[list], str]:
    text, encoding = _decode_csv(content)
    reader = csv.reader(io.StringIO(text))
    rows = []
    for row in reader:
        rows.append(list(row))
        if len(rows) > MAX_ROWS + 5:
            raise ParseError(
                '数据行超过上限 {}，请拆分后导入'.format(MAX_ROWS),
                code='TOO_MANY_ROWS')
    return rows, encoding


def _is_example_row(values: list[str], schema: DatasetSchema) -> bool:
    """模板第 2 行是合成示例，导入时自动忽略。"""
    example = schema.example_row()
    expected = [str(example.get(f.code, '')).strip() for f in schema.fields]
    actual = [str(v or '').strip() for v in values[:len(expected)]]
    return bool(expected) and actual == expected


def parse(content: bytes, filename: str, schema: DatasetSchema) -> tuple[list[dict], dict]:
    """解析为 ``[{字段: 值}]``，并返回元信息。

    不做业务校验，只做**结构**校验（类型/必填/长度/枚举）。
    业务校验（外键存在性等）由适配器在 :mod:`service` 中完成。
    """
    check_size(content)
    fmt = detect_format(filename, content)
    if fmt == 'xlsx':
        check_zip_safety(content)
        table = _read_xlsx_rows(content)
        meta_encoding = 'xlsx'
    else:
        table, meta_encoding = _read_csv_rows(content)

    # 去掉尾部全空行
    while table and all((v is None or str(v).strip() == '') for v in table[-1]):
        table.pop()

    if not table:
        raise ParseError('文件没有任何行', code='EMPTY_FILE')

    header = table[0]
    headers = [_normalize_header(h) for h in header]
    if not any(headers):
        raise ParseError('首行必须是表头', code='MISSING_HEADER')

    missing = [c for c in schema.required_codes if c not in headers]
    if missing:
        raise ParseError(
            '缺少必需列：{}（请使用模板生成的文件）'.format('、'.join(missing)),
            code='MISSING_COLUMN')

    unknown = [h for h in headers if h and h not in schema.codes]
    data_rows = table[1:]

    # 跳过示例行
    skipped_example = 0
    if data_rows and _is_example_row(data_rows[0], schema):
        data_rows = data_rows[1:]
        skipped_example = 1

    if len(data_rows) > MAX_ROWS:
        raise ParseError(
            '数据行 {} 超过上限 {}，请拆分后导入'.format(len(data_rows), MAX_ROWS),
            code='TOO_MANY_ROWS')

    parsed: list[dict] = []
    errors: list[dict] = []
    for index, raw in enumerate(data_rows, start=2 + skipped_example):
        if all((v is None or str(v).strip() == '') for v in raw):
            continue  # 空行忽略
        record = {'__row__': index}
        row_ok = True
        for col, code in enumerate(headers):
            if not code or code not in schema.codes:
                continue
            spec = schema.field(code)
            value = raw[col] if col < len(raw) else None
            try:
                record[code] = spec.normalize(value)
            except ValueError as exc:
                row_ok = False
                errors.append({
                    'row': index, 'column': code,
                    'code': 'INVALID_VALUE', 'message': str(exc),
                })
                record[code] = None
        # 必需字段缺失（列存在但整列为空）
        if row_ok:
            for code in schema.required_codes:
                if record.get(code) in (None, ''):
                    row_ok = False
                    errors.append({
                        'row': index, 'column': code,
                        'code': 'REQUIRED', 'message': '{}不能为空'.format(schema.field(code).label),
                    })
        parsed.append(record)

    meta = {
        'format': fmt,
        'encoding': meta_encoding,
        'headers': headers,
        'unknown_columns': unknown,
        'skipped_example_rows': skipped_example,
        'data_rows': len(parsed),
        'bytes': len(content),
    }
    return parsed, meta, errors

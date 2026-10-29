"""S25 数据交换中心：版本化字段 schema。

设计约束
--------
1. **单一 schema 来源**：模板（xlsx/csv）、解析、校验、导出、错误工作簿全部由
   同一个 ``DatasetSchema`` 生成，避免"模板一套字段、解析另一套"的经典漂移。
2. **版本化**：schema 带 ``version``；上传时校验版本，版本不符直接拒绝并要求
   重新下载模板，而不是猜字段。
3. **不建表**：本模块是纯 Python 库，不新增任何模型/迁移，因此对正式库零影响。
4. **合成示例**：模板里的示例行全部是构造值（``DEMO-`` 前缀、全 0 号码），
   绝不含真实人员信息。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

#: 当前引擎/解析器版本；schema 或解析行为变化时必须递增
ENGINE_VERSION = '1.0.0'

#: 允许的最大数据行数（防止超大文件拖垮进程；超出即拒绝并要求拆分）
MAX_ROWS = 5000

#: 允许的最大上传字节数
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class SchemaError(ValueError):
    """schema 定义或查找失败。"""


@dataclass(frozen=True)
class FieldSpec:
    """一个可导入/导出的字段。"""

    code: str
    label: str
    required: bool = False
    dtype: str = 'str'          # str / int / date / enum / bool
    max_length: int = 0         # 0 表示不限制
    choices: tuple = ()         # enum 取值；同时写入 Options 表
    help: str = ''
    example: str = ''
    #: 是否属于敏感字段（导出时默认脱敏）
    sensitive: bool = False

    def normalize(self, raw):
        """把单元格原始值规范化为 Python 值；失败抛 ``ValueError``。"""
        if raw is None:
            value = ''
        elif isinstance(raw, str):
            value = raw.strip()
        elif isinstance(raw, float) and raw.is_integer():
            value = str(int(raw))
        else:
            value = str(raw).strip()

        if self.dtype == 'int':
            if value == '':
                if self.required:
                    raise ValueError('{}不能为空'.format(self.label))
                return ''
            try:
                return int(value)
            except (TypeError, ValueError):
                raise ValueError('{}必须是整数'.format(self.label))

        if self.dtype == 'date':
            if value == '':
                if self.required:
                    raise ValueError('{}不能为空'.format(self.label))
                return ''
            from datetime import date, datetime

            if isinstance(raw, (date, datetime)):
                return raw.strftime('%Y-%m-%d')
            for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
                try:
                    return datetime.strptime(value, fmt).strftime('%Y-%m-%d')
                except ValueError:
                    continue
            raise ValueError('{}日期格式应为 YYYY-MM-DD'.format(self.label))

        if self.dtype == 'enum':
            if value == '' and not self.required:
                return value
            if value not in self.choices:
                raise ValueError('{}取值必须是 {} 之一'.format(
                    self.label, '/'.join(self.choices)))
            return value

        if self.required and value == '':
            raise ValueError('{}不能为空'.format(self.label))
        if self.max_length and len(value) > self.max_length:
            raise ValueError('{}长度不能超过 {}'.format(self.label, self.max_length))
        return value


@dataclass(frozen=True)
class DatasetSchema:
    """一个数据集（一种可导入的业务对象）的完整定义。"""

    code: str
    version: str
    title: str
    fields: tuple
    instructions: tuple = ()
    notes: tuple = ()
    #: 业务侧必需但允许用户在模板里改的列的说明（可选）
    extra_notes: tuple = ()

    def __post_init__(self):
        codes = [f.code for f in self.fields]
        if len(codes) != len(set(codes)):
            raise SchemaError('{}: 字段 code 重复'.format(self.code))
        for f in self.fields:
            if not re.match(r'^[a-z][a-z0-9_]*$', f.code):
                raise SchemaError('{}: 字段 code 必须小写下划线: {}'.format(self.code, f.code))
            if f.dtype == 'enum' and not f.choices:
                raise SchemaError('{}: enum 字段必须给出 choices: {}'.format(self.code, f.code))

    @property
    def codes(self):
        return tuple(f.code for f in self.fields)

    @property
    def required_codes(self):
        return tuple(f.code for f in self.fields if f.required)

    @property
    def sensitive_codes(self):
        return tuple(f.code for f in self.fields if f.sensitive)

    def field(self, code):
        for f in self.fields:
            if f.code == code:
                return f
        raise SchemaError('{}: 未知字段 {}'.format(self.code, code))

    def example_row(self):
        """一行合成示例（全构造值，不含真实信息）。"""
        return {f.code: f.example or '' for f in self.fields}

    def signature(self):
        """用于令牌绑定的 schema 指纹。"""
        import hashlib

        blob = '|'.join([
            self.code, self.version, ENGINE_VERSION,
            ','.join('{}:{}:{}'.format(f.code, f.dtype, f.required) for f in self.fields),
        ])
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:32]


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, DatasetSchema] = {}


def register(schema: DatasetSchema) -> DatasetSchema:
    key = schema.code
    if key in _REGISTRY and _REGISTRY[key].version != schema.version:
        raise SchemaError(
            '{}: 已注册版本 {}，不能静默替换为 {}（请递增 code 或显式卸载）'.format(
                key, _REGISTRY[key].version, schema.version))
    _REGISTRY[key] = schema
    return schema


def unregister(code: str) -> None:
    _REGISTRY.pop(code, None)


def get(code: str) -> DatasetSchema:
    schema = _REGISTRY.get(code)
    if schema is None:
        raise SchemaError('未注册的数据集: {}'.format(code))
    return schema


def all_schemas() -> Iterable[DatasetSchema]:
    return tuple(_REGISTRY.values())


def require_version(code: str, version: str) -> DatasetSchema:
    """上传文件声明的版本必须与当前 schema 一致。"""
    schema = get(code)
    if version and version != schema.version:
        raise SchemaError(
            '数据集 {} 的模板版本已更新（文件 {} / 当前 {}），请重新下载模板'.format(
                code, version, schema.version))
    return schema


@dataclass
class ValidationResult:
    """一次解析+校验的结果（预检与提交共用）。"""

    schema: DatasetSchema
    rows: list = field(default_factory=list)        # 规范化后的行
    raw_rows: list = field(default_factory=list)    # 原始行（用于错误定位）
    errors: list = field(default_factory=list)      # [{row, column, code, message}]
    total: int = 0
    ok_count: int = 0
    error_count: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    conflict: int = 0

    @property
    def has_errors(self):
        return bool(self.errors)

    def summary(self):
        return {
            'dataset': self.schema.code,
            'schema_version': self.schema.version,
            'engine_version': ENGINE_VERSION,
            'total': self.total,
            'ok': self.ok_count,
            'errors': self.error_count,
            'would_create': self.created,
            'would_update': self.updated,
            'would_skip': self.skipped,
            'would_conflict': self.conflict,
        }

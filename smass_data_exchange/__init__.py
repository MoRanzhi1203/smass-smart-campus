"""SMASS 统一数据交换中心（S25）。

对外 API（业务模块与视图只应该用这些）::

    from smass_data_exchange import (
        get, all_schemas,              # schema 注册表
        build_template,                # 模板下载（xlsx / csv）
        parse, ParseError,             # 上传解析（xlsx / csv）
        preview, commit,               # 预检（零写入）/ 提交（幂等）
        build_error_workbook,          # 错误工作簿
        export_dataset,                # 安全导出（含公式注入中和）
    )

本包**不新增任何模型**，因此不给任何数据库带来迁移负担。
业务适配器在 ``smass_data_exchange.adapters`` 中按需延迟加载。
"""
from .export import export_dataset, export_csv_bytes, export_xlsx_bytes
from .parsing import (
    ALLOWED_EXTENSIONS,
    CSV_ENCODINGS,
    ParseError,
    detect_format,
    parse,
)
from .schema import (
    ENGINE_VERSION,
    MAX_ROWS,
    MAX_UPLOAD_BYTES,
    DatasetSchema,
    FieldSpec,
    SchemaError,
    ValidationResult,
    all_schemas,
    get,
    register,
    require_version,
    unregister,
)
from .service import (
    TICKET_TTL_SECONDS,
    PreviewTicket,
    TicketError,
    build_error_workbook,
    commit,
    file_digest,
    issue_ticket,
    preview,
    read_ticket,
)
from .templates import (
    CSV_MIME,
    XLSX_MIME,
    build_csv_template,
    build_template,
    build_xlsx_template,
    template_filename,
)

def load_builtin_adapters():
    """显式加载内置适配器。

    适配器依赖具体业务 app（``smass_organization`` 等），因此不在包初始化时
    自动加载。视图层/测试在确定业务 app 已安装后调用本函数。
    """
    from . import adapters as _adapters  # noqa: F401  触发注册副作用

    return True


__all__ = [
    'ALLOWED_EXTENSIONS', 'CSV_ENCODINGS', 'CSV_MIME', 'ENGINE_VERSION',
    'MAX_ROWS', 'MAX_UPLOAD_BYTES', 'DatasetSchema', 'FieldSpec',
    'ParseError', 'PreviewTicket', 'SchemaError', 'TICKET_TTL_SECONDS',
    'TicketError', 'ValidationResult', 'XLSX_MIME', 'all_schemas',
    'build_csv_template', 'build_error_workbook', 'build_template',
    'build_xlsx_template', 'commit', 'detect_format', 'export_csv_bytes',
    'export_dataset', 'export_xlsx_bytes', 'file_digest', 'get',
    'issue_ticket', 'load_builtin_adapters', 'parse', 'preview',
    'read_ticket', 'register', 'require_version', 'template_filename',
    'unregister',
]

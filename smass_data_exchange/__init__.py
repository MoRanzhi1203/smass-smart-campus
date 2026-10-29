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
    """显式加载内置适配器，按 app 可用性分组容错。

    - ``r4_students`` 依赖 ``smass_organization``；
    - R5 五类依赖 ``smass_academic``。

    缺少某组依赖时只跳过该组并记录原因，不让整个包导入失败
    （例如 ``settings_r5`` 没有安装 ``smass_organization``）。
    """
    import importlib
    import logging

    logger = logging.getLogger('smass.audit')
    loaded = {}

    for module_name, group in (('adapters', 'r4'), ('adapters_r5', 'r5')):
        try:
            module = importlib.import_module('.' + module_name, __name__)
            register_all = getattr(module, 'register_all', None)
            # 注册本身也可能失败：适配器在实例化时才导入业务模型，
            # 而那个 app 可能没装在这个 settings 里。
            loaded[group] = register_all() if callable(register_all) else True
        except Exception as exc:  # noqa: BLE001 - 对应业务 app 未安装
            logger.info('data_exchange_adapters_skipped group=%s reason=%s: %s',
                        group, type(exc).__name__, exc)
            continue

    from .schema import all_schemas

    logger.info('data_exchange_adapters_loaded groups=%s datasets=%s',
                loaded, len(tuple(all_schemas())))
    return loaded


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

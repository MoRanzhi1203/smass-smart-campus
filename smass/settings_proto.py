"""R2.0 隔离原型专用配置。

与原 ``smass.settings`` 的唯一差别：
1. 数据库指向 ``smass_proto_account``（原型库，绝不等于 ``smass``）；
2. ``INSTALLED_APPS`` 追加 ``proto_account``。

安全断言：原型配置只允许从开发库 ``smass`` 派生。若 ``.env`` 把 ``DB_NAME``
改成了别的库（例如某个真实业务库），这里会直接拒绝启动，避免误连。

用法：
    conda run -n smass python manage.py migrate --settings=smass.settings_proto
    conda run -n smass python manage.py backfill_accounts --dry-run --settings=smass.settings_proto
"""
from .settings import *  # noqa: F401,F403

PROTO_DB_NAME = 'smass_proto_account'

_source_name = DATABASES['default']['NAME']
if _source_name != 'smass':
    raise RuntimeError(
        '原型配置只允许从开发库 smass 派生，当前 DB_NAME={!r}。'
        '请检查 .env，避免误连其他业务库。'.format(_source_name)
    )

DATABASES['default']['NAME'] = PROTO_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_proto_account'

INSTALLED_APPS = list(INSTALLED_APPS) + ['proto_account']

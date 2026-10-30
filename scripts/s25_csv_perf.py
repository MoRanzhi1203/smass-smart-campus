#!/usr/bin/env python
"""S25-PERF：10,000 行 CSV 导出的可复现基准。

在 ``smass.settings_r4`` 的演练库中创建 10,000 条 ``PERF25-*`` 合成学生，
分别测量：

- baseline：``list(queryset)`` + 逐行 ``filtered_extra``（旧实现的 N+1）；
- optimized：``iter_students_csv``（``iterator`` 分批 + 一次字段权限计算）。

结束后删除本次创建的合成数据（除非 ``--keep``）。

用法::

    python scripts/s25_csv_perf.py --json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r4')
import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from r21_account import services as core_services  # noqa: E402
from r21_account.models import Account, RoleCode  # noqa: E402
from smass_organization import export, services  # noqa: E402
from smass_organization.models import (  # noqa: E402
    OrganizationUnit,
    StudentFieldDefinition,
    StudentRecord,
)

PREFIX = 'PERF25-'
ROWS = 10000


def ensure_account():
    account = Account.objects.filter(login_name='PERF25_SYS').first()
    if account is None:
        account = Account.objects.create_user(
            'PERF25_SYS', 'Perf25#Temp', display_name='性能账号',
            person_type='admin')
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        core_services.ensure_role_groups()
        core_services.grant_role(account, RoleCode.SYSTEM_ADMIN,
                                 granted_by='s25_perf')
    return Account.objects.get(pk=account.pk)


def baseline(account):
    queryset = export._scoped_students(account)  # 已 patch 为仅本次合成数据
    rows = list(queryset)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(['student_no', 'name', 'unit', 'status'])
    for record in rows:
        services.filtered_extra(record, account)  # N+1：每行查字段定义
        writer.writerow([record.student_no, record.name,
                         record.unit.code if record.unit else '',
                         record.status])
    return buffer.getvalue()


def optimized(account):
    return ''.join(export.iter_students_csv(account, chunk_size=2000))


def measure(fn, account):
    tracemalloc.start()
    started = time.perf_counter()
    text = fn(account)
    seconds = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {'seconds': round(seconds, 3), 'peak_bytes': peak,
            'bytes': len(text), 'rows': text.count('\n')}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--keep', action='store_true')
    args = ap.parse_args()

    unit, _ = OrganizationUnit.objects.get_or_create(
        code='PERF25', defaults={'name': '性能学院', 'unit_type': 'college'})
    StudentFieldDefinition.objects.get_or_create(
        code='phone', defaults={
            'label': '手机号', 'is_sensitive': True,
            'visible_roles': ['system_admin']})
    account = ensure_account()

    StudentRecord.objects.filter(student_no__startswith=PREFIX).delete()
    StudentRecord.objects.bulk_create([
        StudentRecord(
            student_no='{}{:05d}'.format(PREFIX, index),
            name='学生{:05d}'.format(index), unit=unit,
            extra={'phone': '139{:08d}'.format(index)})
        for index in range(ROWS)
    ], batch_size=2000)

    # 只导出本次合成数据，避免演练库中既有行影响可比性
    from smass_organization import export as export_module
    original = export_module._scoped_students

    def _only_perf(account, *, unit_code=None, keyword=None):
        return original(account, unit_code=unit_code).filter(
            student_no__startswith=PREFIX)

    export_module._scoped_students = _only_perf
    try:
        base = measure(baseline, account)
        opt = measure(optimized, account)
        connection.queries_log.clear()
        with CaptureQueriesContext(connection) as captured:
            for _chunk in export.iter_students_csv(account, chunk_size=2000):
                pass
        queries = len(captured.captured_queries)
        if queries == 0:
            raise SystemExit('查询捕获为空：性能报告不具备查询预算证据')
    finally:
        export_module._scoped_students = original

    report = {
        'rows': ROWS,
        'baseline': base,
        'optimized': opt,
        'speedup': round(base['seconds'] / opt['seconds'], 2)
        if opt['seconds'] else None,
        'memory_ratio': round(base['peak_bytes'] / opt['peak_bytes'], 2)
        if opt['peak_bytes'] else None,
        'optimized_query_count': queries,
        'note': 'baseline 复现旧实现的逐行 filtered_extra（N+1）；'
                'optimized 为 iterator 分批 + 一次字段权限计算',
    }

    if not args.keep:
        StudentRecord.objects.filter(student_no__startswith=PREFIX).delete()
        unit.delete()

    out = Path(os.environ.get('TEMP', '.')) / 's25_csv_perf.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    report['manifest_path'] = str(out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

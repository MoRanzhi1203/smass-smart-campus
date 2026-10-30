#!/usr/bin/env python
"""S23 容量基线与限流压测（进程内，隔离库 ``smass_s23_bench``）。

用法::

    python scripts/s23_capacity_benchmark.py
    python scripts/s23_capacity_benchmark.py --keep
    python scripts/s23_capacity_benchmark.py --json out.json
    python scripts/s23_capacity_benchmark.py --self-test

说明
----
- 用 ``django.test.Client`` 在**当前进程**内驱动真实视图与数据库，得到的是
  "单进程、无网络" 的相对基线；绝对吞吐需在生产同等机器上用 locust/wrk 复测；
- 每个线程使用独立 ``Client``，结束 ``close_old_connections()``；
- 同时验证 S15 限流是否真实触发 429（容量保护有效）；
- 库名必须以 ``smass_s23_`` 开头，结束默认删除。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT.parent / '.local' / 'evidence' / 's23'
BENCH_DB = 'smass_s23_bench'
PASSWORD = 'S23Bench#2026'
ADMIN = 's23bench_admin'


def ensure_prefix(name):
    if not str(name).startswith('smass_s23_'):
        raise SystemExit('拒绝操作非压测库：{!r}（只允许 smass_s23_*）'.format(name))


def db_config():
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_s23')
    import django  # noqa: PLC0415
    django.setup()
    from django.conf import settings  # noqa: PLC0415
    return dict(settings.DATABASES['default'])


def exec_sql(cfg, sql):
    import pymysql  # noqa: PLC0415
    connection = pymysql.connect(
        host=str(cfg['HOST'] or '127.0.0.1'), port=int(cfg['PORT'] or 3306),
        user=str(cfg['USER']), password=str(cfg['PASSWORD']), charset='utf8mb4',
        autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
    finally:
        connection.close()


def migrate():
    completed = subprocess.run(  # noqa: S603 - 固定参数
        [sys.executable, 'manage.py', 'migrate', '--noinput',
         '--settings=smass.settings_s23'],
        cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    if completed.returncode != 0:
        raise SystemExit('migrate 失败：{}'.format(
            (completed.stderr or '').strip()[-1200:]))
    return True


def seed():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'smass.settings_s23'
    import django  # noqa: PLC0415
    django.setup()
    from r21_account import services as account_services  # noqa: PLC0415
    from r21_account.models import Account, RoleCode  # noqa: PLC0415
    from smass_organization.models import (  # noqa: PLC0415
        UNIT_TYPE_CLASS, UNIT_TYPE_COLLEGE, UNIT_TYPE_MAJOR,
        OrganizationUnit, StudentRecord,
    )

    Account.objects.filter(login_name=ADMIN).delete()
    StudentRecord.objects.all().delete()
    OrganizationUnit.objects.all().delete()

    college = OrganizationUnit.objects.create(
        code='S23-C', name='压测学院', unit_type=UNIT_TYPE_COLLEGE)
    major = OrganizationUnit.objects.create(
        code='S23-M', name='压测专业', unit_type=UNIT_TYPE_MAJOR, parent=college)
    klass = OrganizationUnit.objects.create(
        code='S23-K', name='压测班级', unit_type=UNIT_TYPE_CLASS, parent=major)
    for index in range(50):
        StudentRecord.objects.create(
            student_no='S23{:03d}'.format(index), name='压测学生{:02d}'.format(index),
            unit=klass, extra={'phone': '1390000{:04d}'.format(index)})

    account = Account.objects.create_user(
        ADMIN, PASSWORD, display_name='压测管理员', person_type='admin')
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    account_services.grant_role(account, RoleCode.SYSTEM_ADMIN, granted_by='bench')
    return {'students': StudentRecord.objects.count(), 'admin': ADMIN}


def _percentile(values, ratio):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return ordered[index]


def bench(name, path, *, method='get', data=None, total=100, concurrency=4,
          login=None):
    from django.db import close_old_connections  # noqa: PLC0415
    from django.test import Client  # noqa: PLC0415

    per_thread = max(1, total // concurrency)
    latencies = []
    statuses = []

    def worker():
        client = Client()
        if login:
            client.post('/r21/login/', login)
        local = []
        local_status = []
        try:
            for _ in range(per_thread):
                started = time.perf_counter()
                if method == 'post':
                    response = client.post(path, data or {})
                else:
                    response = client.get(path)
                local.append(time.perf_counter() - started)
                local_status.append(response.status_code)
        finally:
            close_old_connections()
        latencies.extend(local)
        statuses.extend(local_status)

    tracemalloc.start()
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _index: worker(), range(concurrency)))
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    count = len(latencies)
    errors = sum(1 for status in statuses if status >= 400)
    return {
        'name': name, 'path': path, 'method': method.upper(),
        'requests': count, 'concurrency': concurrency,
        'elapsed_seconds': round(elapsed, 3),
        'throughput_rps': round(count / elapsed, 2) if elapsed > 0 else 0,
        'latency_ms': {
            'min': round(min(latencies) * 1000, 2) if latencies else 0,
            'p50': round(_percentile(latencies, 0.50) * 1000, 2),
            'p95': round(_percentile(latencies, 0.95) * 1000, 2),
            'p99': round(_percentile(latencies, 0.99) * 1000, 2),
            'max': round(max(latencies) * 1000, 2) if latencies else 0,
        },
        'peak_memory_mb': round(peak / 1024 / 1024, 2),
        'status_summary': {str(code): statuses.count(code)
                           for code in sorted(set(statuses))},
        'errors': errors,
    }


def rate_limit_probe():
    """验证 S15 限流真实生效：连续请求直到出现 429。"""
    from django.test import Client  # noqa: PLC0415
    os.environ['DJANGO_SETTINGS_MODULE'] = 'smass.settings_s23'
    import django  # noqa: PLC0415
    django.setup()
    from smass_api_security import services  # noqa: PLC0415

    admin = services  # 占位，避免未使用导入告警
    from r21_account.models import Account  # noqa: PLC0415
    account = Account.objects.get(login_name=ADMIN)
    client_obj = services.create_client(account, '压测客户端')
    raw, _token = services.issue_token(client_obj, [], ttl_seconds=3600)

    statuses = []
    client = Client()
    for index in range(15):
        response = client.get(
            '/s15/api/v1/ping',
            HTTP_AUTHORIZATION='Bearer {}'.format(raw),
            HTTP_X_TIMESTAMP=str(int(time.time())),
            HTTP_X_NONCE='bench-{}'.format(index))
        statuses.append(response.status_code)
    triggered = 429 in statuses
    return {'statuses': statuses, 'rate_limited': triggered,
            'first_429_at': statuses.index(429) + 1 if triggered else None}


def benchmark(keep=False):
    ensure_prefix(BENCH_DB)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    cfg = db_config()
    report = {'started_utc': datetime.now(dt_timezone.utc).isoformat(),
              'db': BENCH_DB, 'python': sys.version.split()[0]}

    exec_sql(cfg, 'DROP DATABASE IF EXISTS `{}`'.format(BENCH_DB))
    exec_sql(cfg, 'CREATE DATABASE `{}` CHARACTER SET utf8mb4'.format(BENCH_DB))
    report['migrate'] = migrate()
    report['seed'] = seed()
    login_data = {'login_name': ADMIN, 'password': PASSWORD}

    scenarios = [
        bench('anonymous_login_page', '/r21/login/', total=120, concurrency=6),
        bench('login_submit', '/r21/login/', method='post', data=login_data,
              total=40, concurrency=4),
        bench('admin_home', '/r21/home/', total=80, concurrency=4, login=login_data),
        bench('a11y_report', '/s19/', total=40, concurrency=4, login=login_data),
    ]
    report['scenarios'] = scenarios
    report['rate_limit'] = rate_limit_probe()

    finished = datetime.now(dt_timezone.utc)
    started_at = datetime.fromisoformat(report['started_utc'])
    report['total_seconds'] = round((finished - started_at).total_seconds(), 2)
    report['finished_utc'] = finished.isoformat()

    ok = report['rate_limit']['rate_limited'] and all(
        item['errors'] == 0 for item in scenarios)
    report['ok'] = ok

    if not keep:
        exec_sql(cfg, 'DROP DATABASE IF EXISTS `{}`'.format(BENCH_DB))
    return report


def self_test():
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(ensure_prefix('smass_s23_bench') is None, '合法库名通过')
    for name in ('smass', 'smass_r22_account'):
        try:
            ensure_prefix(name)
            failures.append('库名必须被拒绝：{}'.format(name))
        except SystemExit:
            pass
    values = [0.01, 0.02, 0.03, 0.04]
    check(abs(_percentile(values, 0.5) - 0.02) <= 0.011, 'P50 计算合理')
    check(_percentile(values, 0.99) == 0.04, 'P99 取最大值')
    check(_percentile([], 0.5) == 0.0, '空样本返回 0')

    for message in failures:
        print('SELF-TEST FAIL:', message)
    if not failures:
        print('SELF-TEST PASS (6 checks)')
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description='S23 容量基线与限流压测')
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    report = benchmark(keep=args.keep)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    path = Path(args.json_path) if args.json_path else EVIDENCE / 's23_benchmark.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')

    for item in report['scenarios']:
        print('{:<22} rps={:>7} p50={:>7}ms p95={:>7}ms p99={:>7}ms peak={}MB err={}'.format(
            item['name'], item['throughput_rps'], item['latency_ms']['p50'],
            item['latency_ms']['p95'], item['latency_ms']['p99'],
            item['peak_memory_mb'], item['errors']))
    print('限流触发：{}（首次 429 在第 {} 次）'.format(
        report['rate_limit']['rate_limited'],
        report['rate_limit']['first_429_at']))
    print('总耗时 {:.2f}s'.format(report['total_seconds']))
    print('RESULT:', 'PASS' if report['ok'] else 'FAIL')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

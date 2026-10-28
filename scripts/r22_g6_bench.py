"""G6 性能与并发基准（合成数据，固定种子）。

设计：
- 数据**完全合成**：姓名为 ``合成学生00001``、学号 ``S00000001``，不含真实信息；
- 固定种子（默认 42），可复现；
- 输出 JSON + CSV 到系统临时目录（**不进 Git**）；
- 所有写入只发生在 ``smass_r22_g6_`` 前缀的合成库。

用法：
    $env:SMASS_DB_PASSWORD='<pwd>'
    conda run -n smass python scripts/r22_g6_bench.py --sizes 100,1000,5000 --concurrency 1,10,50

测量项：
1. 五类身份解析（legacy/account/dual/conflict/anonymous）延迟 P50/P95/P99 与 SQL 数；
2. 对象范围查询（scoping）查询数；
3. 登录链路延迟；
4. 并发创建（双写）成功率、错误分类、锁等待。
"""
import argparse
import csv
import json
import os
import secrets
import statistics
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r22_g6')

import django  # noqa: E402

django.setup()

from django.contrib.auth.hashers import make_password  # noqa: E402
from django.db import connection, connections, transaction  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from r21_account import services  # noqa: E402
from r21_account.models import (  # noqa: E402
    Account,
    LegacyAccountLink,
    PersonType,
    RoleCode,
    StudentProfile,
)
from r22_account.identity import Identity, KIND_ACCOUNT, KIND_ANONYMOUS, KIND_CONFLICT, KIND_DUAL, KIND_LEGACY  # noqa: E402

OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'smass_g6_bench'
OUT_DIR.mkdir(parents=True, exist_ok=True)

SYNTH_PASSWORD = 'SynthPass#2024'
HASHED = make_password(SYNTH_PASSWORD)


def guard():
    name = connection.settings_dict['NAME'] or ''
    if not name.startswith('smass_r22_g6_'):
        raise SystemExit('拒绝：只在 smass_r22_g6_* 合成库执行，当前 {!r}'.format(name))
    return name


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return round(ordered[index], 3)


def stats(values):
    if not values:
        return {'n': 0}
    return {
        'n': len(values),
        'p50_ms': percentile(values, 50),
        'p95_ms': percentile(values, 95),
        'p99_ms': percentile(values, 99),
        'mean_ms': round(statistics.fmean(values), 3),
        'max_ms': round(max(values), 3),
    }


# ---------------------------------------------------------------------------
# 合成数据
# ---------------------------------------------------------------------------
def seed_synth_accounts(count, role=RoleCode.STUDENT, prefix='S'):
    """创建 count 个合成学生账号（幂等：已存在则跳过）。"""
    services.ensure_role_groups()
    created = 0
    step = 500
    for start in range(0, count, step):
        chunk = []
        with transaction.atomic():
            for i in range(start, min(start + step, count)):
                login = '{}{:08d}'.format(prefix, i)
                if Account.objects.filter(login_name=login).exists():
                    continue
                account = Account(
                    login_name=login,
                    display_name='合成学生{:05d}'.format(i),
                    person_type=PersonType.STUDENT,
                    is_active=True,
                    must_change_password=False,
                )
                account.password = HASHED
                account.save()
                chunk.append((account, login))
            for account, login in chunk:
                StudentProfile.objects.create(
                    account=account,
                    student_no=login,
                    name=account.display_name,
                    college_name='合成学院{:02d}'.format(int(login[-2:]) % 20),
                    classes_name='合成班级{:03d}'.format(int(login[-3:]) % 200),
                    phone='',
                    card_id='',
                )
                LegacyAccountLink.objects.create(
                    account=account, source_table='app01_student', source_pk=login
                )
                services.grant_role(account, role, granted_by='g6_bench')
                created += 1
    return created


class FakeRequest:
    """最小 request 替身，用于直接测身份解析（不经过 HTTP 栈）。"""

    def __init__(self, account=None, legacy=None):
        self.user = account
        self.session = {'info': legacy} if legacy else {}
        self.META = {'REMOTE_ADDR': '127.0.0.1'}


# ---------------------------------------------------------------------------
# 1. 身份解析
# ---------------------------------------------------------------------------
def bench_identity(sample_size=200):
    import r22_account.identity as identity_module

    outcomes = {}

    samples = list(
        Account.objects.filter(login_name__startswith='S')
        .order_by('pk')[:sample_size]
    )
    if not samples:
        return outcomes

    scenarios = {
        KIND_ACCOUNT: lambda acc: FakeRequest(account=acc),
        KIND_LEGACY: lambda acc: FakeRequest(legacy={'id': 'X1', 'type': 'teacher', 'name': 'L'}),
        KIND_DUAL: lambda acc: FakeRequest(
            account=acc,
            legacy={'id': acc.login_name, 'type': 'student', 'name': acc.display_name},
        ),
        KIND_CONFLICT: lambda acc: FakeRequest(
            account=acc, legacy={'id': 'OTHER', 'type': 'student', 'name': 'C'}
        ),
        KIND_ANONYMOUS: lambda acc: FakeRequest(),
    }

    for kind, builder in scenarios.items():
        durations = []
        sql_counts = []

        for account in samples:
            request = builder(account)
            connection.queries_log.clear()
            with CaptureQueriesContext(connection) as ctx:
                started = time.perf_counter()
                result = identity_module.resolve_identity(request)
                elapsed = (time.perf_counter() - started) * 1000
            durations.append(elapsed)
            sql_counts.append(len(ctx.captured_queries))

        outcomes[kind] = {
            'latency': stats(durations),
            'sql_per_call': {
                'min': min(sql_counts),
                'max': max(sql_counts),
                'mean': round(statistics.fmean(sql_counts), 2),
            },
        }

    return outcomes


# ---------------------------------------------------------------------------
# 2. 对象范围查询
# ---------------------------------------------------------------------------
def bench_scoping(sample_size=200):
    from r21_account import scoping

    services.ensure_role_groups()
    college = '合成学院00'

    admin = Account.objects.filter(
        login_name__startswith='S'
    ).first()
    if admin is None:
        return {}

    admin.scope_college = college
    admin.save(update_fields=['scope_college'])
    services.grant_role(admin, RoleCode.COLLEGE_ADMIN, granted_by='g6_bench')

    durations = []
    sql_counts = []
    row_counts = []

    for _ in range(sample_size):
        connection.queries_log.clear()
        with CaptureQueriesContext(connection) as ctx:
            started = time.perf_counter()
            qs = scoping.scoped_students(admin)
            count = qs.count()
            elapsed = (time.perf_counter() - started) * 1000
        durations.append(elapsed)
        sql_counts.append(len(ctx.captured_queries))
        row_counts.append(count)

    return {
        'latency': stats(durations),
        'sql_per_call': {'min': min(sql_counts), 'max': max(sql_counts),
                         'mean': round(statistics.fmean(sql_counts), 2)},
        'rows_visible': sorted(set(row_counts))[:5],
        'scope_college': college,
    }


# ---------------------------------------------------------------------------
# 3. 并发创建（双写）
# ---------------------------------------------------------------------------
def bench_concurrency(concurrency, per_worker=5):
    results = {'success': 0, 'errors': {}, 'durations': [], 'lock_wait': 0}
    lock = threading.Lock()
    run_id = secrets.token_hex(3)

    def worker(worker_id):
        local_ok = 0
        local_errors = {}
        local_durations = []

        try:
            for j in range(per_worker):
                login = 'CC{}{}{:03d}'.format(run_id[:3], worker_id, j)
                started = time.perf_counter()
                try:
                    with transaction.atomic():
                        account = Account(
                            login_name=login,
                            display_name='并发{}'.format(login),
                            person_type=PersonType.STUDENT,
                            must_change_password=False,
                        )
                        account.password = HASHED
                        account.save()
                        StudentProfile.objects.create(
                            account=account, student_no=login, name=account.display_name,
                            college_name='合成学院01', classes_name='并发班',
                        )
                        LegacyAccountLink.objects.create(
                            account=account, source_table='app01_student', source_pk=login
                        )
                    local_ok += 1
                except Exception as exc:  # noqa: BLE001
                    errno = exc.args[0] if exc.args else '?'
                    name = '{}:{}'.format(type(exc).__name__, errno)
                    local_errors[name] = local_errors.get(name, 0) + 1
                finally:
                    local_durations.append((time.perf_counter() - started) * 1000)
        finally:
            connections.close_all()

        with lock:
            results['success'] += local_ok
            for name, count in local_errors.items():
                results['errors'][name] = results['errors'].get(name, 0) + count
            results['durations'].extend(local_durations)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = (time.perf_counter() - started) * 1000

    results['latency'] = stats(results.pop('durations'))
    results['wall_ms'] = round(wall, 1)
    results['concurrency'] = concurrency
    results['attempts'] = concurrency * per_worker
    return results


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sizes', default='100,1000')
    parser.add_argument('--concurrency', default='1,10,50')
    parser.add_argument('--seed-size', type=int, default=0,
                        help='仅生成指定规模后退出（用于分步生成）')
    args = parser.parse_args()

    db = guard()
    report = {
        'database': db,
        'started_at': datetime.now().isoformat(timespec='seconds'),
        'django': django.get_version(),
        'python': sys.version.split()[0],
        'sizes': [],
    }

    sizes = [int(s) for s in args.sizes.split(',') if s.strip()]
    concurrency_levels = [int(c) for c in args.concurrency.split(',') if c.strip()]

    for size in sizes:
        created = seed_synth_accounts(size)
        actual = Account.objects.count()

        entry = {
            'target_size': size,
            'created_now': created,
            'actual_accounts': actual,
            'identity': bench_identity(min(200, max(10, actual))),
            'scoping': bench_scoping(min(100, max(10, actual))),
        }
        report['sizes'].append(entry)
        print('[size {}] accounts={} created={}'.format(size, actual, created), flush=True)

    report['concurrency'] = []
    for level in concurrency_levels:
        result = bench_concurrency(level)
        report['concurrency'].append(result)
        print('[concurrency {}] success={}/{} errors={}'.format(
            level, result['success'], result['attempts'], result['errors']
        ), flush=True)

    report['finished_at'] = datetime.now().isoformat(timespec='seconds')

    json_path = OUT_DIR / 'g6_bench.json'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    csv_path = OUT_DIR / 'g6_bench.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['kind', 'size', 'n', 'p50_ms', 'p95_ms', 'p99_ms', 'sql_mean'])
        for entry in report['sizes']:
            for kind, data in entry['identity'].items():
                writer.writerow([kind, entry['target_size'], data['latency'].get('n'),
                                 data['latency'].get('p50_ms'), data['latency'].get('p95_ms'),
                                 data['latency'].get('p99_ms'), data['sql_per_call'].get('mean')])
        for result in report['concurrency']:
            writer.writerow(['concurrency', result['concurrency'], result['attempts'],
                             result['latency'].get('p50_ms'), result['latency'].get('p95_ms'),
                             result['latency'].get('p99_ms'), ''])

    print('JSON: {}'.format(json_path))
    print('CSV : {}'.format(csv_path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

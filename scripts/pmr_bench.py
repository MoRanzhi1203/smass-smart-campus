"""PM6/PM7：多规模性能、锁测量与多进程并发。

设计原则
--------
- **只记录实测值**，不编造 SLA 阈值。
- 明确记录主机资源（CPU/内存）与 MySQL 版本，让数字可解读。
- 锁与连接指标从 `performance_schema` / `SHOW GLOBAL STATUS` 读，
  不是估算。

用法：
    $env:SMASS_DB_PASSWORD='<root>'
    conda run -n smass python scripts/pmr_bench.py --db smass_pmr_target_1k
    conda run -n smass python scripts/pmr_bench.py --db smass_pmr_target_1k --workers 8
"""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pymysql

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
PYTHON = sys.executable
OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'pmr_bench'


def conn(db=None):
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8mb4', autocommit=True)


def scalar(cur, sql, args=None):
    cur.execute(sql, args or [])
    row = cur.fetchone()
    return row[0] if row else None


def show_value(cur, sql):
    """SHOW VARIABLES/STATUS LIKE 返回 (Variable_name, Value)，取 Value。"""
    cur.execute(sql)
    row = cur.fetchone()
    return row[1] if row else None


def host_profile():
    cpu_count = os.cpu_count() or 0
    mem = None
    try:
        mem = subprocess.run(
            ['wmic', 'ComputerSystem', 'get', 'TotalPhysicalMemory'],
            capture_output=True, text=True, timeout=20)
        lines = [line.strip() for line in mem.stdout.splitlines() if line.strip().isdigit()]
        mem = int(lines[0]) // (1024 ** 3) if lines else None
    except Exception:  # noqa: BLE001
        mem = None

    return {
        'platform': platform.platform(),
        'python': platform.python_version(),
        'cpu_count': cpu_count,
        'ram_gb': mem,
    }


def mysql_profile():
    c = conn()
    try:
        with c.cursor() as cur:
            return {
                'version': scalar(cur, 'SELECT VERSION()'),
                'max_connections': show_value(cur, "SHOW VARIABLES LIKE 'max_connections'"),
                'innodb_buffer_pool_mb': int(
                    show_value(cur, "SHOW VARIABLES LIKE 'innodb_buffer_pool_size'") or 0) // (1024 ** 2),
                'isolation': scalar(cur, 'SELECT @@transaction_isolation'),
                'sql_mode': (scalar(cur, 'SELECT @@sql_mode') or '')[:80],
            }
    finally:
        c.close()


def db_stats():
    """瞬时连接/锁/死锁指标。"""
    c = conn()
    try:
        with c.cursor() as cur:
            stats = {
                'threads_connected': int(show_value(cur, "SHOW STATUS LIKE 'Threads_connected'") or 0),
                'threads_running': int(show_value(cur, "SHOW STATUS LIKE 'Threads_running'") or 0),
                'innodb_row_lock_waits': int(show_value(
                    cur, "SHOW STATUS LIKE 'Innodb_row_lock_waits'") or 0),
                'innodb_row_lock_time_avg': int(show_value(
                    cur, "SHOW STATUS LIKE 'Innodb_row_lock_time_avg'") or 0),
                'innodb_deadlocks': int(show_value(
                    cur, "SHOW STATUS LIKE 'Innodb_deadlocks'") or 0),
                'slow_queries': int(show_value(
                    cur, "SHOW STATUS LIKE 'Slow_queries'") or 0),
            }

            # 当前锁等待（performance_schema）
            try:
                cur.execute(
                    'SELECT COUNT(*) FROM performance_schema.data_lock_waits')
                stats['current_lock_waits'] = cur.fetchone()[0]
            except Exception:  # noqa: BLE001
                stats['current_lock_waits'] = None

            # 活跃事务
            try:
                cur.execute(
                    'SELECT COUNT(*) FROM information_schema.INNODB_TRX')
                stats['active_trx'] = cur.fetchone()[0]
            except Exception:  # noqa: BLE001
                stats['active_trx'] = None
    finally:
        c.close()
    return stats


def percentiles(samples):
    if not samples:
        return {'count': 0}
    ordered = sorted(samples)
    return {
        'count': len(ordered),
        'min_ms': round(ordered[0] * 1000, 2),
        'p50_ms': round(statistics.median(ordered) * 1000, 2),
        'p95_ms': round(ordered[int(len(ordered) * 0.95) - 1] * 1000, 2),
        'p99_ms': round(ordered[int(len(ordered) * 0.99) - 1] * 1000, 2),
        'max_ms': round(ordered[-1] * 1000, 2),
        'mean_ms': round(statistics.mean(ordered) * 1000, 2),
    }


def bench_query(db, label, fn, iterations=30, warmup=3):
    os.environ['PMR_DB'] = db
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')
    import django
    django.setup()

    samples = []
    errors = []
    for i in range(warmup + iterations):
        started = time.perf_counter()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            errors.append('{}: {}'.format(type(exc).__name__, str(exc)[:80]))
            continue
        elapsed = time.perf_counter() - started
        if i >= warmup:
            samples.append(elapsed)

    result = percentiles(samples)
    result['label'] = label
    if errors:
        result['errors'] = errors[:3]
    return result


def run_query_benches(db, iterations):
    os.environ['PMR_DB'] = db
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')
    import django
    django.setup()

    from r21_account.models import Account
    from smass_organization import services as org_services
    from smass_organization import export as org_export

    sys_account = (Account.objects.filter(login_name__startswith='pmr-')
                   .order_by('id').first())
    if sys_account is None:
        # 没有迁移行时，退化为"直接查 StudentRecord 全表"
        from smass_organization.models import StudentRecord
        return {
            'note': '目标库无 pmr- 账号，退化为直接表查询',
            'student_count': StudentRecord.objects.count(),
            'benches': [
                bench_query(db, 'student_count_all',
                            lambda: StudentRecord.objects.count(), iterations),
                bench_query(db, 'student_page_50',
                            lambda: list(StudentRecord.objects.all()[:50]), iterations),
            ],
        }

    from smass_analytics import services as analytics_services

    # 必须用**内置**指标（有计算实现），不能自造 code
    metric, _ = analytics_services.MetricDefinition.objects.get_or_create(
        code='students_scoped',
        defaults={'name': '可见学生（基准）', 'data_source': 'student'})
    if not metric.is_enabled:
        analytics_services.validate_metric(metric)

    def scoped():
        return org_services.scoped_students(sys_account).count()

    def csv_export():
        chunks = []
        for chunk in org_export.export_students_csv(sys_account):
            chunks.append(chunk)
        return chunks

    def metric_compute():
        return analytics_services.compute_metric(metric, sys_account)

    benches = [
        bench_query(db, 'scoped_students_count', scoped, iterations),
        bench_query(db, 'students_csv_export', csv_export, max(5, iterations // 3)),
        bench_query(db, 'r7_metric_compute', metric_compute, max(5, iterations // 3)),
    ]

    return {
        'account': sys_account.login_name,
        'scoped_count': scoped(),
        'benches': benches,
    }


# ---------------------------------------------------------------------------
# 多进程并发（PM7）
# ---------------------------------------------------------------------------
def worker_grant(args):
    """在独立进程中并发授予角色。"""
    db, index, barrier_at = args
    os.environ['PMR_DB'] = db
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')
    import django
    django.setup()

    from django.db import connection
    from r21_account import services as core_services
    from r21_account.models import Account, AccountRole, RoleCode
    from django.db.utils import IntegrityError

    target = Account.objects.filter(login_name__startswith='pmr-').order_by('id').first()
    if target is None:
        return {'index': index, 'outcome': 'no_target'}

    # 用时间对齐降低调度抖动（不保证严格同时，但足够产生竞争）
    wait = barrier_at - time.time()
    if wait > 0:
        time.sleep(wait)

    try:
        core_services.grant_role(
            Account.objects.get(pk=target.pk), RoleCode.TEACHER,
            granted_by='pmr-mp-{}'.format(index))
        outcome = 'ok'
    except IntegrityError:
        outcome = 'duplicate'
    except Exception as exc:  # noqa: BLE001
        outcome = type(exc).__name__
    finally:
        connection.close()

    return {'index': index, 'outcome': outcome, 'pid': os.getpid()}


def worker_create_task(args):
    """在独立进程中并发创建 open 审批任务。"""
    db, index, barrier_at = args
    os.environ['PMR_DB'] = db
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')
    import django
    django.setup()

    from django.db import connection
    from django.db.utils import IntegrityError
    from smass_workflow import services as workflow_services
    from smass_workflow.models import ApprovalTask, WorkflowInstance

    try:
        definition = workflow_services.create_definition(
            'PMRMP{}'.format(index % 3), '多进程基准')
        version = workflow_services.create_draft_version(definition)
        workflow_services.add_node(version, 'start', '发起', 'start')
        workflow_services.add_node(version, 'approve', '审批', 'approval')
        workflow_services.add_node(version, 'end', '完成', 'end')
        workflow_services.add_transition(version, 'start', 'approve', 'submit')
        workflow_services.add_transition(version, 'approve', 'end', 'approve')
        workflow_services.publish_version(version)
        instance = workflow_services.start_instance(
            version, subject_type='mp', subject_id='MP-{}'.format(index),
            created_by='pmr-mp')
    except Exception as exc:  # noqa: BLE001
        connection.close()
        return {'index': index, 'outcome': 'setup_failed',
                'error': type(exc).__name__}

    wait = barrier_at - time.time()
    if wait > 0:
        time.sleep(wait)

    node = version.nodes.get(code='approve')
    try:
        ApprovalTask.objects.create(
            instance=WorkflowInstance.objects.get(pk=instance.pk),
            node=node, status='open', assignee='mp-{}'.format(index))
        outcome = 'ok'
    except IntegrityError:
        outcome = 'duplicate'
    except Exception as exc:  # noqa: BLE001
        outcome = type(exc).__name__
    finally:
        connection.close()

    return {'index': index, 'outcome': outcome, 'instance_pk': instance.pk,
            'pid': os.getpid()}


def run_multiprocess(db, workers):
    """用 ProcessPoolExecutor 起真实多进程。"""
    before = db_stats()

    barrier_at = time.time() + 3.0
    grant_args = [(db, i, barrier_at) for i in range(workers)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        grant_results = list(pool.map(worker_grant, grant_args))

    # 校验最终不变量
    os.environ['PMR_DB'] = db
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')
    import django
    django.setup()
    from r21_account.models import Account, AccountRole, RoleCode

    target = Account.objects.filter(login_name__startswith='pmr-').order_by('id').first()
    active = 0
    if target is not None:
        active = AccountRole.objects.filter(
            account=target, role=RoleCode.TEACHER,
            revoked_at__isnull=True).count()

    # 并发创建 open 任务
    barrier_at2 = time.time() + 3.0
    task_args = [(db, i, barrier_at2) for i in range(workers)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        task_results = list(pool.map(worker_create_task, task_args))

    open_counts = {}
    for item in task_results:
        pk = item.get('instance_pk')
        if pk is None:
            continue
        open_counts[pk] = open_counts.get(pk, 0) + 1

    after = db_stats()

    pids = {item.get('pid') for item in grant_results + task_results if item.get('pid')}

    return {
        'workers': workers,
        'distinct_pids': len(pids),
        'role_grant': {
            'outcomes': [item['outcome'] for item in grant_results],
            'active_account_roles': active,
            'invariant_ok': active <= 1,
        },
        'open_task': {
            'outcomes': [item['outcome'] for item in task_results],
            'instances_touched': len(open_counts),
        },
        'stats_before': before,
        'stats_after': after,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='smass_pmr_target_1k')
    parser.add_argument('--iterations', type=int, default=30)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--skip-multiprocess', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if not ADMIN_PASSWORD:
        raise SystemExit('需要 SMASS_DB_PASSWORD 环境变量')
    if not args.db.startswith('smass_pmr_'):
        raise SystemExit('拒绝：库名必须命中 smass_pmr_ 前缀')

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    report = {
        'database': args.db,
        'host': host_profile(),
        'mysql': mysql_profile(),
        'iterations': args.iterations,
        'steps': [],
    }

    # 表与行数
    c = conn(args.db)
    try:
        with c.cursor() as cur:
            report['table_count'] = scalar(
                cur, 'SELECT COUNT(*) FROM information_schema.TABLES '
                     'WHERE TABLE_SCHEMA=%s', [args.db])
            counts = {}
            for table in ('app01_student', 'app01_admin', 'app01_teacher',
                          'r21_account_account',
                          'smass_organization_studentrecord'):
                try:
                    counts[table] = scalar(
                        cur, 'SELECT COUNT(*) FROM `{}`'.format(table))
                except Exception:  # noqa: BLE001
                    counts[table] = None
            report['row_counts'] = counts
    finally:
        c.close()

    report['steps'].append({'step': 'profile', 'ok': True})

    # 查询基准
    report['query_benches'] = run_query_benches(args.db, args.iterations)
    report['steps'].append({'step': 'query_benches', 'ok': True})

    # 多进程并发
    if not args.skip_multiprocess:
        report['multiprocess'] = run_multiprocess(args.db, args.workers)
        mp = report['multiprocess']
        report['steps'].append({
            'step': 'multiprocess',
            'ok': (mp['distinct_pids'] >= 2
                   and mp['role_grant']['invariant_ok']),
        })

    report['ok'] = all(step.get('ok') for step in report['steps'])
    path = OUT_DIR / 'bench_{}_{}.json'.format(
        args.db.replace('smass_pmr_', ''), stamp)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    report['manifest_path'] = str(path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

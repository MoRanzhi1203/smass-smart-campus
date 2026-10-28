"""R2.2.1 工作流 A：并发容量边界测量（隔离合成库）。

目的：把"服务端连接上限"与"HTTP 并发"分开，测出可安全运行的区间。

约束：
- 只用 ``smass_r22_g6_`` 或 ``smass_r22_g221_`` 合成库；
- 不修改 MySQL 全局设置；
- 每档并发后立即回退，观察 `Threads_connected` 与错误类型；
- 任何持续错误/资源压力立即停止该档，记 BLOCKED 而非 PASS。

用法：
    conda run -n smass python scripts/r221_conn_capacity.py --levels 5,10,15,20,25
"""
import argparse
import json
import os
import secrets
import statistics
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r22_g6')

import django  # noqa: E402

django.setup()

from django.contrib.auth.hashers import make_password  # noqa: E402
from django.db import connection, connections, transaction  # noqa: E402

from r21_account.models import (  # noqa: E402
    Account,
    LegacyAccountLink,
    PersonType,
    StudentProfile,
)

OUT = Path(os.environ.get('TEMP', '.')) / 'smass_r221_capacity'
OUT.mkdir(parents=True, exist_ok=True)

HASHED = make_password('SynthCap#2024')


def guard():
    name = connection.settings_dict['NAME'] or ''
    if not (name.startswith('smass_r22_g6_') or name.startswith('smass_r22_g221_')):
        raise SystemExit('拒绝：只在合成库执行，当前 {!r}'.format(name))
    return name


def server_state():
    with connection.cursor() as cur:
        cur.execute("SHOW VARIABLES LIKE 'max_connections'")
        maxc = int(cur.fetchone()[1])
        cur.execute("SHOW STATUS LIKE 'Threads_connected'")
        threads = int(cur.fetchone()[1])
        cur.execute("SHOW STATUS LIKE 'Max_used_connections'")
        max_used = int(cur.fetchone()[1])
    return {'max_connections': maxc, 'threads_connected': threads,
            'max_used_connections': max_used}


def run_level(level, per_worker=3):
    run_id = secrets.token_hex(3)
    results = {'ok': 0, 'errors': {}}
    durations = []
    lock = threading.Lock()

    def worker(worker_id):
        local_ok = 0
        local_errors = {}
        local_durations = []
        try:
            for j in range(per_worker):
                login = 'CP{}{}{:02d}'.format(run_id, worker_id, j)
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
                            account=account, student_no='SP{}{}{:02d}'.format(run_id[:3], worker_id, j), name=account.display_name,
                            college_name='容量测试', classes_name='容量班',
                        )
                        LegacyAccountLink.objects.create(
                            account=account, source_table='app01_student', source_pk=login
                        )
                    local_ok += 1
                except Exception as exc:  # noqa: BLE001
                    errno = exc.args[0] if exc.args else '?'
                    key = '{}:{}'.format(type(exc).__name__, errno)
                    local_errors[key] = local_errors.get(key, 0) + 1
                finally:
                    local_durations.append((time.perf_counter() - started) * 1000)
        finally:
            connections.close_all()

        with lock:
            results['ok'] += local_ok
            for key, count in local_errors.items():
                results['errors'][key] = results['errors'].get(key, 0) + count
            durations.extend(local_durations)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(level)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = (time.perf_counter() - started) * 1000

    attempts = level * per_worker
    ordered = sorted(durations)
    return {
        'level': level,
        'attempts': attempts,
        'ok': results['ok'],
        'error_rate': round(1 - results['ok'] / attempts, 4) if attempts else 0,
        'errors': results['errors'],
        'wall_ms': round(wall, 1),
        'p50_ms': round(ordered[len(ordered) // 2], 1) if ordered else None,
        'p95_ms': round(ordered[int(len(ordered) * 0.95)] if ordered else 0, 1),
        'server_after': server_state(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--levels', default='5,10,15,20,25')
    parser.add_argument('--per-worker', type=int, default=3)
    args = parser.parse_args()

    db = guard()
    report = {
        'database': db,
        'started_at': datetime.now().isoformat(timespec='seconds'),
        'server_before': server_state(),
        'levels': [],
    }

    for level in [int(x) for x in args.levels.split(',') if x.strip()]:
        # 保守上限：超过 50 个 worker 视为可能饱和共享实例，不再加压
        if level > 50:
            report['levels'].append({'level': level, 'status': 'BLOCKED',
                                     'reason': 'exceeds conservative cap of 50 workers'})
            continue
        result = run_level(level, args.per_worker)
        report['levels'].append(result)
        print('[level {}] ok={}/{} err={}'.format(
            level, result['ok'], result['attempts'], result['errors']), flush=True)

    report['finished_at'] = datetime.now().isoformat(timespec='seconds')

    path = OUT / 'capacity.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['levels'], ensure_ascii=False, indent=2))
    print('evidence: {}'.format(path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

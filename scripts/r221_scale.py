"""R2.2.1 工作流 B：10,000 合成账号全流程（回填/幂等/一致性/回滚/二次回填）。

安全：
- 只在 ``smass_r22_g221_*`` 库执行；
- 全部数据合成（学号 ``S221xxxxx``、姓名 ``合成学生xxxxx``）；
- 不含任何来自 ``smass`` 的真实值；
- 输出 JSON 到临时目录，不进 Git。

用法：
    conda run -n smass python scripts/r221_scale.py --count 10000
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime
from io import StringIO
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r22_g221')

import django  # noqa: E402

django.setup()

from django.contrib.auth.hashers import make_password  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.db.models import Count  # noqa: E402

from app01 import models as legacy  # noqa: E402
from r21_account import services  # noqa: E402
from r21_account.models import (  # noqa: E402
    Account,
    AccountRole,
    LegacyAccountLink,
    StudentProfile,
)
from r22_account import batch_audit  # noqa: E402
from r22_account.models import AccountAuditEvent  # noqa: E402

OUT = Path(os.environ.get('TEMP', '.')) / 'smass_r221_scale'
OUT.mkdir(parents=True, exist_ok=True)

HASHED = make_password('SynthScale#2024')


def guard():
    name = connection.settings_dict['NAME'] or ''
    if not name.startswith('smass_r22_g221_'):
        raise SystemExit('拒绝：只在 smass_r22_g221_* 执行，当前 {!r}'.format(name))
    return name


def snapshot():
    return {
        'accounts': Account.objects.count(),
        'links': LegacyAccountLink.objects.count(),
        'roles': AccountRole.objects.filter(revoked_at__isnull=True).count(),
        'student_profiles': StudentProfile.objects.count(),
        'legacy_students': legacy.Student.objects.count(),
        'audit_events': AccountAuditEvent.objects.count(),
    }


def build_synthetic(count):
    """生成 count 个合成学生（幂等：已存在则跳过）。返回 (created, seconds)。"""
    started = time.perf_counter()

    with transaction.atomic():
        college, _ = legacy.College.objects.get_or_create(name='合成学院A')
        grade, _ = legacy.Grade.objects.get_or_create(name='2021级')
        major, _ = legacy.Major.objects.get_or_create(
            college=college, name='合成专业A'
        )

        existing_classes = {
            c.name: c for c in legacy.Classes.objects.filter(major=major)
        }
        classes_pool = []
        for index in range(20):
            name = '合成班{:03d}'.format(index)
            classes = existing_classes.get(name)
            if classes is None:
                classes = legacy.Classes.objects.create(
                    name=name, grade=grade, major=major
                )
            classes_pool.append(classes)

        existing = set(
            legacy.Student.objects.filter(id__startswith='S221').values_list('id', flat=True)
        )

        batch = []
        created = 0
        BATCH_SIZE = 1000

        for index in range(count):
            student_id = 'S221{:06d}'.format(index)
            if student_id in existing:
                continue

            batch.append(legacy.Student(
                id=student_id,
                name='合成学生{:06d}'.format(index),
                password=HASHED,
                pinyin='hcxs{:06d}'.format(index),
                sex=index % 2,
                nation=None,
                classes=classes_pool[index % len(classes_pool)],
                cardID='',
                phone=None,
                qq=None,
                address=None,
                building=None,
                dormitory=None,
                political=0,
            ))
            created += 1

            if len(batch) >= BATCH_SIZE:
                legacy.Student.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []

        if batch:
            legacy.Student.objects.bulk_create(batch, ignore_conflicts=True)

    return created, round(time.perf_counter() - started, 2)


def run_command(*args):
    out = StringIO()
    started = time.perf_counter()
    call_command(*args, stdout=out)
    return out.getvalue(), round(time.perf_counter() - started, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=10000)
    parser.add_argument('--skip-rollback', action='store_true')
    args = parser.parse_args()

    db = guard()
    report = {
        'database': db,
        'target_count': args.count,
        'started_at': datetime.now().isoformat(timespec='seconds'),
        'python': sys.version.split()[0],
        'django': django.get_version(),
    }

    # ---- 1. 生成 ----
    created, seed_seconds = build_synthetic(args.count)
    report['generate'] = {
        'created': created,
        'seconds': seed_seconds,
        'rows_now': legacy.Student.objects.count(),
    }

    # ---- 2. 回填（首次）----
    _started = time.perf_counter()
    batch_id_1, output, _outcome = batch_audit.run_backfill()
    backfill_seconds = round(time.perf_counter() - _started, 2)
    report['backfill'] = {
        'seconds': backfill_seconds,
        'summary': output.strip().splitlines()[-6:],
        'batch_id': batch_id_1,
        'snapshot': snapshot(),
    }

    # ---- 3. 幂等重跑 ----
    _started = time.perf_counter()
    batch_id_2, output2, _o2 = batch_audit.run_backfill()
    replay_seconds = round(time.perf_counter() - _started, 2)
    report['replay'] = {
        'seconds': replay_seconds,
        'created_line': [line for line in output2.splitlines() if 'created=' in line][:1],
        'batch_id': batch_id_2,
        'snapshot': snapshot(),
    }

    # ---- 4. 一致性（strict）----
    from io import StringIO as SIO
    json_out = SIO()
    call_command('verify_account_consistency', '--strict-count', '--json', stdout=json_out)
    consistency = json.loads(json_out.getvalue().strip().splitlines()[-1])
    report['consistency'] = {
        'ok': consistency['ok'],
        'codes': [issue['code'] for issue in consistency['issues']],
        'counts': consistency['counts'],
    }

    # ---- 5. 回滚 + 二次回填 ----
    if not args.skip_rollback:
        survivors = Account.objects.values_list('login_name', flat=True).count()

        before = snapshot()
        _started = time.perf_counter()
        rollback_batch, rollback_out, _o3 = batch_audit.run_rollback()
        rollback_seconds = round(time.perf_counter() - _started, 2)
        after = snapshot()

        _started = time.perf_counter()
        refill_batch, refill_out, _o4 = batch_audit.run_backfill()
        refill_seconds = round(time.perf_counter() - _started, 2)
        after_refill = snapshot()

        json_out2 = SIO()
        call_command('verify_account_consistency', '--strict-count', '--json', stdout=json_out2)
        consistency2 = json.loads(json_out2.getvalue().strip().splitlines()[-1])

        report['rollback'] = {
            'seconds': rollback_seconds,
            'before': before,
            'after': after,
            'accounts_removed': before['accounts'] - after['accounts'],
            'legacy_untouched': after['legacy_students'] == before['legacy_students'],
            'refill_seconds': refill_seconds,
            'after_refill': after_refill,
            'refill_consistency_ok': consistency2['ok'],
            'refill_codes': [i['code'] for i in consistency2['issues']],
        }

    # ---- 6. 批次审计链 ----
    chain = batch_audit.batch_chain()
    report['batch_audit'] = {
        'events': len(chain),
        'operations': [row[0] for row in chain],
        'latest_backfill': batch_audit.latest_backfill_batch_id(),
        'unbatched_flag': batch_audit.find_unbatched_backfill(window_minutes=120),
    }

    # ---- 7. 分组统计（脱敏）----
    report['distribution'] = {
        'roles_per_account': list(
            AccountRole.objects.filter(revoked_at__isnull=True)
            .values('role')
            .annotate(n=Count('id'))
            .order_by('role')
        ),
        'profiles_by_classes': StudentProfile.objects.values('classes_name')
        .annotate(n=Count('id'))
        .order_by('classes_name')[:5]
        .count(),
    }

    report['finished_at'] = datetime.now().isoformat(timespec='seconds')

    path = OUT / 'scale_{}.json'.format(args.count)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('evidence: {}'.format(path))

    ok = (
        report['generate']['rows_now'] >= args.count
        and report['consistency']['ok']
        and (args.skip_rollback or report['rollback']['refill_consistency_ok'])
    )
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

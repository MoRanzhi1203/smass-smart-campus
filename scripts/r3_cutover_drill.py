"""R3 P0：万级合成库上的 off -> dual -> off 切换演练（含切换期并发写入）。

R3 门禁要求：**不能以 100 账号演练替代万级切换**，且必须证明
"切换期间新写入不丢失"。

本脚本在 ``smass_r22_g221_scale``（10,000 合成账号）上执行：

1. 基线快照与校验和；
2. off -> dual 切换，并验证五类身份；
3. **切换期并发写入**（多线程：新建账号 / 改密 / 停用 / 授权），
   使用独立连接，并发度保守（默认 8，远低于服务端 20 连接上限）；
4. 故障注入（事务中途失败）；
5. dual -> off 回滚；
6. 逐条差异审计：切换期写入必须 100% 保留；
7. 一致性校验 + 批次审计链。

输出 JSON 到临时目录（不进 Git），控制台摘要。

用法：
    conda run -n smass python scripts/r3_cutover_drill.py --workers 8
"""
import argparse
import json
import os
import secrets
import sys
import threading
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
from django.db import connection, connections, transaction  # noqa: E402
from django.test import override_settings  # noqa: E402

from r21_account import dual_write, services  # noqa: E402
from r21_account.models import (  # noqa: E402
    Account,
    AccountRole,
    LegacyAccountLink,
    PersonType,
    RoleCode,
    StudentProfile,
)
from r22_account import batch_audit  # noqa: E402
from r22_account.identity import resolve_identity  # noqa: E402
from r22_account.models import AccountAuditEvent  # noqa: E402

OUT = Path(os.environ.get('TEMP', '.')) / 'smass_r3_drill'
OUT.mkdir(parents=True, exist_ok=True)

HASHED = make_password('SynthR3#2024')

MODE_OFF = {'identity_mode': 'off', 'route_policy_enabled': True,
            'audit_enabled': True, 'dry_run': False, 'legacy_bridge': True}
MODE_DUAL = {'identity_mode': 'dual', 'route_policy_enabled': True,
             'audit_enabled': True, 'dry_run': False, 'legacy_bridge': True}


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
        'audit_events': AccountAuditEvent.objects.count(),
    }


class FakeRequest:
    def __init__(self, account=None, legacy=None):
        self.user = account
        self.session = {'info': legacy} if legacy else {}
        self.META = {'REMOTE_ADDR': '127.0.0.1'}


def identity_kind(account=None, legacy=None):
    with override_settings(R22_FLAGS=MODE_DUAL):
        return resolve_identity(FakeRequest(account, legacy)).kind


# ---------------------------------------------------------------------------
# 切换期并发写入
# ---------------------------------------------------------------------------
def concurrent_writes(workers=8, per_worker=5):
    from app01 import models as legacy

    legacy_classes = list(legacy.Classes.objects.all()[:1])
    if not legacy_classes:
        raise SystemExit('前置失败：没有 app01.Classes，无法双写')

    """在 dual 模式下并发执行业务写入；返回成功/失败明细。"""
    run_id = secrets.token_hex(3)
    lock = threading.Lock()
    result = {'ok': 0, 'errors': {}, 'latencies': [], 'records': []}

    def worker(index):
        local_ok = 0
        local_errors = {}
        local_lat = []
        local_records = []

        try:
            with override_settings(R22_FLAGS=MODE_DUAL):
                for j in range(per_worker):
                    kind = j % 4
                    started = time.perf_counter()
                    try:
                        if kind == 0:
                            # 切换期必须**双写**：只写新表会导致新旧表分叉
                            student_id = 'R3{}{}{:02d}'.format(run_id[:2], index, j)
                            classes = legacy_classes[0]
                            dual_write.create_student(
                                student_id=student_id,
                                name='R3并发{}'.format(student_id),
                                classes=classes,
                                raw_password='R3Synth#2024',
                                card_id='',
                                phone='',
                                actor='r3_concurrent',
                            )
                            local_records.append(('created', student_id))

                        elif kind == 1:
                            target = Account.objects.filter(
                                login_name__startswith='S221'
                            ).order_by('pk').first()
                            if target:
                                # 两表同源改密（否则旧表哈希会落后）
                                dual_write.change_password(
                                    target.login_name, 'R3Changed#2024',
                                    actor='r3_concurrent',
                                )
                                local_records.append(('password', target.login_name))

                        elif kind == 2:
                            target = Account.objects.filter(
                                login_name__startswith='S221', is_active=True
                            ).order_by('-pk').first()
                            if target:
                                target.is_active = False
                                target.save(update_fields=['is_active'])
                                local_records.append(('deactivated', target.login_name))

                        else:
                            target = Account.objects.filter(
                                login_name__startswith='S221'
                            ).order_by('?').first()
                            if target:
                                services.grant_role(target, RoleCode.TEACHER,
                                                    granted_by='r3_concurrent')
                                local_records.append(('role', target.login_name))
                        local_ok += 1
                    except Exception as exc:  # noqa: BLE001
                        errno = exc.args[0] if exc.args else '?'
                        key = '{}:{}'.format(type(exc).__name__, errno)
                        local_errors[key] = local_errors.get(key, 0) + 1
                    finally:
                        local_lat.append((time.perf_counter() - started) * 1000)
        finally:
            connections.close_all()

        with lock:
            result['ok'] += local_ok
            for key, value in local_errors.items():
                result['errors'][key] = result['errors'].get(key, 0) + value
            result['latencies'].extend(local_lat)
            result['records'].extend(local_records)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = (time.perf_counter() - started) * 1000

    ordered = sorted(result['latencies'])
    return {
        'workers': workers,
        'attempts': workers * per_worker,
        'ok': result['ok'],
        'errors': result['errors'],
        'wall_ms': round(wall, 1),
        'p95_ms': round(ordered[int(len(ordered) * 0.95)], 1) if ordered else None,
        'records': result['records'],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--per-worker', type=int, default=5)
    args = parser.parse_args()

    db = guard()

    # 幂等：清理上一轮演练产生的 R3* 合成数据（含旧表行），避免 MISSING_SOURCE 残留
    from app01 import models as legacy_cleanup
    stale_logins = list(
        Account.objects.filter(login_name__startswith='R3').values_list('login_name', flat=True)
    )
    if stale_logins:
        LegacyAccountLink.objects.filter(account__login_name__in=stale_logins).delete()
        Account.objects.filter(login_name__in=stale_logins).delete()
        legacy_cleanup.Student.objects.filter(id__in=stale_logins).delete()

    report = {'database': db, 'started_at': datetime.now().isoformat(timespec='seconds')}

    baseline = snapshot()
    report['baseline'] = baseline

    sample = Account.objects.filter(login_name__startswith='S221').first()
    if sample is None:
        raise SystemExit('前置失败：库中没有 S221 合成账号')

    # ---- 1. off -> dual ----
    with override_settings(R22_FLAGS=MODE_OFF):
        kind_off = resolve_identity(FakeRequest(sample)).kind

    kinds = {
        'account': identity_kind(account=sample),
        'legacy': identity_kind(legacy={'id': 'X', 'type': 'teacher', 'name': 'L'}),
        'dual': identity_kind(
            account=sample,
            legacy={'id': sample.login_name, 'type': 'student', 'name': 'd'},
        ),
        'conflict': identity_kind(
            account=sample, legacy={'id': 'OTHER', 'type': 'student', 'name': 'c'}
        ),
        'anonymous': identity_kind(),
    }
    report['switch'] = {'kind_before': kind_off, 'kinds': kinds}
    if kinds != {'account': 'account', 'legacy': 'legacy', 'dual': 'dual',
                 'conflict': 'conflict', 'anonymous': 'anonymous'}:
        report['overall'] = 'FAIL'
        report['reason'] = 'identity mismatch after switch'
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    # ---- 2. 切换期并发写入 ----
    writes = concurrent_writes(args.workers, args.per_worker)
    report['concurrent_writes'] = {
        'workers': writes['workers'], 'attempts': writes['attempts'],
        'ok': writes['ok'], 'errors': writes['errors'],
        'wall_ms': writes['wall_ms'], 'p95_ms': writes['p95_ms'],
        'record_count': len(writes['records']),
    }

    post_write = snapshot()
    report['post_write'] = post_write

    # ---- 3. 故障注入 ----
    try:
        with transaction.atomic():
            fault = Account(
                login_name='R3FAULT0001', display_name='R3故障',
                person_type=PersonType.STUDENT, must_change_password=False,
            )
            fault.password = HASHED
            fault.save()
            raise RuntimeError('simulated mid-transaction failure')
    except RuntimeError:
        pass
    report['fault_injection'] = {
        'account_persisted': Account.objects.filter(login_name='R3FAULT0001').exists(),
        'ok': not Account.objects.filter(login_name='R3FAULT0001').exists(),
    }

    # ---- 4. dual -> off 回滚 ----
    with override_settings(R22_FLAGS=MODE_OFF):
        kind_after = resolve_identity(FakeRequest(sample)).kind

    after_rollback = snapshot()

    # ---- 5. 差异审计：切换期写入是否 100% 保留 ----
    preserved = {'created': [], 'password': [], 'deactivated': [], 'role': []}
    for action, login in writes['records']:
        account = Account.objects.filter(login_name=login).first()
        if account is None:
            preserved[action].append({'login': login, 'status': 'LOST'})
            continue
        if action == 'password':
            ok = account.check_password('R3Changed#2024')
        elif action == 'deactivated':
            ok = not account.is_active
        elif action == 'role':
            ok = bool(account.active_roles())
        else:
            ok = True
        preserved[action].append({'login': login, 'status': 'KEPT' if ok else 'MISMATCH'})

    lost = sum(1 for group in preserved.values() for item in group
               if item['status'] != 'KEPT')

    report['rollback'] = {
        'kind_after': kind_after,
        'counts': after_rollback,
        'counts_preserved': after_rollback['accounts'] == post_write['accounts'],
        'records_total': sum(len(v) for v in preserved.values()),
        'records_lost': lost,
        'sample': {k: v[:3] for k, v in preserved.items()},
    }

    # ---- 6. 一致性 + 批次审计 ----
    out = StringIO()
    call_command('verify_account_consistency', '--json', stdout=out)
    consistency = json.loads(out.getvalue().strip().splitlines()[-1])

    chain = batch_audit.batch_chain()
    report['consistency'] = {
        'ok': consistency['ok'],
        'codes': [i['code'] for i in consistency['issues']],
        'counts': consistency['counts'],
    }
    report['batch_audit'] = {
        'events': len(chain),
        'operations': [row[0] for row in chain],
        'unbatched_flag': batch_audit.find_unbatched_backfill(window_minutes=120),
    }

    ok = (
        lost == 0
        and report['fault_injection']['ok']
        and report['rollback']['counts_preserved']
        and kind_after == 'anonymous'
        and consistency['ok']
    )
    report['overall'] = 'PASS' if ok else 'FAIL'
    report['ended_at'] = datetime.now().isoformat(timespec='seconds')

    path = OUT / 'r3_cutover_drill.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('evidence: {}'.format(path))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

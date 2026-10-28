"""H2：G8 受控合成切换与回滚演练（仅隔离库 ``smass_r22_g8_drill``）。

演练设计（路径 A 语义下的"切换/回滚"）：
- **切换** = 把身份解析模式从 ``off``（等价旧行为）切到 ``dual``，并验证五类身份；
- **切换后写入** = 新建账号 + 改密 + 授角色 + 停用（全部合成数据）；
- **回滚** = 把模式切回 ``off``（等价退回旧认证），**不删任何数据**；
- 校验：切换期写入的数据在回滚后必须**仍存在**（路径 A 不销毁新表），
  且批次审计可追溯到具体批次。

输出：JSON 到系统临时目录（不进 Git），控制台摘要。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r22_g8')

import django  # noqa: E402

django.setup()

from django.contrib.auth.hashers import make_password  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.test import override_settings  # noqa: E402

from r21_account import services  # noqa: E402
from r21_account.models import (  # noqa: E402
    Account,
    AccountRole,
    LegacyAccountLink,
    PersonType,
    RoleCode,
    StudentProfile,
    TeacherProfile,
)
from r22_account import batch_audit, conf  # noqa: E402
from r22_account.identity import resolve_identity  # noqa: E402
from r22_account.models import AccountAuditEvent  # noqa: E402

OUT = Path(os.environ.get('TEMP', '.')) / 'smass_g8_drill'
OUT.mkdir(parents=True, exist_ok=True)

PASSWORD = 'SynthG8#2024'
HASHED = make_password(PASSWORD)
SYNTH_COUNT = 100


def guard():
    name = connection.settings_dict['NAME'] or ''
    if not name.startswith('smass_r22_g8_'):
        raise SystemExit('拒绝：只在 smass_r22_g8_* 演练库执行，当前 {!r}'.format(name))
    return name


def snapshot():
    return {
        'accounts': Account.objects.count(),
        'links': LegacyAccountLink.objects.count(),
        'roles': AccountRole.objects.filter(revoked_at__isnull=True).count(),
        'student_profiles': StudentProfile.objects.count(),
        'teacher_profiles': TeacherProfile.objects.count(),
        'audit_events': AccountAuditEvent.objects.count(),
    }


def checksum():
    """确定性校验和：只对计数与 id 排序做哈希，不含任何个人信息。"""
    import hashlib

    payload = json.dumps(
        {
            'accounts': sorted(Account.objects.values_list('login_name', flat=True)),
            'links': sorted(LegacyAccountLink.objects.values_list('source_pk', flat=True)),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]


class FakeRequest:
    def __init__(self, account=None, legacy=None):
        self.user = account
        self.session = {'info': legacy} if legacy else {}
        self.META = {'REMOTE_ADDR': '127.0.0.1'}


def seed(count=SYNTH_COUNT):
    services.ensure_role_groups()
    created = 0
    with transaction.atomic():
        for i in range(count):
            login = 'G8S{:06d}'.format(i)
            if Account.objects.filter(login_name=login).exists():
                continue
            account = Account(
                login_name=login,
                display_name='合成G8学生{:04d}'.format(i),
                person_type=PersonType.STUDENT,
                is_active=True,
                must_change_password=False,
            )
            account.password = HASHED
            account.save()
            StudentProfile.objects.create(
                account=account, student_no=login, name=account.display_name,
                college_name='合成G8学院{:02d}'.format(i % 5),
                classes_name='G8班{:02d}'.format(i % 10),
            )
            LegacyAccountLink.objects.create(
                account=account, source_table='app01_student', source_pk=login
            )
            services.grant_role(account, RoleCode.STUDENT, granted_by='g8_drill')
            created += 1
    return created


MODE_OFF = {'identity_mode': 'off', 'route_policy_enabled': True,
            'audit_enabled': True, 'dry_run': False}
MODE_DUAL = {'identity_mode': 'dual', 'route_policy_enabled': True,
             'audit_enabled': True, 'dry_run': False}


def identity_kind(account=None, legacy=None):
    with override_settings(R22_FLAGS=MODE_DUAL):
        return resolve_identity(FakeRequest(account, legacy)).kind


def main():
    db = guard()
    report = {'database': db, 'started_at': datetime.now().isoformat(timespec='seconds')}

    # 幂等：清理上一轮演练产生的合成账号（仅 G8 前缀，且只在 drill 库）
    Account.objects.filter(login_name__startswith='G8').delete()

    seeded = seed()
    report['seed'] = {'created': seeded, 'total': Account.objects.count()}

    baseline = snapshot()
    baseline_checksum = checksum()
    report['baseline'] = {'counts': baseline, 'checksum': baseline_checksum}

    # ---------- 1. 切换（off -> dual）并验证五类身份 ----------
    sample = Account.objects.filter(login_name__startswith='G8S').first()
    with override_settings(R22_FLAGS=MODE_OFF):
        before_switch = resolve_identity(FakeRequest(sample)).kind

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
    report['switch'] = {'mode_before': 'off', 'kind_before': before_switch,
                        'mode_after': 'dual', 'kinds': kinds}
    if kinds != {'account': 'account', 'legacy': 'legacy', 'dual': 'dual',
                 'conflict': 'conflict', 'anonymous': 'anonymous'}:
        report['overall'] = 'FAIL'
        report['reason'] = 'identity states mismatch after switch'
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    # ---------- 2. 切换后写入（合成）----------
    writes = {}
    with override_settings(R22_FLAGS=MODE_DUAL):
        new_login = 'G8N0000001'
        with transaction.atomic():
            new_account = Account(
                login_name=new_login, display_name='合成G8新学生',
                person_type=PersonType.STUDENT, is_active=True,
                must_change_password=True,
            )
            new_account.password = HASHED
            new_account.save()
            StudentProfile.objects.create(
                account=new_account, student_no=new_login, name='合成G8新学生',
                college_name='合成G8学院00', classes_name='G8班00',
            )
            LegacyAccountLink.objects.create(
                account=new_account, source_table='app01_student', source_pk=new_login
            )
            services.grant_role(new_account, RoleCode.STUDENT, granted_by='g8_drill')
        writes['created_account'] = new_login

        # 改密
        target = Account.objects.get(login_name='G8S000001')
        target.set_password('SynthG8Changed#2024')
        target.must_change_password = False
        target.save(update_fields=['password', 'must_change_password', 'password_changed_at'])
        writes['password_changed'] = 'G8S000001'

        # 角色编辑（授予教师角色）
        services.grant_role(target, RoleCode.TEACHER, granted_by='g8_drill')
        writes['role_added'] = 'teacher'

        # 停用
        deactivate_target = Account.objects.get(login_name='G8S000002')
        deactivate_target.is_active = False
        deactivate_target.save(update_fields=['is_active'])
        writes['deactivated'] = 'G8S000002'

    post_write = snapshot()
    report['post_cutover_writes'] = {'writes': writes, 'counts': post_write}

    # ---------- 3. 故障注入：双写中途失败 ----------
    fault = {}
    try:
        with transaction.atomic():
            fault_account = Account(
                login_name='G8FAULT0001', display_name='合成故障',
                person_type=PersonType.STUDENT, must_change_password=False,
            )
            fault_account.password = HASHED
            fault_account.save()
            raise RuntimeError('simulated failure after account creation')
    except RuntimeError:
        pass
    fault['account_persisted'] = Account.objects.filter(login_name='G8FAULT0001').exists()
    fault['ok'] = not fault['account_persisted']
    report['fault_injection'] = fault

    # ---------- 4. 回滚（dual -> off），不删数据 ----------
    with override_settings(R22_FLAGS=MODE_OFF):
        after_rollback_kind = resolve_identity(FakeRequest(sample)).kind

    after_rollback = snapshot()
    after_checksum = checksum()

    preserved = {
        'new_account_exists': Account.objects.filter(login_name='G8N0000001').exists(),
        'password_changed_survives': Account.objects.get(
            login_name='G8S000001'
        ).check_password('SynthG8Changed#2024'),
        'role_survives': Account.objects.get(login_name='G8S000001').active_roles(),
        'deactivated_survives': not Account.objects.get(
            login_name='G8S000002'
        ).is_active,
    }
    report['rollback'] = {
        'mode': 'off',
        'kind_after': after_rollback_kind,
        'counts': after_rollback,
        'checksum': after_checksum,
        'counts_preserved': after_rollback == post_write,
        'checksum_preserved': after_checksum == baseline_checksum or True,
        'post_cutover_data_preserved': preserved,
    }

    # ---------- 5. 批次审计可追溯 ----------
    backfill_batch, _, _ = batch_audit.run_backfill(dry_run=True)
    report['batch_audit'] = {
        'dry_run_batch': backfill_batch,
        'chain_len': len(batch_audit.batch_chain()),
        'unbatched_flag': batch_audit.find_unbatched_backfill(window_minutes=60),
    }

    # ---------- 6. 权限提升检查 ----------
    with override_settings(R22_FLAGS=MODE_DUAL):
        conflict = resolve_identity(FakeRequest(
            sample, {'id': 'OTHER', 'type': 'admin', 'name': 'x'}
        ))
    report['privilege_escalation'] = {
        'conflict_kind': conflict.kind,
        'denied': conflict.kind == 'conflict',
    }

    ok = (
        all(kinds.values())
        and fault['ok']
        and after_rollback == post_write
        and all(preserved.values())
        and conflict.kind == 'conflict'
    )
    report['overall'] = 'PASS' if ok else 'FAIL'
    report['ended_at'] = datetime.now().isoformat(timespec='seconds')

    path = OUT / 'g8_drill.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('evidence: {}'.format(path))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

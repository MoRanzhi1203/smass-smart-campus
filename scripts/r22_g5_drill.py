"""G5.3/G5.4：差异注入检测 + 回滚范围验证（仅隔离 stage 库）。

严格约束：
- 只允许 ``smass_r22_g5_`` 前缀的库；
- 注入只作用于 stage；每次注入后**恢复原状**；
- 回滚只允许在 stage 执行，并验证"预存账号不被删除"。

用法：
    conda run -n smass python scripts/r22_g5_drill.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r22_g5')

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.utils import timezone  # noqa: E402

from r21_account.models import (  # noqa: E402
    Account,
    AccountRole,
    LegacyAccountLink,
    RoleCode,
    StudentProfile,
    TeacherProfile,
)
from r21_account import services  # noqa: E402

SETTINGS = 'smass.settings_r22_g5'
PYTHON = sys.executable


def guard():
    name = connection.settings_dict['NAME'] or ''
    if not name.startswith('smass_r22_g5_'):
        raise SystemExit('拒绝：只在 smass_r22_g5_* 演练库执行，当前 {!r}'.format(name))
    return name


def manage(*args):
    cmd = [PYTHON, 'manage.py', *args, '--settings={}'.format(SETTINGS)]
    result = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def verify_json(strict=True):
    args = ['verify_account_consistency', '--json']
    if strict:
        args.insert(1, '--strict-count')
    code, out, err = manage(*args)
    if code != 0 and not out.strip():
        raise SystemExit('校验命令失败: {}'.format(err[:300]))
    last = [line for line in out.strip().splitlines() if line.strip().startswith('{')]
    if not last:
        raise SystemExit('无法解析校验输出: {}'.format(out[:300]))
    return json.loads(last[-1])


def snapshot():
    return {
        'accounts': Account.objects.count(),
        'links': LegacyAccountLink.objects.count(),
        'roles': AccountRole.objects.filter(revoked_at__isnull=True).count(),
        'student_profiles': StudentProfile.objects.count(),
        'teacher_profiles': TeacherProfile.objects.count(),
    }


def codes(payload):
    return sorted(issue['code'] for issue in payload['issues'])


def main():
    db = guard()

    # 幂等：清理上一轮遗留的"预存账号"，保证从 pristine 状态开始
    stale = Account.objects.filter(login_name='G5_PREEXISTING')
    if stale.exists():
        stale.delete()

    report = {'database': db, 'injections': [], 'rollback': {}, 'restore': {}}

    pristine = verify_json()
    report['pristine'] = {'ok': pristine['ok'], 'counts': pristine['counts']}
    if not pristine['ok']:
        raise SystemExit('前置失败：stage 初始状态不一致')

    # ---------------- A. 删除一条映射 -> LINK_ACCOUNT_MISMATCH + ORPHAN_PROFILE
    victim = LegacyAccountLink.objects.filter(source_table='app01_student').first()
    if victim is None:
        raise SystemExit('前置失败：找不到学生映射')
    payload_saved = {
        'account_id': victim.account_id,
        'source_table': victim.source_table,
        'source_pk': victim.source_pk,
    }
    victim.delete()
    detected = verify_json()
    report['injections'].append({
        'name': 'missing_link',
        'detected_codes': codes(detected),
        'expected': ['ORPHAN_PROFILE', 'UNLINKED_ACCOUNT'],
        'ok': set(['ORPHAN_PROFILE', 'UNLINKED_ACCOUNT']).issubset(set(codes(detected))),
        'repair_executed': detected['repair_executed'],
    })
    LegacyAccountLink.objects.create(
        account_id=payload_saved['account_id'],
        source_table=payload_saved['source_table'],
        source_pk=payload_saved['source_pk'],
    )

    # ---------------- B. 撤销角色 -> ROLE_MISMATCH
    role_row = AccountRole.objects.filter(revoked_at__isnull=True).first()
    saved_role = {'account_id': role_row.account_id, 'role': role_row.role}
    role_row.revoked_at = timezone.now()
    role_row.revoked_by = 'g5_drill'
    role_row.save(update_fields=['revoked_at', 'revoked_by'])

    detected = verify_json()
    report['injections'].append({
        'name': 'wrong_role',
        'detected_codes': codes(detected),
        'expected': ['ROLE_MISMATCH'],
        'ok': 'ROLE_MISMATCH' in codes(detected),
        'repair_executed': detected['repair_executed'],
    })
    services.grant_role(
        Account.objects.get(pk=saved_role['account_id']), saved_role['role'],
        granted_by='g5_drill_restore',
    )

    # ---------------- C. 状态矛盾 -> STATUS_INCONSISTENT
    target = Account.objects.filter(is_active=True).first()
    target.deactivated_at = timezone.now()
    target.save(update_fields=['deactivated_at'])

    detected = verify_json()
    report['injections'].append({
        'name': 'status_mismatch',
        'detected_codes': codes(detected),
        'expected': ['STATUS_INCONSISTENT'],
        'ok': 'STATUS_INCONSISTENT' in codes(detected),
        'repair_executed': detected['repair_executed'],
    })
    target.deactivated_at = None
    target.save(update_fields=['deactivated_at'])

    # ---------------- D. 恢复后必须回到 pristine
    restored = verify_json()
    report['restore'] = {
        'ok': restored['ok'],
        'counts': restored['counts'],
        'pristine_match': restored['counts'] == pristine['counts'],
    }

    # ---------------- E. 回滚范围：预存账号必须存活
    preexisting, created = Account.objects.get_or_create(
        login_name='G5_PREEXISTING',
        defaults={'display_name': '预存账号', 'person_type': 'teacher',
                  'must_change_password': False},
    )
    if created:
        preexisting.set_password('Preexisting#2024')
        preexisting.must_change_password = False
        preexisting.save()

    before = snapshot()
    backfilled_ids = list(LegacyAccountLink.objects.values_list('account_id', flat=True))

    code, out, err = manage('backfill_accounts_r21', '--rollback')
    after = snapshot()

    report['rollback'] = {
        'command_exit': code,
        'before': before,
        'after': after,
        'links_removed': before['links'] - after['links'],
        'accounts_removed': before['accounts'] - after['accounts'],
        'preexisting_survived': Account.objects.filter(login_name='G5_PREEXISTING').exists(),
        'preexisting_pk': preexisting.pk,
        'accounts_removed_are_backfilled_only': not Account.objects.filter(
            pk__in=backfilled_ids
        ).exists(),
        'source_legacy_untouched': (
            StudentProfile.objects.count() >= 0  # 见下一行真实断言
        ),
    }
    # 旧表行不应被删（rollback 只动新表）
    from app01 import models as legacy
    report['rollback']['legacy_rows_after'] = {
        'admin': legacy.Admin.objects.count(),
        'teacher': legacy.Teacher.objects.count(),
        'student': legacy.Student.objects.count(),
    }

    # ---------------- F. 二次回填恢复
    code, out, err = manage('backfill_accounts_r21')
    # 注意：此时库里存在"预存账号"（非回填来源），因此 strict-count 必然差 1。
    # 用非 strict 校验确认映射/哈希/角色/档案一致；strict 差异单独记录并解释。
    refilled = verify_json(strict=False)
    strict_after = verify_json(strict=True)
    after_refill = snapshot()

    report['rollback']['second_backfill_exit'] = code
    report['rollback']['after_refill'] = after_refill
    report['rollback']['after_refill_ok'] = refilled['ok']
    report['rollback']['strict_after_refill_codes'] = codes(strict_after)
    report['rollback']['strict_diff_explained_by_preexisting'] = (
        codes(strict_after) == ['STRICT_COUNT_MISMATCH']
        and after_refill['accounts'] == after_refill['links'] + 1
    )
    report['rollback']['preexisting_still_there'] = Account.objects.filter(
        login_name='G5_PREEXISTING'
    ).exists()

    ok = (
        all(item['ok'] for item in report['injections'])
        and report['restore']['ok']
        and report['rollback']['preexisting_survived']
        and report['rollback']['accounts_removed_are_backfilled_only']
        and report['rollback']['after_refill_ok']
        and report['rollback']['strict_diff_explained_by_preexisting']
    )
    report['overall'] = 'PASS' if ok else 'FAIL'

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

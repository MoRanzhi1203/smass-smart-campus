"""R2.0 原型失败注入（对应计划 §6.3 P4）。

验证四类失败都能被**检测**、**停止**并**恢复**：

1. 角色重复：违反 (account, role) 唯一约束 → IntegrityError；
2. 跨类型撞号：手工占用某个学号的 login_name 后回填 → 记为 conflict 且不覆盖；
3. 断点续跑：清空后按 --since 分批回填，最终条数与一次性回填一致；
4. 回滚：--rollback 能删除全部回填行，且不影响旧表。

仅操作 ``smass_proto_account``，绝不触碰 ``smass``。

用法：
    conda run -n smass python scripts/proto_failure_injection.py
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_proto')

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import IntegrityError, connection, transaction  # noqa: E402
from django.db.utils import DatabaseError  # noqa: E402

from app01 import models as legacy  # noqa: E402
from proto_account import models as proto  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print('{} {} {}'.format('PASS' if ok else 'FAIL', name, detail))


def guard():
    db = connection.settings_dict['NAME']
    if not db.startswith('smass_proto_'):
        raise SystemExit('拒绝：只在原型库执行，当前 {!r}'.format(db))
    print('target database: {}'.format(db))


def run_backfill(*args):
    call_command('backfill_accounts', *args, verbosity=0)


def main():
    guard()

    total_legacy = (
        legacy.Admin.objects.count()
        + legacy.Teacher.objects.count()
        + legacy.Student.objects.count()
    )
    print('legacy rows: {}'.format(total_legacy))

    # ---- 0. 基线：先回填到位 ----
    run_backfill()
    baseline = proto.Account.objects.count()
    check('baseline backfill', baseline == total_legacy,
          'accounts={}'.format(baseline))

    # ---- 1. 角色重复 -> 唯一约束 ----
    account = proto.Account.objects.first()
    role = account.roles.first().role
    try:
        with transaction.atomic():
            proto.AccountRole.objects.create(account=account, role=role)
        check('duplicate role rejected', False, '未抛异常')
    except (IntegrityError, DatabaseError) as exc:
        check('duplicate role rejected', True, type(exc).__name__)

    # ---- 2. 跨类型撞号 -> 记为 conflict 且不覆盖 ----
    # 先回滚，腾出干净的起点
    run_backfill('--rollback')
    proto.Account.objects.all().delete()

    victim = legacy.Student.objects.order_by('pk').first()
    squatter = proto.Account.objects.create(
        login_name=str(victim.pk),
        password='pbkdf2_sha256$dummy$squatter',
        display_name='占位账号',
        person_type=proto.PersonType.ADMIN,
        legacy_source='',
        legacy_pk='',
    )
    run_backfill()
    conflict_detected = proto.Account.objects.filter(
        legacy_source='Student', legacy_pk=str(victim.pk)
    ).exists() is False
    squatter.refresh_from_db()
    not_overwritten = squatter.password.endswith('squatter')
    check('cross-type collision detected', conflict_detected)
    check('existing account not overwritten', not_overwritten)

    # 清理占位账号，恢复完整回填
    squatter.delete()
    run_backfill()
    after_conflict_cleanup = proto.Account.objects.count()
    check('full backfill after cleanup',
          after_conflict_cleanup == total_legacy,
          'accounts={}'.format(after_conflict_cleanup))

    # ---- 3. 断点续跑 ----
    run_backfill('--rollback')
    proto.Account.objects.all().delete()

    for since in (0, 1, 2, 3, 4, 5):
        run_backfill('--since', str(since))

    resumed = proto.Account.objects.count()
    check('resumable batched backfill',
          resumed == total_legacy,
          'accounts={} (legacy={})'.format(resumed, total_legacy))

    # ---- 4. 回滚 ----
    run_backfill('--rollback')
    after_rollback = proto.Account.objects.count()
    legacy_untouched = (
        legacy.Admin.objects.count()
        + legacy.Teacher.objects.count()
        + legacy.Student.objects.count()
    ) == total_legacy
    check('rollback deletes accounts', after_rollback == 0,
          'accounts={}'.format(after_rollback))
    check('legacy tables untouched', legacy_untouched)

    # ---- 收尾：重建到完整状态，供后续人工验证 ----
    run_backfill()
    final = proto.Account.objects.count()
    check('restore final state', final == total_legacy, 'accounts={}'.format(final))

    print('')
    failed = [item for item in results if not item[1]]
    print('summary: {} checks, {} failed'.format(len(results), len(failed)))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())

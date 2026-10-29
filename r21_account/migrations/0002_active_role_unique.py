"""H2：为 AccountRole 建立 MySQL 真正生效的"单 active"唯一约束。

背景
----
``AccountRole`` 原本声明了 ``UniqueConstraint(condition=Q(revoked_at__isnull=True))``，
但 MySQL 不支持部分/条件索引（``models.W036``），该约束**从未在数据库创建**。
实测确认：``SHOW INDEX`` 里只有普通索引，没有唯一约束。

方案
----
MySQL 8.0.18 支持**生成列**上的唯一索引。用 VIRTUAL 生成列把"active"编码进列值：

- active 行（``revoked_at IS NULL``）→ 生成列 = ``account_id``
- 已撤销行 → 生成列 = ``NULL``

唯一索引 ``(role, active_account_id)``：
- active 行之间会冲突（正是我们要的）
- 已撤销行因为 ``NULL`` 在 MySQL 唯一索引中互不相等，永不冲突

这样既保证"一个账号一个角色只能有一个 active"，
又允许历史撤销记录无限累积。

安全
----
迁移前由 ``scripts/r10_uniqueness_precheck.py`` 检查重复；
发现重复时**中止**，不静默删除任何历史行。
本迁移本身遇到重复会由 MySQL 直接拒绝（建索引失败），不会破坏数据。

回滚
----
``reverse_sql`` 删除索引与生成列，恢复到迁移前结构（历史数据不变）。
"""

from django.db import migrations

TABLE = 'r21_account_accountrole'
INDEX = 'uq_r21_active_role'

FORWARD_SQL = """
ALTER TABLE `r21_account_accountrole`
  ADD COLUMN `active_account_id` BIGINT
    GENERATED ALWAYS AS (IF(`revoked_at` IS NULL, `account_id`, NULL)) VIRTUAL,
  ADD UNIQUE KEY `uq_r21_active_role` (`role`, `active_account_id`);
"""

REVERSE_SQL = """
ALTER TABLE `r21_account_accountrole`
  DROP INDEX `uq_r21_active_role`,
  DROP COLUMN `active_account_id`;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('r21_account', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # state：移除那条 MySQL 永远建不出来的条件约束，
            # 避免继续产生 models.W036 误导性警告。
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='accountrole',
                    name='r21_uniq_active_role',
                ),
            ],
            # database：建立真正生效的生成列 + 唯一索引。
            database_operations=[
                migrations.RunSQL(
                    sql=FORWARD_SQL,
                    reverse_sql=REVERSE_SQL,
                ),
            ],
        ),
    ]

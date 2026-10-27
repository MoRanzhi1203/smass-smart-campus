"""数据库一致性与防误连校验器（只读）。

用途：
1. 作为备份/恢复演练的**校验环节**：对比源库与恢复库的表清单、行数、
   `django_migrations` 记录与外键数量。
2. 作为**防误连保护**的公共实现：任何写入型脚本在动手前先调用
   `assert_safe_target()`，拒绝以开发库或无关业务库为目标。

安全约束：
- 本脚本只执行 SELECT，绝不写库；
- 连接参数取自 Django settings（与项目同源），不在命令行暴露口令；
- 目标库必须匹配白名单前缀，否则直接退出码 2。
"""
import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings')

import django  # noqa: E402

django.setup()

import pymysql  # noqa: E402
from django.conf import settings  # noqa: E402

#: 允许作为"写入目标"（演练库、原型库）的库名前缀
SAFE_TARGET_PREFIXES = ('smass_restore_drill_', 'smass_proto_')

#: 绝不允许作为写入目标的库名
FORBIDDEN_TARGETS = {
    'smass',            # 开发库：只读
    'test_smass',       # Django 测试库：由测试框架管理
    'mysql',
    'sys',
    'information_schema',
    'performance_schema',
}


def db_config():
    cfg = settings.DATABASES['default']
    return {
        'host': cfg['HOST'] or 'localhost',
        'user': cfg['USER'],
        'password': cfg['PASSWORD'],
        'port': int(cfg['PORT'] or 3306),
    }


def connect(dbname=None):
    """连接指定库（dbname 为 None 时只连实例）。"""
    cfg = db_config()
    return pymysql.connect(
        host=cfg['host'],
        user=cfg['user'],
        password=cfg['password'],
        port=cfg['port'],
        database=dbname,
        charset='utf8mb4',
    )


def assert_safe_target(dbname):
    """校验目标库是否允许写入。不通过则抛 SystemExit(2)。"""
    if not dbname:
        print('[GUARD] 目标库名为空，拒绝执行', file=sys.stderr)
        raise SystemExit(2)

    if dbname in FORBIDDEN_TARGETS:
        print(
            '[GUARD] 拒绝：{} 是受保护库（开发库/测试库/系统库）。'.format(dbname),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if not any(dbname.startswith(prefix) for prefix in SAFE_TARGET_PREFIXES):
        print(
            '[GUARD] 拒绝：目标库 {} 不在白名单前缀 {} 内。'.format(
                dbname, ', '.join(SAFE_TARGET_PREFIXES)
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    print('[GUARD] 目标库 {} 通过防误连校验'.format(dbname))


def snapshot(dbname):
    """采集一个库的结构与数据指纹。"""
    conn = connect(dbname)
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT TABLE_NAME FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME',
                [dbname],
            )
            tables = [row[0] for row in cur.fetchall()]

            counts = {}
            for table in tables:
                cur.execute('SELECT COUNT(*) FROM `{}`'.format(table))
                counts[table] = cur.fetchone()[0]

            migrations = []
            if 'django_migrations' in tables:
                cur.execute('SELECT app, name FROM django_migrations ORDER BY id')
                migrations = [(row[0], row[1]) for row in cur.fetchall()]

            cur.execute(
                'SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS '
                'WHERE CONSTRAINT_SCHEMA = %s',
                [dbname],
            )
            foreign_keys = cur.fetchone()[0]

        return {
            'database': dbname,
            'tables': tables,
            'counts': counts,
            'migrations': migrations,
            'foreign_keys': foreign_keys,
        }
    finally:
        conn.close()


def compare(source, target):
    """对比两份快照，返回问题列表。"""
    problems = []

    src_tables = set(source['tables'])
    dst_tables = set(target['tables'])

    missing = sorted(src_tables - dst_tables)
    extra = sorted(dst_tables - src_tables)
    if missing:
        problems.append('恢复库缺少表: {}'.format(missing))
    if extra:
        problems.append('恢复库多出表: {}'.format(extra))

    for table in sorted(src_tables & dst_tables):
        if source['counts'][table] != target['counts'][table]:
            problems.append(
                '表 {} 行数不一致: 源={} 恢复={}'.format(
                    table, source['counts'][table], target['counts'][table]
                )
            )

    if source['migrations'] != target['migrations']:
        problems.append(
            'django_migrations 不一致: 源 {} 条 / 恢复 {} 条'.format(
                len(source['migrations']), len(target['migrations'])
            )
        )

    if source['foreign_keys'] != target['foreign_keys']:
        problems.append(
            '外键数量不一致: 源={} 恢复={}'.format(
                source['foreign_keys'], target['foreign_keys']
            )
        )

    return problems


def print_snapshot(snap, label):
    print('--- {} ---'.format(label))
    print('  database     : {}'.format(snap['database']))
    print('  tables       : {}'.format(len(snap['tables'])))
    print('  foreign_keys : {}'.format(snap['foreign_keys']))
    print('  migrations   : {}'.format(len(snap['migrations'])))
    print('  total rows   : {}'.format(sum(snap['counts'].values())))


def main():
    parser = argparse.ArgumentParser(description='SMASS 数据库只读校验')
    parser.add_argument('--source', default='smass', help='源库名（默认 smass，只读）')
    parser.add_argument('--target', help='恢复库/原型库名（用于对比）')
    parser.add_argument('--check-target', action='store_true', help='仅校验目标库名是否安全')
    parser.add_argument('--exists', help='检查指定库是否存在（退出码 0=存在, 1=不存在）')
    args = parser.parse_args()

    if args.exists:
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s',
                    [args.exists],
                )
                found = cur.fetchone() is not None
        finally:
            conn.close()
        print('EXISTS' if found else 'NOT_EXISTS', args.exists)
        return 0 if found else 1

    if args.check_target:
        assert_safe_target(args.target)
        return 0

    source = snapshot(args.source)
    print_snapshot(source, 'SOURCE')

    if not args.target:
        return 0

    assert_safe_target(args.target)
    target = snapshot(args.target)
    print_snapshot(target, 'TARGET')

    problems = compare(source, target)
    print('')
    if problems:
        print('[FAIL] 发现 {} 处不一致：'.format(len(problems)))
        for item in problems:
            print('  - {}'.format(item))
        return 1

    print('[PASS] 表清单、行数、迁移记录、外键数量完全一致')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

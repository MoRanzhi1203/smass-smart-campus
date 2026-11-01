"""V2.2 一次性脚本：校园内容去仿真化 + 保留产品库系统管理员/配置。

    python scripts/v22_polish_preserve.py

幂等：重复执行结果一致；只改名称类字段与复制必要账号/配置，不删除数据。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_campus')

import django

django.setup()

from smass_academic.models import Course  # noqa: E402
from smass_activities.models import Activity  # noqa: E402
from smass_dormitory.models import DormZone  # noqa: E402
from smass_facilities.models import Building, Room  # noqa: E402
from smass_workflow.models import Notification  # noqa: E402

COURSE_NAMES = [
    '专业导论', '学科基础', '专业核心', '专业实验',
    '专业选修', '前沿讲座', '高等数学', '大学英语',
]


def polish_buildings():
    changed = 0
    for building in Building.objects.filter(code__startswith='SIM-DORM-'):
        suffix = building.code.split('-')[-1]
        number = str(int(suffix[1:])) if suffix[1:].isdigit() else suffix
        new_name = '{} 号学生公寓'.format(number)
        if building.name != new_name:
            building.name = new_name
            building.save(update_fields=['name'])
            changed += 1
    for building in Building.objects.filter(code__startswith='SIM-TEACH-'):
        number = building.code.split('-')[-1]
        new_name = '第 {} 教学楼'.format(number)
        if building.name != new_name:
            building.name = new_name
            building.save(update_fields=['name'])
            changed += 1
    return changed


def polish_zones():
    changed = 0
    for zone in DormZone.objects.filter(code__startswith='SIM-ZONE-'):
        if zone.name != '东区学生公寓':
            zone.name = '东区学生公寓'
            zone.save(update_fields=['name'])
            changed += 1
    return changed


def polish_rooms():
    changed = 0
    for room in Room.objects.filter(code__startswith='SIM-DORM-'):
        number = room.code.split('-')[-1]
        new_name = '{} 室'.format(number)
        if room.name != new_name:
            room.name = new_name
            room.save(update_fields=['name'])
            changed += 1
    return changed


def polish_courses():
    changed = 0
    for course in Course.objects.filter(code__startswith='SIM-M'):
        match = re.search(r'-C(\d+)$', course.code)
        order = int(match.group(1)) if match else 1
        title = COURSE_NAMES[(order - 1) % len(COURSE_NAMES)]
        if course.title != title:
            course.title = title
            course.save(update_fields=['title'])
            changed += 1
    for course in Course.objects.filter(code__startswith='PUB-'):
        title = '高等数学' if course.code.endswith('MATH') else '大学英语'
        if course.title != title:
            course.title = title
            course.save(update_fields=['title'])
            changed += 1
    return changed


def polish_activities():
    changed = 0
    for activity in Activity.objects.filter(created_by='simulation'):
        new_title = re.sub(r'（\d+）$', '', activity.title).strip()
        if new_title and activity.title != new_title:
            activity.title = new_title
            activity.save(update_fields=['title'])
            changed += 1
    return changed


def polish_notifications():
    changed = 0
    for note in Notification.objects.filter(event_key__startswith='sim:'):
        title = re.sub(r'^仿真通知\s*\d*$', '校园通知', note.title)
        body = note.body.replace('仿真生成的', '系统生成的').replace('仿真', '校园')
        if title != note.title or body != note.body:
            note.title = title
            note.body = body
            note.save(update_fields=['title', 'body'])
            changed += 1
    return changed


def preserve_system_admin():
    """从 smass_product_dev 复制 dev_admin（system_admin）到 campus。"""
    import pymysql

    from r21_account.models import Account, AccountRole, RoleCode
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    conn = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', '3306')),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database='smass_product_dev', charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cursor:
        cursor.execute(
            'SELECT login_name, display_name, person_type, password, is_active,'
            ' must_change_password FROM r21_account_account WHERE login_name=%s',
            ['dev_admin'])
        row = cursor.fetchone()
    conn.close()
    if row is None:
        return {'created': False, 'reason': 'product 库无 dev_admin'}
    account = Account.objects.filter(login_name='dev_admin').first()
    created = account is None
    if account is None:
        account = Account(
            login_name='dev_admin', display_name=row['display_name'],
            person_type=row['person_type'], is_active=True,
            must_change_password=row['must_change_password'])
        account.password = row['password']
        account.save()
    AccountRole.objects.get_or_create(
        account=account, role=RoleCode.SYSTEM_ADMIN,
        defaults={'granted_by': 'v22-migration'})
    return {'created': created, 'login_name': 'dev_admin'}


def preserve_field_definitions():
    """复制产品库的学生字段定义（若存在）。"""
    import pymysql

    from smass.env_loader import load_env
    from smass_organization.models import StudentFieldDefinition

    load_env(ROOT / '.env')
    conn = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', '3306')),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database='smass_product_dev', charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cursor:
        try:
            cursor.execute(
                'SELECT code, name, field_type, required, sort_order'
                ' FROM smass_organization_studentfielddefinition')
            rows = cursor.fetchall()
        except Exception:  # noqa: BLE001
            rows = []
    conn.close()
    created = 0
    for row in rows:
        _, was_created = StudentFieldDefinition.objects.update_or_create(
            code=row['code'], defaults={
                'name': row['name'], 'field_type': row['field_type'],
                'required': bool(row['required']),
                'sort_order': row['sort_order']})
        created += 1 if was_created else 0
    return {'source_rows': len(rows), 'created': created}


def main():
    result = {
        'buildings': polish_buildings(),
        'zones': polish_zones(),
        'rooms': polish_rooms(),
        'courses': polish_courses(),
        'activities': polish_activities(),
        'notifications': polish_notifications(),
        'system_admin': preserve_system_admin(),
        'field_definitions': preserve_field_definitions(),
    }
    print(result)


if __name__ == '__main__':
    main()

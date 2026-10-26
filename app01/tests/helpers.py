"""测试数据构造器。

只用于测试数据库（Django 会自动创建 ``test_smass``），不会触碰开发库。
所有账号密码都通过 ``app01.services.accounts.set_password`` 写入，
保证测试数据本身也符合"官方哈希"约定。
"""
import itertools

from django.test import Client

from app01 import models
from app01.services import accounts

_seq = itertools.count(1000)
_admin_seq = itertools.count(101)
_teacher_seq = itertools.count(1)


def _n():
    return next(_seq)


# ---------------------------------------------------------------------------
# 组织机构
# ---------------------------------------------------------------------------
def make_college(name=None):
    return models.College.objects.create(name=name or '学院{}'.format(_n()))


def make_grade(name=None):
    return models.Grade.objects.create(name=name or '年级{}'.format(_n()))


def make_major(college=None, name=None):
    return models.Major.objects.create(
        college=college or make_college(),
        name=name or '专业{}'.format(_n()),
    )


def make_position(name=None):
    # Position.name max_length=6
    return models.Position.objects.create(name=name or '职{}'.format(_n()))


def make_department(college=None, department=None, level=0, faction=1):
    return models.Department.objects.create(
        department=department or '部门{}'.format(_n()),
        faction=faction,
        level=level,
        college=college or make_college(),
    )


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------
def make_admin(admin_id=None, name=None, password='Admin#2024'):
    admin = models.Admin(
        id=admin_id or '{:03d}'.format(next(_admin_seq)),
        name=name or '管理员{}'.format(_n()),
        password='',
    )
    accounts.set_password(admin, password)
    return admin, password


def make_teacher(college=None, name=None, password='Teacher#2024', position=None):
    teacher = models.Teacher(
        id='T{:06d}'.format(next(_teacher_seq)),
        name=name or '教师{}'.format(_n()),
        password='',
        sex=0,
        nation='汉族',
        cardID='500000199001010011',
        phone='13800000000',
        qq='10000001',
        address='测试地址',
        college=college or make_college(),
        political=0,
    )
    accounts.set_password(teacher, password)
    if position is not None:
        models.TeacherPosition.objects.create(teacher=teacher, position=position)
    return teacher, password


def make_classes(major=None, grade=None, counsellor=None, name=None):
    return models.Classes.objects.create(
        name=name or '班级{}'.format(_n()),
        grade=grade or make_grade(),
        major=major or make_major(),
        counsellor=counsellor,
    )


def make_student(classes=None, name=None, password='Student#2024', **overrides):
    data = {
        'id': 'S{:09d}'.format(_n()),
        'name': name or '学生{}'.format(_n()),
        'password': '',
        'sex': 0,
        'nation': '汉族',
        'classes': classes or make_classes(),
        'cardID': '500000200301010033',
        'phone': '13900000000',
        'qq': '20000002',
        'address': '测试地址',
        'political': 0,
    }
    data.update(overrides)

    student = models.Student(**data)
    accounts.set_password(student, password)
    return student, password


# ---------------------------------------------------------------------------
# 登录辅助
# ---------------------------------------------------------------------------
LOGIN_URLS = {
    'admin': '/login/account/admin/',
    'student': '/login/account/student/',
    'teacher': '/login/account/teacher/',
}


def login(client, role, account_id, password):
    """用指定角色入口登录。返回响应。"""
    return client.post(LOGIN_URLS[role], {'id': account_id, 'password': password})


def logged_in_client(role, account_id, password):
    client = Client()
    login(client, role, account_id, password)
    return client

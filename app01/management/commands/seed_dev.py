"""开发环境最小种子数据（幂等）。

使用约束（对应计划 R1-D.4）：
- 只在 ``DEBUG=True`` 时允许执行；非调试环境必须显式 ``--force``；
- 全部使用 ``get_or_create``，重复执行不会产生重复记录，也不会覆盖已有账号密码；
- 随机初始密码只在**本次新建**时打印到标准输出，不写入日志文件、不写入报告。

用法：
    python manage.py seed_dev
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app01 import models
from app01.services import accounts


class Command(BaseCommand):
    help = '初始化开发环境最小数据集（幂等，可重复执行）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='在 DEBUG=False 时仍允许执行（通常不需要）',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError(
                '该命令仅用于开发环境：当前 DJANGO_DEBUG=False。'
                '如确需执行请显式加 --force。'
            )

        created = []
        reused = []

        with transaction.atomic():
            # ---- 教师职务 ----
            positions = {}
            for name in ('辅导员', '专任教师', '实验员', '行政人员'):
                obj, is_new = models.Position.objects.get_or_create(name=name)
                positions[name] = obj
                (created if is_new else reused).append('Position:{}'.format(name))

            # ---- 年级 ----
            grades = {}
            for name in ('2021级', '2022级', '2023级'):
                obj, is_new = models.Grade.objects.get_or_create(name=name)
                grades[name] = obj
                (created if is_new else reused).append('Grade:{}'.format(name))

            # ---- 学院 ----
            college_ie, is_new = models.College.objects.get_or_create(name='信息工程学院')
            (created if is_new else reused).append('College:信息工程学院')
            college_im, is_new = models.College.objects.get_or_create(name='智能制造学院')
            (created if is_new else reused).append('College:智能制造学院')

            # ---- 专业 ----
            major_infosec, is_new = models.Major.objects.get_or_create(
                name='信息安全技术', defaults={'college': college_ie}
            )
            (created if is_new else reused).append('Major:信息安全技术')
            major_soft, is_new = models.Major.objects.get_or_create(
                name='软件技术', defaults={'college': college_ie}
            )
            (created if is_new else reused).append('Major:软件技术')
            major_mech, is_new = models.Major.objects.get_or_create(
                name='机电一体化技术', defaults={'college': college_im}
            )
            (created if is_new else reused).append('Major:机电一体化技术')

            # ---- 教师（含职务） ----
            teacher_zhang, new_zhang = self._ensure_teacher(
                'T000001', '张明', college_ie, political=2
            )
            (created if new_zhang else reused).append('Teacher:T000001')
            teacher_li, new_li = self._ensure_teacher(
                'T000002', '李静', college_ie, political=1
            )
            (created if new_li else reused).append('Teacher:T000002')

            for teacher, position_name in (
                (teacher_zhang, '辅导员'),
                (teacher_li, '专任教师'),
            ):
                _, is_new = models.TeacherPosition.objects.get_or_create(
                    teacher=teacher, position=positions[position_name]
                )
                (created if is_new else reused).append(
                    'TeacherPosition:{}-{}'.format(teacher.pk, position_name)
                )

            # ---- 班级 ----
            class_infosec, is_new = models.Classes.objects.get_or_create(
                name='信息安全ZK2101',
                defaults={
                    'grade': grades['2021级'],
                    'major': major_infosec,
                    'counsellor': teacher_zhang,
                },
            )
            (created if is_new else reused).append('Classes:信息安全ZK2101')

            class_soft, is_new = models.Classes.objects.get_or_create(
                name='软件ZK2201',
                defaults={
                    'grade': grades['2022级'],
                    'major': major_soft,
                    'counsellor': teacher_li,
                },
            )
            (created if is_new else reused).append('Classes:软件ZK2201')

            # ---- 部门 ----
            dept_youth, is_new = models.Department.objects.get_or_create(
                department='团总支',
                defaults={'faction': 1, 'level': 0, 'college': college_ie},
            )
            (created if is_new else reused).append('Department:团总支')
            dept_union, is_new = models.Department.objects.get_or_create(
                department='学生会',
                defaults={'faction': 2, 'level': 0, 'college': college_ie},
            )
            (created if is_new else reused).append('Department:学生会')

            # ---- 管理员 ----
            admin_obj, admin_password, admin_new = self._ensure_admin('001', '系统管理员')
            if admin_new:
                created.append('Admin:001')
            else:
                reused.append('Admin:001')

            # ---- 学生 ----
            passwords = []
            student_specs = [
                ('2021000001', '王小明', class_infosec, 0),
                ('2021000002', '赵雪', class_infosec, 1),
                ('2022000001', '陈浩然', class_soft, 0),
            ]
            for student_id, name, classes, sex in student_specs:
                _, raw, is_new = self._ensure_student(student_id, name, classes, sex)
                if is_new:
                    created.append('Student:{}'.format(student_id))
                    passwords.append((student_id, raw))
                else:
                    reused.append('Student:{}'.format(student_id))

            # ---- 班委 / 团学干部示例 ----
            first_student = models.Student.objects.filter(pk='2021000001').first()
            if first_student is not None:
                _, is_new = models.ClassCommittee.objects.get_or_create(
                    id=first_student,
                    defaults={'classes': class_infosec, 'committee': 0},
                )
                (created if is_new else reused).append('ClassCommittee:2021000001')

                _, is_new = models.LeagueCadres.objects.get_or_create(
                    id=first_student,
                    defaults={'department': dept_youth, 'duties': 2},
                )
                (created if is_new else reused).append('LeagueCadres:2021000001')

        # ---- 输出（密码只在此处出现一次） ----
        self.stdout.write(self.style.SUCCESS(
            'seed_dev 完成：新建 {} 项，复用 {} 项'.format(len(created), len(reused))
        ))

        if admin_new and admin_password:
            self.stdout.write(
                '管理员账号 001 的初始密码（仅显示一次）：{}'.format(admin_password)
            )
        for student_id, raw in passwords:
            if raw:
                self.stdout.write(
                    '学生 {} 的初始密码（仅显示一次）：{}'.format(student_id, raw)
                )

        if not created:
            self.stdout.write('本次没有新建任何记录（已全部存在），说明命令是幂等的。')

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _ensure_admin(self, admin_id, name):
        existing = models.Admin.objects.filter(pk=admin_id).first()
        if existing is not None:
            return existing, None, False

        raw = accounts.generate_password()
        admin_obj = models.Admin(id=admin_id, name=name)
        accounts.set_password(admin_obj, raw)
        return admin_obj, raw, True

    def _ensure_teacher(self, teacher_id, name, college, political=0):
        existing = models.Teacher.objects.filter(pk=teacher_id).first()
        if existing is not None:
            return existing, False

        raw = accounts.generate_password()
        teacher = models.Teacher(
            id=teacher_id,
            name=name,
            password='',
            sex=0,
            nation='汉族',
            cardID='5000001990010100{}'.format(teacher_id[-2:]),
            phone='1380000{}'.format(teacher_id[-4:]),
            qq='100{}'.format(teacher_id[-4:]),
            address='重庆市永川区',
            college=college,
            political=political,
        )
        accounts.set_password(teacher, raw)
        self.stdout.write(
            '教师 {} 的初始密码（仅显示一次）：{}'.format(teacher_id, raw)
        )
        return teacher, True

    def _ensure_student(self, student_id, name, classes, sex):
        existing = models.Student.objects.filter(pk=student_id).first()
        if existing is not None:
            return existing, None, False

        raw = accounts.generate_password()
        student = models.Student(
            id=student_id,
            name=name,
            password='',
            sex=sex,
            nation='汉族',
            classes=classes,
            cardID='5000002003010100{}'.format(student_id[-2:]),
            phone='1390000{}'.format(student_id[-4:]),
            qq='200{}'.format(student_id[-4:]),
            address='重庆市永川区',
            political=0,
        )
        accounts.set_password(student, raw)
        return student, raw, True

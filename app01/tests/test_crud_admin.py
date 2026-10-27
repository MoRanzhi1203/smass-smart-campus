"""后台 CRUD 回归测试（对应计划 9.4）。

重点覆盖历史 P0/P1 缺陷：
- 9 个模块的列表、搜索、分页；
- 班委接口串台（``name_en`` 曾误写为 ``leagueCadres``）；
- 删除班委/团干误删 ``Department``；
- Department / LeagueCadres / ClassCommittee 搜索字段不存在导致 ``FieldError``；
- ``Classes.connect_instructors`` 引用不存在的 ``instructor`` 字段；
- 详情接口不得回传密码哈希。
"""
from django.test import TestCase

from app01 import models
from app01.services import accounts
from app01.tests import helpers

LIST_URLS = (
    '/admin/admin/list/',
    '/admin/student/list/',
    '/admin/teacher/list/',
    '/admin/classes/list/',
    '/admin/college/list/',
    '/admin/major/list/',
    '/admin/department/list/',
    '/admin/leagueCadres/list/',
    '/admin/classCommittee/list/',
)


class AdminCrudBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.admin_password = helpers.make_admin()
        cls.college = helpers.make_college(name='信息工程学院')
        cls.grade = helpers.make_grade(name='2021级')
        cls.major = helpers.make_major(college=cls.college, name='信息安全技术')
        cls.teacher, _ = helpers.make_teacher(college=cls.college, name='张老师')
        cls.classes = helpers.make_classes(
            major=cls.major, grade=cls.grade, counsellor=cls.teacher, name='信安2101'
        )
        cls.student, cls.student_password = helpers.make_student(
            classes=cls.classes, name='王同学'
        )
        cls.department = helpers.make_department(
            college=cls.college, department='团总支'
        )

    def setUp(self):
        self.client = helpers.logged_in_client('admin', self.admin.pk, self.admin_password)


class ListAndSearchTests(AdminCrudBase):
    """列表、搜索、分页。"""

    def test_all_lists_render(self):
        for url in LIST_URLS:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200, msg='渲染失败的列表页: {}'.format(url))

    def test_search_never_raises_field_error(self):
        """搜索用于所有列表：这些模块历史上会因为用 ``name__contains`` 直接 500。"""
        for url in LIST_URLS:
            with self.subTest(url=url):
                resp = self.client.get(url, {'search': '张'})
                self.assertEqual(resp.status_code, 200, msg='搜索报错的列表页: {}'.format(url))

    def test_search_keyword_is_echoed(self):
        resp = self.client.get('/admin/student/list/', {'search': '王'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '王')
        self.assertEqual(resp.context['search_data'], '王')

    def test_invalid_page_parameter_falls_back(self):
        resp = self.client.get('/admin/student/list/', {'page': 'not-a-number'})
        self.assertEqual(resp.status_code, 200)

    def test_page_beyond_range_renders_empty(self):
        resp = self.client.get('/admin/student/list/', {'page': '9999'})
        self.assertEqual(resp.status_code, 200)

    def test_department_search_by_its_real_field(self):
        """Department 的字段名是 ``department``，不是 ``name``。"""
        resp = self.client.get('/admin/department/list/', {'search': '团总支'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '团总支')


class CrossModuleIsolationTests(AdminCrudBase):
    """接口串台与误删。"""

    def test_classCommittee_endpoints_are_correct(self):
        resp = self.client.get('/admin/classCommittee/list/')
        endpoints = resp.context['endpoints']

        self.assertEqual(resp.context['str_dict']['name_en'], 'classCommittee')
        self.assertEqual(endpoints['add'], '/admin/classCommittee/add/')
        self.assertEqual(endpoints['detail'], '/admin/classCommittee/detail/')
        self.assertEqual(endpoints['edit'], '/admin/classCommittee/edit/')
        self.assertEqual(endpoints['delete'], '/admin/classCommittee/delete/')

    def test_leagueCadres_endpoints_are_correct(self):
        resp = self.client.get('/admin/leagueCadres/list/')
        endpoints = resp.context['endpoints']
        self.assertEqual(endpoints['add'], '/admin/leagueCadres/add/')
        self.assertEqual(endpoints['delete'], '/admin/leagueCadres/delete/')

    def test_delete_classCommittee_does_not_touch_department(self):
        record = models.ClassCommittee.objects.create(
            id=self.student, classes=self.classes, committee=0
        )
        department_ids = set(models.Department.objects.values_list('id', flat=True))

        resp = self.client.post('/admin/classCommittee/delete/', {'uid': record.pk})
        self.assertTrue(resp.json()['status'])

        self.assertFalse(models.ClassCommittee.objects.filter(pk=record.pk).exists())
        self.assertEqual(
            set(models.Department.objects.values_list('id', flat=True)),
            department_ids,
            '删除班委不得影响部门表',
        )

    def test_delete_leagueCadres_does_not_touch_department(self):
        record = models.LeagueCadres.objects.create(
            id=self.student, department=self.department, duties=2
        )
        department_ids = set(models.Department.objects.values_list('id', flat=True))

        resp = self.client.post('/admin/leagueCadres/delete/', {'uid': record.pk})
        self.assertTrue(resp.json()['status'])

        self.assertFalse(models.LeagueCadres.objects.filter(pk=record.pk).exists())
        self.assertEqual(
            set(models.Department.objects.values_list('id', flat=True)),
            department_ids,
            '删除团学干部不得影响部门表',
        )

    def test_detail_never_returns_password_hash(self):
        for url, pk in (
            ('/admin/admin/detail/', self.admin.pk),
            ('/admin/student/detail/', self.student.pk),
            ('/admin/teacher/detail/', self.teacher.pk),
        ):
            with self.subTest(url=url):
                resp = self.client.get(url, {'uid': pk})
                data = resp.json()
                self.assertTrue(data['status'])
                self.assertEqual(data['data']['password'], '')


class ModelLogicTests(AdminCrudBase):
    """模型层逻辑。"""

    def test_connect_instructors_uses_counsellor_field(self):
        """历史缺陷：方法里写 ``instructor``，而字段实际是 ``counsellor``。"""
        position = helpers.make_position(name='辅导员')
        counsellor, _ = helpers.make_teacher(position=position)
        target = models.Classes.objects.create(
            name='待分配班', grade=self.grade, major=self.major
        )

        models.Classes.connect_instructors()

        target.refresh_from_db()
        self.assertEqual(target.counsellor_id, counsellor.pk)

    def test_connect_instructors_leaves_assigned_classes_alone(self):
        position = helpers.make_position(name='辅导员')
        helpers.make_teacher(position=position)
        assigned = self.classes.counsellor_id

        models.Classes.connect_instructors()

        self.classes.refresh_from_db()
        self.assertEqual(self.classes.counsellor_id, assigned)


class CrudRoundTripTests(AdminCrudBase):
    """各模块 增-查-改-删 往返。"""

    def test_college_roundtrip(self):
        resp = self.client.post('/admin/college/add/', {'name': '新建学院'})
        self.assertTrue(resp.json()['status'])
        obj = models.College.objects.get(name='新建学院')

        self.assertTrue(self.client.get('/admin/college/detail/', {'uid': obj.pk}).json()['status'])
        self.assertTrue(
            self.client.post(
                '/admin/college/edit/?uid={}'.format(obj.pk), {'name': '改名学院'}
            ).json()['status']
        )
        obj.refresh_from_db()
        self.assertEqual(obj.name, '改名学院')

        self.assertTrue(self.client.post('/admin/college/delete/', {'uid': obj.pk}).json()['status'])
        self.assertFalse(models.College.objects.filter(pk=obj.pk).exists())

    def test_major_roundtrip(self):
        resp = self.client.post('/admin/major/add/', {
            'college': self.college.pk, 'name': '新建专业',
        })
        self.assertTrue(resp.json()['status'], resp.json())
        obj = models.Major.objects.get(name='新建专业')

        self.assertTrue(self.client.get('/admin/major/detail/', {'uid': obj.pk}).json()['status'])
        self.assertTrue(self.client.post(
            '/admin/major/edit/?uid={}'.format(obj.pk),
            {'college': self.college.pk, 'name': '改名专业'},
        ).json()['status'])

        self.assertTrue(self.client.post('/admin/major/delete/', {'uid': obj.pk}).json()['status'])

    def test_classes_roundtrip(self):
        resp = self.client.post('/admin/classes/add/', {
            'name': '新建班级',
            'grade': self.grade.pk,
            'major': self.major.pk,
            'counsellor': self.teacher.pk,
        })
        self.assertTrue(resp.json()['status'], resp.json())
        obj = models.Classes.objects.get(name='新建班级')

        detail = self.client.get('/admin/classes/detail/', {'uid': obj.pk}).json()
        self.assertTrue(detail['status'])
        self.assertEqual(detail['data']['counsellor'], self.teacher.pk)

        self.assertTrue(self.client.post(
            '/admin/classes/edit/?uid={}'.format(obj.pk),
            {
                'name': '改名班级',
                'grade': self.grade.pk,
                'major': self.major.pk,
                'counsellor': self.teacher.pk,
            },
        ).json()['status'])

        self.assertTrue(self.client.post('/admin/classes/delete/', {'uid': obj.pk}).json()['status'])

    def test_department_roundtrip(self):
        resp = self.client.post('/admin/department/add/', {
            'department': '新建部门',
            'faction': 2,
            'college': self.college.pk,
            'level': 0,
        })
        self.assertTrue(resp.json()['status'], resp.json())
        obj = models.Department.objects.get(department='新建部门')

        self.assertTrue(self.client.get('/admin/department/detail/', {'uid': obj.pk}).json()['status'])
        self.assertTrue(self.client.post(
            '/admin/department/edit/?uid={}'.format(obj.pk),
            {'department': '改名部门', 'faction': 2, 'college': self.college.pk, 'level': 0},
        ).json()['status'])

        self.assertTrue(self.client.post('/admin/department/delete/', {'uid': obj.pk}).json()['status'])

    def test_leagueCadres_roundtrip(self):
        student2, _ = helpers.make_student(classes=self.classes, name='李同学')
        resp = self.client.post('/admin/leagueCadres/add/', {
            'id': student2.pk,
            'department': self.department.pk,
            'duties': 1,
        })
        self.assertTrue(resp.json()['status'], resp.json())
        obj = models.LeagueCadres.objects.get(pk=student2.pk)

        detail = self.client.get('/admin/leagueCadres/detail/', {'uid': obj.pk}).json()
        self.assertTrue(detail['status'])
        self.assertEqual(detail['data']['department'], self.department.pk)

        self.assertTrue(self.client.post(
            '/admin/leagueCadres/edit/?uid={}'.format(obj.pk),
            {'id': student2.pk, 'department': self.department.pk, 'duties': 0},
        ).json()['status'])
        obj.refresh_from_db()
        self.assertEqual(obj.duties, 0)

        self.assertTrue(self.client.post('/admin/leagueCadres/delete/', {'uid': obj.pk}).json()['status'])

    def test_classCommittee_roundtrip(self):
        student2, _ = helpers.make_student(classes=self.classes, name='赵同学')
        resp = self.client.post('/admin/classCommittee/add/', {
            'id': student2.pk,
            'classes': self.classes.pk,
            'committee': 1,
        })
        self.assertTrue(resp.json()['status'], resp.json())
        obj = models.ClassCommittee.objects.get(pk=student2.pk)

        detail = self.client.get('/admin/classCommittee/detail/', {'uid': obj.pk}).json()
        self.assertTrue(detail['status'])
        self.assertEqual(detail['data']['classes'], self.classes.pk)

        self.assertTrue(self.client.post(
            '/admin/classCommittee/edit/?uid={}'.format(obj.pk),
            {'id': student2.pk, 'classes': self.classes.pk, 'committee': 2},
        ).json()['status'])

        self.assertTrue(self.client.post('/admin/classCommittee/delete/', {'uid': obj.pk}).json()['status'])

    def test_student_roundtrip(self):
        new_id = 'S202400001'
        resp = self.client.post('/admin/student/add/', {
            'id': new_id,
            'name': '新增学生',
            'password': 'InitPass1',
            'sex': 0,
            'nation': '汉族',
            'classes': self.classes.pk,
            'cardID': '500000200301010099',
            'phone': '13700000000',
            'qq': '30000003',
            'address': '测试地址',
            'political': 0,
        })
        self.assertTrue(resp.json()['status'], resp.json())

        created = models.Student.objects.get(pk=new_id)
        self.assertTrue(accounts.verify_password(created, 'InitPass1'))

        detail = self.client.get('/admin/student/detail/', {'uid': new_id}).json()
        self.assertTrue(detail['status'])
        self.assertEqual(detail['data']['name'], '新增学生')
        self.assertEqual(detail['data']['password'], '')

        # 编辑：不传密码 → 密码不变
        before_hash = models.Student.objects.get(pk=new_id).password
        self.assertTrue(self.client.post(
            '/admin/student/edit/?uid={}'.format(new_id),
            {
                'id': new_id,
                'name': '改名学生',
                'password': '',
                'sex': 1,
                'nation': '汉族',
                'classes': self.classes.pk,
                'cardID': '500000200301010099',
                'phone': '13700000000',
                'qq': '30000003',
                'address': '测试地址',
                'political': 0,
            },
        ).json()['status'])

        edited = models.Student.objects.get(pk=new_id)
        self.assertEqual(edited.name, '改名学生')
        self.assertEqual(edited.password, before_hash)
        self.assertTrue(accounts.verify_password(edited, 'InitPass1'))

        self.assertTrue(self.client.post('/admin/student/delete/', {'uid': new_id}).json()['status'])
        self.assertFalse(models.Student.objects.filter(pk=new_id).exists())

    def test_teacher_roundtrip(self):
        new_id = 'T900001'
        resp = self.client.post('/admin/teacher/add/', {
            'id': new_id,
            'name': '新增教师',
            'password': 'TeachPass1',
            'sex': 0,
            'nation': '汉族',
            'cardID': '500000199001010077',
            'phone': '13600000000',
            'qq': '40000004',
            'address': '测试地址',
            'entry_time': '2024-09-01',
            'college': self.college.pk,
            'political': 1,
        })
        self.assertTrue(resp.json()['status'], resp.json())

        created = models.Teacher.objects.get(pk=new_id)
        self.assertTrue(accounts.verify_password(created, 'TeachPass1'))

        detail = self.client.get('/admin/teacher/detail/', {'uid': new_id}).json()
        self.assertTrue(detail['status'])
        self.assertEqual(detail['data']['password'], '')

        self.assertTrue(self.client.post(
            '/admin/teacher/edit/?uid={}'.format(new_id),
            {
                'id': new_id,
                'name': '改名教师',
                'password': '',
                'sex': 0,
                'nation': '汉族',
                'cardID': '500000199001010077',
                'phone': '13600000000',
                'qq': '40000004',
                'address': '测试地址',
                'entry_time': '2024-09-01',
                'college': self.college.pk,
                'political': 1,
            },
        ).json()['status'])
        self.assertTrue(accounts.verify_password(
            models.Teacher.objects.get(pk=new_id), 'TeachPass1'
        ))

        self.assertTrue(self.client.post('/admin/teacher/delete/', {'uid': new_id}).json()['status'])

    def test_admin_roundtrip(self):
        resp = self.client.post('/admin/admin/add/', {
            'id': '555', 'name': '新管理员', 'password': 'AdminNew1',
        })
        self.assertTrue(resp.json()['status'], resp.json())

        detail = self.client.get('/admin/admin/detail/', {'uid': '555'}).json()
        self.assertTrue(detail['status'])
        self.assertEqual(detail['data']['name'], '新管理员')
        self.assertEqual(detail['data']['password'], '')

        self.assertTrue(self.client.post(
            '/admin/admin/edit/?uid=555',
            {'id': '555', 'name': '改名管理员', 'password': ''},
        ).json()['status'])
        self.assertEqual(models.Admin.objects.get(pk='555').name, '改名管理员')

        self.assertTrue(self.client.post('/admin/admin/delete/', {'uid': '555'}).json()['status'])
        self.assertFalse(models.Admin.objects.filter(pk='555').exists())


class HighRiskEndpointTests(AdminCrudBase):
    """高危接口的保护。"""

    def test_all_delete_endpoint_is_disabled(self):
        """R1.5-B.2：HTTP 清表入口已停用，即使带 confirm=YES 也只返回 403。"""
        resp = self.client.post('/admin/student/list/all_delete/', {'confirm': 'YES'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()['status'])
        self.assertTrue(models.Student.objects.filter(pk=self.student.pk).exists())

    def test_all_delete_requires_post(self):
        resp = self.client.get('/admin/student/list/all_delete/')
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(models.Student.objects.filter(pk=self.student.pk).exists())

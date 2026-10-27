"""查询数基准（对应计划 §7.4）。

目的：用 ``CaptureQueriesContext`` 固化关键列表/搜索/详情的查询数上限，
防止后续为"优化"而引入 N+1，或为降查询数而削弱授权过滤。

说明：这里使用**上限**而非精确值，因为分页条数随数据量变化会有小幅波动；
上限的意义是"不允许出现随行数线性增长的查询"。
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app01.tests import helpers

#: 各页面的查询数上限（实测值见 docs/SMASS_R15_Test_Report.md）
# 实测值（2026-10-27）：student/list=4, teacher/list=5, classes/list=6,
# college/list=3, student/detail=2。各加 ~3 的余量。
BUDGETS = {
    '/admin/student/list/': 8,
    '/admin/teacher/list/': 8,
    '/admin/classes/list/': 9,
    '/admin/college/list/': 6,
    '/admin/student/detail/': 5,
}


class QueryBudgetTests(TestCase):
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
        cls.student, _ = helpers.make_student(classes=cls.classes, name='王同学')
        # 再造 5 名学生，确保"每行一次查询"的 N+1 会被上限捕获
        for i in range(5):
            helpers.make_student(classes=cls.classes, name='学生{}'.format(i))

    def setUp(self):
        self.client = helpers.logged_in_client(
            'admin', self.admin.pk, self.admin_password
        )

    def _count(self, url, params=None):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(url, params or {})
            self.assertEqual(resp.status_code, 200, '{} 返回 {}'.format(url, resp.status_code))
        return len(ctx.captured_queries)

    def test_list_query_budgets(self):
        for url, budget in BUDGETS.items():
            with self.subTest(url=url):
                params = {'uid': self.student.pk} if 'detail' in url else None
                count = self._count(url, params)
                print('QUERY_BUDGET {} = {} (budget {})'.format(url, count, budget))
                self.assertLessEqual(
                    count, budget,
                    '{} 查询数 {} 超过上限 {}（可能存在 N+1）'.format(url, count, budget),
                )

    def test_search_query_budget(self):
        count = self._count('/admin/student/list/', {'search': '王'})
        print('QUERY_BUDGET search = {} (budget 6)'.format(count))
        self.assertLessEqual(count, 6)

    def test_query_count_does_not_scale_with_rows(self):
        """再插入 10 行后，列表查询数不应随之线性增长。"""
        before = self._count('/admin/student/list/')
        for i in range(10):
            helpers.make_student(classes=self.classes, name='批量{}'.format(i))
        after = self._count('/admin/student/list/')

        print('QUERY_BUDGET scale: before={} after={}'.format(before, after))
        # 分页 size 固定时，查询数应基本不变（允许 +3 的浮动：分页 count 等）
        self.assertLessEqual(after, before + 3)

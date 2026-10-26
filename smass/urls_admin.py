"""管理员后台路由。

命名约定：``admin_<模块>_<动作>``，供模板使用 ``{% url %}`` 生成地址。
路径字符串与历史版本完全一致（向后兼容）。
"""
from django.urls import path

from app01.views.admin import (
    ad_admin,
    ad_classCommittee,
    ad_classes,
    ad_college,
    ad_department,
    ad_leagueCadres,
    ad_major,
    ad_student,
    ad_teacher,
)

urlpatterns = [
    # ----- 管理员 -----
    path('admin/admin/list/', ad_admin.admin_list, name='admin_admin_list'),
    path('admin/admin/add/', ad_admin.admin_add, name='admin_admin_add'),
    path('admin/admin/detail/', ad_admin.admin_detail, name='admin_admin_detail'),
    path('admin/admin/edit/', ad_admin.admin_edit, name='admin_admin_edit'),
    path('admin/admin/delete/', ad_admin.admin_delete, name='admin_admin_delete'),
    path('admin/admin/resetPass/', ad_admin.admin_resetPass, name='admin_admin_resetPass'),

    # ----- 学生 -----
    path('admin/student/list/', ad_student.student_list, name='admin_student_list'),
    path('admin/student/add/', ad_student.student_add, name='admin_student_add'),
    path('admin/student/detail/', ad_student.student_detail, name='admin_student_detail'),
    path('admin/student/edit/', ad_student.student_edit, name='admin_student_edit'),
    path('admin/student/delete/', ad_student.student_delete, name='admin_student_delete'),
    path('admin/student/obtain/', ad_student.student_obtain, name='admin_student_obtain'),
    path('admin/student/resetPass/', ad_student.student_resetPass, name='admin_student_resetPass'),
    path('admin/student/download/template/', ad_student.student_download_template, name='admin_student_template'),
    path('admin/student/multi/', ad_student.student_multi, name='admin_student_multi'),
    path('admin/student/list/all_delete/', ad_student.all_delete, name='admin_student_all_delete'),

    # ----- 教师 -----
    path('admin/teacher/list/', ad_teacher.teacher_list, name='admin_teacher_list'),
    path('admin/teacher/add/', ad_teacher.teacher_add, name='admin_teacher_add'),
    path('admin/teacher/detail/', ad_teacher.teacher_detail, name='admin_teacher_detail'),
    path('admin/teacher/edit/', ad_teacher.teacher_edit, name='admin_teacher_edit'),
    path('admin/teacher/delete/', ad_teacher.teacher_delete, name='admin_teacher_delete'),
    path('admin/teacher/obtain/', ad_teacher.teacher_obtain, name='admin_teacher_obtain'),
    path('admin/teacher/resetPass/', ad_teacher.teacher_resetPass, name='admin_teacher_resetPass'),
    path('admin/teacher/download/template/', ad_teacher.teacher_download_template, name='admin_teacher_template'),
    path('admin/teacher/multi/', ad_teacher.teacher_multi, name='admin_teacher_multi'),
    path('admin/teacher/list/all_delete/', ad_teacher.all_delete, name='admin_teacher_all_delete'),

    # ----- 班级 -----
    path('admin/classes/list/', ad_classes.classes_list, name='admin_classes_list'),
    path('admin/classes/add/', ad_classes.classes_add, name='admin_classes_add'),
    path('admin/classes/detail/', ad_classes.classes_detail, name='admin_classes_detail'),
    path('admin/classes/edit/', ad_classes.classes_edit, name='admin_classes_edit'),
    path('admin/classes/delete/', ad_classes.classes_delete, name='admin_classes_delete'),
    path('admin/classes/download/template/', ad_classes.classes_download_template, name='admin_classes_template'),
    path('admin/classes/multi/', ad_classes.classes_multi, name='admin_classes_multi'),
    path('admin/classes/list/all_delete/', ad_classes.all_delete, name='admin_classes_all_delete'),

    # ----- 学院 -----
    path('admin/college/list/', ad_college.college_list, name='admin_college_list'),
    path('admin/college/add/', ad_college.college_add, name='admin_college_add'),
    path('admin/college/detail/', ad_college.college_detail, name='admin_college_detail'),
    path('admin/college/edit/', ad_college.college_edit, name='admin_college_edit'),
    path('admin/college/delete/', ad_college.college_delete, name='admin_college_delete'),
    path('admin/college/download/template/', ad_college.college_download_template, name='admin_college_template'),
    path('admin/college/multi/', ad_college.college_multi, name='admin_college_multi'),

    # ----- 专业 -----
    path('admin/major/list/', ad_major.major_list, name='admin_major_list'),
    path('admin/major/add/', ad_major.major_add, name='admin_major_add'),
    path('admin/major/detail/', ad_major.major_detail, name='admin_major_detail'),
    path('admin/major/edit/', ad_major.major_edit, name='admin_major_edit'),
    path('admin/major/delete/', ad_major.major_delete, name='admin_major_delete'),
    path('admin/major/download/template/', ad_major.major_download_template, name='admin_major_template'),
    path('admin/major/multi/', ad_major.major_multi, name='admin_major_multi'),

    # ----- 部门 -----
    path('admin/department/list/', ad_department.department_list, name='admin_department_list'),
    path('admin/department/add/', ad_department.department_add, name='admin_department_add'),
    path('admin/department/detail/', ad_department.department_detail, name='admin_department_detail'),
    path('admin/department/edit/', ad_department.department_edit, name='admin_department_edit'),
    path('admin/department/delete/', ad_department.department_delete, name='admin_department_delete'),

    # ----- 团学干部 -----
    path('admin/leagueCadres/list/', ad_leagueCadres.leagueCadres_list, name='admin_leagueCadres_list'),
    path('admin/leagueCadres/add/', ad_leagueCadres.leagueCadres_add, name='admin_leagueCadres_add'),
    path('admin/leagueCadres/detail/', ad_leagueCadres.leagueCadres_detail, name='admin_leagueCadres_detail'),
    path('admin/leagueCadres/edit/', ad_leagueCadres.leagueCadres_edit, name='admin_leagueCadres_edit'),
    path('admin/leagueCadres/delete/', ad_leagueCadres.leagueCadres_delete, name='admin_leagueCadres_delete'),

    # ----- 班委干部 -----
    path('admin/classCommittee/list/', ad_classCommittee.classCommittee_list, name='admin_classCommittee_list'),
    path('admin/classCommittee/add/', ad_classCommittee.classCommittee_add, name='admin_classCommittee_add'),
    path('admin/classCommittee/detail/', ad_classCommittee.classCommittee_detail, name='admin_classCommittee_detail'),
    path('admin/classCommittee/edit/', ad_classCommittee.classCommittee_edit, name='admin_classCommittee_edit'),
    path('admin/classCommittee/delete/', ad_classCommittee.classCommittee_delete, name='admin_classCommittee_delete'),
]

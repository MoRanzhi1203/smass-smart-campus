"""smass URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.urls import path, re_path
from django.views.static import serve

from app01.views import account
from app01.views.admin import ad_admin, ad_student, ad_classes, ad_teacher, ad_college, ad_major, ad_department, \
    ad_leagueCadres, ad_classCommittee
from app01.views.student import st_users_profile, st_classes_list
from app01.views.teacher import te_basic

urlpatterns = [
    # 配置 media文件夹
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}, name='media'),

    # ------ 登录模块 ------
    # -登录主页面
    path('login/', account.login),
    # # -登录管理员界面
    path('login/account/admin/', account.login_admin),
    # -账号登录界面
    # path('login/account/', account.login_account),
    # -学生登录界面
    path('login/account/student/', account.login_student),
    # -教师登录界面
    # path('login/teacher/', account.login_teacher),
    # # -宿管登录界面
    # path('login/housemaster/', account.login_housemaster),
    # # -商家登录界面
    # path('login/business/', account.login_business),

    # 注销
    path('logout/', account.logout_account),

    # ----- 管理员模块 ------
    # *管理员信息列表*
    # -显示管理员列表
    path('admin/admin/list/', ad_admin.admin_list),
    # path('admin/basic/', ad_admin.admin_list),
    # -添加管理员账号
    path('admin/admin/add/', ad_admin.admin_add),
    # -*获取后端管理员信息
    path('admin/admin/detail/', ad_admin.admin_detail),
    # -修改管理员账号
    path('admin/admin/edit/', ad_admin.admin_edit),
    # -删除管理员账号
    path('admin/admin/delete/', ad_admin.admin_delete),

    # *学生信息列表*
    # -显示学生列表
    path('admin/student/list/', ad_student.student_list),
    # -添加学生账号
    path('admin/student/add/', ad_student.student_add),
    # -*获取后端学生信息
    path('admin/student/detail/', ad_student.student_detail),
    # -修改学生账号
    path('admin/student/edit/', ad_student.student_edit),
    # -删除学生账号
    path('admin/student/delete/', ad_student.student_delete),
    # -*获取后端学生账号密码
    path('admin/student/obtain/', ad_student.student_obtain),
    # -重置学生账号密码
    path('admin/student/resetPass/', ad_student.student_resetPass),
    # -下载【批量添加学生账号】模版
    path('admin/student/download/template/', ad_student.student_download_template),
    # -批量添加学生账号
    path('admin/student/multi/', ad_student.student_multi),
    # !*清空学生表
    path('admin/student/list/all_delete/', ad_student.all_delete),

    # *教师信息列表*
    # -显示教师列表
    path('admin/teacher/list/', ad_teacher.teacher_list),
    # -添加教师账号
    path('admin/teacher/add/', ad_teacher.teacher_add),
    # -*获取后端教师信息
    path('admin/teacher/detail/', ad_teacher.teacher_detail),
    # -修改教师账号
    path('admin/teacher/edit/', ad_teacher.teacher_edit),
    # -删除教师账号
    path('admin/teacher/delete/', ad_teacher.teacher_delete),
    # -*获取后端教师账号密码
    path('admin/teacher/obtain/', ad_teacher.teacher_obtain),
    # -重置教师账号密码
    path('admin/teacher/resetPass/', ad_teacher.teacher_resetPass),
    # -下载【批量添加教师账号】模版
    path('admin/teacher/download/template/', ad_teacher.teacher_download_template),
    # -批量添加教师账号
    path('admin/teacher/multi/', ad_teacher.teacher_multi),
    # !*清空教师表
    path('admin/teacher/list/all_delete/', ad_teacher.all_delete),

    # *班级信息列表*
    # -显示班级信息列表
    path('admin/classes/list/', ad_classes.classes_list),
    # -添加班级行
    path('admin/classes/add/', ad_classes.classes_add),
    # -*获取后端班级信息
    path('admin/classes/detail/', ad_classes.classes_detail),
    # -修改班级信息
    path('admin/classes/edit/', ad_classes.classes_edit),
    # -删除班级行
    path('admin/classes/delete/', ad_classes.classes_delete),
    # -下载【批量添加班级】模版
    path('admin/classes/download/template/', ad_classes.classes_download_template),
    # -批量添加班级行
    path('admin/classes/multi/', ad_classes.classes_multi),
    # !*清空班级表
    path('admin/classes/list/all_delete/', ad_classes.all_delete),

    # *学院信息列表*
    # -显示学院信息列表
    path('admin/college/list/', ad_college.college_list),
    # -添加学院行
    path('admin/college/add/', ad_college.college_add),
    # -*获取后端学院信息
    path('admin/college/detail/', ad_college.college_detail),
    # -修改学院信息
    path('admin/college/edit/', ad_college.college_edit),
    # -删除学院行
    path('admin/college/delete/', ad_college.college_delete),
    # -下载【批量添加学院】模版
    path('admin/college/download/template/', ad_college.college_download_template),
    # -批量添加学院行
    path('admin/college/multi/', ad_college.college_multi),

    # *专业信息列表*
    # -显示专业信息列表
    path('admin/major/list/', ad_major.major_list),
    # -添加专业行
    path('admin/major/add/', ad_major.major_add),
    # -*获取后端专业数据
    path('admin/major/detail/', ad_major.major_detail),
    # -修改专业信息
    path('admin/major/edit/', ad_major.major_edit),
    # -删除专业行
    path('admin/major/delete/', ad_major.major_delete),
    # -下载【批量添加专业】模版
    path('admin/major/download/template/', ad_major.major_download_template),
    # -批量添加专业行
    path('admin/major/multi/', ad_major.major_multi),

    # *学生部门列表*
    # -显示学生部门列表
    path('admin/department/list/', ad_department.department_list),
    # -添加学生部门行
    path('admin/department/add/', ad_department.department_add),
    # -*获取后端学生部门数据
    path('admin/department/detail/', ad_department.department_detail),
    # -修改学生部门信息
    path('admin/department/edit/', ad_department.department_edit),
    # -删除学生部门行
    path('admin/department/delete/', ad_department.department_delete),

    # *团学干部列表*
    path('admin/leagueCadres/list/', ad_leagueCadres.leagueCadres_list),
    # -添加学生部门行
    path('admin/leagueCadres/add/', ad_leagueCadres.leagueCadres_add),
    # -*获取后端学生部门数据
    path('admin/leagueCadres/detail/', ad_leagueCadres.leagueCadres_detail),
    # -修改学生部门信息
    path('admin/leagueCadres/edit/', ad_leagueCadres.leagueCadres_edit),
    # -删除学生部门行
    path('admin/leagueCadres/delete/', ad_leagueCadres.leagueCadres_delete),

    # *班委列表*
    path('admin/classCommittee/list/', ad_classCommittee.classCommittee_list),
    # -添加学生部门行
    path('admin/classCommittee/add/', ad_classCommittee.classCommittee_add),
    # -*获取后端学生部门数据
    path('admin/classCommittee/detail/', ad_classCommittee.classCommittee_detail),
    # -修改学生部门信息
    path('admin/classCommittee/edit/', ad_classCommittee.classCommittee_edit),
    # -删除学生部门行
    path('admin/classCommittee/delete/', ad_classCommittee.classCommittee_delete),

    # *楼栋信息列表*
    # -显示楼栋信息列表

    # ----- 学生账号模块 ------
    # -显示学生个人主页
    path('student/users/profile/', st_users_profile.student_users_profile),
    # -修改学生密码
    path('student/users/change/password/', st_users_profile.student_change_password),

    # -显示所在班级的学生列表
    path('student/classes/list/', st_classes_list.classes_list),





    # ----- 教师账号模块 ------
    # -显示教师本人基本信息
    path('teacher/basic/', te_basic.teacher_basic),

]

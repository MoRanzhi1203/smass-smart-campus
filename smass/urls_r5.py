"""R5 隔离 URL：学年/学期/课程/教学班/工作台/我的课程 + 统一数据导入。"""
from django.urls import path

from r21_account import views as r21_views
from smass_academic import views
from smass_data_exchange import views as exchange_views

urlpatterns = [
    path('r5/login/', r21_views.login_view, name='r5_login'),
    path('r5/logout/', r21_views.logout_view, name='r5_logout'),

    path('r5/health/', views.health, name='r5_health'),

    path('r5/years/', views.year_list, name='r5_year_list'),
    path('r5/years/create/', views.year_create, name='r5_year_create'),
    path('r5/years/<int:pk>/activate/', views.year_activate, name='r5_year_activate'),

    path('r5/terms/', views.term_list, name='r5_term_list'),
    path('r5/terms/create/', views.term_create, name='r5_term_create'),

    path('r5/courses/', views.course_list, name='r5_course_list'),
    path('r5/courses/create/', views.course_create, name='r5_course_create'),

    path('r5/sections/', views.section_list, name='r5_section_list'),
    path('r5/sections/create/', views.section_create, name='r5_section_create'),

    path('r5/workspace/', views.teacher_workspace, name='r5_teacher_workspace'),
    path('r5/sections/<int:pk>/roster/', views.section_roster, name='r5_section_roster'),

    path('r5/my-courses/', views.my_sections, name='r5_my_sections'),

    # ------------------------------------------------------------------
    # S25 统一数据交换中心（R5 的学年/学期/课程/教学班/选课五类模板与导入）
    # ------------------------------------------------------------------
    path('exchange/', exchange_views.exchange_home, name='exchange_home'),
    path('exchange/template/<str:dataset>/', exchange_views.template_download,
         name='exchange_template'),
    path('exchange/import/<str:dataset>/', exchange_views.import_page,
         name='exchange_import'),
    path('exchange/preview/<str:dataset>/', exchange_views.api_preview,
         name='exchange_preview'),
    path('exchange/commit/<str:dataset>/', exchange_views.api_commit,
         name='exchange_commit'),
    path('exchange/errors/<str:dataset>/<int:job_id>/', exchange_views.error_download,
         name='exchange_errors'),
    path('exchange/history/<str:dataset>/', exchange_views.job_history,
         name='exchange_history'),
    path('exchange/export/<str:dataset>/', exchange_views.export_view,
         name='exchange_export'),
]

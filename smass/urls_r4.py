"""R4 隔离 URL：组织与档案的最小可用页面/接口。"""
from django.urls import path

from r21_account import views as r21_views

from smass_data_exchange import views as exchange_views
from smass_organization import views

urlpatterns = [
    # R4 浏览器 E2E 需要登录入口（复用 R2.1 统一认证）
    path('r4/login/', r21_views.login_view, name='r4_login'),
    path('r4/logout/', r21_views.logout_view, name='r4_logout'),
    path('r4/units/', views.unit_list, name='r4_unit_list'),
    path('r4/units/tree/', views.unit_tree, name='r4_unit_tree'),
    path('r4/units/create/', views.unit_create, name='r4_unit_create'),
    path('r4/units/<int:pk>/move/', views.unit_move, name='r4_unit_move'),
    path('r4/students/', views.student_list, name='r4_student_list'),
    path('r4/students/export/', views.student_export, name='r4_student_export'),
    path('r4/students/<str:student_no>/', views.student_detail, name='r4_student_detail'),
    path('r4/import/preview/', views.import_preview_view, name='r4_import_preview'),
    path('r4/import/commit/', views.import_commit_view, name='r4_import_commit'),
    path('r4/health/', views.health, name='r4_health'),

    # ------------------------------------------------------------------
    # S25 统一数据交换中心：模板下载 / 上传预检 / 提交 / 错误 / 历史 / 导出
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

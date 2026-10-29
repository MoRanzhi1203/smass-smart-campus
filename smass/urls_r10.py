"""R10 隔离 URL：统一外壳 + 各模块路由汇合。"""
from django.urls import path
from django.views.generic import RedirectView

from r21_account import views as r21_views
from smass_academic import ui_views as r5_ui
from smass_operations import ui_views, views as ops_views
from smass_organization import ui_views as r4_ui
from smass_workflow import ui_views as r6_ui

from smass.urls_r4 import urlpatterns as r4_patterns
from smass.urls_r5 import urlpatterns as r5_patterns
from smass.urls_r6 import urlpatterns as r6_patterns
from smass.urls_r7 import urlpatterns as r7_patterns
from smass.urls_r8 import urlpatterns as r8_patterns
from smass.urls_r9 import urlpatterns as r9_patterns

urlpatterns = [
    path('r10/', ops_views.nav_home, name='r10_home'),

    # 统一身份入口
    path('r21/login/', r21_views.login_view, name='r21_login'),
    path('r21/logout/', r21_views.logout_view, name='r21_logout'),
    path('r21/home/', RedirectView.as_view(url='/r10/', permanent=False),
         name='r21_home'),
    path('r21/change-password/', RedirectView.as_view(url='/r10/', permanent=False),
         name='r21_change_password_redirect'),

    # U3：R4
    path('r4/units/new/', r4_ui.unit_new, name='r4_unit_new'),
    path('r4/units/<int:pk>/edit/', r4_ui.unit_edit, name='r4_unit_edit'),
    path('r4/students/<str:student_no>/edit/', r4_ui.student_edit, name='r4_student_edit'),
    path('r4/students/<str:student_no>/', r4_ui.student_detail_page, name='r4_student_detail_page'),
    path('r4/import/', ui_views.import_page, name='r4_import_page'),
    path('r4/import/preview/', ui_views.import_preview, name='r4_import_preview_ui'),
    path('r4/import/commit/', r4_ui.import_commit_page, name='r4_import_commit_ui'),

    # U4：R5
    path('r5/years/new/', r5_ui.year_new, name='r5_year_new'),
    path('r5/terms/new/', r5_ui.term_new, name='r5_term_new'),
    path('r5/courses/new/', r5_ui.course_new, name='r5_course_new'),
    path('r5/sections/new/', r5_ui.section_new, name='r5_section_new'),
    path('r5/sections/<int:pk>/assign/', r5_ui.section_assign, name='r5_section_assign'),
    path('r5/sections/<int:pk>/roster/<int:enrollment_id>/drop/',
         r5_ui.roster_drop, name='r5_roster_drop'),
    path('r5/sections/<int:pk>/roster/', r5_ui.section_roster_page, name='r5_roster_page'),
    path('r5/assignments/<int:pk>/revoke/', r5_ui.assignment_revoke, name='r5_assignment_revoke'),
    path('r5/enroll/', r5_ui.enroll_page, name='r5_enroll_page'),
    path('r5/enroll/<int:pk>/', r5_ui.enroll_action, name='r5_enroll_action'),
    path('r5/enrollments/<int:pk>/drop/', r5_ui.drop_action, name='r5_drop_action'),

    # U5：R6
    path('r6/definitions/new/', r6_ui.definition_new, name='r6_definition_new'),
    path('r6/definitions/<int:pk>/publish/', r6_ui.definition_publish, name='r6_definition_publish'),
    path('r6/definitions/<int:pk>/', r6_ui.definition_detail, name='r6_definition_detail'),
    path('r6/instances/new/', r6_ui.instance_new, name='r6_instance_new'),
    path('r6/instances/<int:pk>/', r6_ui.instance_detail, name='r6_instance_detail'),
    path('r6/instances/<int:pk>/action/', r6_ui.instance_action, name='r6_instance_action'),
    path('r6/tasks/<int:pk>/complete/', r6_ui.task_complete, name='r6_task_complete'),
    path('r6/tasks/', r6_ui.task_list_page, name='r6_task_list_page'),
    path('r6/notifications/<int:pk>/read/', r6_ui.notification_read, name='r6_notification_read'),
    path('r6/notifications/', r6_ui.notification_page, name='r6_notification_page'),

    # U7
    path('r8/docs/', ui_views.api_docs, name='r8_api_docs'),
    path('r9/status/', ui_views.ops_status, name='r9_ops_status'),
]

for patterns in (r4_patterns, r5_patterns, r6_patterns, r7_patterns,
                 r8_patterns, r9_patterns):
    urlpatterns += patterns

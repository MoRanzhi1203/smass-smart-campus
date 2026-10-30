"""R11 隔离 URL：排课规划与三张课表。"""
from django.urls import path

from r21_account import views as r21_views
from smass_scheduling import views

urlpatterns = [
    path('r11/login/', r21_views.login_view, name='r11_login'),
    path('r11/logout/', r21_views.logout_view, name='r11_logout'),

    # 教务规划
    path('r11/plan/', views.plan_page, name='r11_plan'),
    path('r11/plan/<int:run_id>/solve/', views.plan_solve, name='r11_plan_solve'),
    path('r11/plan/<int:run_id>/publish/', views.plan_publish, name='r11_plan_publish'),
    path('r11/plan/<int:run_id>/conflicts/', views.plan_conflicts,
         name='r11_plan_conflicts'),

    # 三张课表
    path('r11/timetable/student/', views.student_timetable,
         name='r11_student_timetable'),
    path('r11/timetable/teacher/', views.teacher_timetable,
         name='r11_teacher_timetable'),
    path('r11/timetable/room/<int:room_id>/', views.room_timetable,
         name='r11_room_timetable'),
    path('r11/timetable/mine.json', views.my_timetable_json,
         name='r11_my_timetable_json'),
]

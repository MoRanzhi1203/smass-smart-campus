"""R5 隔离 URL：学年/学期/课程/教学班/工作台/我的课程。"""
from django.urls import path

from r21_account import views as r21_views
from smass_academic import views

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
]

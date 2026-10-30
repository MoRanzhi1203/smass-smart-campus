"""教师工作台路由。"""
from django.urls import path

from .views import teacher as views

urlpatterns = [
    path('', views.home, name='teacher_home'),
    path('courses/', views.courses, name='teacher_courses'),
    path('sections/', views.sections, name='teacher_sections'),
    path('timetable/', views.timetable, name='teacher_timetable'),
    path('attendance/', views.attendance, name='teacher_attendance'),
    path('attendance/create/', views.attendance_create,
         name='teacher_attendance_create'),
    path('attendance/<int:pk>/', views.attendance_detail,
         name='teacher_attendance_detail'),
    path('attendance/<int:pk>/mark/', views.attendance_mark,
         name='teacher_attendance_mark'),
    path('attendance/<int:pk>/close/', views.attendance_close,
         name='teacher_attendance_close'),
    path('students/', views.students, name='teacher_students'),
    path('students/<int:pk>/', views.student_detail, name='teacher_student_detail'),
    path('approvals/', views.approvals, name='teacher_approvals'),
    path('approvals/leave/<int:pk>/<str:action>/', views.leave_action,
         name='teacher_leave_action'),
    path('approvals/makeup/<int:pk>/<str:action>/', views.makeup_action,
         name='teacher_makeup_action'),
    path('approvals/task/<int:pk>/complete/', views.task_complete,
         name='teacher_task_complete'),
    path('approvals/booking/<int:pk>/<str:action>/', views.booking_action,
         name='teacher_booking_action'),
    path('classes/', views.classes, name='teacher_classes'),
    path('counselor/students/', views.counselor_students,
         name='teacher_counselor_students'),
    path('counselor/leaves/', views.leave_review, name='teacher_leave_review'),
    path('notices/', views.notices, name='teacher_notices'),
]

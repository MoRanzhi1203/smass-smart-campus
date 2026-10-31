"""学生工作台路由。"""
from django.urls import path

from .views import student as views

urlpatterns = [
    path('', views.home, name='student_home'),
    path('timetable/', views.timetable, name='student_timetable'),
    path('courses/', views.courses, name='student_courses'),
    path('courses/<int:pk>/enroll/', views.course_enroll,
         name='student_course_enroll'),
    path('courses/enrollments/<int:pk>/drop/', views.course_drop,
         name='student_course_drop'),
    path('record/', views.record, name='student_record'),
    path('attendance/', views.attendance, name='student_attendance'),
    path('attendance/leave/', views.leave_submit, name='student_leave_submit'),
    path('attendance/leave/<int:pk>/cancel/', views.leave_cancel,
         name='student_leave_cancel'),
    path('fees/', views.fees, name='student_fees'),
    path('fees/<int:pk>/pay/', views.fee_pay, name='student_fee_pay'),
    path('bookings/', views.bookings, name='student_bookings'),
    path('bookings/create/', views.booking_create, name='student_booking_create'),
    path('bookings/<int:pk>/cancel/', views.booking_cancel,
         name='student_booking_cancel'),
    path('activities/', views.activities, name='student_activities'),
    path('activities/<int:pk>/register/', views.activity_register,
         name='student_activity_register'),
    path('activities/registrations/<int:pk>/cancel/', views.activity_cancel,
         name='student_activity_cancel'),
    path('volunteer/', views.volunteer, name='student_volunteer'),
    path('clubs/', views.clubs, name='student_clubs'),
    path('clubs/<int:pk>/apply/', views.club_apply, name='student_club_apply'),
    path('organizations/', views.organizations, name='student_organizations'),
    path('dormitory/', views.dormitory, name='student_dormitory'),
    path('notices/', views.notices, name='student_notices'),
]

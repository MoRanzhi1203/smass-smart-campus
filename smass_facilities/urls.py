"""R16 场地预约 URL（命名空间 ``r16``）。"""
from django.urls import path

from . import views

app_name = 'r16'

urlpatterns = [
    path('rooms/', views.room_list, name='rooms'),
    path('rooms/<int:pk>/', views.room_detail, name='room_detail'),
    path('rooms/<int:pk>/book/', views.create_booking, name='create_booking'),
    path('calendar/', views.shared_calendar, name='calendar'),
    path('bookings/', views.my_bookings, name='bookings'),
    path('bookings/<int:pk>/cancel/', views.cancel_booking, name='cancel_booking'),
    path('bookings/<int:pk>/checkin/', views.check_in, name='check_in'),
    path('bookings/<int:pk>/release/', views.release, name='release'),
    path('approvals/', views.approvals, name='approvals'),
    path('approvals/<int:pk>/approve/', views.approve, name='approve'),
    path('approvals/<int:pk>/reject/', views.reject, name='reject'),
]

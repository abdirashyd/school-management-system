from django.urls import path
from . import views

urlpatterns = [
    path('', views.user_notifications, name='user_notifications'),
    path('send/', views.send_notification, name='send_notification'),
    path('mark-read/<int:pk>/', views.mark_as_read, name='mark_as_read'),
    path('mark-all-read/', views.mark_all_as_read, name='mark_all_as_read'),
    path('delete/<int:pk>/', views.delete_notification, name='delete_notification'),
    path('unread-count/', views.unread_count_api, name='unread_count_api'),
    path('latest/', views.latest_notifications_api, name='latest_notifications_api'),
]
from django.urls import path
from . import views

urlpatterns = [
    path('all/', views.student_list_view, name='student_list'),
    path('profile/<int:pk>/', views.student_detail, name='students_detail'),
    path('attendance/', views.attendance_report, name='attendance_report'),
    path('delete/<int:pk>/', views.delete_student, name='delete_student'),
    path('promote/', views.promote_students, name='promote_students'),
]
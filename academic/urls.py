from django.urls import path
from . import views

urlpatterns = [
    # Teacher URLs
    path('teachers/', views.teacher_list, name='teacher_list'),
    path('delete-teacher/<int:pk>/', views.delete_teacher, name='delete_teacher'),
    
    # Classroom URLs
    path('classroom/', views.classroom_list, name='classroom_list'),
    path('classroom/add/', views.add_classroom, name='add_classroom'),
    
    # Subject URLs
    path('subject/', views.subject_list, name='subject_list'),
    path('subject/add/', views.add_subject, name='add_subject'),
    
    # Exam URLs
    path('exam/', views.exam_list, name='exam_list'),
    path('exam/add/', views.add_exam, name='add_exam'),
    
    # Results URLs
    path('results/add/', views.add_results, name='add_results'),
    path('class-results/', views.class_results, name='class_results'),
    path('report-card/', views.report_card, name='report_card'),
    path('download-pdf/<str:identifier>/<int:exam_id>/', views.download_results_pdf, name='download_results_pdf'),  # ✅ ADD THIS
    
    # Results Approval
    path('pending-approvals/', views.pending_approvals, name='pending_approvals'),
    path('submission-dashboard/', views.submission_dashboard, name='submission_dashboard'),
    path('publish-all-results/', views.publish_all_results, name='publish_all_results'),
    
    # Allocations
    path('allocations/', views.subject_allocations, name='subject_allocations'),
    path('my-allocations/', views.my_allocations, name='my_allocations'),
]
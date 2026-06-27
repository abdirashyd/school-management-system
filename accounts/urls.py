from django.urls import path
from .views import (
    dashboard_view, login_view, register_teacher_view, register_student_view,
    school_payment_settings, test_mpesa_connection, register_head_teacher,
    user_list_view, admin_reset_password, logout_view, register_parents,
    check_toast, edit_profile, offline_page, register_page, delete_user,
    change_password, super_admin_schools_list, super_admin_add_school,
    super_admin_school_detail, super_admin_delete_school, register_admin_view,
    subscription_dashboard, initiate_subscription_payment, check_subscription_payment,
    subscription_mpesa_callback,manual_subscription_payment,confirm_subscription_payment,profile_view,check_auth,landing_page
)

urlpatterns = [
    path('', landing_page, name='landing'),
    path('dashboard/', dashboard_view, name='dashboard'),  # ← ADD THIS
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('register-teacher/', register_teacher_view, name='register_teacher'),
    path('register-student/', register_student_view, name='register_students'),
    path('register-parents/', register_parents, name='register_parents'),
    path('register-head-teacher/', register_head_teacher, name='register_head_teacher'),
    path('register/', register_page, name='register_page'),
    path('user-list/', user_list_view, name='user_list'),
    path('reset-password/<int:user_id>/', admin_reset_password, name='admin_reset_password'),
    path('delete-user/<int:user_id>/', delete_user, name='delete_user'),
    path('change-password/', change_password, name='change_password'),
    path('schools/', super_admin_schools_list, name='super_admin_schools'),
    path('schools/add/', super_admin_add_school, name='super_admin_add_school'),
    path('schools/<int:school_id>/', super_admin_school_detail, name='super_admin_school_detail'),
    path('schools/delete/<int:school_id>/', super_admin_delete_school, name='super_admin_delete_school'),
    path('register-admin/', register_admin_view, name='register_admin'),
    path('edit-profile/', edit_profile, name='edit_profile'),
    path('check-toast/', check_toast, name='check_toast'),
    path('payment-settings/', school_payment_settings, name='school_payment_settings'),
    path('test-mpesa/', test_mpesa_connection, name='test_mpesa_connection'),
    path('subscription/', subscription_dashboard, name='subscription_dashboard'),
    path('initiate-subscription-payment/', initiate_subscription_payment, name='initiate_subscription_payment'),
    path('check-subscription-payment/<int:payment_id>/', check_subscription_payment, name='check_subscription_payment'),
    path('subscription-mpesa-callback/', subscription_mpesa_callback, name='subscription_mpesa_callback'),
    path('offline/', offline_page, name='offline_page'),
    path('manual-subscription-payment/', manual_subscription_payment, name='manual_subscription_payment'),
    path('confirm-subscription-payment/<int:school_id>/', confirm_subscription_payment, name='confirm_subscription_payment'),
    path('profile/', profile_view, name='profile'),
    path('api/check-auth/', check_auth, name='check_auth'),


]
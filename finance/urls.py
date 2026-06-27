from django.urls import path
from . import views

urlpatterns = [
    # Payment URLs
    path('payment/', views.payement_detail, name='payement_detail'),
    path('process-payment/', views.process_payment, name='process_payment'),
    
    # M-Pesa URLs
    path('mpesa/pay/', views.mpesa_payment, name='mpesa_payment'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    
    # Receipt URL
    path('receipt/<int:payment_id>/', views.download_payment_receipt, name='download_payment_receipt'),
    
    # Bank Payment URLs
    path('bank-payment/', views.bank_payment_instructions, name='bank_payment_instructions'),
    path('upload-proof/', views.upload_payment_proof, name='upload_payment_proof'),

    # Status check URLs (no duplicates)
    path('check-payment-status/<int:payment_id>/', views.check_payment_status, name='check_payment_status'),
    path('delete-pending-payment/<int:payment_id>/', views.delete_pending_payment, name='delete_pending_payment'),

    path('finance-dashboard/', views.finance_dashboard, name='finance_dashboard'),
]
# finance/mpesa_views.py

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .mpesa_utility import stk_push
from .models import Payement
from students.models import Students
import json
import datetime


@login_required
def mpesa_payment_view(request):
    """Handle M-Pesa STK Push - Automatic payment"""
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        amount = request.POST.get('amount')
        reg_number = request.POST.get('reg_number')
        month = request.POST.get('month')
        
        if not all([phone_number, amount, reg_number, month]):
            messages.error(request, "Please fill all fields.")
            return redirect('payement_detail')
        
        # Find student
        try:
            student = Students.objects.get(registration_number=reg_number)
        except Students.DoesNotExist:
            messages.error(request, f"Student '{reg_number}' not found!")
            return redirect('payement_detail')
        
        # Create pending payment record
        payment = Payement.objects.create(
            student=student,
            amount_paid=amount,
            reference=f"PENDING_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
            method='M-Pesa',
            month=int(month),
            year=datetime.datetime.now().year,
            recorded_by=request.user if request.user.is_authenticated else None
        )
        
        # Initiate STK Push
        result = stk_push(
            phone_number=phone_number,
            amount=amount,
            reg_number=reg_number,
            transaction_desc=f"Fee payment for {student.first_name} {student.last_name}"
        )
        
        print(f"STK Push Result: {result}")  # Debugging
        
        if result.get('ResponseCode') == '0':
            # Update payment with checkout request ID
            checkout_id = result.get('CheckoutRequestID')
            if checkout_id:
                payment.reference = checkout_id
                payment.save()
            messages.success(request, "M-Pesa prompt sent! Check your phone and enter your PIN.")
        else:
            payment.delete()  # Remove pending payment
            error_msg = result.get('errorMessage', result.get('ResponseDescription', 'Payment failed'))
            messages.error(request, f"Payment failed: {error_msg}")
        
        return redirect('payement_detail')
    
    return redirect('payement_detail')


@csrf_exempt
def mpesa_callback(request):
    """M-Pesa callback URL - Updates payment when confirmed"""
    print("=" * 50)
    print("M-PESA CALLBACK RECEIVED")
    print("=" * 50)
    
    try:
        # Log the raw request body
        raw_body = request.body.decode('utf-8')
        print(f"Raw body: {raw_body}")
        
        data = json.loads(raw_body)
        print(f"Parsed data: {data}")
        
        body = data.get('Body', {})
        stk_callback = body.get('stkCallback', {})
        result_code = stk_callback.get('ResultCode')
        result_desc = stk_callback.get('ResultDesc')
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        
        print(f"Result Code: {result_code}")
        print(f"Result Desc: {result_desc}")
        print(f"Checkout ID: {checkout_request_id}")
        
        if result_code == 0:
            # Payment successful
            callback_metadata = stk_callback.get('CallbackMetadata', {})
            items = callback_metadata.get('Item', [])
            
            mpesa_receipt = None
            amount = None
            
            for item in items:
                if item.get('Name') == 'MpesaReceiptNumber':
                    mpesa_receipt = item.get('Value')
                elif item.get('Name') == 'Amount':
                    amount = item.get('Value')
            
            print(f"✅ Payment Successful! Receipt: {mpesa_receipt}, Amount: {amount}")
            
            # Update payment record
            payment = Payement.objects.filter(reference=checkout_request_id).first()
            if payment:
                payment.reference = mpesa_receipt
                payment.save()
                print(f"✅ Updated payment: {payment.id}")
                
                # Send notifications
                try:
                    from notification.models import Notification
                    
                    # Notify student
                    if payment.student and payment.student.user:
                        Notification.objects.create(
                            recipient=payment.student.user,
                            sender=None,
                            title="✅ Payment Successful",
                            message=f"KES {amount:,.2f} payment confirmed. Receipt: {mpesa_receipt}",
                            notification_type='FEE'
                        )
                    
                    # Notify parent
                    if payment.student and payment.student.parents:
                        Notification.objects.create(
                            recipient=payment.student.parents,
                            sender=None,
                            title=f"✅ Payment Successful - {payment.student.first_name}",
                            message=f"KES {amount:,.2f} payment confirmed. Receipt: {mpesa_receipt}",
                            notification_type='FEE'
                        )
                    print("✅ Notifications sent")
                except Exception as e:
                    print(f"Notification error: {e}")
            else:
                print(f"❌ Payment not found for checkout ID: {checkout_request_id}")
        
        else:
            # Payment failed
            print(f"❌ Payment Failed: {result_desc}")
            
            # Delete pending payment
            payment = Payement.objects.filter(reference=checkout_request_id).first()
            if payment:
                payment.delete()
                print(f"❌ Deleted failed payment: {checkout_request_id}")
        
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Success"})
        
    except Exception as e:
        print(f"❌ Callback error: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)})
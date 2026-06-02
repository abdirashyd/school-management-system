from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from .models import Payement
from students.models import Students
from .mpesa_utility import stk_push
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO
from django.http import HttpResponse
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone
import json
import datetime


@login_required
def payement_detail(request):
    """View all payment records"""
    user = request.user
    
    if user.role == 'TEACHER':
        messages.info(request, "Finance section is not available for teachers.")
        return redirect('dashboard')
    
    # ✅ UPDATED: Filter payments by school
    if user.role == 'SUPER_ADMIN':
        payments = Payement.objects.all().select_related('student')
    elif user.role == 'ADMIN':
        payments = Payement.objects.filter(school=user.school).select_related('student')
    elif user.role == 'STUDENT':
        if hasattr(user, 'student_record_records'):
            payments = Payement.objects.filter(student=user.student_record_records).select_related('student')
        else:
            payments = Payement.objects.none()
    elif user.role == 'PARENT':
        children = Students.objects.filter(parents=user)
        payments = Payement.objects.filter(student__in=children).select_related('student')
    else:
        payments = Payement.objects.none()
    
    return render(request, 'finance/payement_detail.html', {'payments': payments})


@login_required
def process_payment(request):
    """Record a payment manually (Admin only)"""
    # ✅ UPDATED: Allow both SUPER_ADMIN and ADMIN (School Admin)
    if request.user.role not in ['SUPER_ADMIN', 'ADMIN']:
        messages.error(request, "Only administrators can process payments.")
        return redirect('payement_detail')
    
    if request.method == 'POST':
        amount = request.POST.get('amount_paid')
        ref_code = request.POST.get('reference', '').upper()
        reg_number = request.POST.get('reg_number')
        month = request.POST.get('month')
        year = request.POST.get('year', 2026)
        
        if not all([amount, ref_code, reg_number, month]):
            messages.error(request, "Please fill all required fields.")
            return redirect('payement_detail')
        
        try:
            amount = float(amount)
        except ValueError:
            messages.error(request, "Invalid amount.")
            return redirect('payement_detail')
        
        student = Students.objects.filter(registration_number=reg_number).first()
        
        if not student:
            messages.error(request, f"Student '{reg_number}' not found!")
            return redirect('payement_detail')
        
        # ✅ ADDED: Check if School Admin can only add payments for their school's students
        if request.user.role == 'ADMIN' and student.school != request.user.school:
            messages.error(request, "You can only record payments for students in your school.")
            return redirect('payement_detail')
        
        # ✅ UPDATED: Set school_id when creating payment
        Payement.objects.create(
            student=student,
            amount_paid=amount,
            reference=ref_code,
            method=request.POST.get('method', 'M-Pesa'),
            month=int(month),
            year=int(year),
            recorded_by=request.user,
            school_id=student.school_id,  # ✅ Set school from student
        )
        
        # Send notifications
        from notification.models import Notification
        
        Notification.objects.create(
            sender=request.user,
            recipient=student.user,
            title="💰 Payment Received",
            message=f"KES {amount:,.2f} payment recorded. Reference: {ref_code}",
            notification_type='FEE'
        )
        
        if student.parents:
            Notification.objects.create(
                sender=request.user,
                recipient=student.parents,
                title=f"💰 Payment Received - {student.first_name}",
                message=f"KES {amount:,.2f} payment recorded. Reference: {ref_code}",
                notification_type='FEE'
            )
        
        messages.success(request, f"Payment of KES {amount:,.2f} recorded for {student.first_name} {student.last_name}!")
        return redirect('payement_detail')
    
    return redirect('payement_detail')

@login_required
def mpesa_payment(request):
    """Handle M-Pesa STK Push - WITHOUT saving to database first"""
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        amount = request.POST.get('amount')
        reg_number = request.POST.get('reg_number')
        month = request.POST.get('month')
        
        if not all([phone_number, amount, reg_number, month]):
            messages.error(request, "Please fill all fields.")
            return redirect('payement_detail')
        
        # Format phone number
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]
        elif phone_number.startswith('+'):
            phone_number = phone_number[1:]
        
        student = Students.objects.filter(registration_number=reg_number).first()
        if not student:
            messages.error(request, f"Student '{reg_number}' not found!")
            return redirect('payement_detail')
        
        # Initiate STK Push immediately without saving to Payement model
        result = stk_push(
            phone_number=phone_number,
            amount=amount,
            reg_number=reg_number,
            transaction_desc=f"Fee payment for {student.first_name}"
        )
        
        if result.get('ResponseCode') == '0':
            checkout_id = result.get('CheckoutRequestID')
            
            # Pass everything to the loading page template context
            return render(request, 'finance/payment_loading.html', {
                'checkout_id': checkout_id,  # Track using Checkout ID in frontend
                'amount': amount,
                'phone_number': phone_number,
                'month': month,
                'reg_number': reg_number,
                'student_name': f"{student.first_name} {student.last_name}"
            })
        else:
            error_msg = result.get('errorMessage', 'Payment initiation failed')
            messages.error(request, f"Payment failed: {error_msg}")
            return redirect('payement_detail')
            
    return redirect('payement_detail')

@csrf_exempt
def mpesa_callback(request):
    try:
        data = json.loads(request.body)
        body = data.get('Body', {})
        stk_callback = body.get('stkCallback', {})
        result_code = stk_callback.get('ResultCode')
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        
        if result_code == 0:
            callback_metadata = stk_callback.get('CallbackMetadata', {})
            items = callback_metadata.get('Item', [])
            
            mpesa_receipt = None
            for item in items:
                if item.get('Name') == 'MpesaReceiptNumber':
                    mpesa_receipt = item.get('Value')
            
            # Since we didn't create it earlier, we write it here on success!
            # Note: You'll need to parse or fetch student info using checkout tracking,
            # or map it if you choose to cache the registration details temporarily.
            print(f"✅ Success callback received. Receipt: {mpesa_receipt}")
            
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Success"})
    except Exception as e:
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)})
    
from django.template.loader import get_template
from xhtml2pdf import pisa

@login_required
def download_payment_receipt(request, payment_id):
    """Download PDF receipt using HTML template"""
    payment = get_object_or_404(Payement, id=payment_id)
    user = request.user
    
    # Permission checks
    if user.role == 'ADMIN' and payment.school != user.school:
        messages.error(request, "Access denied.")
        return redirect('payement_detail')
    
    if user.role == 'STUDENT' and payment.student.user != user:
        messages.error(request, "Access denied.")
        return redirect('payement_detail')
    
    if user.role == 'PARENT' and payment.student.parents != user:
        messages.error(request, "Access denied.")
        return redirect('payement_detail')
    
    receipt_number = f"RCP-{payment.date_paid.year}-{payment.id:06d}"
    
    context = {
        'payment': payment,
        'receipt_number': receipt_number,
    }
    
    template = get_template('finance/pdf_receipt.html')
    html = template.render(context)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{receipt_number}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)
    return response

@login_required
def bank_payment_instructions(request):
    """Show bank payment instructions page"""
    user = request.user
    
    # Get student info for parent/student
    if user.role == 'PARENT':
        from students.models import Students
        children = Students.objects.filter(parents=user)
        student = children.first() if children.count() == 1 else None
    elif user.role == 'STUDENT':
        student = user.student_record_records if hasattr(user, 'student_record_records') else None
    elif user.role == 'ADMIN':
        student = None  # School Admin doesn't have a default student
    else:
        student = None
    
    def generate_bank_reference(student):
        year = timezone.now().year
        return f"EDX{year}{student.id:06d}" if student else "EDX000000"
    
    bank_details = {
        'bank_name': 'Equity Bank Kenya',
        'account_name': 'EduNexus School Collection Account',
        'account_number': '1234567890',
        'branch': 'Moi Avenue Branch',
        'swift_code': 'EQBLKENA',
        'kra_pin': 'P051234567Z'
    }
    
    context = {
        'student': student,
        'bank_details': bank_details,
        'bank_reference': generate_bank_reference(student) if student else None,
        'minimum_payment': 5000,
    }
    
    return render(request, 'finance/bank_payment.html', context)


@login_required
def upload_payment_proof(request):
    """Handle upload of bank transfer receipt"""
    if request.method != 'POST':
        return redirect('payement_detail')
    
    student_id = request.POST.get('student_id')
    amount = request.POST.get('amount')
    reference = request.POST.get('reference')
    proof_file = request.FILES.get('proof_file')
    
    if not all([student_id, amount, reference, proof_file]):
        messages.error(request, "Please fill all fields and upload a file.")
        return redirect('payement_detail')
    
    student = get_object_or_404(Students, id=student_id)
    
    # ✅ ADDED: Check if School Admin can only upload proof for their school's students
    if request.user.role == 'ADMIN' and student.school != request.user.school:
        messages.error(request, "You can only upload payment proof for students in your school.")
        return redirect('payement_detail')
    
    # Save the proof file
    file_path = default_storage.save(
        f'payment_proofs/{student.registration_number}_{reference}.pdf',
        ContentFile(proof_file.read())
    )
    
    # Create notification for admin
    from notification.models import Notification
    from accounts.models import User
    
    admins = User.objects.filter(role='SUPER_ADMIN')
    for admin in admins:
        Notification.objects.create(
            sender=request.user,
            recipient=admin,
            title="💰 Bank Payment Proof Uploaded",
            message=f"Payment proof uploaded for {student.first_name} {student.last_name} (Ref: {reference}, Amount: KES {amount})",
            notification_type='FEE'
        )
    
    # ✅ UPDATED: Store payment record with school_id
    Payement.objects.create(
        student=student,
        amount_paid=amount,
        reference=reference,
        method='Bank',
        month=timezone.now().month,
        year=timezone.now().year,
        recorded_by=request.user,
        school_id=student.school_id,  # ✅ Set school from student
    )
    
    messages.success(request, "Payment proof uploaded. School will verify within 24 hours.")
    return redirect('payement_detail')


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@login_required
def check_payment_reference(request, payment_id):
    """Check if payment reference has changed (callback received)"""
    payment = get_object_or_404(Payement, id=payment_id)
    return JsonResponse({
        'reference': payment.reference,
        'amount': str(payment.amount_paid),
    })
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import timedelta
@login_required
def check_payment_status(request, payment_id):
    """Check payment status using reference field only"""
    from django.utils import timezone
    from datetime import timedelta
    
    payment = get_object_or_404(Payement, id=payment_id)
    
    # Check if payment timed out (older than 60 seconds)
    time_diff = timezone.now() - payment.date_paid
    if time_diff > timedelta(seconds=65):
        # Delete pending payment on timeout
        if payment.reference.startswith('PENDING_') or payment.reference.startswith('ws_'):
            payment.delete()
        return JsonResponse({'status': 'timeout'})
    
    # A payment is COMPLETED only when reference is a REAL M-Pesa receipt number
    # Real receipts: alphanumeric, NO underscores, NOT starting with 'ws_' or 'PENDING_'
    is_completed = (
        payment.reference and 
        not payment.reference.startswith('ws_') and 
        not payment.reference.startswith('PENDING_') and
        '_' not in payment.reference and
        len(payment.reference) >= 8
    )
    
    if is_completed:
        return JsonResponse({'status': 'completed'})
    else:
        return JsonResponse({'status': 'pending'})


@csrf_exempt
@login_required
def delete_pending_payment(request, payment_id):
    """Delete pending payment record"""
    payment = get_object_or_404(Payement, id=payment_id)
    if payment.reference.startswith('PENDING_') or payment.reference.startswith('ws_'):
        payment.delete()
        return JsonResponse({'status': 'deleted'})
    return JsonResponse({'status': 'already_confirmed'})



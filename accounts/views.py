from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from .models import User,School
from academic.models import Classroom, Teacher, Subject
from students.models import Students
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.db import models
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from finance.models import Payement  # Add this line


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
import json
import base64
import requests

from .models import User, School, SchoolSubscription, SubscriptionPayment, SchoolMpesaConfig, SubscriptionInvoice
from finance.mpesa_utility import stk_push  # Your existing M-Pesa utility


# accounts/views.py
from django.http import JsonResponse

@login_required
def check_auth(request):
    """API endpoint to check if user is authenticated"""
    return JsonResponse({
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else None,
    })


def landing_page(request):
    """
    Landing page - Shows when user is not logged in
    - Logged in users → Redirect to dashboard
    - PWA users → Download button hidden (CSS handles this)
    - Browser users → Download button visible
    """
    
    # If user is already logged in, redirect to dashboard
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    # Get real-time stats
    from django.db.models import Count
    from students.models import Students
    from academic.models import Teacher, Classroom
    from .models import School
    
    total_schools = School.objects.filter(is_active=True).count()
    total_students = Students.objects.filter(is_active=True).count()
    total_teachers = Teacher.objects.count()
    
    context = {
        'total_schools': total_schools,
        'total_students': total_students,
        'total_teachers': total_teachers,
    }
    
    return render(request, 'accounts/landing.html', context)

@login_required
def subscription_dashboard(request):
    """School Admin - View subscription status and pay"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    subscription = request.user.school.subscription
    student_count = subscription.get_student_count()
    monthly_fee = subscription.calculate_monthly_fee()
    termly_fee = monthly_fee * 3
    annual_fee = monthly_fee * 9
    
    # Get status message
    days_left = subscription.days_until_expiry() if hasattr(subscription, 'days_until_expiry') else 0
    
    if subscription.status == 'PENDING':
        status_msg = {
            'type': 'warning',
            'title': ' Awaiting First Payment',
            'message': f'Please pay KES {subscription.get_current_fee():,.0f} to activate your subscription.',
        }
    elif subscription.status == 'ACTIVE':
        if days_left <= 3 and days_left > 0:
            status_msg = {
                'type': 'warning',
                'title': '⚠️ Subscription Ending Soon',
                'message': f'Your subscription ends in {days_left} days. Please renew.',
            }
        else:
            status_msg = {
                'type': 'success',
                'title': ' Subscription Active',
                'message': f'Next billing: {subscription.next_billing_date.strftime("%d/%m/%Y") if subscription.next_billing_date else "Not set"}',
            }
    elif subscription.status == 'OVERDUE':
        status_msg = {
            'type': 'danger',
            'title': ' Payment Overdue',
            'message': 'Your subscription payment is overdue. Please pay immediately.',
        }
    else:
        status_msg = {
            'type': 'critical',
            'title': ' Subscription Suspended',
            'message': 'Your subscription has been suspended. Please contact support.',
        }
    
    # Get payment history
    payments = SubscriptionPayment.objects.filter(school=request.user.school).order_by('-created_at')[:10]
    
    context = {
        'subscription': subscription,
        'status_msg': status_msg,
        'student_count': student_count,
        'monthly_fee': monthly_fee,
        'termly_fee': termly_fee,
        'annual_fee': annual_fee,
        'payments': payments,
    }
    return render(request, 'accounts/subscription_dashboard.html', context)


@login_required
def initiate_subscription_payment(request):
    """Initiate M-Pesa payment for subscription"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        billing_cycle = request.POST.get('billing_cycle')
        
        subscription = request.user.school.subscription
        
        # Update billing cycle if changed
        if subscription.billing_cycle != billing_cycle:
            subscription.billing_cycle = billing_cycle
            subscription.save()
        
        amount = subscription.get_current_fee()
        
        # Create payment record
        payment = SubscriptionPayment.objects.create(
            subscription=subscription,
            school=request.user.school,
            amount=amount,
            billing_cycle=billing_cycle,
            period_start=subscription.current_period_end or timezone.now(),
            period_end=None,
            status='PENDING',
        )
        
        # Format phone number
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]
        elif phone_number.startswith('+'):
            phone_number = phone_number[1:]
        
        # Use YOUR M-Pesa credentials (from settings)
        result = stk_push(
            phone_number=phone_number,
            amount=amount,
            reg_number=request.user.school.code,
            transaction_desc=f"EduNexus Subscription - {request.user.school.name}"
        )
        
        if result.get('ResponseCode') == '0':
            checkout_id = result.get('CheckoutRequestID')
            payment.transaction_id = checkout_id
            payment.save()
            
            # Store in session for callback
            request.session['pending_subscription_payment'] = payment.id
            
            return render(request, 'accounts/subscription_loading.html', {
                'payment_id': payment.id,
                'amount': amount,
                'phone_number': phone_number,
                'school_name': request.user.school.name,
            })
        else:
            payment.delete()
            messages.error(request, "Payment initiation failed. Please try again.")
            return redirect('subscription_dashboard')
    
    return redirect('subscription_dashboard')


@login_required
def check_subscription_payment(request, payment_id):
    """Check subscription payment status (AJAX)"""
    payment = get_object_or_404(SubscriptionPayment, id=payment_id)
    return JsonResponse({'status': payment.status.lower()})


@csrf_exempt
def subscription_mpesa_callback(request):
    """M-Pesa callback for subscription payments"""
    try:
        data = json.loads(request.body)
        body = data.get('Body', {})
        stk_callback = body.get('stkCallback', {})
        result_code = stk_callback.get('ResultCode')
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        
        if result_code == 0:
            # Payment successful
            callback_metadata = stk_callback.get('CallbackMetadata', {})
            items = callback_metadata.get('Item', [])
            
            mpesa_receipt = None
            for item in items:
                if item.get('Name') == 'MpesaReceiptNumber':
                    mpesa_receipt = item.get('Value')
            
            payment = SubscriptionPayment.objects.filter(transaction_id=checkout_request_id).first()
            if payment:
                payment.mark_completed(checkout_request_id, mpesa_receipt)
                
                # Create invoice
                SubscriptionInvoice.objects.create(
                    school=payment.school,
                    subscription=payment.subscription,
                    invoice_number=f"INV-{payment.school.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    amount=payment.amount,
                    status='PAID',
                    billing_period_start=payment.period_start,
                    billing_period_end=payment.subscription.current_period_end,
                    due_date=timezone.now(),
                    paid_date=timezone.now(),
                    student_count_at_billing=payment.subscription.get_student_count(),
                    fee_breakdown={'billing_cycle': payment.billing_cycle},
                )
                
                print(f" Subscription payment completed for {payment.school.name}")
        
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Success"})
        
    except Exception as e:
        print(f"Callback error: {e}")
        return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)})


@login_required
def manual_subscription_payment(request):
    """Handle manual subscription payment request"""
    if request.user.role != 'ADMIN':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Access denied."})
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        billing_cycle = request.POST.get('billing_cycle')
        subscription = request.user.school.subscription
        
        # Update billing cycle
        subscription.billing_cycle = billing_cycle
        subscription.save()
        
        amount = subscription.get_current_fee()
        
        # Create a pending payment record (manual)
        payment = SubscriptionPayment.objects.create(
            subscription=subscription,
            school=request.user.school,
            amount=amount,
            billing_cycle=billing_cycle,
            period_start=timezone.now(),
            period_end=None,
            status='PENDING',
        )
        
        # Send notification to Super Admin
        from notification.models import Notification
        from accounts.models import User
        
        super_admins = User.objects.filter(role='SUPER_ADMIN')
        school_name = request.user.school.name
        admin_name = request.user.get_full_name() or request.user.username
        
        for admin in super_admins:
            Notification.objects.create(
                sender=request.user,
                recipient=admin,
                title=" New Subscription Payment Request",
                message=f"{admin_name} from {school_name} requests to pay KES {amount:,.0f} for {billing_cycle} plan. Please confirm payment.",
                notification_type='FEE'
            )
        
        # If AJAX request, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Request sent successfully'})
        
        # For regular form submission, show loading page
        plan_names = {
            'MONTHLY': 'Monthly Plan',
            'TERMLY': 'Termly Plan',
            'ANNUALLY': 'Annual Plan'
        }
        
        return render(request, 'accounts/subscription_loading.html', {
            'payment_type': 'manual',
            'amount': amount,
            'plan_name': plan_names.get(billing_cycle, billing_cycle),
        })
    
    return redirect('subscription_dashboard')

@login_required
def confirm_subscription_payment(request, school_id):
    """Super Admin - Confirm manual payment and activate school"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can confirm payments.")
        return redirect('dashboard')
    
    school = get_object_or_404(School, id=school_id)
    subscription = school.subscription
    
    # Update subscription status
    subscription.status = 'ACTIVE'
    subscription.is_first_month = False
    subscription.update_billing_dates()
    subscription.save()
    
    # Update any pending payments to completed
    SubscriptionPayment.objects.filter(
        school=school,
        status='PENDING'
    ).update(status='COMPLETED', paid_at=timezone.now())
    
    # ✅ SEND NOTIFICATION TO SCHOOL ADMIN
    from notification.models import Notification
    
    # Get the school admin
    school_admins = User.objects.filter(role='ADMIN', school=school)
    
    for admin in school_admins:
        Notification.objects.create(
            sender=request.user,
            recipient=admin,
            title="Subscription Activated",
            message=f"Your subscription payment has been confirmed. Your school is now active until {subscription.current_period_end.strftime('%d %b %Y')}.",
            notification_type='FEE'
        )
    
    messages.success(request, f"Subscription payment confirmed for {school.name}. School is now active.")
    return redirect('super_admin_school_detail', school_id=school_id)

# accounts/views.py - Add this view

@login_required
def super_admin_pending_payments(request):
    """Super Admin - View ALL pending subscription payments"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    pending_payments = SubscriptionPayment.objects.filter(
        status='PENDING'
    ).select_related('school', 'subscription').order_by('-created_at')
    
    # Also show overdue subscriptions
    overdue_schools = School.objects.filter(
        subscription__status='OVERDUE'
    ).select_related('subscription')
    
    return render(request, 'accounts/pending_payments.html', {
        'pending_payments': pending_payments,
        'overdue_schools': overdue_schools,
    })

from .models import SchoolMpesaConfig
from .forms import SchoolMpesaConfigForm
import requests
import base64
from django.http import JsonResponse

@login_required
def school_payment_settings(request):
    """School Admin - Configure their M-Pesa settings"""
    
    # Only School Admin can access
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    school = request.user.school
    config, created = SchoolMpesaConfig.objects.get_or_create(school=school)
    
    if request.method == 'POST':
        form = SchoolMpesaConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "M-Pesa settings saved successfully!")
            return redirect('school_payment_settings')
    else:
        form = SchoolMpesaConfigForm(instance=config)
    
    context = {
        'form': form,
        'config': config,
        'school': school,
    }
    return render(request, 'accounts/school_payment_settings.html', context)


@login_required
def test_mpesa_connection(request):
    """Test if school's M-Pesa credentials are valid"""
    
    if request.user.role != 'ADMIN':
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    school = request.user.school
    config = school.mpesa_config
    
    if not all([config.consumer_key, config.consumer_secret]):
        return JsonResponse({'success': False, 'message': 'Please enter Consumer Key and Consumer Secret first'})
    
    # Determine API URL
    if config.environment == 'sandbox':
        api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    else:
        api_url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    # Encode credentials
    credentials = f"{config.consumer_key}:{config.consumer_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    
    headers = {'Authorization': f'Basic {encoded}'}
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            config.is_configured = True
            config.last_tested = timezone.now()
            config.test_response = " Connection successful!"
            config.save()
            return JsonResponse({'success': True, 'message': 'Connection successful! Your M-Pesa is ready.'})
        else:
            config.is_configured = False
            config.test_response = f" Error: {response.status_code}"
            config.save()
            return JsonResponse({'success': False, 'message': f'Invalid credentials. Error: {response.status_code}'})
            
    except Exception as e:
        config.is_configured = False
        config.test_response = f" Error: {str(e)}"
        config.save()
        return JsonResponse({'success': False, 'message': f'Connection failed: {str(e)}'})


@login_required
def edit_profile(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # ========== UPDATE PROFILE INFORMATION ==========
        if action == 'profile':
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            email = request.POST.get('email')
            phone_number = request.POST.get('phone_number')
            
            if not first_name or not last_name or not email:
                messages.error(request, "First name, last name, and email are required.")
                return redirect('edit_profile')
            
            if User.objects.exclude(id=request.user.id).filter(email=email).exists():
                messages.error(request, "Email is already in use by another account.")
                return redirect('edit_profile')
            
            request.user.first_name = first_name
            request.user.last_name = last_name
            request.user.email = email
            request.user.phone_number = phone_number
            request.user.save()
            
            messages.success(request, "Your profile has been updated successfully!")
            return redirect('edit_profile')
        
        # ========== CHANGE PASSWORD ==========
        elif action == 'password':
            old_password = request.POST.get('old_password')
            new_password = request.POST.get('new_password')
            confirm_password = request.POST.get('confirm_password')
            
            if not request.user.check_password(old_password):
                messages.error(request, "Current password is incorrect.")
            elif new_password != confirm_password:
                messages.error(request, "New passwords do not match.")
            elif len(new_password) < 6:
                messages.error(request, "Password must be at least 6 characters.")
            else:
                request.user.set_password(new_password)
                request.user.save()
                # Keep the user logged in after password change
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password changed successfully!")
            
            return redirect('edit_profile')
    
    return render(request, 'accounts/edit_profile.html', {'user': request.user})

def check_toast(request):
    """Return any toast message stored in session and clear it"""
    message = request.session.pop('toast_message', None)
    toast_type = request.session.pop('toast_type', 'success')
    toast_title = request.session.pop('toast_title', 'Notification')
    
    return JsonResponse({
        'message': message,
        'type': toast_type,
        'title': toast_title
    })

def generate_parent_id():
    """
    Generate a unique Parent ID like: PRT-2024-001
    """
    import random
    import datetime
    
    year = datetime.datetime.now().year
    parent_count = User.objects.filter(role='PARENT').count()
    next_number = parent_count + 1
    
    return f"PRT-{year}-{next_number:03d}"


@login_required
def dashboard_view(request):
    from students.models import Students
    from academic.models import Classroom, Teacher, Subject, Results, Exam, SubjectAllocation
    from students.models import Attendance
    from django.db.models import Avg, Count, Q, Sum
    from django.utils import timezone
    from datetime import timedelta
    from finance.models import Payement
    from .models import SubscriptionPayment  
    
    user = request.user
    
    # ========== SUPER ADMIN DASHBOARD ==========
    if user.role == 'SUPER_ADMIN':
        subjects = Subject.objects.all()
        improvements = []
        # Get pending subscription payments
      
        
        for subject in subjects:
            result = Results.objects.filter(subject=subject).aggregate(avg=Avg('marks_obtained'))
            avg_marks = result.get('avg')

            if avg_marks:
                percentage = round(avg_marks)
                improvements.append({
                    'name': subject.name,
                    'percentage': percentage,
                    'color': 'fill-blue'
                })
            else:
                improvements.append({
                    'name': subject.name,
                    'percentage': 0,
                    'color': 'fill-blue'
                })
            
            if len(improvements) >= 5:
                break
        
        student_count = Students.objects.count()
        teacher_count = Teacher.objects.count()
        class_count = Classroom.objects.count()
        recent_students = Students.objects.all().order_by('-id')[:5]
        top_subjects = Subject.objects.all()[:5]
        
        classrooms = Classroom.objects.all()
        chart_data = []
        
        for classroom in classrooms:
            boys = Students.objects.filter(current_class=classroom, gender='MALE').count()
            girls = Students.objects.filter(current_class=classroom, gender='FEMALE').count()
            chart_data.append({
                'class_name': f"{classroom.name} {classroom.stream}" if classroom.stream else classroom.name,
                'boys': boys,
                'girls': girls,
            })
        
        # ========== REVENUE FOR SUPER ADMIN (Subscription Payments from schools) ==========
        total_revenue = SubscriptionPayment.objects.filter(
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Also get recent payments (subscription payments)
        recent_payments = SubscriptionPayment.objects.filter(
            status='COMPLETED'
        ).order_by('-created_at')[:5]

        pending_payments = SubscriptionPayment.objects.filter(
            status='PENDING'
        ).select_related('school', 'subscription').order_by('-created_at')

        # Get schools with their stats
        schools = School.objects.all().order_by('-created_at')
        for school in schools:
            school.student_count = Students.objects.filter(school=school).count()
            school.teacher_count = Teacher.objects.filter(school=school).count()
            school.payment_total = SubscriptionPayment.objects.filter(
                school=school, 
                status='COMPLETED'
            ).aggregate(total=Sum('amount'))['total'] or 0
        
        context = {
            'total_schools': schools.count(),
            'total_students': student_count,
            'total_teachers': teacher_count,
            'total_revenue': total_revenue,
            'recent_students': recent_students,
            'recent_payments': recent_payments,
            'top_subjects': top_subjects,
            'chart_data': chart_data,
            'school_plan': 'Basic',
            'plan_expiry': '01/05/2024',
            'improvements': improvements,
            'schools': schools,
            'pending_payments': pending_payments,
        }
        return render(request, 'dashboard.html', context)
    
    # ========== ADMIN DASHBOARD ==========
    elif user.role == 'ADMIN':
        if not user.school:
            messages.error(request, "Your account is not associated with any school. Please contact Super Admin.")
            return render(request, 'dashboard.html', {'error': 'No school assigned'})

        school_classrooms = Classroom.objects.filter(school=user.school)
        subjects = Subject.objects.all()
        improvements = []

        for subject in subjects:
            result = Results.objects.filter(
                subject=subject,
                school=user.school
            ).aggregate(avg=Avg('marks_obtained'))
            
            avg_marks = result.get('avg')

            if avg_marks:
                percentage = round(avg_marks)
                improvements.append({
                    'name': subject.name,
                    'percentage': percentage,
                    'color': 'fill-blue'
                })
            else:
                improvements.append({
                    'name': subject.name,
                    'percentage': 0,
                    'color': 'fill-blue'
                })
            
            if len(improvements) >= 5:
                break

        student_count = Students.objects.filter(school=user.school).count()
        teacher_count = Teacher.objects.filter(school=user.school).count()
        class_count = school_classrooms.count()
        recent_students = Students.objects.filter(school=user.school).order_by('-id')[:5]
        top_subjects = Subject.objects.all()[:5]

        chart_data = []
        for classroom in school_classrooms:
            boys = Students.objects.filter(current_class=classroom, gender='MALE', school=user.school).count()
            girls = Students.objects.filter(current_class=classroom, gender='FEMALE', school=user.school).count()
            chart_data.append({
                'class_name': f"{classroom.name} {classroom.stream}" if classroom.stream else classroom.name,
                'boys': boys,
                'girls': girls,
            })
        
        # ========== REVENUE FOR SCHOOL ADMIN (Parent Fee Payments) ==========
        total_revenue = Payement.objects.filter(
            school=user.school
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        # Recent payments (fee payments from parents)
        recent_payments = Payement.objects.filter(
            school=user.school
        ).order_by('-date_paid')[:5]

        context = {
            'total_students': student_count,
            'total_teachers': teacher_count,
            'total_classes': class_count,
            'total_revenue': total_revenue,
            'recent_students': recent_students,
            'recent_payments': recent_payments,
            'top_subjects': top_subjects,
            'chart_data': chart_data,
            'school_plan': 'Basic',
            'plan_expiry': '01/05/2024',
            'improvements': improvements,
        }
        return render(request, 'dashboard.html', context)
    
 # ========== HEAD TEACHER DASHBOARD ==========
    elif user.role == 'HEAD_TEACHER':
        school = user.school
        
        if not school:
            messages.error(request, "Your account is not associated with any school.")
            return render(request, 'dashboard.html', {'error': 'No school assigned'})
        
        # Student Statistics
        total_students = Students.objects.filter(school=school, is_active=True).count()
        total_teachers = Teacher.objects.filter(school=school).count()
        total_classes = Classroom.objects.filter(school=school).count()
        
        # Today's Attendance
        today = timezone.now().date()
        today_attendance = Attendance.objects.filter(
            student__school=school,
            date=today
        )
        present_today = today_attendance.filter(status='Present').count()
        absent_today = today_attendance.filter(status='Absent').count()
        attendance_percentage = round((present_today / today_attendance.count() * 100), 1) if today_attendance.count() > 0 else 0
        
        # Pending Results Approval
        pending_results = Results.objects.filter(
            school=school,
            status='PENDING'
        ).count()
        
        # Recent Students (last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        recent_students = Students.objects.filter(
            school=school,
            date_enrolled__gte=week_ago
        ).order_by('-date_enrolled')[:5]
        
        # Upcoming Exams (next 30 days) - REMOVED the school filter
        month_from_now = timezone.now() + timedelta(days=30)
        upcoming_exams = Exam.objects.filter(
            school=school,  # ← ADD THIS!
            date_started__gte=timezone.now(),
            date_started__lte=month_from_now
        ).order_by('date_started')[:5]
        
        # Class-wise Student Distribution
        classes = Classroom.objects.filter(school=school)
        class_data = []
        for classroom in classes:
            student_count = Students.objects.filter(current_class=classroom).count()
            class_data.append({
                'name': str(classroom),
                'count': student_count
            })
        
        # Subject Performance Summary
        subjects = Subject.objects.all()
        subject_performance = []
        for subject in subjects[:5]:
            result = Results.objects.filter(
                subject=subject,
                school=school
            ).aggregate(avg=Avg('marks_obtained'))
            avg_marks = result.get('avg') or 0
            subject_performance.append({
                'name': subject.name,
                'avg': round(avg_marks, 1)
            })
        
        context = {
            'total_students': total_students,
            'total_teachers': total_teachers,
            'total_classes': total_classes,
            'present_today': present_today,
            'absent_today': absent_today,
            'attendance_percentage': attendance_percentage,
            'pending_results': pending_results,
            'recent_students': recent_students,
            'upcoming_exams': upcoming_exams,
            'class_data': class_data,
            'subject_performance': subject_performance,
            'user_role': user.role,
        }
        return render(request, 'dashboard.html', context)
    # ========== TEACHER DASHBOARD ==========
    elif user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            
            # Get classes where teacher is assigned via SubjectAllocation
            assigned_classroom_ids = SubjectAllocation.objects.filter(
                teacher=teacher_record
            ).values_list('classroom_id', flat=True).distinct()
            
            # Also get classes where teacher is class teacher
            class_teacher_ids = Classroom.objects.filter(
                class_teacher=user
            ).values_list('id', flat=True)
            
            # Combine both
            all_classroom_ids = set(assigned_classroom_ids) | set(class_teacher_ids)
            my_classes = Classroom.objects.filter(id__in=all_classroom_ids)
            
            total_students = Students.objects.filter(current_class__in=my_classes).count()
            
            # Get subjects this teacher is assigned to
            my_subjects_count = SubjectAllocation.objects.filter(
                teacher=teacher_record
            ).values('subject_id').distinct().count()
            
            subject_performance = []
            subjects_taught = Subject.objects.filter(
                allocations__teacher=teacher_record
            ).distinct()
            
            for subject in subjects_taught:
                avg_data = Results.objects.filter(
                    subject=subject
                ).aggregate(Avg('marks_obtained'))
                
                avg_marks = avg_data.get('marks_obtained__avg') or 0
                subject_performance.append({
                    'name': subject.name,
                    'avg': round(avg_marks, 1)
                })
            
            recent_students = Students.objects.filter(
                current_class__in=my_classes
            ).order_by('-date_enrolled')[:5]
            
            context = {
                'my_classes': my_classes,
                'total_students': total_students,
                'my_subjects': my_subjects_count,
                'pending_results': 0,
                'subject_performance': subject_performance,
                'recent_students': recent_students,
            }
            return render(request, 'dashboard.html', context)
            
        except Teacher.DoesNotExist:
            context = {
                'my_classes': [],
                'total_students': 0,
                'my_subjects': 0,
                'pending_results': 0,
                'subject_performance': [],
                'recent_students': [],
            }
            return render(request, 'dashboard.html', context)
    
    # ========== STUDENT DASHBOARD ==========
    elif user.role == 'STUDENT':
        try:
            student = user.student_record_records
            
            total_days = student.attendances.count()
            present_days = student.attendances.filter(status='Present').count()
            attendance_percent = round((present_days / total_days * 100) if total_days > 0 else 0)
            
            recent_results = student.results.all().select_related('subject', 'exam').order_by('-exam__date_started')[:5]
            recent_attendance = student.attendances.all().order_by('-date')[:5]
            
            subject_scores = []
            unique_subjects = student.results.values('subject__id', 'subject__name').distinct()
            for sub in unique_subjects:
                latest_result = student.results.filter(subject_id=sub['subject__id']).order_by('-exam__date_started').first()
                if latest_result:
                    subject_scores.append({
                        'name': sub['subject__name'],
                        'marks': latest_result.marks_obtained
                    })
            
            context = {
                'student': student,
                'attendance_percent': attendance_percent,
                'total_marks': student.get_total_marks(),
                'mean_score': round(student.get_mean_marks(), 1),
                'class_rank': student.get_rank(),
                'fee_balance': student.get_fee_balance(),
                'recent_results': recent_results,
                'recent_attendance': recent_attendance,
                'subject_scores': subject_scores,
            }
            return render(request, 'dashboard.html', context)
            
        except Exception as e:
            messages.error(request, f"Error loading student profile: {e}")
            return render(request, 'dashboard.html', {'error': 'Student profile not found'})
    
    # ========== PARENT DASHBOARD ==========
    elif user.role == 'PARENT':
        children = Students.objects.filter(parents=user).select_related('current_class')
        children_count = children.count()
        
        if children_count == 1:
            student = children.first()
            
            total_days = student.attendances.count()
            present_days = student.attendances.filter(status='Present').count()
            attendance_percent = round((present_days / total_days * 100) if total_days > 0 else 0)
            
            recent_results = student.results.all().select_related('subject', 'exam').order_by('-exam__date_started')[:5]
            
            subject_scores = []
            unique_subjects = student.results.values('subject__id', 'subject__name').distinct()
            for sub in unique_subjects:
                latest_result = student.results.filter(subject_id=sub['subject__id']).order_by('-exam__date_started').first()
                if latest_result:
                    subject_scores.append({
                        'name': sub['subject__name'],
                        'marks': latest_result.marks_obtained
                    })
            
            context = {
                'student': student,
                'children_count': children_count,
                'children': children,
                'attendance_percent': attendance_percent,
                'total_marks': student.get_total_marks(),
                'mean_score': round(student.get_mean_marks(), 1),
                'class_rank': student.get_rank(),
                'fee_balance': student.get_fee_balance(),
                'recent_results': recent_results,
                'subject_scores': subject_scores,
                'is_single_child': True,
            }
            return render(request, 'dashboard.html', context)
        
        else:
            context = {
                'children': children,
                'children_count': children_count,
                'is_multiple_children': True,
            }
            return render(request, 'dashboard.html', context)
    
    return render(request, 'dashboard.html', {'error': 'Role not recognized'})

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if not user.is_approved:
                messages.error(request, "Your account is pending approval. Please contact the administrator.")
                return render(request, 'accounts/login.html')
            
            login(request, user)
            
            # ✅ Add welcome message
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            
            # ✅ Correct way to check multiple roles
            if user.role in ['STUDENT', 'HEAD_TEACHER', 'ADMIN', 'TEACHER', 'PARENT']:
                return redirect('dashboard')
            else:
                return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password. Please try again.")
    
    return render(request, 'accounts/login.html')

@login_required
def logout_view(request):
    logout(request)
    
    # ✅ Add logout message (don't clear anything)
    messages.success(request, "You have been successfully logged out.")
    
    return redirect('login')



@login_required
def profile_view(request):
    """Universal profile page for all users"""
    user = request.user
    
    context = {'user': user}
    
    # ===== SUPER ADMIN =====
    if user.role == 'SUPER_ADMIN':
        from students.models import Students
        from academic.models import Teacher, Classroom
        from .models import School, SubscriptionPayment
        from django.db.models import Sum
        
        schools = School.objects.all()
        for school in schools:
            school.student_count = Students.objects.filter(school=school).count()
            school.teacher_count = Teacher.objects.filter(school=school).count()
            school.payment_total = SubscriptionPayment.objects.filter(
                school=school, status='COMPLETED'
            ).aggregate(total=Sum('amount'))['total'] or 0
        
        context.update({
            'total_schools': schools.count(),
            'total_students': Students.objects.count(),
            'total_teachers': Teacher.objects.count(),
            'total_revenue': SubscriptionPayment.objects.filter(status='COMPLETED').aggregate(total=Sum('amount'))['total'] or 0,
            'schools': schools,
        })
    
    # ===== ADMIN =====
    elif user.role == 'ADMIN':
        from students.models import Students
        from academic.models import Teacher, Classroom
        from finance.models import Payement
        from django.db.models import Sum
        
        school = user.school
        context.update({
            'student_count': Students.objects.filter(school=school).count(),
            'teacher_count': Teacher.objects.filter(school=school).count(),
            'class_count': Classroom.objects.filter(school=school).count(),
            'revenue': Payement.objects.filter(school=school).aggregate(total=Sum('amount_paid'))['total'] or 0,
            'recent_students': Students.objects.filter(school=school).order_by('-id')[:5],
        })
    
    # ===== HEAD TEACHER =====
    elif user.role == 'HEAD_TEACHER':
        from students.models import Students, Attendance
        from academic.models import Teacher, Classroom, Results
        from django.utils import timezone
        
        school = user.school
        today = timezone.now().date()
        today_attendance = Attendance.objects.filter(student__school=school, date=today)
        present_today = today_attendance.filter(status='Present').count()
        
        context.update({
            'student_count': Students.objects.filter(school=school, is_active=True).count(),
            'teacher_count': Teacher.objects.filter(school=school).count(),
            'class_count': Classroom.objects.filter(school=school).count(),
            'attendance_percentage': round((present_today / today_attendance.count() * 100), 1) if today_attendance.count() > 0 else 0,
            'pending_results': Results.objects.filter(school=school, status='PENDING').count(),
            'recent_students': Students.objects.filter(school=school).order_by('-id')[:5],
        })
    
    # ===== TEACHER =====
    elif user.role == 'TEACHER':
        from academic.models import Teacher as TeacherModel, SubjectAllocation, Classroom, Subject, Results
        from students.models import Students
        from django.db.models import Avg
        
        try:
            teacher = TeacherModel.objects.get(user=user)
            
            # Get classes
            assigned_classroom_ids = SubjectAllocation.objects.filter(
                teacher=teacher
            ).values_list('classroom_id', flat=True).distinct()
            class_teacher_ids = Classroom.objects.filter(class_teacher=user).values_list('id', flat=True)
            all_classroom_ids = set(assigned_classroom_ids) | set(class_teacher_ids)
            my_classes = Classroom.objects.filter(id__in=all_classroom_ids)
            
            # Get subjects
            subjects_taught = Subject.objects.filter(allocations__teacher=teacher).distinct()
            
            # Subject performance
            subject_performance = []
            for subject in subjects_taught:
                avg_data = Results.objects.filter(subject=subject).aggregate(Avg('marks_obtained'))
                subject_performance.append({
                    'name': subject.name,
                    'avg': round(avg_data.get('marks_obtained__avg') or 0, 1)
                })
            
            context.update({
                'my_classes': my_classes.count(),
                'my_students': Students.objects.filter(current_class__in=my_classes).count(),
                'my_subjects': subjects_taught.count(),
                'pending_results': 0,
                'subject_performance': subject_performance,
            })
        except TeacherModel.DoesNotExist:
            context.update({
                'my_classes': 0,
                'my_students': 0,
                'my_subjects': 0,
                'pending_results': 0,
                'subject_performance': [],
            })
    
    # ===== STUDENT =====
    elif user.role == 'STUDENT':
        student = user.student_record_records if hasattr(user, 'student_record_records') else None
        if student:
            total_days = student.attendances.count()
            present_days = student.attendances.filter(status='Present').count()
            context.update({
                'student': student,
                'attendance_percent': round((present_days / total_days * 100) if total_days > 0 else 0),
                'fee_balance': student.get_fee_balance(),
            })
    
    # ===== PARENT =====
    elif user.role == 'PARENT':
        from students.models import Students
        
        children = Students.objects.filter(parents=user)
        total_balance = sum(child.get_fee_balance() for child in children)
        total_results = sum(child.results.count() for child in children)
        
        context.update({
            'children': children,
            'children_results': total_results,
            'children_attendance': 0,  # You can calculate this
            'total_fee_balance': total_balance,
        })
    
    return render(request, 'profile.html', context)
# ========== SUPER ADMIN SCHOOL MANAGEMENT ==========

@login_required
def super_admin_schools_list(request):
    """List all schools - Super Admin only"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can access this page.")
        return redirect('dashboard')
    
    from django.db import models
    from students.models import Students
    from academic.models import Teacher
    from finance.models import Payement
    
    schools = School.objects.all().order_by('-created_at')
    
    for school in schools:
        school.student_count = Students.objects.filter(school=school).count()
        school.teacher_count = Teacher.objects.filter(school=school).count()
        school.payment_total = Payement.objects.filter(school=school).aggregate(total=models.Sum('amount_paid'))['total'] or 0
    
    return render(request, 'accounts/schools_list.html', {'schools': schools})



@login_required
def super_admin_add_school(request):
    """Add a new school - Super Admin only"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can add schools.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        name = request.POST.get('name')
        code = request.POST.get('code')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        address = request.POST.get('address', '')
        
        if not all([name, code, email, phone]):
            messages.error(request, "Please fill all required fields.")
            return redirect('super_admin_add_school')
        
        if School.objects.filter(code=code).exists():
            messages.error(request, f"School code '{code}' already exists.")
            return redirect('super_admin_add_school')
        
        try:
            school = School.objects.create(
                name=name,
                code=code.lower(),
                email=email,
                phone=phone,
                address=address,
                created_by=request.user,
                is_active=True
            )
            messages.success(request, f"School '{name}' created successfully!")
            return redirect('super_admin_schools')
        except Exception as e:
            messages.error(request, f"Error: {e}")
    
    return render(request, 'accounts/add_school.html')


@login_required
def super_admin_school_detail(request, school_id):
    """View school details - Super Admin only"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can access this page.")
        return redirect('dashboard')
    
    from django.db import models
    from students.models import Students
    from academic.models import Teacher, Classroom
    from finance.models import Payement
    
    school = get_object_or_404(School, id=school_id)
    
    context = {
        'school': school,
        'student_count': Students.objects.filter(school=school).count(),
        'teacher_count': Teacher.objects.filter(school=school).count(),
        'classroom_count': Classroom.objects.filter(school=school).count(),
        'payment_total': Payement.objects.filter(school=school).aggregate(total=models.Sum('amount_paid'))['total'] or 0,
        'recent_students': Students.objects.filter(school=school).order_by('-id')[:10],
    }
    return render(request, 'accounts/school_detail.html', context)


@login_required
def super_admin_delete_school(request, school_id):
    """Delete a school - Super Admin only"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can delete schools.")
        return redirect('dashboard')
    
    from students.models import Students
    from academic.models import Teacher
    from finance.models import Payement
    from accounts.models import User
    
    school = get_object_or_404(School, id=school_id)
    
    if request.method == 'POST':
        school_name = school.name
        
        # Delete all users belonging to this school FIRST
        User.objects.filter(school=school).delete()
        
        # Delete other related data
        Students.objects.filter(school=school).delete()
        Teacher.objects.filter(school=school).delete()
        Payement.objects.filter(school=school).delete()
        
        # Delete the school
        school.delete()
        
        messages.success(request, f"School '{school_name}' and all its users have been deleted successfully!")
        return redirect('super_admin_schools')
    
    return render(request, 'accounts/confirm_delete_school.html', {'school': school})

def register_admin_view(request):
    """Register a School Admin user - Super Admin only"""
    if request.user.is_authenticated and request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can register school admins.")
        return redirect('dashboard')
    
    if request.method == "POST":
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone_number')
        username = request.POST.get('username')
        school_id = request.POST.get('school_id')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        
        # Validation
        if not all([first_name, last_name, email, username, school_id, password]):
            messages.error(request, "Please fill all required fields.")
            return redirect('register_page')
        
        if password != password_confirm:
            messages.error(request, "Passwords do not match.")
            return redirect('register_page')
        
        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return redirect('register_page')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
            return redirect('register_page')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, f"Email '{email}' already exists.")
            return redirect('register_page')
        
        try:
            school = School.objects.get(id=school_id)
        except School.DoesNotExist:
            messages.error(request, "Selected school does not exist.")
            return redirect('register_page')
        
        try:
            user = User.objects.create_user(
                email=email,
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role='ADMIN',
                phone_number=phone,
                school=school,
                is_approved=True
            )
            messages.success(request, f"School Admin '{username}' created successfully for {school.name}!")
            return redirect('user_list')
        except Exception as e:
            messages.error(request, f"Error creating admin: {e}")
    
    return redirect('register_page')

@user_passes_test(lambda u: u.is_staff or u.role in ['ADMIN', 'SUPER_ADMIN', 'HEAD_TEACHER'])
def admin_reset_password(request, user_id):
    # Check permissions
    if request.user.role == 'SUPER_ADMIN':
        pass  # Super Admin can reset any user's password
    elif request.user.role in ['ADMIN', 'HEAD_TEACHER']:
        # School Admin or Head Teacher can only reset passwords for users in their school
        user_to_reset = get_object_or_404(User, id=user_id)
        if user_to_reset.school != request.user.school:
            messages.error(request, "You can only reset passwords for users in your school.")
            return redirect('user_list')
        # Head Teachers cannot reset passwords for Admins
        if request.user.role == 'HEAD_TEACHER' and user_to_reset.role == 'ADMIN':
            messages.error(request, "Head Teacher cannot reset Admin passwords.")
            return redirect('user_list')
    else:
        messages.error(request, "You don't have permission to reset passwords.")
        return redirect('dashboard')
    
    user_to_reset = get_object_or_404(User, id=user_id)
    default_pass = settings.DEFAULT_PASSWORD
    user_to_reset.set_password(default_pass)
    user_to_reset.save()
    
    messages.success(request, f"Password for {user_to_reset.username} reset to: {default_pass}")
    return redirect('user_list')

def register_student_view(request):
    # Only HEAD_TEACHER and CLASS TEACHER can register students
    if request.user.is_authenticated and request.user.role not in ['HEAD_TEACHER', 'TEACHER']:
        messages.error(request, "You don't have permission to register students.")
        return redirect('dashboard')
    
    # If user is TEACHER, check if they are a class teacher
    teacher_classes = []
    if request.user.role == 'TEACHER':
        teacher_classes = Classroom.objects.filter(class_teacher=request.user)
        if not teacher_classes.exists():
            messages.error(request, "You are not assigned as a class teacher. Please contact Head Teacher.")
            return redirect('dashboard')
        # Store the class IDs for validation
        teacher_class_ids = [c.id for c in teacher_classes]
    
    if request.method == "POST":
        class_id = request.POST.get('grade_level')
        parent_id = request.POST.get('parent_id')
        gender = request.POST.get('gender')
        has_leadership = request.POST.get('has_leadership') == 'true'
        address = request.POST.get('address')
        medical_condition = request.POST.get('medical_condition')
        
        if not class_id:
            messages.error(request, "Please select a grade/classroom.")
            return redirect('register_students')

        try:
            with transaction.atomic():
                selected_class = Classroom.objects.get(id=class_id)
                
                # ✅ NEW: Validate teacher can only add to their own class
                if request.user.role == 'TEACHER':
                    if selected_class.id not in teacher_class_ids:
                        messages.error(request, f"You can only add students to your assigned class ({teacher_classes.first().name if teacher_classes else 'None'}).")
                        return redirect('register_students')
                
                admission_number = request.POST.get('admission_number')
                admission_number = admission_number.strip().upper()
                
                if Students.objects.filter(registration_number=admission_number).exists():
                    messages.error(request, f"Student with admission number {admission_number} already exists!")
                    return redirect('register_students')
                
                if User.objects.filter(username=admission_number).exists():
                    messages.error(request, f"Username {admission_number} is already taken!")
                    return redirect('register_students')
                
                school = request.user.school
                
                user = User.objects.create_user(
                    email=request.POST.get('email'),
                    username=admission_number,
                    password=settings.DEFAULT_PASSWORD,
                    first_name=request.POST.get('first_name'),
                    last_name=request.POST.get('last_name'),
                    role='STUDENT',
                    is_approved=True,
                    school=school,
                )

                student = Students.objects.create(
                    user=user,
                    first_name=request.POST.get('first_name'),
                    last_name=request.POST.get('last_name'),
                    registration_number=admission_number,
                    current_class=selected_class,
                    parents_id=parent_id if parent_id else None,
                    gender=gender,
                    has_leadership=has_leadership,
                    address=address,
                    medical_condition=medical_condition,
                    school=school,
                )

                # Send notification to Head Teacher
                if selected_class.class_teacher:
                    from notification.models import Notification
                    Notification.objects.create(
                        sender=request.user,
                        recipient=selected_class.class_teacher,
                        title="👨‍🎓 New Student Added",
                        message=f"{student.first_name} {student.last_name} ({admission_number}) has been added to {selected_class.name} {selected_class.stream or ''}.",
                        notification_type='STUDENT'
                    )
                    messages.info(request, f"Notification sent to {selected_class.class_teacher.get_full_name()}")

                messages.success(request, f"Student {admission_number} registered successfully!")
                messages.info(request, f"Username: {admission_number} | Password: {settings.DEFAULT_PASSWORD}")
                return redirect('user_list')

        except Classroom.DoesNotExist:
            messages.error(request, "Selected classroom does not exist!")
        except Exception as e:
            messages.error(request, f"Error: {e}")

    # ========== GET REQUEST - Load form with appropriate data ==========
    if request.user.role == 'TEACHER':
        # Class Teacher - only see their OWN classes
        all_classrooms = Classroom.objects.filter(class_teacher=request.user)
        all_parents = User.objects.filter(role='PARENT', school=request.user.school)
    else:  # HEAD_TEACHER
        # Head Teacher sees all classes in their school (emergency only)
        all_classrooms = Classroom.objects.filter(school=request.user.school)
        all_parents = User.objects.filter(role='PARENT', school=request.user.school)

    return render(request, 'accounts/register_form.html', {
        'classrooms': all_classrooms,
        'parents': all_parents,
    })
 
@login_required
def register_head_teacher(request):
    """Register a Head Teacher - Only School Admin (Director) can do this"""
    
    # Check for ADMIN role (School Director)
    if request.user.role != 'ADMIN':
        messages.error(request, "Only School Admin can register head teachers.")
        return redirect('dashboard')
    
    if request.method == "POST":
        email = request.POST.get('email')
        tsc_number = request.POST.get('tsc_number')
        f_name = request.POST.get('first_name')
        l_name = request.POST.get('last_name')
        phone = request.POST.get('phone')
        date_appointed = request.POST.get('date_appointed')
        qualifications = request.POST.get('qualifications')
        
        tsc_number = tsc_number.strip().upper()
        
       
       
        
        # Check if user already exists
        if User.objects.filter(username=tsc_number).exists():
            messages.error(request, f"Username {tsc_number} is already taken!")
            return redirect('register_page')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, f"Email {email} is already registered!")
            return redirect('register_page')
        
        try:
            with transaction.atomic():
                school = request.user.school  # School Admin's school
                
                # Create User account with HEAD_TEACHER role
                user = User.objects.create_user(
                    email=email,
                    username=tsc_number,
                    password=settings.DEFAULT_PASSWORD,
                    first_name=f_name,
                    last_name=l_name,
                    role='HEAD_TEACHER',  # Make sure this is correct
                    is_approved=True,
                    phone_number=phone,
                    school=school,
                )
                
                print(f"Created user: {user.username} with role: {user.role}")
                
                # Create Teacher profile
                from academic.models import Teacher
                teacher = Teacher.objects.create(
                    user=user,
                    name=f"{f_name} {l_name}",
                    tsc_number=tsc_number,
                    phone=phone,
                    school=school,
                )
                
                messages.success(request, f"Head Teacher {f_name} {l_name} registered successfully!")
                messages.info(request, f"Username: {tsc_number} | Password: {settings.DEFAULT_PASSWORD}")
                return redirect('user_list')
                
        except Exception as e:
            print(f"Error: {e}")
            messages.error(request, f"Error registering head teacher: {e}")
    
    return redirect('register_page')

def register_teacher_view(request):
    # Only HEAD_TEACHER can register teachers
    if request.user.is_authenticated and request.user.role not in ['HEAD_TEACHER']:
        messages.error(request, "Only Head Teacher can register teachers.")
        return redirect('dashboard')
        
    if request.method == "POST":
        email = request.POST.get('email')
        tsc_number = request.POST.get('tsc_number')
        f_name = request.POST.get('first_name')
        l_name = request.POST.get('last_name')
        subject_id = request.POST.get('assigned_subject')
        
        date_of_joining = request.POST.get('date_of_joining')
        experience = request.POST.get('experience')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        qualification = request.POST.get('qualification')
        
        tsc_number = tsc_number.strip().upper()
        
        if Teacher.objects.filter(tsc_number=tsc_number).exists():
            messages.error(request, f"Teacher with TSC number {tsc_number} already exists!")
            return redirect('register_teacher')
        
        if User.objects.filter(username=tsc_number).exists():
            messages.error(request, f"Username {tsc_number} is already taken!")
            return redirect('register_teacher')
        
        try:
            with transaction.atomic():
                # Determine which school to assign
                if request.user.role == 'SUPER_ADMIN':
                    school = request.user.school  # Or get from form
                else:
                    school = request.user.school
                
                user = User.objects.create_user(
                    email=email,
                    username=tsc_number,
                    password=settings.DEFAULT_PASSWORD,
                    first_name=f_name,
                    last_name=l_name,
                    role='TEACHER',
                    is_approved=True,
                    phone_number=phone,
                    school=school,
                )

                teacher = Teacher.objects.create(
                    user=user,
                    name=f"{f_name} {l_name}",
                    tsc_number=tsc_number,
                    phone=phone,
                    address=address,
                    date_of_joining=date_of_joining if date_of_joining else None,
                    experience=experience if experience else None,
                    qualification=qualification if qualification else None,
                    school=school,
                )

                if subject_id:
                    try:
                        subject_obj = Subject.objects.get(id=subject_id)
                        subject_obj.teacher = user
                        subject_obj.save()
                        messages.info(request, f"Subject {subject_obj.name} assigned to teacher.")
                    except Subject.DoesNotExist:
                        messages.warning(request, "Selected subject not found. You can assign subject later.")

                messages.success(request, f"Teacher {f_name} {l_name} registered successfully!")
                messages.info(request, f"Username: {tsc_number} | Password: {settings.DEFAULT_PASSWORD}")
                return redirect('teacher_list')
                
        except Exception as e:
            messages.error(request, f"Error: {e}")
        
        if request.user.role == 'SUPER_ADMIN':
            subjects = Subject.objects.all()
        else:
            subjects = Subject.objects.all() 
    return render(request, 'accounts/register_form.html', {'subjects': subjects})

@login_required
def user_list_view(request):
    # Allow HEAD_TEACHER to view user list
    if request.user.role not in ['ADMIN', 'SUPER_ADMIN', 'HEAD_TEACHER']:
        messages.error(request, "You don't have permission to view user list.")
        return redirect('dashboard')
    
    role_filter = request.GET.get('role')
    search_query = request.GET.get('search', '')
    
    # Filter users based on role
    if request.user.role == 'SUPER_ADMIN':
        if role_filter:
            all_users = User.objects.filter(role=role_filter).order_by('-date_joined')
        else:
            all_users = User.objects.all().order_by('-date_joined')
    elif request.user.role == 'HEAD_TEACHER':
        # Head Teacher sees only users in their school
        if role_filter:
            all_users = User.objects.filter(role=role_filter, school=request.user.school).order_by('-date_joined')
        else:
            all_users = User.objects.filter(school=request.user.school).order_by('-date_joined')
    else:  # ADMIN (School Admin)
        if role_filter:
            all_users = User.objects.filter(role=role_filter, school=request.user.school).order_by('-date_joined')
        else:
            all_users = User.objects.filter(school=request.user.school).order_by('-date_joined')
    
    if search_query:
        all_users = all_users.filter(
            models.Q(username__icontains=search_query) |
            models.Q(first_name__icontains=search_query) |
            models.Q(last_name__icontains=search_query) |
            models.Q(email__icontains=search_query)
        )
    
    return render(request, 'accounts/user_list.html', {
        'users': all_users,
        'search_query': search_query,
        'role_filter': role_filter,
    })


def register_parents(request):
    # Only HEAD_TEACHER (emergency) and CLASS TEACHER can register parents
    if request.user.is_authenticated and request.user.role not in ['HEAD_TEACHER', 'TEACHER']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "You don't have permission."})
        messages.error(request, "Only Class Teachers or Head Teacher can register parents.")
        return redirect('dashboard')
    
    # Check if user is a class teacher (for TEACHER role)
    if request.user.role == 'TEACHER':
        my_classes = Classroom.objects.filter(class_teacher=request.user)
        if not my_classes.exists():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': "You are not assigned as a class teacher."})
            messages.error(request, "You are not assigned as a class teacher.")
            return redirect('dashboard')
    
    if request.method == "POST":
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone_number')
        id_number = request.POST.get('id_number')

        if not id_number:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': "ID Number is required!"})
            messages.error(request, "ID Number is required for parent registration!")
            return redirect('register_page')
        
        id_number = id_number.strip()

        if User.objects.filter(username=id_number).exists():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': f"User with ID Number {id_number} already exists!"})
            messages.error(request, f"User with ID Number {id_number} already exists!")
            return redirect('register_page')
        
        if User.objects.filter(email=email).exists():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': f"User with email {email} already exists!"})
            messages.error(request, f"User with email {email} already exists!")
            return redirect('register_page')
        
        try:
            school = request.user.school
            
            user = User.objects.create_user(
                email=email,
                username=id_number,
                password=settings.DEFAULT_PASSWORD,
                first_name=first_name,
                last_name=last_name,
                role='PARENT',
                phone_number=phone,
                is_approved=True,
                school=school,
            )
            
            # If AJAX request, return JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'parent_id': user.id,
                    'parent_name': f"{first_name} {last_name}",
                    'parent_phone': phone,
                    'parent_id_number': id_number,
                    'message': f"Parent {first_name} {last_name} registered successfully!"
                })
            
            messages.success(request, f"Parent {first_name} {last_name} registered successfully!")
            messages.info(request, f"Username: {id_number} | Password: {settings.DEFAULT_PASSWORD}")
            messages.warning(request, "Please inform the parent to change their password on first login.")
            return redirect('user_list')
            
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)})
            messages.error(request, f"Error creating parent: {e}")
    
    return render(request, 'accounts/register_form.html')


@login_required
def change_password(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not request.user.check_password(old_password):
            messages.error(request, "Current password is incorrect.")
        elif new_password != confirm_password:
            messages.error(request, "New passwords do not match.")
        elif len(new_password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
        else:
            request.user.set_password(new_password)
            request.user.save()
            messages.success(request, "Password changed successfully! Please login again.")
            return redirect('login')
    
    return render(request, 'accounts/change_password.html')


@login_required
def delete_user(request, user_id):
    """Delete a user - Only Super Admin or School Admin"""
    if request.user.role not in ['SUPER_ADMIN', 'ADMIN']:
        messages.error(request, "You don't have permission to delete users.")
        return redirect('user_list')
    
    # Get the user to delete
    user_to_delete = get_object_or_404(User, id=user_id)
    
    # Check permissions for School Admin
    if request.user.role == 'ADMIN' and request.user.school:
        if user_to_delete.school != request.user.school:
            messages.error(request, "You can only delete users in your school.")
            return redirect('user_list')
        if user_to_delete.role == 'ADMIN':
            messages.error(request, "School Admin cannot delete another Admin.")
            return redirect('user_list')
    
    username = user_to_delete.username
    
    # Delete related records based on role
    if user_to_delete.role == 'STUDENT':
        Students.objects.filter(user=user_to_delete).delete()
    elif user_to_delete.role == 'TEACHER':
        Teacher.objects.filter(user=user_to_delete).delete()
    
    user_to_delete.delete()
    
    messages.success(request, f"User '{username}' has been deleted successfully!")
    return redirect('user_list')

def register_page(request):
    """One page for all registrations"""
    from academic.models import Classroom, Subject
    from accounts.models import User, School
    
    # Role-based permission check
    if request.user.is_authenticated and request.user.role not in ['SUPER_ADMIN', 'ADMIN', 'HEAD_TEACHER', 'TEACHER']:
        messages.error(request, "You don't have permission to register users.")
        return redirect('dashboard')
    
    # Initialize my_classes for TEACHER role
    my_classes = []
    if request.user.role == 'TEACHER':
        my_classes = Classroom.objects.filter(class_teacher=request.user)
    
    # Filter data based on user role
    if request.user.role == 'SUPER_ADMIN':
        classrooms = Classroom.objects.all()
        parents = User.objects.filter(role='PARENT')
        subjects = Subject.objects.all()
        schools = School.objects.filter(is_active=True)
        
    elif request.user.role == 'ADMIN':
        school = request.user.school
        classrooms = Classroom.objects.filter(school=school)
        parents = User.objects.filter(role='PARENT', school=school)
        subjects = Subject.objects.all()
        schools = None
        
    elif request.user.role == 'HEAD_TEACHER':
        school = request.user.school
        classrooms = Classroom.objects.filter(school=school)  # All classes in school
        parents = User.objects.filter(role='PARENT', school=school)
        subjects = Subject.objects.all()
        schools = None
        
    else:  # TEACHER (Class Teacher)
        school = request.user.school
        classrooms = my_classes  # Only their classes
        parents = User.objects.filter(role='PARENT', school=school)
        subjects = Subject.objects.all()
        schools = None
    
    context = {
        'classrooms': classrooms,
        'subjects': subjects,
        'parents': parents,
        'schools': schools,
        'user_role': request.user.role,
        'my_classes': my_classes,  # For checking if teacher is class teacher
    }
    return render(request, 'accounts/register_form.html', context)

def offline_page(request):
    """Offline page when user has no internet connection"""
    return render(request, 'accounts/offline.html')


@login_required
def super_admin_school_detail(request, school_id):
    """View school details - Super Admin only"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can access this page.")
        return redirect('dashboard')
    
    from django.db import models
    from students.models import Students
    from academic.models import Teacher, Classroom
    from finance.models import Payement
    
    school = get_object_or_404(School, id=school_id)
    
    context = {
        'school': school,
        'student_count': Students.objects.filter(school=school).count(),
        'teacher_count': Teacher.objects.filter(school=school).count(),
        'classroom_count': Classroom.objects.filter(school=school).count(),
        'payment_total': Payement.objects.filter(school=school).aggregate(total=models.Sum('amount_paid'))['total'] or 0,
        'recent_students': Students.objects.filter(school=school).order_by('-id')[:10],
    }
    return render(request, 'accounts/school_detail.html', context)


@login_required
def super_admin_delete_school(request, school_id):
    """Delete a school - Super Admin only"""
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can delete schools.")
        return redirect('dashboard')
    
    school = get_object_or_404(School, id=school_id)
    
    if request.method == 'POST':
        school_name = school.name
        # Delete related data first
        Students.objects.filter(school=school).delete()
        Teacher.objects.filter(school=school).delete()
        Payement.objects.filter(school=school).delete()
        User.objects.filter(school=school).update(school=None)
        school.delete()
        messages.success(request, f"School '{school_name}' has been deleted successfully!")
        return redirect('super_admin_schools')
    
    return render(request, 'accounts/confirm_delete_school.html', {'school': school})



from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from .models import Notification
from academic.models import Classroom, Teacher
from students.models import Students
from accounts.models import User
from django.core.mail import send_mail
from django.conf import settings


@login_required
def send_notification(request):
    user = request.user
    
    # Allow SUPER_ADMIN, ADMIN, and TEACHER
    if user.role not in ['SUPER_ADMIN', 'ADMIN','HEAD_TEACHER', 'TEACHER']:
        messages.error(request, "You don't have permission to send notifications.")
        return redirect('dashboard')
    
    my_classes = []
    if user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            my_classes = Classroom.objects.filter(class_teacher=user).distinct()
        except Teacher.DoesNotExist:
            my_classes = []
    
    if request.method == 'POST':
        title = request.POST.get('title')
        message_text = request.POST.get('message')
        notification_type = request.POST.get('notification_type')
        target_class_id = request.POST.get('target_class')
        
        if not title or not message_text:
            messages.error(request, "Please fill in both title and message.")
            return redirect('send_notification')
        
        try:
            with transaction.atomic():
                recipients_list = []
                
                # ========== SUPER ADMIN - Can send to ANYONE ==========
                if user.role == 'SUPER_ADMIN':
                    if notification_type == 'CLASS' and target_class_id:
                        target_class = Classroom.objects.get(id=target_class_id)
                        students = Students.objects.filter(current_class=target_class)
                        recipients_list = [student.user for student in students]
                        
                    elif notification_type == 'ALL':
                        recipients_list = User.objects.filter(is_active=True)
                        
                    elif notification_type == 'TEACHER':
                        recipients_list = User.objects.filter(role='TEACHER')
                        
                    elif notification_type == 'PARENT':
                        recipients_list = User.objects.filter(role='PARENT')
                
                # ========== SCHOOL ADMIN - Only THEIR SCHOOL ==========
                elif user.role == 'ADMIN':
                    school = user.school
                    
                    if notification_type == 'CLASS' and target_class_id:
                        target_class = Classroom.objects.get(id=target_class_id, school=school)
                        students = Students.objects.filter(current_class=target_class, school=school)
                        recipients_list = [student.user for student in students]
                        
                    elif notification_type == 'ALL':
                        recipients_list = User.objects.filter(is_active=True, school=school)
                        
                    elif notification_type == 'TEACHER':
                        recipients_list = User.objects.filter(role='TEACHER', school=school)
                        
                    elif notification_type == 'PARENT':
                        recipients_list = User.objects.filter(role='PARENT', school=school)
                        
                    elif notification_type == 'STUDENT':
                        recipients_list = User.objects.filter(role='STUDENT', school=school)
                
                elif user.role == 'HEAD_TEACHER':
                    school = user.school
                    
                    if notification_type == 'CLASS' and target_class_id:
                        target_class = Classroom.objects.get(id=target_class_id, school=school)
                        students = Students.objects.filter(current_class=target_class, school=school)
                        recipients_list = [student.user for student in students]
                        
                    elif notification_type == 'TEACHER':
                        recipients_list = User.objects.filter(role='TEACHER', school=school)
                        
                    elif notification_type == 'PARENT':
                        recipients_list = User.objects.filter(role='PARENT', school=school)
                        
                    elif notification_type == 'STUDENT':
                        recipients_list = User.objects.filter(role='STUDENT', school=school)
                
                # ========== TEACHER - Only their CLASSES ==========
                elif user.role == 'TEACHER':
                    if notification_type == 'CLASS' and target_class_id:
                        # Teacher can only send to classes they teach
                        teacher_record = Teacher.objects.get(user=user)
                        target_class = Classroom.objects.get(
                            id=target_class_id,
                            class_teacher=user
                        )
                        students = Students.objects.filter(current_class=target_class)
                        recipients_list = [student.user for student in students]
                    else:
                        messages.error(request, "Teachers can only send notifications to their own classes.")
                        return redirect('send_notification')
                
                # Create notifications and send emails
                for recipient in recipients_list:
                    # Create in-app notification
                    Notification.objects.create(
                        sender=user,
                        recipient=recipient,
                        title=title,
                        message=message_text,
                        notification_type=notification_type
                    )
                    
                    # Send email
                    if recipient.email:
                        try:
                            send_mail(
                                subject=f"📢 EduNexus: {title}",
                                message=f"Dear {recipient.get_full_name() or recipient.username},\n\n{message_text}\n\n---\nLogin to view: {request.build_absolute_uri('/notifications/')}",
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                recipient_list=[recipient.email],
                                fail_silently=True,
                            )
                        except Exception as e:
                            print(f"Email failed for {recipient.email}: {e}")
                
                messages.success(request, f"✅ Notification sent to {len(recipients_list)} recipient(s)!")
                return redirect('send_notification')
                
        except Exception as e:
            messages.error(request, f"❌ Error sending notification: {e}")
    
    context = {
        'my_classes': my_classes,
        'user_role': user.role,
    }
    return render(request, 'notification/send.html', context)


@login_required
def user_notifications(request):
    notifications = Notification.objects.filter(recipient=request.user).select_related('sender')
    
    if request.GET.get('mark_all_read'):
        notifications.filter(is_read=False).update(is_read=True)
        messages.success(request, "✅ All notifications marked as read.")
        return redirect('user_notifications')
    
    # Mark all as read when viewing the page
    notifications.filter(is_read=False).update(is_read=True)
    
    context = {
        'notifications': notifications,
        'unread_count': 0,
    }
    return render(request, 'notification/notification_list.html', context)


@login_required
def mark_as_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save()
    messages.success(request, "✅ Notification marked as read.")
    return redirect('user_notifications')


@login_required
def mark_all_as_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    messages.success(request, "✅ All notifications marked as read.")
    return redirect('user_notifications')


@login_required
def delete_notification(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.delete()
    messages.success(request, "🗑️ Notification deleted.")
    return redirect('user_notifications')


@login_required
def unread_count_api(request):
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'unread_count': count})


@login_required
def latest_notifications_api(request):
    """Get latest unread notifications for popup display"""
    notifications = Notification.objects.filter(
        recipient=request.user, 
        is_read=False
    ).order_by('-created_at')[:5]
    
    data = []
    for notif in notifications:
        data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'created_at': notif.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return JsonResponse(data, safe=False)
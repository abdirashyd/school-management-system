from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from .models import Students, Attendance
from django.utils import timezone
from academic.models import Classroom, Teacher, Subject
from datetime import datetime, timedelta
from django.utils import timezone
from .utils import export_attendance_to_excel


@login_required
def student_list_view(request):
    user = request.user
    search_query = request.GET.get('search', '')
    leadership_filter = request.GET.get('has_leadership', '')
    
    # ✅ UPDATED: SUPER_ADMIN sees all students
    # ✅ UPDATED: ADMIN sees only students in their school
    if user.role == 'SUPER_ADMIN':
        students = Students.objects.all().select_related('current_class', 'parents')
    elif user.role == 'ADMIN':
        students = Students.objects.filter(school=user.school).select_related('current_class', 'parents')
    elif user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            class_teacher_classes = Classroom.objects.filter(class_teacher=user)
            subject_teacher_classes = Classroom.objects.filter(
                subjects__teacher=user
            ).values_list('id', flat=True).distinct()
            all_class_ids = list(class_teacher_classes.values_list('id', flat=True)) + list(subject_teacher_classes)
            if all_class_ids:
                students = Students.objects.filter(
                    current_class_id__in=all_class_ids
                ).select_related('current_class', 'parents')
            else:
                students = Students.objects.none()
        except Teacher.DoesNotExist:
            students = Students.objects.none()
    elif user.role == 'PARENT':
        students = Students.objects.filter(parents=user).select_related('current_class')
    elif user.role == 'STUDENT':
        messages.info(request, "You can only view your own profile.")
        if hasattr(user, 'student_record_records'):
            return redirect('students_detail', pk=user.student_record_records.id)
        else:
            students = Students.objects.none()
    else:
        students = Students.objects.none()
    
    if search_query:
        students = students.filter(
            models.Q(first_name__icontains=search_query) |
            models.Q(last_name__icontains=search_query) |
            models.Q(registration_number__icontains=search_query)
        )
    
    if leadership_filter == 'true':
        students = students.filter(has_leadership=True)
    elif leadership_filter == 'false':
        students = students.filter(has_leadership=False)
    
    return render(request, 'students/student_list.html', {
        'students': students,
        'search_query': search_query,
        'leadership_filter': leadership_filter,
    })


@login_required
def student_detail(request, pk):
    student = get_object_or_404(Students, pk=pk)
    user = request.user
    
    # ✅ UPDATED: Permission checks with school filtering
    if user.role == 'SUPER_ADMIN':
        pass  # Super Admin can view any student
    elif user.role == 'ADMIN':
        # School Admin can only view students from their school
        if student.school != user.school:
            messages.error(request, "You can only view students from your school.")
            return redirect('student_list')
    elif user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            is_class_teacher = (student.current_class and student.current_class.class_teacher == user)
            teaches_subject = Subject.objects.filter(
                teacher=user,
                classrooms=student.current_class
            ).exists()
            if not (is_class_teacher or teaches_subject):
                messages.error(request, "You don't have permission to view this student.")
                return redirect('student_list')
        except Teacher.DoesNotExist:
            messages.error(request, "Teacher record not found.")
            return redirect('student_list')
    elif user.role == 'PARENT':
        if student.parents != user:
            messages.error(request, "You can only view your own children.")
            return redirect('student_list')
    elif user.role == 'STUDENT':
        if not hasattr(user, 'student_record_records') or user.student_record_records != student:
            messages.error(request, "You can only view your own profile.")
            return redirect('student_list')
    
    return render(request, 'students/students_detail.html', {'student': student})


@login_required
def attendance_report(request):
    user = request.user
    
    if user.role not in ['SUPER_ADMIN', 'ADMIN', 'TEACHER']:
        messages.error(request, "You don't have permission to mark attendance.")
        return redirect('dashboard')
    
    # ✅ UPDATED: Get students based on role with school filtering
    if user.role == 'SUPER_ADMIN':
        students = Students.objects.all().select_related('current_class')
    elif user.role == 'ADMIN':
        students = Students.objects.filter(school=user.school).select_related('current_class')
    elif user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            class_teacher_classes = Classroom.objects.filter(class_teacher=user)
            subject_teacher_classes = Classroom.objects.filter(
                subjects__teacher=user
            ).values_list('id', flat=True).distinct()
            all_class_ids = list(class_teacher_classes.values_list('id', flat=True)) + list(subject_teacher_classes)
            if all_class_ids:
                students = Students.objects.filter(
                    current_class_id__in=all_class_ids
                ).select_related('current_class')
            else:
                students = Students.objects.none()
        except Teacher.DoesNotExist:
            students = Students.objects.none()
    else:
        students = Students.objects.none()
    
    today = timezone.now().date()
    default_start = today - timedelta(days=30)
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    else:
        start_date = default_start
    
    if end_date:
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    else:
        end_date = today
    
    # Check if download requested
    if request.GET.get('export') == 'excel':
        classroom_name = request.GET.get('class_name', 'All Classes')
        attendance_records = {}
        for student in students:
            records = Attendance.objects.filter(
                student=student,
                date__gte=start_date,
                date__lte=end_date
            ).order_by('date')
            attendance_records[student.id] = records
        
        return export_attendance_to_excel(
            students, 
            attendance_records, 
            start_date.strftime('%Y-%m-%d'), 
            end_date.strftime('%Y-%m-%d'),
            classroom_name
        )
    
    # ========== HANDLE POST REQUEST (CHECKBOX LOGIC) ==========
    if request.method == 'POST':
        saved_count = 0
        for student in students:
            is_present = request.POST.get(f'present_{student.id}') == 'on'
            remarks = request.POST.get(f'remarks_{student.id}', '')
            
            status = 'Present' if is_present else 'Absent'
            
            # ✅ UPDATED: Also save school_id when creating attendance
            Attendance.objects.update_or_create(
                student=student,
                date=today,
                defaults={
                    'status': status, 
                    'remarks': remarks, 
                    'marked_by': user,
                    'school_id': student.school_id,  # ✅ Set school from student
                }
            )
            saved_count += 1
        
        if saved_count > 0:
            messages.success(request, f"Attendance for {saved_count} student(s) on {today} saved successfully!")
        else:
            messages.warning(request, "No attendance records were saved.")
        return redirect('attendance_report')
    
    # ========== GET REQUEST - LOAD EXISTING ATTENDANCE ==========
    today_records = {att.student_id: att for att in Attendance.objects.filter(date=today)}
    
    present_students = [student_id for student_id, att in today_records.items() if att.status == 'Present']
    
    context = {
        'students': students,
        'today_records': today_records,
        'present_students': present_students,
        'today': today,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'students/attendance_report.html', context)


@login_required
def delete_student(request, pk):
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can delete students.")
        return redirect('student_list')
    
    student = get_object_or_404(Students, pk=pk)
    name = f"{student.first_name} {student.last_name}"
    
    if student.user:
        student.user.delete()
    else:
        student.delete()
    
    messages.success(request, f"Student {name} deleted successfully!")
    return redirect('student_list')


@login_required
def promote_students(request):
    """Promote all students to next grade - Only Head Teacher"""
    # Only HEAD TEACHER can promote students
    if request.user.role != 'HEAD_TEACHER':
        messages.error(request, "Only Head Teacher can promote students.")
        return redirect('dashboard')
    
    # Also ensure the Head Teacher has a school assigned
    if not request.user.school:
        messages.error(request, "Your account is not associated with any school.")
        return redirect('dashboard')
    
    from academic.models import GradeLevel, PromotionHistory
    from django.utils import timezone
    
    current_year = timezone.now().year
    next_year = current_year + 1
    academic_year = f"{current_year}-{next_year}"
    
    if request.method == 'POST':
        # Get all active students in THIS SCHOOL only (not graduated)
        students = Students.objects.filter(
            school=request.user.school,
            is_graduated=False
        )
        
        promoted_count = 0
        graduated_count = 0
        skipped_count = 0
        
        for student in students:
            current_grade = student.current_grade
            
            if not current_grade:
                skipped_count += 1
                continue
            
            next_grade = current_grade.next_grade
            
            if next_grade:
                PromotionHistory.objects.create(
                    student=student,
                    from_grade=current_grade,
                    to_grade=next_grade,
                    promoted_by=request.user,
                    academic_year=academic_year,
                    school=request.user.school,  # ✅ Set school
                )
                student.current_grade = next_grade
                student.save()
                promoted_count += 1
                
            else:
                # No next grade - this is graduation (Grade 12)
                PromotionHistory.objects.create(
                    student=student,
                    from_grade=current_grade,
                    to_grade=None,
                    promoted_by=request.user,
                    academic_year=academic_year,
                    school=request.user.school,  # ✅ Set school
                )
                student.is_graduated = True
                student.graduation_year = current_year
                student.current_grade = None
                student.save()
                graduated_count += 1
                
                if student.parents:
                    from notification.models import Notification
                    Notification.objects.create(
                        recipient=student.parents,
                        title="🎓 Congratulations Graduate!",
                        message=f"Your child {student.first_name} {student.last_name} has graduated from Grade {current_grade.grade_number}. Congratulations!",
                        notification_type='STUDENT'
                    )
        
        messages.success(
            request, 
            f"Promotion complete! Promoted: {promoted_count}, Graduated: {graduated_count}, Skipped (no grade): {skipped_count}"
        )
        return redirect('dashboard')
    
    # GET request - show confirmation page (only students from this school)
    students = Students.objects.filter(
        school=request.user.school,
        is_graduated=False
    ).select_related('current_grade')
    
    students_by_grade = {}
    
    for student in students:
        if student.current_grade:
            grade_num = student.current_grade.grade_number
            if grade_num not in students_by_grade:
                students_by_grade[grade_num] = []
            students_by_grade[grade_num].append(student)
        else:
            if 'no_grade' not in students_by_grade:
                students_by_grade['no_grade'] = []
            students_by_grade['no_grade'].append(student)
    
    all_grades = GradeLevel.objects.all().order_by('grade_number')
    
    context = {
        'students_by_grade': students_by_grade,
        'all_grades': all_grades,
        'total_students': students.count(),
        'academic_year': academic_year,
    }
    return render(request, 'students/promote_students.html', context)
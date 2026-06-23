# Django Core
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

# Models
from .models import Teacher, Classroom, Subject, Exam, Results, SubjectAllocation
from students.models import Students
from accounts.models import User, School
from notification.models import Notification
from finance.models import Payement

# PDF Generation
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Excel Generation (if you still need it)
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

# Python built-in
import csv
from datetime import datetime, timedelta


@login_required
def teacher_list(request):
    user = request.user
    search_query = request.GET.get('search', '')
    
    # ✅ UPDATED: SUPER_ADMIN sees all teachers
    # ✅ UPDATED: ADMIN (School Admin) sees only teachers in their school
    if user.role == 'SUPER_ADMIN':
        teachers = Teacher.objects.all()
    elif user.role == 'ADMIN':
        teachers = Teacher.objects.filter(school=user.school)
    elif user.role == 'HEAD_TEACHER':
        teachers = Teacher.objects.filter(school=user.school)
    elif user.role == 'TEACHER':
        teachers = Teacher.objects.filter(user=user)
    else:
        teachers = Teacher.objects.none()
    
    # Apply search filter
    if search_query:
        teachers = teachers.filter(
            models.Q(name__icontains=search_query) |
            models.Q(tsc_number__icontains=search_query) |
            models.Q(user__email__icontains=search_query) |
            models.Q(user__first_name__icontains=search_query) |
            models.Q(user__last_name__icontains=search_query)
        )
    
    return render(request, 'academic/teacher_list.html', {
        'teachers': teachers,
        'search_query': search_query,
    })


@login_required
def class_results(request):
    """Class Results view for School Admins, Head Teachers, and Teachers"""
    
    # Allow ADMIN, HEAD_TEACHER, and TEACHER
    if request.user.role not in ['ADMIN', 'HEAD_TEACHER', 'TEACHER']:
        messages.error(request, "You don't have permission to view class results.")
        return redirect('dashboard')
    user = request.user
    
    # Get filter parameters
    selected_class_id = request.GET.get('class')
    selected_exam_id = request.GET.get('exam')
        
    # Get available classes based on role
    if user.role == 'ADMIN':
        # School Admin sees all classes in their school
        classes = Classroom.objects.filter(school=user.school)
    elif user.role == 'HEAD_TEACHER':
        # Head Teacher sees all classes in their school
        classes = Classroom.objects.filter(school=user.school)
    else:  # TEACHER
        # Teacher sees only classes they teach
        try:
            teacher_record = Teacher.objects.get(user=user)
            class_ids = set(
                Classroom.objects.filter(class_teacher=user).values_list('id', flat=True)
            ) | set(
                Classroom.objects.filter(
                    subject_allocations__teacher=teacher_record
                ).values_list('id', flat=True)
            )
            classes = Classroom.objects.filter(id__in=class_ids)
        except Teacher.DoesNotExist:
            classes = Classroom.objects.none()
    
    # Get all exams
    exams = Exam.objects.all().order_by('-date_started')
    
    # Prepare data for selected class
    class_data = None
    students_data = []
    subjects = []
    class_average = 0
    highest_score = None
    lowest_score = None
    
    if selected_class_id and selected_exam_id:
        try:
            selected_class = Classroom.objects.get(id=selected_class_id)
            selected_exam = Exam.objects.get(id=selected_exam_id)
            
            # Get all students in the class
            students = Students.objects.filter(current_class=selected_class).order_by('first_name')
            
            # Get all subjects for this class
            subjects = selected_class.subjects.all()
            if not subjects.exists():
                subjects = Subject.objects.all()
            
            # Build student results data
            for student in students:
                student_total = 0
                student_max = 0
                subject_results = []
                
                for subject in subjects:
                    result = Results.objects.filter(
                        student=student,
                        subject=subject,
                        exam=selected_exam
                    ).first()
                    
                    if result:
                        marks = result.marks_obtained
                        grade = result.grades
                        remark = result.teacher_remark or '-'
                        student_total += result.marks_obtained
                        student_max += result.out_of
                    else:
                        marks = '-'
                        grade = '-'
                        remark = '-'
                        student_max += 100
                    
                    subject_results.append({
                        'subject': subject,
                        'marks': marks,
                        'grade': grade,
                        'remark': remark,
                    })
                
                percentage = round((student_total / student_max * 100), 1) if student_max > 0 else 0
                
                students_data.append({
                    'student': student,
                    'subject_results': subject_results,
                    'total': student_total,
                    'max': student_max,
                    'percentage': percentage,
                })
            
            # Calculate class statistics
            if students_data:
                percentages = [s['percentage'] for s in students_data if s['percentage'] > 0]
                class_average = round(sum(percentages) / len(percentages), 1) if percentages else 0
                highest_score = max(students_data, key=lambda x: x['percentage']) if students_data else None
                lowest_score = min(students_data, key=lambda x: x['percentage']) if students_data else None
            
            class_data = {
                'classroom': selected_class,
                'exam': selected_exam,
            }
            
        except (Classroom.DoesNotExist, Exam.DoesNotExist):
            messages.error(request, "Selected class or exam not found.")
    
    context = {
        'classes': classes,
        'exams': exams,
        'selected_class_id': selected_class_id,
        'selected_exam_id': selected_exam_id,
        'class_data': class_data,
        'students_data': students_data,
        'subjects': subjects,
        'class_average': class_average,
        'highest_score': highest_score,
        'lowest_score': lowest_score,
        'user_role': user.role,
    }
    return render(request, 'academic/class_results.html', context)


@login_required
def report_card(request):
    """Report Card view for Students and Parents"""
    
    user = request.user
    
    # Only allow Students and Parents
    if user.role not in ['STUDENT', 'PARENT']:
        messages.error(request, "You don't have permission to view report cards.")
        return redirect('dashboard')
    
    selected_student_id = request.GET.get('student')
    selected_exam_id = request.GET.get('exam')
    
    # Get all exams for filter
    exams = Exam.objects.all().order_by('-date_started')
    
    # Get students based on role
    if user.role == 'STUDENT':
        # Student sees only themselves
        if hasattr(user, 'student_record_records'):
            students = Students.objects.filter(id=user.student_record_records.id)
            selected_student_id = user.student_record_records.id
        else:
            students = Students.objects.none()
    else:  # PARENT
        # Parent sees their children
        students = Students.objects.filter(parents=user)
    
    # If no student selected and there's only one, auto-select
    if not selected_student_id and students.count() == 1:
        selected_student_id = students.first().id
    
    # Prepare report card data
    report_data = None
    student = None
    exam = None
    
    if selected_student_id and selected_exam_id:
        try:
            student = Students.objects.get(id=selected_student_id)
            exam = Exam.objects.get(id=selected_exam_id)
            
            # Check permission
            if user.role == 'PARENT' and student.parents != user:
                messages.error(request, "You can only view your own children's results.")
                return redirect('report_card')
            
            # Get subjects for this student's class
            subjects = student.current_class.subjects.all() if student.current_class else Subject.objects.all()
            if not subjects.exists():
                subjects = Subject.objects.all()
            
            # Get results for each subject
            subject_results = []
            student_total = 0
            student_max = 0
            
            for subject in subjects:
                result = Results.objects.filter(
                    student=student,
                    subject=subject,
                    exam=exam,
                    status='PUBLISHED'
                ).first()
                
                if result:
                    marks = result.marks_obtained
                    out_of = result.out_of
                    grade = result.grades
                    remark = result.teacher_remark or '-'
                    student_total += marks
                    student_max += out_of
                else:
                    marks = '-'
                    out_of = '-'
                    grade = '-'
                    remark = '-'
                
                subject_results.append({
                    'subject': subject,
                    'marks': marks,
                    'out_of': out_of,
                    'grade': grade,
                    'remark': remark,
                })
            
            # Calculate overall percentage and grade
            percentage = round((student_total / student_max * 100), 1) if student_max > 0 else 0
            
            if percentage >= 80:
                overall_grade = 'A (Exceeding Expectations)'
            elif percentage >= 70:
                overall_grade = 'B (Meeting Expectations)'
            elif percentage >= 60:
                overall_grade = 'C (Approaching Expectations)'
            elif percentage >= 50:
                overall_grade = 'D (Below Expectations)'
            else:
                overall_grade = 'E (Needs Improvement)'
            
            # Get class rank
            class_rank = student.get_rank()
            
            report_data = {
                'student': student,
                'exam': exam,
                'subjects': subjects,
                'subject_results': subject_results,
                'total_marks': student_total,
                'max_marks': student_max,
                'percentage': percentage,
                'overall_grade': overall_grade,
                'class_rank': class_rank,
            }
            
        except Students.DoesNotExist:
            messages.error(request, "Student not found.")
        except Exam.DoesNotExist:
            messages.error(request, "Exam not found.")
    
    context = {
        'students': students,
        'exams': exams,
        'selected_student_id': selected_student_id,
        'selected_exam_id': selected_exam_id,
        'report_data': report_data,
        'is_parent': user.role == 'PARENT',
        'user_role': user.role,
    }
    return render(request, 'academic/report_card.html', context)



from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa

@login_required
def download_results_pdf(request, identifier, exam_id):
    """
    Download results as PDF using HTML template
    """
    user = request.user
    exam = get_object_or_404(Exam, id=exam_id)
    
    if user.role in ['ADMIN', 'TEACHER']:
        # Class Results
        classroom = get_object_or_404(Classroom, id=identifier)
    elif user.role == 'TEACHER':
        teacher = Teacher.objects.get(user=user)
        # Check if teacher teaches this class
        if not SubjectAllocation.objects.filter(teacher=teacher, classroom=classroom).exists():
            messages.error(request, "You can only download results for classes you teach.")
            return redirect('dashboard')
        
        # Permission checks
        if user.role == 'ADMIN' and classroom.school != user.school:
            messages.error(request, "Access denied.")
            return redirect('dashboard')
        
        # Get data
        students = Students.objects.filter(current_class=classroom).order_by('first_name')
        subjects = classroom.subjects.all()
        if not subjects.exists():
            subjects = Subject.objects.all()
        
        students_data = []
        for student in students:
            student_total = 0
            student_max = 0
            subject_results = []
            overall_grade = ''
            
            for subject in subjects:
                result = Results.objects.filter(
                    student=student, subject=subject, exam=exam
                ).first()
                
                if result:
                    subject_results.append({
                        'subject': subject,
                        'marks': result.marks_obtained,
                        'grade': result.grades
                    })
                    student_total += result.marks_obtained
                    student_max += result.out_of
                    overall_grade = result.grades
                else:
                    subject_results.append({
                        'subject': subject,
                        'marks': '-',
                        'grade': '-'
                    })
                    student_max += 100
            
            percentage = round((student_total / student_max * 100), 1) if student_max > 0 else 0
            students_data.append({
                'student': student,
                'subject_results': subject_results,
                'total': student_total,
                'max': student_max,
                'percentage': percentage,
                'grade': overall_grade
            })
        
        # Calculate class stats
        percentages = [s['percentage'] for s in students_data if s['percentage'] > 0]
        class_average = round(sum(percentages) / len(percentages), 1) if percentages else 0
        highest_score = max(students_data, key=lambda x: x['percentage']) if students_data else None
        lowest_score = min(students_data, key=lambda x: x['percentage']) if students_data else None
        
        context = {
            'classroom': classroom,
            'exam': exam,
            'subjects': subjects,
            'students_data': students_data,
            'class_average': class_average,
            'highest_score': highest_score,
            'lowest_score': lowest_score,
            'generated_at': timezone.now(),
        }
        
        template = get_template('academic/pdf_class_results.html')
        html = template.render(context)
        
    else:
        # Individual Report Card
        student = get_object_or_404(Students, id=identifier)
        
        # Permission checks
        if user.role == 'STUDENT':
            if not hasattr(user, 'student_record_records') or user.student_record_records != student:
                messages.error(request, "Access denied.")
                return redirect('dashboard')
        elif user.role == 'PARENT':
            if student.parents != user:
                messages.error(request, "Access denied.")
                return redirect('dashboard')
        
        # Get results
        subjects = student.current_class.subjects.all() if student.current_class else Subject.objects.all()
        results = Results.objects.filter(
            student=student, exam=exam, status='PUBLISHED'
        ).select_related('subject')
        
        total_marks = sum(r.marks_obtained for r in results)
        max_marks = sum(r.out_of for r in results) if results else len(subjects) * 100
        percentage = round((total_marks / max_marks * 100), 1) if max_marks > 0 else 0
        
        def get_grade(percentage):
            if percentage >= 80: return "E (Exceeding Expectations)"
            elif percentage >= 70: return "D- (Meeting Expectations)"
            elif percentage >= 60: return "D (Meeting Expectations)"
            elif percentage >= 50: return "C- (Approaching Expectations)"
            elif percentage >= 40: return "C (Approaching Expectations)"
            elif percentage >= 30: return "B (Below Expectations)"
            else: return "A (Below Expectations)"
        
        context = {
            'student': student,
            'exam': exam,
            'results': results,
            'total_marks': total_marks,
            'max_marks': max_marks,
            'percentage': percentage,
            'overall_grade': get_grade(percentage),
            'class_rank': student.get_rank(),
            'generated_at': timezone.now(),
        }
        
        template = get_template('academic/pdf_report_card.html')
        html = template.render(context)
    
    # Generate PDF
    response = HttpResponse(content_type='application/pdf')
    filename = f"results_{identifier}_{exam_id}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)
    return response

@login_required
def exam_list(request):
    user = request.user
    
    # Only ADMIN and HEAD_TEACHER can view exams
    if user.role not in ['ADMIN', 'HEAD_TEACHER']:
        messages.error(request, "You don't have permission to view exams.")
        return redirect('dashboard')
    
    # Filter exams by school
    exams = Exam.objects.filter(school=user.school).order_by('-date_started')
    
    return render(request, 'academic/exam_list.html', {'exams': exams})

@login_required
def classroom_list(request):
    user = request.user
    
    # ✅ UPDATED: SUPER_ADMIN sees all classrooms
    # ✅ UPDATED: ADMIN sees only classrooms in their school
    if user.role == 'SUPER_ADMIN':
        classrooms = Classroom.objects.all().select_related('class_teacher')
    elif user.role == 'ADMIN':
        classrooms = Classroom.objects.filter(school=user.school).select_related('class_teacher')
    elif user.role == 'HEAD_TEACHER':
        classrooms = Classroom.objects.filter(school=user.school)
    elif user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            
            # Get IDs of classes where teacher is CLASS TEACHER
            class_teacher_ids = Classroom.objects.filter(
                class_teacher=user
            ).values_list('id', flat=True)
            
            # Get IDs of classes that have subjects taught by this teacher
            subject_teacher_ids = Classroom.objects.filter(
                subjects__teacher=user
            ).values_list('id', flat=True)
            
            # Combine IDs using set
            combined_ids = set(class_teacher_ids) | set(subject_teacher_ids)
            
            # Get classrooms using the combined IDs
            classrooms = Classroom.objects.filter(id__in=combined_ids).select_related('class_teacher')
            
        except Teacher.DoesNotExist:
            classrooms = Classroom.objects.none()
    elif user.role == 'STUDENT':
        if hasattr(user, 'student_record_records') and user.student_record_records.current_class:
            classrooms = Classroom.objects.filter(id=user.student_record_records.current_class.id)
        else:
            classrooms = Classroom.objects.none()
    elif user.role == 'PARENT':
        from students.models import Students
        children = Students.objects.filter(parents=user)
        classroom_ids = children.exclude(current_class=None).values_list('current_class_id', flat=True).distinct()
        classrooms = Classroom.objects.filter(id__in=classroom_ids)
    else:
        classrooms = Classroom.objects.none()
    
    return render(request, 'academic/classroom_list.html', {'classrooms': classrooms})


@login_required
def subject_list(request):
    user = request.user
    
    # Get subjects based on user role
    if user.role == 'SUPER_ADMIN':
        subjects = Subject.objects.all()
    elif user.role == 'ADMIN':
        subjects = Subject.objects.all()
    elif user.role == 'TEACHER':
        # Teachers see subjects they are assigned to
        try:
            teacher = Teacher.objects.get(user=user)
            subjects = Subject.objects.filter(
                allocations__teacher=teacher
            ).distinct()
        except Teacher.DoesNotExist:
            subjects = Subject.objects.none()
    elif user.role == 'STUDENT':
        if hasattr(user, 'student_record_records') and user.student_record_records.current_class:
            subjects = user.student_record_records.current_class.subjects.all()
        else:
            subjects = Subject.objects.none()
    elif user.role == 'PARENT':
        from students.models import Students
        children = Students.objects.filter(parents=user)
        subjects = Subject.objects.none()
        for child in children:
            if child.current_class:
                subjects = subjects | child.current_class.subjects.all()
        subjects = subjects.distinct()
    else:
        subjects = Subject.objects.none()
    
    # For each subject, get the teacher from SubjectAllocation for this school
    subjects_with_teachers = []
    for subject in subjects:
        teacher_name = "Not Assigned"
        teacher_email = "-"
        
        if user.role == 'ADMIN' and user.school:
            # Get teacher from SubjectAllocation for this school
            allocation = SubjectAllocation.objects.filter(
                school=user.school,
                subject=subject
            ).first()
            if allocation and allocation.teacher:
                teacher_name = allocation.teacher.name
                if allocation.teacher.user:
                    teacher_email = allocation.teacher.user.email
        
        subjects_with_teachers.append({
            'subject': subject,
            'teacher_name': teacher_name,
            'teacher_email': teacher_email,
        })
    
    return render(request, 'academic/subject_list.html', {
        'subjects_with_teachers': subjects_with_teachers,
    })

@login_required
def add_classroom(request):
    # Only School Admin can add classrooms
    if request.user.role != 'HEAD_TEACHER':
        messages.error(request, "Only School Admin can add classrooms.")
        return redirect('classroom_list')
    
    from accounts.models import User
    # ✅ Get teachers from the Admin's school only
    teachers = User.objects.filter(role='TEACHER', school=request.user.school)

    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        stream = request.POST.get('stream', '').strip()
        class_teacher_id = request.POST.get('class_teacher')
        
        # Get selected subjects
        subject_ids = request.POST.getlist('subjects')

        if not name:
            messages.error(request, "Class Name is required!")
        else:
            try:
                # Create the classroom
                classroom = Classroom.objects.create(
                    name=name,
                    stream=stream if stream else None,
                    class_teacher_id=class_teacher_id if class_teacher_id else None,
                    school=request.user.school  # ✅ This is the key - assign to their school
                )
                
                # Assign subjects if any selected
                if subject_ids:
                    classroom.subjects.set(subject_ids)
                
                messages.success(request, f"Classroom '{name} {stream}' added successfully!")
                return redirect('classroom_list')
                
            except Exception as e:
                messages.error(request, f"Error creating classroom: {e}")
                print(f"Error details: {e}")  # For debugging

    all_subjects = Subject.objects.all()
    return render(request, 'academic/add_classroom.html', {
        'teachers': teachers,
        'all_subjects': all_subjects,
    })


@login_required
def add_subject(request):
    # Only Super Admin can add subjects (global subjects)
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can add subjects.")
        return redirect('subject_list')
    
    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        description = request.POST.get('description', '')

        if not name or not code:
            messages.error(request, "Subject Name and Code are required!")
        else:
            try:
                Subject.objects.create(
                    name=name, 
                    code=code, 
                    description=description
                )
                messages.success(request, f"Subject '{name} ({code})' added successfully!")
                return redirect('subject_list')
            except Exception as e:
                messages.error(request, f"Error adding subject: {e}")

    return render(request, 'academic/add_subject.html')  # No teachers context needed


@login_required
def add_exam(request):
    # Only ADMIN and HEAD_TEACHER can add exams for their school
    if request.user.role not in ['ADMIN', 'HEAD_TEACHER']:
        messages.error(request, "Only School Admin or Head Teacher can add exams.")
        return redirect('exam_list')
    
    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        exam_type = request.POST.get('exam_type')
        date_started = request.POST.get('date_started')

        if not name or not exam_type or not date_started:
            messages.error(request, "All fields are required!")
        else:
            try:
                Exam.objects.create(
                    name=name, 
                    exam_type=exam_type, 
                    date_started=date_started,
                    school=request.user.school,  # ✅ Assign to their school
                    max_marks=100
                )
                messages.success(request, f"Exam '{name}' added successfully!")
                return redirect('exam_list')
            except Exception as e:
                messages.error(request, f"Error saving exam: {e}")

    return render(request, 'academic/add_exam.html', {'exam_type': Exam.EXAM_TYPE})

@login_required
def add_results(request):
    user = request.user
    
    # ✅ SUPER ADMIN CANNOT ENTER RESULTS
    if user.role == 'SUPER_ADMIN':
        messages.error(request, "Super Admin cannot enter results. Only teachers can.")
        return redirect('dashboard')
    
    # Only ADMIN, HEAD_TEACHER, and TEACHER can enter results
    if user.role not in ['ADMIN', 'HEAD_TEACHER', 'TEACHER']:
        messages.error(request, "You don't have permission to add results.")
        return redirect('dashboard')
    
    # ========== GET FILTER PARAMETERS ==========
    selected_class = request.GET.get('class')
    selected_exam = request.GET.get('exam')
    
    # Initialize empty variables
    subjects_taught = Subject.objects.none()
    classes_taught = Classroom.objects.none()
    students = Students.objects.none()
    existing_results = {}
    
    # ========== ADMIN VIEW (School Admin) ==========
    if user.role == 'ADMIN':
        subjects_taught = Subject.objects.all()
        classes_taught = Classroom.objects.filter(school=user.school)
        
        if selected_class:
            students = Students.objects.filter(
                current_class_id=selected_class,
                school=user.school
            ).order_by('first_name')
    
    # ========== HEAD TEACHER VIEW ==========
    elif user.role == 'HEAD_TEACHER':
        subjects_taught = Subject.objects.all()
        classes_taught = Classroom.objects.filter(school=user.school)
        
        if selected_class:
            students = Students.objects.filter(
                current_class_id=selected_class,
                school=user.school
            ).order_by('first_name')
    
    # ========== TEACHER VIEW ==========
    elif user.role == 'TEACHER':
        try:
            teacher_record = Teacher.objects.get(user=user)
            
            # Get subjects this teacher teaches via SubjectAllocation
            subjects_taught = Subject.objects.filter(
                allocations__teacher=teacher_record
            ).distinct()
            
            # Get class IDs where teacher is assigned
            class_ids_from_allocations = set(
                Classroom.objects.filter(
                    subject_allocations__teacher=teacher_record
                ).values_list('id', flat=True)
            )
            
            class_ids_from_class_teacher = set(
                Classroom.objects.filter(class_teacher=user).values_list('id', flat=True)
            )
            
            all_class_ids = class_ids_from_allocations | class_ids_from_class_teacher
            classes_taught = Classroom.objects.filter(id__in=all_class_ids) if all_class_ids else Classroom.objects.none()
            
            if selected_class:
                if int(selected_class) in all_class_ids:
                    students = Students.objects.filter(current_class_id=selected_class).order_by('first_name')
                    if not students.exists():
                        messages.info(request, "No students found in this class. Please add students first.")
                else:
                    messages.error(request, "You are not authorized to enter results for this class.")
                    students = Students.objects.none()
            
        except Teacher.DoesNotExist:
            messages.error(request, "Teacher profile not found.")
            return redirect('dashboard')
    
    else:
        messages.error(request, "You don't have permission to add results.")
        return redirect('dashboard')
    
    exams = Exam.objects.all()
    
    # Get existing results for matrix pre-fill
    if selected_class and selected_exam and students.exists():
        results_qs = Results.objects.filter(
            exam_id=selected_exam,
            student_id__in=[s.id for s in students]
        ).select_related('student', 'subject')
        
        for result in results_qs:
            key = f"{result.student.id}_{result.subject.id}"
            existing_results[key] = {
                'marks': result.marks_obtained,
                'remark': result.teacher_remark,
                'status': result.status,
                'result_id': result.id,
            }
    
    # ========== HANDLE POST REQUEST ==========
    if request.method == "POST":
        action = request.POST.get('action')
        class_id = request.POST.get('class_id')
        exam_id = request.POST.get('exam_id')
        
        if not class_id or not exam_id:
            messages.error(request, "Missing class or exam information.")
            return redirect('add_results')
        
        selected_class = class_id
        selected_exam = exam_id
        
        students_in_class = Students.objects.filter(current_class_id=class_id)
        subjects_in_class = Subject.objects.all()
        
        # If teacher, filter subjects they teach
        if user.role == 'TEACHER':
            try:
                teacher_record = Teacher.objects.get(user=user)
                subjects_in_class = Subject.objects.filter(
                    allocations__teacher=teacher_record
                ).distinct()
            except Teacher.DoesNotExist:
                subjects_in_class = Subject.objects.none()
        
        success_count = 0
        error_count = 0
        
        for student in students_in_class:
            for subject in subjects_in_class:
                marks_key = f'marks_{student.id}_{subject.id}'
                remark_key = f'remark_{student.id}_{subject.id}'
                marks = request.POST.get(marks_key)
                
                if marks and marks.strip():
                    try:
                        marks_value = int(marks)
                        if 0 <= marks_value <= 100:
                            remark = request.POST.get(remark_key, '')
                            
                            # Check if result already exists and is published
                            existing = Results.objects.filter(
                                student=student,
                                subject=subject,
                                exam_id=exam_id
                            ).first()
                            
                            if existing and existing.status == 'PUBLISHED' and user.role != 'SUPER_ADMIN':
                                messages.warning(request, f"Cannot edit {student.first_name} - {subject.name} results already published.")
                                continue
                            
                            # Set status based on action
                            if action == 'save_draft':
                                status = 'DRAFT'
                                submitted_by = None
                                submitted_at = None
                            elif action == 'submit_approval':
                                status = 'PENDING'
                                submitted_by = user
                                submitted_at = timezone.now()
                            else:
                                status = 'DRAFT'
                                submitted_by = None
                                submitted_at = None
                            
                            Results.objects.update_or_create(
                                student=student,
                                subject=subject,
                                exam_id=exam_id,
                                defaults={
                                    'marks_obtained': marks_value,
                                    'teacher_remark': remark,
                                    'out_of': 100,
                                    'status': status,
                                    'submitted_by': submitted_by,
                                    'submitted_at': submitted_at,
                                    'school_id': student.school_id,
                                }
                            )
                            success_count += 1
                        else:
                            error_count += 1
                    except ValueError:
                        error_count += 1
        
        # Send notification if submitted for approval
        if action == 'submit_approval' and success_count > 0:
            from notification.models import Notification
            from accounts.models import User
            
            # Get school from first student
            if students_in_class.exists():
                school = students_in_class.first().school
                school_admins = User.objects.filter(role='ADMIN', school=school)
                class_obj = Classroom.objects.get(id=class_id)
                exam_obj = Exam.objects.get(id=exam_id)
                
                for admin in school_admins:
                    Notification.objects.create(
                        sender=user,
                        recipient=admin,
                        title="📋 Results Pending Approval",
                        message=f"{user.get_full_name()} submitted results for {class_obj.name} ({exam_obj.name}).",
                        notification_type='RESULT'
                    )
        
        if success_count > 0:
            if action == 'save_draft':
                messages.success(request, f"Saved {success_count} results as DRAFT.")
            elif action == 'submit_approval':
                messages.success(request, f"Submitted {success_count} results for approval. School Admin has been notified.")
        if error_count > 0:
            messages.warning(request, f"Failed to save {error_count} results. Marks must be between 0-100.")
        
        return redirect(f"{request.path}?class={class_id}&exam={exam_id}")
    
    # ========== PREPARE CONTEXT FOR TEMPLATE ==========
    context = {
        'subjects': subjects_taught,
        'classes': classes_taught,
        'exams': exams,
        'students': students,
        'existing_results': existing_results,
        'selected_class': selected_class,
        'selected_exam': selected_exam,
        'user_role': user.role,
    }
    
    return render(request, 'academic/add_results.html', context)

@login_required
def delete_teacher(request, pk):
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Only Super Admin can delete teachers.")
        return redirect('teacher_list')
    
    teacher = get_object_or_404(Teacher, pk=pk)
    name = teacher.name
    
    if teacher.user:
        teacher.user.delete()
    else:
        teacher.delete()
    
    messages.success(request, f"Teacher {name} deleted successfully!")
    return redirect('teacher_list')


from django.utils import timezone
from datetime import timedelta


@login_required
def pending_approvals(request):
    user = request.user
    
    # Only School Admin can approve results
    if user.role != 'ADMIN':
        messages.error(request, "Only School Admin can approve results.")
        return redirect('dashboard')
    
    # School Admin sees ONLY their school's pending results
    pending_results = Results.objects.filter(
        status='PENDING',
        school=user.school
    ).select_related('student', 'subject', 'exam', 'submitted_by', 'school')
    
    # Group by exam and subject
    grouped = {}
    for result in pending_results:
        key = f"{result.exam.id}_{result.subject.id}_{result.school.id if result.school else 0}"
        if key not in grouped:
            grouped[key] = {
                'exam': result.exam,
                'subject': result.subject,
                'school': result.school,
                'submitted_by': result.submitted_by,
                'submitted_at': result.submitted_at,
                'results': []
            }
        grouped[key]['results'].append(result)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        result_id = request.POST.get('result_id')
        rejection_reason = request.POST.get('rejection_reason', '')
        
        result = get_object_or_404(Results, id=result_id)
        
        # Check permission for School Admin (can only approve their school's results)
        if user.role == 'ADMIN' and result.school != user.school:
            messages.error(request, "You can only approve results from your school.")
            return redirect('pending_approvals')
        
        if action == 'approve':
            result.status = 'APPROVED'
            result.approved_by = user
            result.approved_at = timezone.now()
            result.published_at = timezone.now()
            result.expires_at = timezone.now() + timedelta(days=21)
            result.save()
            
            # Update all results for same exam, subject, and class
            Results.objects.filter(
                exam=result.exam,
                subject=result.subject,
                student__current_class=result.student.current_class
            ).update(
                status='PUBLISHED',
                published_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=21)
            )
            
            from notification.models import Notification
            if result.submitted_by:
                Notification.objects.create(
                    sender=user,
                    recipient=result.submitted_by,
                    title="✅ Results Approved",
                    message=f"Your {result.subject.name} results have been approved and published.",
                    notification_type='ALL'
                )
            
            messages.success(request, f"✅ Results approved successfully!")
            
        elif action == 'reject':
            result.status = 'REJECTED'
            result.rejection_reason = rejection_reason
            result.save()
            
            from notification.models import Notification
            if result.submitted_by:
                Notification.objects.create(
                    sender=user,
                    recipient=result.submitted_by,
                    title="❌ Results Rejected",
                    message=f"Your {result.subject.name} results were rejected. Reason: {rejection_reason}",
                    notification_type='ALL'
                )
            
            messages.warning(request, f"❌ Results rejected.")
        
        return redirect('pending_approvals')
    
    context = {
        'grouped_pending': grouped.values(),
        'pending_count': pending_results.count(),
        'user_role': user.role,
    }
    return render(request, 'academic/pending_approvals.html', context)

@login_required
def submission_dashboard(request):
    """School Admin - View submission progress"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Only School Admin can access this page.")
        return redirect('dashboard')
    
    school = request.user.school
    selected_exam_id = request.GET.get('exam')
    
    exams = Exam.objects.all().order_by('-date_started')
    classrooms = Classroom.objects.filter(school=school)
    subjects = Subject.objects.all()
    
    if not selected_exam_id and exams.exists():
        selected_exam_id = exams.first().id
    
    selected_exam = None
    if selected_exam_id:
        selected_exam = get_object_or_404(Exam, id=selected_exam_id)
    
    classes_data = []
    total_subjects_count = 0
    total_submitted_count = 0
    total_pending_count = 0
    
    for classroom in classrooms:
        classroom_subjects = classroom.subjects.all()
        if not classroom_subjects.exists():
            classroom_subjects = subjects
        
        submitted_count = 0
        pending_count = 0
        missing_count = 0
        
        for subject in classroom_subjects:
            total_subjects_count += 1
            
            results = Results.objects.filter(
                school=school,
                exam=selected_exam,
                subject=subject,
                student__current_class=classroom
            )
            
            if results.filter(status='PUBLISHED').exists():
                submitted_count += 1
                total_submitted_count += 1
            elif results.filter(status='PENDING').exists():
                pending_count += 1
                total_pending_count += 1
                total_submitted_count += 1
            else:
                missing_count += 1
        
        class_total = len(classroom_subjects)
        class_percentage = round(((submitted_count + pending_count) / class_total * 100), 1) if class_total > 0 else 0
        
        classes_data.append({
            'classroom': classroom,
            'total_subjects': class_total,
            'submitted_count': submitted_count,
            'pending_count': pending_count,
            'missing_count': missing_count,
            'percentage': class_percentage,
        })
    
    overall_percentage = round((total_submitted_count / total_subjects_count * 100), 1) if total_subjects_count > 0 else 0
    
    context = {
        'exams': exams,
        'selected_exam': selected_exam,
        'classes_data': classes_data,
        'total_subjects': total_subjects_count,
        'total_submitted': total_submitted_count,
        'pending_count': total_pending_count,
        'overall_percentage': overall_percentage,
    }
    return render(request, 'academic/submission_dashboard.html', context)


from django.utils import timezone
from datetime import timedelta

@login_required
def publish_all_results(request):
    """School Admin - Publish ALL pending results for an exam"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Only School Admin can publish results.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        exam_id = request.POST.get('exam_id')
        school = request.user.school
        
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Get all pending results for this school and exam
        pending_results = Results.objects.filter(
            school=school,
            exam=exam,
            status='PENDING'
        )
        
        count = pending_results.count()
        
        if count == 0:
            messages.warning(request, f"No pending results found for {exam.name}.")
        else:
            # Publish all
            pending_results.update(
                status='PUBLISHED',
                approved_by=request.user,
                approved_at=timezone.now(),
                published_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=21)
            )
            
            # Send notifications to teachers
            from notification.models import Notification
            teachers_notified = set()
            for result in pending_results:
                if result.submitted_by and result.submitted_by.id not in teachers_notified:
                    teachers_notified.add(result.submitted_by.id)
                    Notification.objects.create(
                        sender=request.user,
                        recipient=result.submitted_by,
                        title="✅ Results Published",
                        message=f"All results for {exam.name} have been approved and published.",
                        notification_type='ALL'
                    )
            
            messages.success(request, f"✅ Published {count} results for {exam.name}!")
        
        return redirect('submission_dashboard')
    
    return redirect('submission_dashboard')


def subject_allocations(request):
    if request.user.role not in ['ADMIN', 'HEAD_TEACHER']:
        messages.error(request, "Only Head Teacher can manage subject allocations.")
        return redirect('dashboard')
    
    school = request.user.school
    classrooms = Classroom.objects.filter(school=school)
    subjects = Subject.objects.all()
    teachers = Teacher.objects.filter(school=school)
    
    # Create a simple lookup dict: "classroom_id_subject_id" -> teacher_id
    allocation_map = {}
    allocations = SubjectAllocation.objects.filter(school=school)
    for alloc in allocations:
        key = f"{alloc.classroom.id}_{alloc.subject.id}"
        allocation_map[key] = str(alloc.teacher.id)  # Store as string for comparison
    
    if request.method == 'POST':
        # Process form submissions
        for classroom in classrooms:
            for subject in subjects:
                field_name = f'teacher_{classroom.id}_{subject.id}'
                teacher_id = request.POST.get(field_name)
                
                if teacher_id and teacher_id != '':
                    # Update or create allocation
                    SubjectAllocation.objects.update_or_create(
                        school=school,
                        classroom=classroom,
                        subject=subject,
                        defaults={'teacher_id': teacher_id}
                    )
                else:
                    # Delete allocation if exists (teacher removed)
                    SubjectAllocation.objects.filter(
                        school=school,
                        classroom=classroom,
                        subject=subject
                    ).delete()
        
        messages.success(request, "Teacher assignments saved successfully!")
        return redirect('subject_allocations')  # ✅ Fixed: stay on same page
    
    context = {
        'classrooms': classrooms,
        'subjects': subjects,
        'teachers': teachers,
        'allocation_map': allocation_map,
    }
    return render(request, 'academic/subject_allocations.html', context)

@login_required
def my_allocations(request):
    """Teacher view - See their assigned subjects and classes"""
    if request.user.role != 'TEACHER':
        return redirect('dashboard')
    
    try:
        teacher = Teacher.objects.get(user=request.user)
        allocations = SubjectAllocation.objects.filter(
            teacher=teacher,
            school=request.user.school
        ).select_related('classroom', 'subject')
        
        # Group by classroom
        classes_dict = {}
        for alloc in allocations:
            class_name = str(alloc.classroom)
            if class_name not in classes_dict:
                classes_dict[class_name] = []
            classes_dict[class_name].append(alloc.subject.name)
        
        context = {
            'allocations': allocations,
            'classes_dict': classes_dict,
        }
        return render(request, 'academic/my_allocations.html', context)
        
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect('dashboard')
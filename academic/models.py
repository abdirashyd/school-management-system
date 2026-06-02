from django.db import models
from django.core.exceptions import ValidationError
import csv
from django.http import HttpResponse
from django.conf import settings


class Classroom(models.Model):
    # School field - which school this classroom belongs to
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='classrooms', null=True, blank=True)
    
    name = models.CharField(max_length=50)
    stream = models.CharField(max_length=50, null=True, blank=True)
    subjects = models.ManyToManyField('Subject', related_name='classrooms', blank=True)

    class_teacher = models.OneToOneField(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role': 'TEACHER'},
        related_name='manage_classes'
    )

    def __str__(self):
        if self.stream:
            return f"{self.name} {self.stream}"
        return self.name
    
    def get_students_count(self):
        return self.students.count()
    
    def get_capacity_status(self):
        count = self.get_students_count()
        if count >= 70:
            return "Full"
        elif count >= 55:
            return "Nearly Full"
        else:
            return "Available"


class Teacher(models.Model):
    # School field - which school this teacher belongs to
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='teachers', null=True, blank=True)
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='academic_teacher',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    tsc_number = models.CharField(max_length=50, unique=True)
   
    phone = models.CharField(max_length=15)
    address = models.TextField(blank=True, null=True)
    experience = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    qualification = models.CharField(max_length=100, blank=True, null=True)
    
    date_of_joining = models.DateField(blank=True, null=True)
    
    def __str__(self):
        return self.name if self.name else 'Unnamed Teacher'


class Subject(models.Model):
    # NO school field - Super Admin controls subjects centrally
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True, null=True)
    
    # Optional: Default teacher (can be overridden by SubjectAllocation)
    teacher = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role': 'TEACHER'},
        related_name='subjects_taught'
    )

    def __str__(self):
        return f"{self.name} ({self.code})"


class Exam(models.Model):
    EXAM_TYPE = (
        ('OPENER', 'Opener Exam'),
        ('MIDTERM', 'Midterm Exam'),
        ('ENDTERM', 'End of Term'),
    )
    # ADD THIS FIELD
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, 
                               related_name='exams', null=True, blank=True)
    name = models.CharField(max_length=100)
    exam_type = models.CharField(max_length=20, choices=EXAM_TYPE)
    date_started = models.DateTimeField()
    max_marks = models.IntegerField(default=100)

    def __str__(self):
        return f"{self.name} ({self.get_exam_type_display()})"


class Results(models.Model):
    # School field - for filtering by school
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='results', null=True, blank=True)
    
    student = models.ForeignKey('students.Students', on_delete=models.CASCADE, related_name='results')
    subject = models.ForeignKey('academic.Subject', on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)

    marks_obtained = models.PositiveIntegerField()
    out_of = models.PositiveIntegerField(default=100)

    teacher_remark = models.TextField(blank=True, null=True)
    create_at = models.DateTimeField(auto_now_add=True)

    STATUS_CHOICES = (
        ('DRAFT', 'Draft - Not Submitted'),
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('PUBLISHED', 'Published - Visible'),
        ('EXPIRED', 'Expired'),
    )
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_results'
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_results'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    class Meta:
        unique_together = ('student', 'subject', 'exam')

    @property
    def grades(self):
        percentage = (self.marks_obtained / self.out_of) * 100
        
        if percentage >= 80:
            return "E (Exceeding Expectations)"
        elif percentage >= 70:
            return "D- (Meeting Expectations)"
        elif percentage >= 60:
            return "D (Meeting Expectations)"
        elif percentage >= 50:
            return "C- (Approaching Expectations)"
        elif percentage >= 40:
            return "C (Approaching Expectations)"
        elif percentage >= 30:
            return "B (Below Expectations)"
        else:
            return "A (Below Expectations)"

    def __str__(self):
        return f"{self.student.first_name} - {self.subject.name}: {self.marks_obtained}/{self.out_of}"
    
    def clean(self):
        if self.marks_obtained > self.out_of:
            raise ValidationError(
                f"Wait! Marks ({self.marks_obtained}) cannot be higher than the total ({self.out_of})."
            )


def download_marks_sheet(modeladmin, request, queryset):
    """Download CSV template for marks entry"""
    from students.models import Students
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="mark_sheet_template.csv"'

    writer = csv.writer(response)
    writer.writerow(['Student_ID', 'Reg_No', 'Full_Name', 'Marks_Out_of_100'])

    for exam in queryset:
        students = Students.objects.all()[:10]
        for s in students:
            writer.writerow([s.id, s.registration_number, f"{s.first_name} {s.last_name}", ""])
    
    return response


def get_class_rankings(classroom_id, exam_id):
    """Calculate rankings for a class in a specific exam"""
    from django.db.models import Sum
    from students.models import Students
    
    students = Students.objects.filter(current_class_id=classroom_id)
    rank_list = []
    
    for student in students:
        total_data = student.results.filter(exam_id=exam_id).aggregate(Sum('marks_obtained'))
        total = int(total_data['marks_obtained__sum'] or 0)
        rank_list.append({'student': student, 'total': total})

    rank_list.sort(key=lambda x: x['total'], reverse=True)

    last_total = None
    last_rank = 0
    for index, item in enumerate(rank_list):
        if item['total'] == last_total:
            item['rank'] = last_rank
        else:
            item['rank'] = index + 1
            last_rank = item['rank']
            last_total = item['total']

    return rank_list


class GradeLevel(models.Model):
    """Grade configuration for CBC curriculum (Grade 1 to Grade 12)"""
    grade_number = models.IntegerField(unique=True)
    grade_name = models.CharField(max_length=50)
    level = models.CharField(max_length=20, choices=[
        ('PRIMARY', 'Primary School'),
        ('JUNIOR', 'Junior School'),
        ('SENIOR', 'Senior School'),
    ], default='PRIMARY')
    next_grade = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    is_graduation_grade = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Grade {self.grade_number}"
    
    class Meta:
        ordering = ['grade_number']


class PromotionHistory(models.Model):
    """Track student promotion history"""
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='promotion_histories', null=True, blank=True)
    
    student = models.ForeignKey('students.Students', on_delete=models.CASCADE, related_name='promotion_history')
    from_grade = models.ForeignKey(GradeLevel, on_delete=models.SET_NULL, null=True, related_name='promotions_from')
    to_grade = models.ForeignKey(GradeLevel, on_delete=models.SET_NULL, null=True, related_name='promotions_to')
    promoted_at = models.DateTimeField(auto_now_add=True)
    promoted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    academic_year = models.CharField(max_length=20, blank=True, null=True)
    
    def __str__(self):
        if self.to_grade:
            return f"{self.student.first_name} - Grade {self.from_grade.grade_number} → Grade {self.to_grade.grade_number}"
        return f"{self.student.first_name} - Graduated"
    
    class Meta:
        ordering = ['-promoted_at']


# ========== NEW: SUBJECT ALLOCATION MODEL ==========
class SubjectAllocation(models.Model):
    """Which teacher teaches which subject in which class for which school"""
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='subject_allocations')
    classroom = models.ForeignKey('Classroom', on_delete=models.CASCADE, related_name='subject_allocations')
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, related_name='allocations')
    teacher = models.ForeignKey('Teacher', on_delete=models.CASCADE, related_name='subject_allocations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['school', 'classroom', 'subject']  # One teacher per subject per class
        ordering = ['classroom__name', 'subject__name']
    
    def __str__(self):
        return f"{self.classroom.name} - {self.subject.name} → {self.teacher.name}"
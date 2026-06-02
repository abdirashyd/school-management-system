from django.db import models
from django.conf import settings
from accounts.models import User


class Students(models.Model):
    # ✅ ADD THIS - School field (which school this student belongs to)
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='students', null=True, blank=True)
    
    user = models.OneToOneField(
        'accounts.User', 
        on_delete=models.CASCADE, 
        related_name='student_record_records',
        null=True,
        blank=True
    )
    
    parents = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='children',
        null=True,
        blank=True,
        limit_choices_to={'role': 'PARENT'},
    )

    current_class = models.ForeignKey(
        'academic.Classroom',
        on_delete=models.SET_NULL,
        null=True,
        related_name='students',
    )
    
    GENDER_CH0ICES = (
        ('MALE', 'male'),
        ('FEMALE', 'female')
    )
    
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    registration_number = models.CharField(max_length=20, unique=True)

    is_active = models.BooleanField(default=True)
    date_enrolled = models.DateTimeField(auto_now_add=True)
    gender = models.CharField(max_length=10, choices=GENDER_CH0ICES, null=True, blank=True)
    
    last_total_marks = models.FloatField(default=0.0, editable=False)
    last_mean_score = models.FloatField(default=0.0, editable=False)
    address = models.TextField(blank=True, null=True, help_text="Residential address")
    has_leadership = models.BooleanField(default=False)
    medical_condition = models.TextField(blank=True, null=True, help_text="Any underlying medical conditions")

    current_grade = models.ForeignKey('academic.GradeLevel', on_delete=models.SET_NULL, null=True, blank=True)
    is_graduated = models.BooleanField(default=False)
    graduation_year = models.IntegerField(null=True, blank=True)
        
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.registration_number})"
    
    def get_total_marks(self, exam=None):
        """Get total marks for a specific exam or all exams"""
        from academic.models import Results
        
        if exam:
            results = self.results.filter(exam=exam)
        else:
            results = self.results.all()
        
        total = sum(res.marks_obtained for res in results)
        return total
    
    def get_mean_marks(self, exam=None):
        """Get mean marks for a specific exam or all exams"""
        from academic.models import Results
        
        if exam:
            results = self.results.filter(exam=exam)
        else:
            results = self.results.all()
        
        count = results.count()
        if count == 0:
            return 0
        return self.get_total_marks(exam) / count
    
    def get_mean_mark(self, exam=None):
        """Alias for get_mean_marks"""
        return self.get_mean_marks(exam)
    
    def get_fee_balance(self):
        """Calculate fee balance for this student"""
        from finance.models import Payement
        
        # Get total paid
        payments = Payement.objects.filter(student=self)
        total_paid = sum(float(p.amount_paid) for p in payments)
        
        # Return total paid (or modify based on your needs)
        # Since fee_amount was removed, just return total_paid or 0
        return total_paid
    
    def get_rank(self):
        """Calculate student's rank within their class based on total marks"""
        if not self.current_class:
            return "N/A"
        
        # Get all students in same class, ordered by total marks
        same_class_students = Students.objects.filter(
            current_class=self.current_class
        ).order_by('-last_total_marks')
        
        # Convert to list and find position
        student_list = list(same_class_students)
        if self in student_list:
            rank = student_list.index(self) + 1
            return f"{rank}/{len(student_list)}"
        return "N/A"
    
    def update_total_payable(self):
        """Update the total payable amount for this student"""
        from finance.models import Payement
        
        if self.current_class:
            fee_record, created = Payement.objects.get_or_create(student=self)
            fee_record.total_payable = self.current_class.fee_amount
            fee_record.save()

    def create_fee_notification(self):
        """Create notification for fee balance"""
        balance = self.get_fee_balance()
        if balance > 0:
            from django.apps import apps
            Notification = apps.get_model('notification', 'Notification')
            Notification.objects.create(
                student=self,
                title="Fee Balance Alert",
                message=f"Student {self.first_name} {self.last_name} has a pending balance of KES {balance:.2f}. Please follow up."
            )


class Attendance(models.Model):
    # ✅ ADD THIS - School field (which school this attendance belongs to)
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='attendances', null=True, blank=True)
    
    STATUS_CHOICES = (
        ('Present', 'Present'),
        ('Absent', 'Absent'),
        ('Excused', 'Excused'),
        ('Late', 'Late'),
    )
    
    student = models.ForeignKey(Students, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Present')
    remarks = models.TextField(blank=True, null=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marked_attendances'
    )

    class Meta:
        unique_together = ('student', 'date')

    def __str__(self):
        return f"{self.student.first_name} - {self.date} ({self.status})"
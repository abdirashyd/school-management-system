from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from decimal import Decimal
import math
from django.utils import timezone
from datetime import timedelta

# ========== SCHOOL MODEL ==========
class School(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='school_logos/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_schools')
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['name']


# ========== USER MODEL ==========
class UserManager(BaseUserManager):
    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set!")
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'SUPER_ADMIN')
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, username, password, **extra_fields)
    

class User(AbstractUser):
    ROLE_CHOICES = (
        ('SUPER_ADMIN', 'super_Admin'),
        ('ADMIN', 'admin'),
        ('HEAD_TEACHER', 'Head Teacher'), 
        ('TEACHER', 'teacher'),
        ('STUDENT', 'student'),
        ('PARENT', 'parent')
    )
    objects = UserManager()
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='STUDENT')
    is_approved = models.BooleanField(default=False)
    school = models.ForeignKey('School', on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


# ========== SCHOOL SUBSCRIPTION MODEL ==========
class SchoolSubscription(models.Model):
    """School subscription and billing information"""
    
    BILLING_CYCLE_CHOICES = (
        ('MONTHLY', 'Monthly'),
        ('TERMLY', 'Termly (3 months)'),
        ('ANNUALLY', 'Annually (9 months)'),
    )
    
    STATUS_CHOICES = (
        ('ACTIVE', 'Active - Paid'),
        ('PENDING', 'Pending Payment'),
        ('OVERDUE', 'Overdue'),
        ('SUSPENDED', 'Suspended'),
        ('CANCELLED', 'Cancelled'),
    )
    
    school = models.OneToOneField('School', on_delete=models.CASCADE, related_name='subscription')
    
    # Subscription status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default='MONTHLY')
    
    # First month flag (special KES 2,700 onboarding)
    is_first_month = models.BooleanField(default=True)
    
    # Pricing configuration
    small_school_fee = models.DecimalField(max_digits=10, decimal_places=2, default=2500)  # 0-149 students
    base_fee = models.DecimalField(max_digits=10, decimal_places=2, default=2700)  # 150 students
    block_size = models.IntegerField(default=7)  # 7 students per block
    block_increase_percent = models.DecimalField(max_digits=5, decimal_places=2, default=2.0)  # 2% per block
    
    # Dates
    subscription_start = models.DateTimeField(auto_now_add=True)
    current_period_start = models.DateTimeField(auto_now_add=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    next_billing_date = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def days_until_expiry(self):
        """Returns number of days until subscription expires"""
        if not self.current_period_end:
            return 0
        from django.utils import timezone
        delta = self.current_period_end - timezone.now()
        return max(0, delta.days)
    
    
    def get_student_count(self):
        """Get current active student count for this school"""
        from students.models import Students
        return Students.objects.filter(school=self.school, is_active=True).count()
    
    def calculate_monthly_fee(self, student_count=None):
        """Calculate monthly fee based on student count"""
        if self.is_first_month:
            return Decimal('2700.00')
        
        if student_count is None:
            student_count = self.get_student_count()
        
        if student_count < 150:
            return self.small_school_fee
        
        students_above_150 = student_count - 150
        blocks = math.ceil(students_above_150 / self.block_size)
        
        multiplier = (1 + (self.block_increase_percent / 100)) ** blocks
        fee = self.base_fee * Decimal(str(multiplier))
        
        return round(fee, 2)
    
    def calculate_termly_fee(self, student_count=None):
        monthly = self.calculate_monthly_fee(student_count)
        return monthly * 3
    
    def calculate_annual_fee(self, student_count=None):
        monthly = self.calculate_monthly_fee(student_count)
        return monthly * 9
    
    def get_current_fee(self, student_count=None):
        if self.billing_cycle == 'MONTHLY':
            return self.calculate_monthly_fee(student_count)
        elif self.billing_cycle == 'TERMLY':
            return self.calculate_termly_fee(student_count)
        else:
            return self.calculate_annual_fee(student_count)
    
    def update_billing_dates(self):
        from django.utils import timezone
        from datetime import timedelta
        
        if self.billing_cycle == 'MONTHLY':
            duration = timedelta(days=30)
        elif self.billing_cycle == 'TERMLY':
            duration = timedelta(days=90)
        else:
            duration = timedelta(days=270)
        
        self.current_period_end = timezone.now() + duration
        self.next_billing_date = timezone.now() + duration
        self.save()
    
    def can_access_system(self):
        if self.status == 'ACTIVE':
            return True
        if self.status == 'OVERDUE':
            if self.current_period_end:
                grace_end = self.current_period_end + timedelta(days=7)
                return timezone.now() <= grace_end
        return False
    
    def __str__(self):
        return f"{self.school.name} - {self.status}"


# ========== SUBSCRIPTION PAYMENT MODEL ==========
class SubscriptionPayment(models.Model):
    """Record of subscription payments made by school"""
    
    PAYMENT_STATUS = (
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    )
    
    subscription = models.ForeignKey('SchoolSubscription', on_delete=models.CASCADE, related_name='payments')
    school = models.ForeignKey('School', on_delete=models.CASCADE, related_name='subscription_payments')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    billing_cycle = models.CharField(max_length=20, choices=SchoolSubscription.BILLING_CYCLE_CHOICES)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField(null=True, blank=True)
    
    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    mpesa_receipt = models.CharField(max_length=100, blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='PENDING')
    paid_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def mark_completed(self, transaction_id, mpesa_receipt=None):
        from django.utils import timezone
        self.status = 'COMPLETED'
        self.transaction_id = transaction_id
        self.mpesa_receipt = mpesa_receipt
        self.paid_at = timezone.now()
        self.save()
        
        # Update subscription dates
        self.subscription.update_billing_dates()
    
    def __str__(self):
        return f"{self.school.name} - KES {self.amount} - {self.status}"


# ========== MPESA CONFIGURATION MODEL ==========
class SchoolMpesaConfig(models.Model):
    """M-Pesa configuration for each school"""
    
    ENV_CHOICES = (
        ('sandbox', 'Sandbox (Testing)'),
        ('production', 'Production (Live)'),
    )
    
    school = models.OneToOneField('School', on_delete=models.CASCADE, related_name='mpesa_config')
    
    # M-Pesa Credentials
    shortcode = models.CharField(max_length=50, blank=True, null=True, help_text="Paybill/Till Number")
    consumer_key = models.CharField(max_length=200, blank=True, null=True)
    consumer_secret = models.CharField(max_length=200, blank=True, null=True)
    passkey = models.CharField(max_length=200, blank=True, null=True)
    
    # Environment
    environment = models.CharField(max_length=20, choices=ENV_CHOICES, default='sandbox')
    
    # Status
    is_configured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_tested = models.DateTimeField(null=True, blank=True)
    test_response = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        status = "✅ Configured" if self.is_configured else "❌ Not configured"
        return f"{self.school.name} - {status}"


# ========== SUBSCRIPTION INVOICE MODEL ==========
class SubscriptionInvoice(models.Model):
    """Invoice for each billing period"""
    
    INVOICE_STATUS = (
        ('DRAFT', 'Draft'),
        ('SENT', 'Sent'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled'),
    )
    
    school = models.ForeignKey('School', on_delete=models.CASCADE, related_name='invoices')
    subscription = models.ForeignKey('SchoolSubscription', on_delete=models.CASCADE, related_name='invoices')
    
    invoice_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default='DRAFT')
    
    billing_period_start = models.DateTimeField()
    billing_period_end = models.DateTimeField()
    due_date = models.DateTimeField()
    paid_date = models.DateTimeField(null=True, blank=True)
    
    student_count_at_billing = models.IntegerField()
    fee_breakdown = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def mark_as_paid(self):
        from django.utils import timezone
        self.status = 'PAID'
        self.paid_date = timezone.now()
        self.save()
        self.subscription.status = 'ACTIVE'
        self.subscription.save()
    
    def is_overdue(self):
        from django.utils import timezone
        return self.status != 'PAID' and timezone.now() > self.due_date
    
    def __str__(self):
        return f"{self.invoice_number} - {self.school.name} - KES {self.amount}"


# ========== SIGNAL TO CREATE SUBSCRIPTION WHEN SCHOOL IS CREATED ==========
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=School)
def create_school_subscription(sender, instance, created, **kwargs):
    """Auto-create subscription when a new school is created"""
    if created:
        SchoolSubscription.objects.create(school=instance)
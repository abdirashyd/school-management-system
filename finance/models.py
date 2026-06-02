from django.db import models
from django.conf import settings


class Payement(models.Model):
    # ✅ ADD THIS - School field (which school this payment belongs to)
    school = models.ForeignKey('accounts.School', on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    
    METHODS = [
        ('M-Pesa', 'M-Pesa'),
        ('Bank', 'Bank Transfer'),
        ('Cash', 'Cash')
    ]
    
    student = models.ForeignKey('students.Students', on_delete=models.CASCADE, related_name="payments")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100)
    method = models.CharField(max_length=20, choices=METHODS, default='M-Pesa')
    date_paid = models.DateTimeField(auto_now_add=True)
    month = models.IntegerField(null=True, blank=True)
    year = models.IntegerField(default=2026, null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.student.first_name} - KES {self.amount_paid} ({self.reference})"
    
    class Meta:
        ordering = ['-date_paid']
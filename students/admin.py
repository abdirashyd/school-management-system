from django.contrib import admin
from .models import Students, Attendance
import csv
from django.http import HttpResponse


@admin.register(Students)
class StudentsAdmin(admin.ModelAdmin):
    list_display = (
        'first_name',
        'last_name',
        'registration_number',
        'current_class',
        'display_total',
        'display_mean',
        'class_rank',
        'grade_rank',
        'parents',
    )
    search_fields = ('first_name', 'last_name', 'registration_number')
    list_filter = ('current_class',)
    actions = ['export_students_csv']

    def display_total(self, obj):
        from academic.models import Results
        user_results = Results.objects.filter(student=obj)
        total = sum(r.marks_obtained for r in user_results)
        return total
    display_total.short_description = 'Total marks'

    def display_mean(self, obj):
        from academic.models import Results
        user_results = Results.objects.filter(student=obj)
        count = user_results.count()
        if count > 0:
            total = sum(r.marks_obtained for r in user_results)
            return round(total / count, 1)
        return "0.0"
    display_mean.short_description = 'Overall Mean'

    def class_rank(self, obj):
        queryset = Students.objects.filter(current_class=obj.current_class).order_by('-last_total_marks')
        student_ids = list(queryset.values_list('id', flat=True))
        try:
            rank = student_ids.index(obj.id) + 1
            return f"{rank}/{len(student_ids)}"
        except ValueError:
            return "_"
    class_rank.short_description = "Class Pos"

    def grade_rank(self, obj):
        queryset = Students.objects.filter(current_class__name=obj.current_class.name).order_by('-last_mean_score')
        student_ids = list(queryset.values_list('id', flat=True))
        try:
            rank = student_ids.index(obj.id) + 1
            return f"{rank}/{len(student_ids)}"
        except ValueError:
            return "_"
    grade_rank.short_description = "Grade Pos"

    @admin.action(description='Export Selected Students to CSV')
    def export_students_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="school_students.csv"'
        writer = csv.writer(response)
        writer.writerow(['Reg No', 'First_name', 'Last_name', 'Class', 'Balance'])
        
        for s in queryset:
            writer.writerow([
                s.registration_number,
                s.first_name,
                s.last_name,
                s.current_class,
                self.display_balance(s) if hasattr(self, 'display_balance') else "0"
            ])
        return response


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'status')
    list_filter = ('date', 'status', 'student__current_class')
    search_fields = ('student__first_name', 'student__registration_number')
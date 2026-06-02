from django import forms
from .models import SchoolMpesaConfig

class SchoolMpesaConfigForm(forms.ModelForm):
    class Meta:
        model = SchoolMpesaConfig
        fields = ['shortcode', 'consumer_key', 'consumer_secret', 'passkey', 'environment']
        widgets = {
            'shortcode': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 123456'}),
            'consumer_key': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter Consumer Key'}),
            'consumer_secret': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter Consumer Secret'}),
            'passkey': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter Passkey'}),
            'environment': forms.Select(attrs={'class': 'form-control'}),
        }
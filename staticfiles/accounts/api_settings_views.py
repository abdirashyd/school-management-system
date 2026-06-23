from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
import os
import base64
import requests

from .models import SchoolMpesaConfig, School
from dotenv import set_key, load_dotenv


# ========== API SETTINGS DASHBOARD ==========
@login_required
def api_settings_dashboard(request):
    """Super Admin - Central API Settings Dashboard"""
    
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied. Only Super Admin can access API settings.")
        return redirect('dashboard')
    
    # Get all schools with their M-Pesa configs
    schools = School.objects.all()
    school_configs = []
    
    for school in schools:
        config, created = SchoolMpesaConfig.objects.get_or_create(school=school)
        school_configs.append({
            'school': school,
            'config': config,
            'has_credentials': bool(config.consumer_key and config.consumer_secret)
        })
    
    # Get global settings from .env
    load_dotenv()
    
    context = {
        'schools': school_configs,
        'global_mpesa_configured': bool(os.getenv('MPESA_CONSUMER_KEY')),
        'stripe_configured': bool(os.getenv('STRIPE_SECRET_KEY')),
        'email_configured': bool(os.getenv('EMAIL_HOST_USER')),
    }
    
    return render(request, 'accounts/api_settings_dashboard.html', context)


# ========== M-PESA GLOBAL SETTINGS ==========
@login_required
def api_mpesa_global_settings(request):
    """Super Admin - Set global M-Pesa credentials"""
    
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        consumer_key = request.POST.get('consumer_key', '').strip()
        consumer_secret = request.POST.get('consumer_secret', '').strip()
        shortcode = request.POST.get('shortcode', '').strip()
        passkey = request.POST.get('passkey', '').strip()
        environment = request.POST.get('environment', 'sandbox')
        apply_to_all = request.POST.get('apply_to_all_schools') == 'on'
        
        # Update .env file
        env_path = os.path.join(settings.BASE_DIR, '.env')
        
        if consumer_key:
            set_key(env_path, 'MPESA_CONSUMER_KEY', consumer_key)
        if consumer_secret:
            set_key(env_path, 'MPESA_CONSUMER_SECRET', consumer_secret)
        if shortcode:
            set_key(env_path, 'MPESA_SHORTCODE', shortcode)
        if passkey:
            set_key(env_path, 'MPESA_PASSKEY', passkey)
        set_key(env_path, 'MPESA_ENV', environment)
        
        # Apply to all schools if checked
        if apply_to_all:
            for school in School.objects.all():
                config, _ = SchoolMpesaConfig.objects.get_or_create(school=school)
                config.consumer_key = consumer_key
                config.consumer_secret = consumer_secret
                config.shortcode = shortcode
                config.passkey = passkey
                config.environment = environment
                config.is_configured = bool(consumer_key and consumer_secret)
                config.save()
            messages.info(request, f"Applied to {School.objects.count()} schools.")
        
        messages.success(request, "Global M-Pesa settings updated successfully!")
        return redirect('api_settings')
    
    load_dotenv()
    context = {
        'consumer_key': os.getenv('MPESA_CONSUMER_KEY', ''),
        'consumer_secret': os.getenv('MPESA_CONSUMER_SECRET', ''),
        'shortcode': os.getenv('MPESA_SHORTCODE', ''),
        'passkey': os.getenv('MPESA_PASSKEY', ''),
        'environment': os.getenv('MPESA_ENV', 'sandbox'),
        'schools_count': School.objects.count(),
    }
    return render(request, 'accounts/api_mpesa_global.html', context)


# ========== M-PESA SCHOOL SPECIFIC SETTINGS ==========
@login_required
def api_mpesa_school_settings(request, school_id):
    """Super Admin - Configure M-Pesa for a specific school"""
    
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    school = get_object_or_404(School, id=school_id)
    config, created = SchoolMpesaConfig.objects.get_or_create(school=school)
    
    if request.method == 'POST':
        config.consumer_key = request.POST.get('consumer_key', '').strip()
        config.consumer_secret = request.POST.get('consumer_secret', '').strip()
        config.shortcode = request.POST.get('shortcode', '').strip()
        config.passkey = request.POST.get('passkey', '').strip()
        config.environment = request.POST.get('environment', 'sandbox')
        config.is_configured = bool(config.consumer_key and config.consumer_secret)
        config.save()
        
        messages.success(request, f"M-Pesa settings for {school.name} updated!")
        return redirect('api_settings')
    
    context = {
        'school': school,
        'config': config,
    }
    return render(request, 'accounts/api_mpesa_school.html', context)


# ========== STRIPE SETTINGS ==========
@login_required
def api_stripe_settings(request):
    """Super Admin - Configure Stripe globally"""
    
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        public_key = request.POST.get('public_key', '').strip()
        secret_key = request.POST.get('secret_key', '').strip()
        webhook_secret = request.POST.get('webhook_secret', '').strip()
        
        env_path = os.path.join(settings.BASE_DIR, '.env')
        
        if public_key:
            set_key(env_path, 'STRIPE_PUBLIC_KEY', public_key)
        if secret_key:
            set_key(env_path, 'STRIPE_SECRET_KEY', secret_key)
        if webhook_secret:
            set_key(env_path, 'STRIPE_WEBHOOK_SECRET', webhook_secret)
        
        messages.success(request, "Stripe settings updated successfully!")
        return redirect('api_settings')
    
    load_dotenv()
    context = {
        'public_key': os.getenv('STRIPE_PUBLIC_KEY', ''),
        'secret_key': os.getenv('STRIPE_SECRET_KEY', ''),
        'webhook_secret': os.getenv('STRIPE_WEBHOOK_SECRET', ''),
    }
    return render(request, 'accounts/api_stripe_settings.html', context)


# ========== EMAIL SETTINGS ==========
@login_required
def api_email_settings(request):
    """Super Admin - Configure Email globally"""
    
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        host = request.POST.get('email_host', '').strip()
        port = request.POST.get('email_port', '587').strip()
        user = request.POST.get('email_user', '').strip()
        password = request.POST.get('email_password', '').strip()
        use_tls = request.POST.get('use_tls') == 'on'
        
        env_path = os.path.join(settings.BASE_DIR, '.env')
        
        if host:
            set_key(env_path, 'EMAIL_HOST', host)
        if port:
            set_key(env_path, 'EMAIL_PORT', port)
        if user:
            set_key(env_path, 'EMAIL_HOST_USER', user)
        if password:
            set_key(env_path, 'EMAIL_HOST_PASSWORD', password)
        set_key(env_path, 'EMAIL_USE_TLS', 'True' if use_tls else 'False')
        
        messages.success(request, "Email settings updated successfully!")
        return redirect('api_settings')
    
    load_dotenv()
    context = {
        'email_host': os.getenv('EMAIL_HOST', 'smtp.gmail.com'),
        'email_port': os.getenv('EMAIL_PORT', '587'),
        'email_user': os.getenv('EMAIL_HOST_USER', ''),
        'email_use_tls': os.getenv('EMAIL_USE_TLS', 'True') == 'True',
    }
    return render(request, 'accounts/api_email_settings.html', context)


# ========== SYSTEM SETTINGS ==========
@login_required
def api_system_settings(request):
    """Super Admin - System-wide settings"""
    
    if request.user.role != 'SUPER_ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        site_name = request.POST.get('site_name', 'EduNexus').strip()
        default_password = request.POST.get('default_password', 'School2026')
        enable_mpesa = request.POST.get('enable_mpesa') == 'on'
        enable_stripe = request.POST.get('enable_stripe') == 'on'
        enable_email = request.POST.get('enable_email') == 'on'
        
        env_path = os.path.join(settings.BASE_DIR, '.env')
        
        set_key(env_path, 'SITE_NAME', site_name)
        set_key(env_path, 'DEFAULT_PASSWORD', default_password)
        set_key(env_path, 'ENABLE_MPESA', 'True' if enable_mpesa else 'False')
        set_key(env_path, 'ENABLE_STRIPE', 'True' if enable_stripe else 'False')
        set_key(env_path, 'ENABLE_EMAIL', 'True' if enable_email else 'False')
        
        messages.success(request, "System settings updated successfully!")
        return redirect('api_settings')
    
    load_dotenv()
    context = {
        'site_name': os.getenv('SITE_NAME', 'EduNexus'),
        'default_password': os.getenv('DEFAULT_PASSWORD', 'School2026'),
        'enable_mpesa': os.getenv('ENABLE_MPESA', 'True') == 'True',
        'enable_stripe': os.getenv('ENABLE_STRIPE', 'False') == 'True',
        'enable_email': os.getenv('ENABLE_EMAIL', 'True') == 'True',
    }
    return render(request, 'accounts/api_system_settings.html', context)


# ========== SCHOOL API STATUS ==========
@login_required
def school_api_status(request):
    """School Admin - View API status (read-only)"""
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    config = request.user.school.mpesa_config
    
    context = {
        'is_configured': config.is_configured,
        'environment': config.environment,
        'last_tested': config.last_tested,
        'test_response': config.test_response,
    }
    return render(request, 'accounts/school_api_status.html', context)


# ========== TEST M-PESA CONNECTION ==========
@login_required
def api_test_mpesa_connection(request, school_id=None):
    """Super Admin - Test M-Pesa connection"""
    
    if request.user.role != 'SUPER_ADMIN':
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    if school_id:
        school = get_object_or_404(School, id=school_id)
        config = school.mpesa_config
    else:
        return JsonResponse({'success': False, 'message': 'School ID required'}, status=400)
    
    if not config or not config.consumer_key:
        return JsonResponse({'success': False, 'message': 'No M-Pesa credentials configured for this school'})
    
    if config.environment == 'sandbox':
        api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    else:
        api_url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    credentials = f"{config.consumer_key}:{config.consumer_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    headers = {'Authorization': f'Basic {encoded}'}
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            config.is_configured = True
            config.last_tested = timezone.now()
            config.test_response = "✅ Connection successful!"
            config.save()
            return JsonResponse({'success': True, 'message': 'Connection successful!'})
        else:
            config.is_configured = False
            config.test_response = f"❌ Error: {response.status_code}"
            config.save()
            return JsonResponse({'success': False, 'message': f'Invalid credentials. Error: {response.status_code}'})
            
    except Exception as e:
        config.is_configured = False
        config.test_response = f"❌ Error: {str(e)}"
        config.save()
        return JsonResponse({'success': False, 'message': f'Connection failed: {str(e)}'})
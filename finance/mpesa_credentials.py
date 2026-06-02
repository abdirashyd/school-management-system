# finance/mpesa_credentials.py

from django.conf import settings

# Read from Django settings (which loads from .env)
CONSUMER_KEY = settings.MPESA_CONSUMER_KEY
CONSUMER_SECRET = settings.MPESA_CONSUMER_SECRET
PASSKEY = settings.MPESA_PASSKEY
SHORTCODE = settings.MPESA_SHORTCODE
CALLBACK_URL = settings.MPESA_CALLBACK_URL

# Determine API base URL based on environment
if settings.MPESA_ENV == 'sandbox':
    API_BASE_URL = "https://sandbox.safaricom.co.ke"
else:
    API_BASE_URL = "https://api.safaricom.co.ke"

OAUTH_URL = "/oauth/v1/generate?grant_type=client_credentials"
STK_PUSH_URL = "/mpesa/stkpush/v1/processrequest"
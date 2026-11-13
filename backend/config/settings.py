import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Safe by default: debug only when asked for, and no shared fallback key outside debug.
DEBUG = os.environ.get('DJANGO_DEBUG') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or ('dev-only-insecure-key' if DEBUG else None)
if not SECRET_KEY:
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development).')

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # raise to a year, add includeSubDomains, once HTTPS is proven
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Behind a TLS-terminating proxy, trust its X-Forwarded-Proto, or SSL redirect loops.
    # The proxy must overwrite that header from clients.
    if os.environ.get('DJANGO_NUM_PROXIES', '0') != '0':
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'django_otp',
    'django_otp.plugins.otp_totp',  # admin 2FA: authenticator-app codes
    'shop',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',  # marks admin sessions that passed 2FA
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [{  # admin only
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],  # admin/base_site.html: branding and styles on every admin page
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ.get('POSTGRES_DB', 'haat'),
    'USER': os.environ.get('POSTGRES_USER', ''),
    'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
    'HOST': os.environ.get('POSTGRES_HOST', ''),  # empty = local Unix socket
    'PORT': os.environ.get('POSTGRES_PORT', ''),
}}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': f'django.contrib.auth.password_validation.{v}'}
    for v in ['UserAttributeSimilarityValidator', 'MinimumLengthValidator',
              'CommonPasswordValidator', 'NumericPasswordValidator']
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'  # `manage.py collectstatic` target, for admin CSS in production
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Throttle and admin-lockout counters live here. Every worker must share them, so set REDIS_URL
# whenever more than one process serves the site; local memory is per process and resets on restart.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': os.environ['REDIS_URL']}
          if os.environ.get('REDIS_URL') else {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# Errors and security events (admin lockouts) go to stdout, where the process manager collects them.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO' if DEBUG else 'WARNING'},
        'shop': {'handlers': ['console'], 'level': 'INFO'},
    },
}

OTP_TOTP_ISSUER = 'Haat admin'

# Frontend talks to /api via the Vite dev proxy, so no CORS setup needed.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['shop.auth.ExpiringTokenAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'EXCEPTION_HANDLER': 'shop.views.exception_handler',  # adds `message` to every error
    # The browsable HTML API is a dev tool; production speaks JSON only.
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer']
                                + (['rest_framework.renderers.BrowsableAPIRenderer'] if DEBUG else []),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',  # only views with throttle_scope
    ],
    # signup: per IP per day, against bulk accounts that hoard stock with free COD orders.
    # Mobile carriers put many people behind one IP (CGNAT), so this stays loose.
    'DEFAULT_THROTTLE_RATES': {'anon': '120/min', 'user': '300/min', 'auth': '5/min', 'signup': '50/day'},
    # Client IP comes from REMOTE_ADDR, so a forged X-Forwarded-For can't dodge throttles.
    # Set to the number of reverse proxies in front of Django when deployed behind one.
    'NUM_PROXIES': int(os.environ.get('DJANGO_NUM_PROXIES', '0')),
}

FREE_DELIVERY_MIN = 299  # taka; Cartup-style free delivery threshold
DELIVERY_FEE = 60
MAX_PENDING_ORDERS = 5  # per buyer and per phone number; COD orders cost nothing, so this stops stock hoarding
TOKEN_TTL_DAYS = 30  # API tokens die after this; logging in again issues a fresh one
ADMIN_LOGIN_MAX_FAILS = 5  # per IP and per username, then locked out for ADMIN_LOCKOUT_SECONDS
ADMIN_LOCKOUT_SECONDS = 15 * 60

ADMIN_PATH = os.environ.get('DJANGO_ADMIN_PATH', 'admin/')  # use a non-default path in production

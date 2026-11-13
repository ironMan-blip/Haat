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
    # Behind a TLS-terminating proxy, also set SECURE_PROXY_SSL_HEADER, or SSL redirect loops.

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'shop',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [{  # admin only
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

# PostgreSQL when POSTGRES_DB is set; SQLite otherwise (CI, quick local runs).
if os.environ.get('POSTGRES_DB'):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['POSTGRES_DB'],
        'USER': os.environ.get('POSTGRES_USER', ''),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
        'HOST': os.environ.get('POSTGRES_HOST', ''),  # empty = local Unix socket
        'PORT': os.environ.get('POSTGRES_PORT', ''),
    }}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

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
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Frontend talks to /api via the Vite dev proxy, so no CORS setup needed.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.TokenAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',  # only views with throttle_scope
    ],
    # shortcut: counters live in the per-process local-memory cache; use a shared cache (Redis) with >1 worker.
    'DEFAULT_THROTTLE_RATES': {'anon': '120/min', 'user': '300/min', 'auth': '5/min'},
    # Client IP comes from REMOTE_ADDR, so a forged X-Forwarded-For can't dodge throttles.
    # Set to the number of reverse proxies in front of Django when deployed behind one.
    'NUM_PROXIES': int(os.environ.get('DJANGO_NUM_PROXIES', '0')),
}

FREE_DELIVERY_MIN = 299  # taka; Cartup-style free delivery threshold
DELIVERY_FEE = 60
MAX_PENDING_ORDERS = 5  # per buyer; COD orders cost nothing, so this stops stock hoarding

ADMIN_PATH = os.environ.get('DJANGO_ADMIN_PATH', 'admin/')  # use a non-default path in production

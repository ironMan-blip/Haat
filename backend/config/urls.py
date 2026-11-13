from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from shop.admin import HaatAdminSite

admin.site.__class__ = HaatAdminSite  # 2FA + lockout on the one admin site, as django-otp documents

urlpatterns = [
    path(settings.ADMIN_PATH, admin.site.urls),
    path('api/', include('shop.urls')),
]

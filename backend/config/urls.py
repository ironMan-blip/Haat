from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from oauth2_provider.views import OAuthServerMetadataView

from shop.admin import HaatAdminSite

admin.site.__class__ = HaatAdminSite  # lockout on the one admin site

urlpatterns = [
    path(settings.ADMIN_PATH, admin.site.urls),
    path('api/', include('shop.api.urls')),
    # RFC 8414: AI apps find the sign-in endpoints (under /api/oauth/) here; the issuer is the site itself.
    path('.well-known/oauth-authorization-server', OAuthServerMetadataView.as_view()),
]

import logging

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.http import HttpResponse
from django_otp.admin import OTPAdminSite
from rest_framework.throttling import BaseThrottle

from .models import Category, Order, OrderItem, Product

log = logging.getLogger("shop.security")


class HaatAdminSite(OTPAdminSite):
    """Admin login needs the password and an authenticator-app code (`manage.py admin_totp <user>`),
    and locks an IP or a username out after repeated failures. DRF throttles don't cover the admin.
    Tradeoff: anyone who knows an admin username can lock it out for a while; the hidden path limits that."""

    def login(self, request, extra_context=None):
        if request.method != "POST":
            return super().login(request, extra_context)
        username = request.POST.get("username", "")[:150].lower()
        ip = BaseThrottle().get_ident(request)  # honours NUM_PROXIES like the API throttles
        keys = [f"admin-fails:ip:{ip}", f"admin-fails:user:{username}"]
        if any(cache.get(k, 0) >= settings.ADMIN_LOGIN_MAX_FAILS for k in keys):
            log.warning("admin login locked out: ip=%s username=%r", ip, username)
            return HttpResponse("Too many failed logins. Try again later.", status=429, content_type="text/plain")
        response = super().login(request, extra_context)
        if response.status_code == 302:  # logged in
            cache.delete(keys[1])
        else:
            log.warning("admin login failed: ip=%s username=%r", ip, username)
            for k in keys:
                cache.add(k, 0, settings.ADMIN_LOCKOUT_SECONDS)
                cache.incr(k)
        return response


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "price", "stock"]
    list_filter = ["category"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


class OrderItemInline(admin.TabularInline):
    # Items are what the buyer ordered and what stock was taken for: never edited, added or removed.
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ["product", "name", "price", "quantity"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "full_name", "total", "status", "created"]
    list_filter = ["status"]
    list_editable = ["status"]
    inlines = [OrderItemInline]

    def has_delete_permission(self, request, obj=None):
        return False  # deleting would lose the stock it took; cancel instead, which puts it back

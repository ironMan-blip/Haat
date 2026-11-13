import logging
from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html
from django_otp.admin import OTPAdminSite

from .auth import client_ident, locked_out, login_fail_keys, record_login_failure
from .display import cdn, taka
from .models import LOW_STOCK, Category, Order, OrderItem, Product

log = logging.getLogger("shop.security")


class HaatAdminSite(OTPAdminSite):
    """Admin login needs the password and an authenticator-app code (`manage.py admin_totp <user>`),
    and locks an IP or a username out after repeated failures. DRF throttles don't cover the admin.
    Tradeoff: anyone who knows an admin username can lock it out for a while; the hidden path limits that."""

    def login(self, request, extra_context=None):
        if request.method != "POST":
            return super().login(request, extra_context)
        username = request.POST.get("username", "")[:150]
        ip = client_ident(request)
        keys = login_fail_keys(username, request)  # user counter shared with the API login
        if locked_out(keys):
            log.warning("admin login locked out: ip=%s username=%r", ip, username)
            return HttpResponse("Too many failed logins. Try again later.", status=429, content_type="text/plain")
        response = super().login(request, extra_context)
        if response.status_code == 302:  # logged in
            cache.delete_many(login_fail_keys(username))
        else:
            log.warning("admin login failed: ip=%s username=%r", ip, username)
            record_login_failure(keys)
        return response


    index_template = "admin/haat_index.html"  # own name: shop's templates load after django.contrib.admin's
    site_header = site_title = "Haat admin"
    index_title = "Dashboard"

    def index(self, request, extra_context=None):
        if request.user.has_perm("shop.view_order"):  # sales numbers only for staff who may see orders
            today = timezone.localdate()
            live = Order.objects.exclude(status="cancelled")
            extra_context = {
                **(extra_context or {}),
                "stats": [  # label, value, order-list query string, hint
                    ("Pending orders", Order.objects.filter(status="pending").count(), "?status__exact=pending",
                     "Waiting to be shipped"),
                    ("Orders today", Order.objects.filter(created__date=today).count(),
                     f"?created__year={today.year}&created__month={today.month}&created__day={today.day}",
                     "Placed since midnight"),
                    ("Sales today", taka(live.filter(created__date=today).aggregate(s=Sum("total"))["s"]), "",
                     "Excluding cancelled"),
                    ("Sales, last 30 days", taka(live.filter(created__date__gt=today - timedelta(days=30))
                                                 .aggregate(s=Sum("total"))["s"]), "", "Excluding cancelled"),
                ],
                "sold_out": Product.objects.filter(stock=0).count(),
                "recent_orders": Order.objects.select_related("user")[:8],
                "low_stock": Product.objects.filter(stock__lt=LOW_STOCK).order_by("stock", "name")[:8],
                "low_stock_limit": LOW_STOCK,
            }
        return super().index(request, extra_context)


def badge(label, tone):
    """Coloured pill; `tone` is an order status or a stock level, styled in shop/static/shop/admin.css."""
    return format_html('<span class="haat-badge haat-{}">{}</span>', tone, label)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "product_count"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("products"))

    @admin.display(description="Products", ordering="n")
    def product_count(self, obj):
        return obj.n


class StockFilter(admin.SimpleListFilter):
    title = parameter_name = "stock"

    def lookups(self, request, model_admin):
        return [("out", "Sold out"), ("low", f"Low (under {LOW_STOCK})"), ("in", "In stock")]

    def queryset(self, request, queryset):
        return {"out": queryset.filter(stock=0), "low": queryset.filter(stock__gt=0, stock__lt=LOW_STOCK),
                "in": queryset.filter(stock__gte=LOW_STOCK)}.get(self.value(), queryset)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["thumb", "name", "category", "price", "original_price", "discount_badge", "stock",
                    "stock_status", "rating", "created"]
    list_display_links = ["thumb", "name"]
    list_editable = ["price", "original_price", "stock"]
    list_per_page = 25
    save_on_top = True
    list_filter = [StockFilter, "category"]
    list_select_related = ["category"]
    search_fields = ["name", "slug", "description"]
    prepopulated_fields = {"slug": ["name"]}
    readonly_fields = ["preview", "created"]
    fieldsets = [
        (None, {"fields": ["name", "slug", "category", "description"]}),
        ("Price and stock", {"fields": ["price", "original_price", "stock"]}),
        ("Image", {"fields": ["image", "preview"],
                   "description": "Paste an image URL. The preview updates as you type."}),
        ("Reviews", {"fields": ["rating", "reviews", "created"]}),
    ]

    formfield_overrides = {models.URLField: {"widget": forms.URLInput(attrs={
        "class": "vURLField", "placeholder": "https://…", "data-haat-image": ""})}}  # no "Currently/Change" clutter

    class Media:
        js = ["shop/admin.js"]  # live preview and broken-image fallback

    @admin.display(description="Image")
    def thumb(self, obj):
        return format_html('<span class="haat-frame haat-thumb"><img src="{}" alt="" loading="lazy"></span>',
                           cdn(obj.image, 120))

    @admin.display(description="Preview")
    def preview(self, obj):
        return format_html(
            '<span class="haat-frame haat-preview"><img src="{}" alt="Product image preview"></span>'
            '<a class="haat-original" href="{}" target="_blank" rel="noopener"{}>Open full size</a>',
            cdn(obj.image, 600), obj.image, "" if obj.image else " hidden")

    @admin.display(description="Discount", ordering="original_price")
    def discount_badge(self, obj):
        return badge(f"-{obj.discount}%", "sale") if obj.discount else "-"

    @admin.display(description="Availability", ordering="stock")
    def stock_status(self, obj):
        return badge(obj.stock_label, obj.stock_level)


class OrderItemInline(admin.TabularInline):
    # Items are what the buyer ordered and what stock was taken for: never edited, added or removed.
    model = OrderItem
    extra = 0
    can_delete = False
    fields = ["product", "name", "price", "quantity", "line_total"]
    readonly_fields = fields

    @admin.display(description="Line total")
    def line_total(self, obj):
        return taka(obj.price * obj.quantity)

    def has_add_permission(self, request, obj=None):
        return False


def set_status(status):
    """Bulk action. Saves each order one by one so Order.save() puts cancelled stock back."""

    @admin.action(description=f"Mark selected orders {status}", permissions=["change"])
    def action(modeladmin, request, queryset):
        done, refused = 0, []
        for order in queryset.exclude(status=status):
            order.status = status
            try:
                order.save(update_fields=["status"])
                done += 1
            except ValidationError:  # cancelled orders can't reopen, shipped ones can't go back to pending
                refused.append(str(order))
        modeladmin.message_user(request, f"{done} order(s) marked {status}.")
        if refused:
            modeladmin.message_user(request, f"Skipped orders that can't be marked {status}: {', '.join(refused)}.",
                                    messages.WARNING)

    action.__name__ = f"mark_{status}"
    return action


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "created", "full_name", "phone", "city", "item_count", "total_taka", "status_badge",
                    "user"]
    list_display_links = ["id", "full_name"]
    list_filter = ["status", "city", "created"]
    list_per_page = 25
    save_on_top = True
    list_select_related = ["user"]
    search_fields = ["=id", "full_name", "phone", "user__username", "user__email"]
    date_hierarchy = "created"
    actions = [set_status(s) for s, _ in Order.STATUS]
    inlines = [OrderItemInline]
    fieldsets = [
        (None, {"fields": ["status", "user", "created"]}),
        ("Delivery", {"fields": ["full_name", "phone", "address", "city"]}),
        ("Payment", {"fields": ["payment", "subtotal", "delivery_fee", "total"]}),
    ]
    # Money and buyer are what the order was placed with; stock was taken for these amounts.
    readonly_fields = ["user", "created", "payment", "subtotal", "delivery_fee", "total"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Sum("items__quantity"))

    @admin.display(description="Items", ordering="n")
    def item_count(self, obj):
        return obj.n

    @admin.display(description="Total", ordering="total")
    def total_taka(self, obj):
        return taka(obj.total)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return badge(obj.get_status_display(), obj.status)

    def has_add_permission(self, request):
        return False  # orders come from checkout, which checks stock and prices

    def has_delete_permission(self, request, obj=None):
        return False  # deleting would lose the stock it took; cancel instead, which puts it back


class OrderInline(admin.TabularInline):
    model = Order
    extra = 0
    show_change_link = True
    fields = readonly_fields = ["created", "total", "status", "city"]
    can_delete = False
    verbose_name_plural = "Orders placed by this customer"

    def has_add_permission(self, request, obj=None):
        return False


class HaatUserAdmin(UserAdmin):
    list_display = ["username", "email", "first_name", "last_name", "order_count", "is_staff", "is_active",
                    "date_joined", "last_login"]
    list_filter = UserAdmin.list_filter + ("date_joined",)
    list_per_page = 25
    inlines = [OrderInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("orders"))

    @admin.display(description="Orders", ordering="n")
    def order_count(self, obj):
        return obj.n


admin.site.unregister(User)  # swap Django's stock user admin for the one above with orders
admin.site.register(User, HaatUserAdmin)

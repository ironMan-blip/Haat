import logging
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import Count, Exists, F, OuterRef, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django_otp.admin import OTPAdminSite

from .auth import client_ident, locked_out, login_fail_keys, record_login_failure
from .display import cdn, taka
from .staff import StaffViews, grantable, hold, may, outranks, parts
from .models import COMMENT_PAGE, LOW_STOCK, Category, Comment, Order, OrderItem, Product, ProductImage, ProductOption, ProductVariant, options_error, variant_keys

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
        keys = login_fail_keys(username, request, ip_lock=True)  # user counters shared with the API login
        if locked_out(keys):
            log.warning("admin login locked out: ip=%s username=%r", ip, username)
            return HttpResponse("Too many failed logins. Try again later.", status=429, content_type="text/plain")
        response = super().login(request, extra_context)
        if response.status_code == 302:  # logged in
            cache.delete_many(login_fail_keys(username, request))  # the IP counter stays: other names it guessed
        else:
            log.warning("admin login failed: ip=%s username=%r", ip, username)
            record_login_failure(keys)
        return response

    def get_urls(self):
        return StaffViews(self).urls() + super().get_urls()  # before the catch-all app URLs

    index_template = "admin/haat_index.html"  # own name: shop's templates load after django.contrib.admin's
    site_header = site_title = "Haat admin"
    site_url = settings.SITE_URL
    index_title = "Dashboard"

    def password_change(self, request, extra_context=None):
        if request.user.is_superuser:  # the owner's password is set from .env: `manage.py sync_owner --reset-password`
            raise PermissionDenied
        return super().password_change(request, extra_context)

    def index(self, request, extra_context=None):
        now = timezone.localtime()
        extra_context = {**(extra_context or {}), "now": now,
                         "greeting": "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17
                         else "Good evening"}
        if request.user.has_perm("shop.view_order"):  # sales numbers only for staff who may see orders
            extra_context.update(dashboard(now.date()))
        return super().index(request, extra_context)


def change(cur, prev, against):
    """(tone, text) comparing two periods, or None when there's nothing to compare against."""
    if not prev:
        return None
    pct = round((cur - prev) / prev * 100)
    return ("up" if pct > 0 else "down" if pct < 0 else "flat", f"{pct:+d}% vs {against}")


def dashboard(today):
    live = Order.objects.exclude(status="cancelled")
    rows = (live.filter(created__date__gt=today - timedelta(days=60)).annotate(d=TruncDate("created"))
            .values("d").annotate(s=Sum("total"), n=Count("id")).order_by())
    by_day = {r["d"]: r for r in rows}

    def total(key, first, last):  # sum of `key` from `first` to `last` days ago, both included
        return sum(by_day.get(today - timedelta(days=i), {}).get(key) or 0 for i in range(first, last + 1))

    sales_today, sales_30, orders_30 = total("s", 0, 0), total("s", 0, 29), total("n", 0, 29)
    pending = Order.objects.filter(status="pending").count()
    orders_today = Order.objects.filter(created__date=today).count()

    chart = [{"day": today - timedelta(days=i), "s": total("s", i, i), "orders": total("n", i, i), "today": i == 0}
             for i in range(13, -1, -1)]  # last 14 days, oldest first
    peak = max(c["s"] for c in chart) or 1
    for c in chart:
        c["pct"], c["sales"] = round(c["s"] / peak * 100), taka(c["s"])

    counts = dict(Order.objects.values_list("status").annotate(n=Count("id")).order_by())
    all_orders = sum(counts.values()) or 1
    status_mix = [{"key": k, "label": label, "n": counts.get(k, 0), "pct": round(counts.get(k, 0) / all_orders * 100)}
                  for k, label in Order.STATUS]

    top = (OrderItem.objects.filter(order__created__date__gt=today - timedelta(days=30))
           .exclude(order__status="cancelled").values("product_id", "product__name")
           .annotate(qty=Sum("quantity"), revenue=Sum(F("price") * F("quantity"))).order_by("-qty")[:5])

    return {
        "stats": [
            {"label": "Pending orders", "value": pending, "icon": "box", "query": "?status__exact=pending",
             "hint": "Waiting to be shipped" if pending else "All caught up", "alert": pending > 0},
            {"label": "Orders today", "value": orders_today, "icon": "bag",
             "query": f"?created__year={today.year}&created__month={today.month}&created__day={today.day}",
             "hint": "Placed since midnight"},
            {"label": "Sales today", "value": taka(sales_today), "icon": "coin", "hint": "Excluding cancelled",
             "delta": change(sales_today, total("s", 1, 1), "yesterday")},
            {"label": "Sales, last 30 days", "value": taka(sales_30), "icon": "chart",
             "hint": f"Avg. order {taka(sales_30 // orders_30 if orders_30 else 0)}",
             "delta": change(sales_30, total("s", 30, 59), "prior 30 days")},
        ],
        "pending": pending,
        "chart": chart,
        "chart_total": taka(total("s", 0, 13)),
        "chart_empty": not any(c["orders"] for c in chart),
        "status_mix": status_mix,
        "order_total": sum(counts.values()),
        "top_sellers": [{**t, "revenue": taka(t["revenue"])} for t in top],
        "sold_out": Product.objects.filter(stock=0).count(),
        "recent_orders": [(o, taka(o.total)) for o in Order.objects.all()[:8]],
        "low_stock": Product.objects.filter(stock__lt=LOW_STOCK).order_by("stock", "name")[:8],
        "low_stock_limit": LOW_STOCK,
    }


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


class PartInline(admin.TabularInline):
    """An inline whose rights follow its parent's permissions, not its own model's (those are never handed out):
    seen by whoever sees the parent, edited by whoever may add the parent or holds one of `parts` of changing it."""
    parts = ()

    def parent(self):
        return self.parent_model._meta.model_name

    def has_view_permission(self, request, obj=None):
        m = self.parent()
        return request.user.has_perm(f"shop.view_{m}") or may(request.user, m, *parts(self.parent_model))

    def has_change_permission(self, request, obj=None):
        return (obj is None and request.user.has_perm(f"shop.add_{self.parent()}")) or \
            may(request.user, self.parent(), *self.parts)

    has_add_permission = has_delete_permission = has_change_permission


class ProductImageInline(PartInline):
    parts = ["edit_product_details"]
    model = ProductImage
    extra = 1
    fields = ["thumb", "url", "position"]
    readonly_fields = ["thumb"]
    verbose_name_plural = "More photos (shown after the main image on the product page)"

    @admin.display(description="Photo")
    def thumb(self, obj):
        return format_html('<span class="haat-frame haat-thumb"><img src="{}" alt="" loading="lazy"></span>',
                           cdn(obj.url, 120)) if obj.url else "-"


class OptionFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        kept = [f.cleaned_data for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        names = [d["name"].strip().lower() for d in kept]
        if len(names) != len(set(names)):
            raise forms.ValidationError("Each option needs its own name.")
        options = [(d["name"], ProductOption(values=d["values"]).choices) for d in kept]
        if error := options_error(options):
            raise forms.ValidationError(error)
        # Renaming an option or fixing a typo in a choice makes new combinations: the old ones, with their stock
        # and price, would be deleted. Refuse while any of them still holds stock.
        if self.instance.pk and (lost := self.instance.variants.filter(stock__gt=0).exclude(key__in=variant_keys(options))):
            raise forms.ValidationError(
                f"This change removes combinations that still have stock: {', '.join(v.label for v in lost)}. "
                "Set their stock to 0 and save first, then change the options. New combinations start with 0 stock "
                "and the product's price.")


class ProductOptionInline(PartInline):
    parts = ["edit_product_details"]
    model = ProductOption
    formset = OptionFormSet
    extra = 1
    fields = ["name", "values", "position"]
    verbose_name_plural = "Options the buyer picks when ordering (e.g. Size: S, M, L)"


def stock_field(field, db_field):
    """Posts back the stock the page showed, so `changed_data` tells a staff edit from orders placed since
    (Django's own initial is read again on save). Without it, saving the page would undo those sales."""
    if db_field.name == "stock" and field:
        field.show_hidden_initial = True
    return field


class ProductVariantInline(PartInline):
    """Every combination of the options above, made on save; staff set each one's stock and price here."""
    parts = ["edit_product_price", "edit_product_stock"]
    model = ProductVariant
    extra = 0
    can_delete = False  # change the options instead: combinations follow them
    fields = ["combination", "price", "stock"]
    readonly_fields = ["combination"]
    verbose_name_plural = "Stock and price per combination (the product's stock is their total)"

    def has_add_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [*self.readonly_fields, *ProductAdmin.locked(request.user, ["price", "stock"])]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        return stock_field(super().formfield_for_dbfield(db_field, request, **kwargs), db_field)

    @admin.display(description="Combination")
    def combination(self, obj):
        return obj.label


class CommentInline(PartInline):
    """Customers' comments on this product, newest first. Staff fix or remove abuse; deleting a comment
    also deletes its replies. Comments are written by customers, so staff can't add them here."""
    parts = ["moderate_product_comments"]
    model = Comment
    fk_name = "product"
    extra = 0
    fields = ["created", "user", "reply_to", "text", "like_count", "edited", "deleted"]
    readonly_fields = ["created", "user", "reply_to", "like_count", "edited", "deleted"]
    formfield_overrides = {models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 60})}}
    verbose_name_plural = "Customer comments (deleting one also deletes its replies)"
    ordering = ["-id"]
    template = "admin/shop/comment_inline.html"  # the stock table plus a "Show more" link
    more_url = None
    page_size = COMMENT_PAGE

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("user", "parent").annotate(n_likes=Count("likes"))
        if request.method != "GET":  # saving: every comment the page showed must be found, even if new ones came
            return qs
        # Viewing: the newest COMMENT_PAGE, and COMMENT_PAGE more each time staff click "Show more" (?comments=N).
        try:
            shown = max(int(request.GET.get("comments", COMMENT_PAGE)), COMMENT_PAGE)
        except ValueError:
            shown = COMMENT_PAGE
        product = request.resolver_match.kwargs.get("object_id")
        ids = list(Comment.objects.filter(product_id=product).order_by("-id").values_list("pk", flat=True)[:shown + 1])
        if len(ids) > shown:  # Django makes a fresh inline per request, so this is per page view
            params = request.GET.copy()
            params["comments"] = shown + COMMENT_PAGE
            self.more_url = f"?{params.urlencode()}#comments-group"
        return qs.filter(pk__in=ids[:shown])

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Reply to")
    def reply_to(self, obj):
        if not obj.parent:
            return "-"
        return "(deleted comment)" if obj.parent.deleted else f"{obj.parent.user}: {obj.parent.text[:40]}"

    @admin.display(description="Likes")
    def like_count(self, obj):
        return obj.n_likes


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductImageInline, ProductOptionInline, ProductVariantInline, CommentInline]
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
        ("Main image", {"fields": ["image", "preview"],
                   "description": "Paste an image URL. The preview updates as you type."}),
        ("Reviews", {"fields": ["rating", "reviews", "created"]}),
    ]

    formfield_overrides = {models.URLField: {"widget": forms.URLInput(attrs={
        "class": "vURLField", "placeholder": "https://…", "data-haat-image": ""})}}  # no "Currently/Change" clutter

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

    # Which fields each part of "change product" unlocks. Adding a product needs none of them.
    PART_FIELDS = {"edit_product_details": ["name", "slug", "category", "description", "image", "rating", "reviews"],
                   "edit_product_price": ["price", "original_price"], "edit_product_stock": ["stock"]}

    @classmethod
    def locked(cls, user, fields=None):
        """The fields (of `fields`, else all part fields) that `user` may not change on an existing product."""
        out = [f for part, fs in cls.PART_FIELDS.items() if not may(user, "product", part) for f in fs]
        return [f for f in out if fields is None or f in fields]

    def has_change_permission(self, request, obj=None):
        return may(request.user, "product", *parts(Product))

    def get_readonly_fields(self, request, obj=None):
        # With options, stock is the total of the combinations below; Product.clean() guards the list page too.
        has_variants = obj is not None and obj.variants.exists()
        ro = [*self.readonly_fields, *(self.locked(request.user) if obj else [])]
        return [*ro, "stock"] if has_variants and "stock" not in ro else ro

    def get_prepopulated_fields(self, request, obj=None):
        return {} if obj and "slug" in self.locked(request.user) else self.prepopulated_fields

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(has_variants=Exists(ProductVariant.objects.filter(product=OuterRef("pk"))))

    def get_changelist_form(self, request, **kwargs):
        class Form(super().get_changelist_form(request, **kwargs)):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                # A stale stock number from the list page would fail Product.clean() or overwrite a sale.
                if getattr(self.instance, "has_variants", False):
                    self.fields["stock"].disabled = True
                for f in locked:  # list-page columns this person's parts don't cover
                    self.fields[f].disabled = True
        locked = self.locked(request.user, self.list_editable)
        return Form

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        return stock_field(super().formfield_for_dbfield(db_field, request, **kwargs), db_field)

    def save_model(self, request, obj, form, change):
        # The form's stock is what the page read; orders placed since lowered it. Write it only if staff changed it.
        if change and "stock" not in form.changed_data:
            obj.save(update_fields=[f.name for f in obj._meta.concrete_fields if not f.primary_key and f.name != "stock"])
            obj.refresh_from_db(fields=["stock"])
        else:
            super().save_model(request, obj, form, change)
        obj.sync_stock()  # the save wrote the stock read before any order placed meanwhile; re-total it

    def save_formset(self, request, form, formset, change):
        if formset.model is not ProductVariant:
            return super().save_formset(request, form, formset, change)
        formset.new_objects, formset.changed_objects, formset.deleted_objects = [], [], []  # read by the change log
        for f in formset.forms:  # same as save_model: a price edit must not write back the stock the page read
            if fields := [n for n in ("price", "stock") if n in f.changed_data]:
                f.instance.save(update_fields=fields)
                formset.changed_objects.append((f.instance, fields))

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if added := form.instance.sync_variants():
            self.message_user(request, f"{added} new option combination(s) start with 0 stock: set their stock below.",
                              messages.WARNING)

    @admin.display(description="Discount", ordering="original_price")
    def discount_badge(self, obj):
        return badge(f"-{obj.discount}%", "sale") if obj.discount else "-"

    @admin.display(description="Availability", ordering="stock")
    def stock_status(self, obj):
        return badge(obj.stock_label, obj.stock_level)


OVERRIDE_WARNING = ("Owner only. This changes your shop's records: totals, stock and order history may stop matching "
                    "what really happened. Stock is not taken or put back for these edits.")
CONFIRM = "confirm_override"


class OwnerItemFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if self.has_changed() and not self.data.get(CONFIRM):
            raise ValidationError("Changing an order's items needs the \"I understand\" tick at the bottom.")


class OrderItemInline(PartInline):
    # Items are what the buyer ordered and what stock was taken for: only the owner edits them, after a warning.
    model = OrderItem
    extra = 0
    fields = ["product", "name", "options", "price", "quantity", "line_total"]

    @admin.display(description="Line total")
    def line_total(self, obj):
        return taka(obj.price * obj.quantity) if obj.pk else "-"

    def get_formset(self, request, obj=None, **kwargs):
        if request.user.is_superuser:
            kwargs["formset"] = OwnerItemFormSet
        return super().get_formset(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        return ["line_total"] if request.user.is_superuser else self.fields

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class OwnerOrderForm(forms.ModelForm):
    """The owner may break the order rules (add, edit money, reopen), but only after ticking the warning."""
    confirm_override = forms.BooleanField(required=False, label="I understand, do it anyway")
    PROTECTED = ["user", "payment", "subtotal", "delivery_fee", "total"]

    def clean(self):
        data = super().clean()
        was = Order.objects.filter(pk=self.instance.pk).values_list("status", flat=True).first() if self.instance.pk else None
        breaks_status = bool(Order(status=data.get("status")).refusal(was))
        if (not self.instance.pk or breaks_status or set(self.PROTECTED) & set(self.changed_data)) \
                and not data.get(CONFIRM):
            raise ValidationError("This breaks the order rules. Read the warning at the bottom, tick \"I understand\" "
                                  "and save again.")
        self.instance.override = breaks_status  # read by Order.clean() and Order.save()
        return data


def set_status(status):
    """Bulk action. Saves each order one by one so Order.save() puts cancelled stock back."""

    @admin.action(description=f"Mark selected orders {status}", permissions=["cancel" if status == "cancelled" else "ship"])
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
    list_display = ["id", "created", "full_name", "phone_link", "city", "item_count", "total_taka", "status_badge",
                    "user"]
    list_display_links = ["id", "full_name"]
    list_filter = ["status", "city", "created"]
    list_per_page = 25
    save_on_top = True
    list_select_related = ["user"]
    empty_value_display = "Guest"  # orders placed without an account have no user
    search_fields =["=id", "full_name", "phone", "user__username", "user__email"]
    date_hierarchy = "created"
    actions = [set_status(s) for s, _ in Order.STATUS]
    inlines = [OrderItemInline]
    fieldsets = [
        (None, {"fields": ["progress", "status", "user", "created"]}),
        ("Delivery", {"fields": ["full_name", "phone", "email", "address", "city"]}),
        ("Payment", {"fields": ["payment", "subtotal", "delivery_fee", "total"]}),
    ]
    # Money and buyer are what the order was placed with; stock was taken for these amounts.
    readonly_fields = ["progress", "user", "created", "payment", "subtotal", "delivery_fee", "total"]

    @admin.display(description="Progress")
    def progress(self, obj):
        if obj.status == "cancelled":
            return format_html('<div class="haat-steps haat-steps-cancelled"><span class="is-done">Placed</span>'
                               '<span class="is-now">Cancelled</span></div>')
        steps = ["pending", "shipped", "delivered"]
        reached = steps.index(obj.status)
        return format_html('<div class="haat-steps">{}</div>', format_html_join(
            "", '<span class="{}">{}</span>',
            (("is-now" if i == reached else "is-done" if i < reached else "", label)
             for i, label in enumerate(["Placed", "Shipped", "Delivered"]))))

    @admin.display(description="Phone", ordering="phone")
    def phone_link(self, obj):
        return format_html('<a href="tel:{}">{}</a>', obj.phone, obj.phone)

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

    # Orders come from checkout, which checks stock and prices, and deleting one loses its history: staff cancel
    # instead. The owner may do both, behind a warning.
    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    DELIVERY = ["full_name", "phone", "email", "address", "city"]

    def has_change_permission(self, request, obj=None):
        return may(request.user, "order", *parts(Order))

    def has_ship_permission(self, request):  # read by the bulk actions
        return may(request.user, "order", "ship_order")

    def has_cancel_permission(self, request):
        return may(request.user, "order", "cancel_order")

    def statuses(self, request):
        """The statuses this person may move an order to."""
        return ({"pending", "shipped", "delivered"} if self.has_ship_permission(request) else set()) | \
            ({"cancelled"} if self.has_cancel_permission(request) else set())

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ["progress", "created"]
        return [*self.readonly_fields, *([] if self.statuses(request) else ["status"]),
                *([] if may(request.user, "order", "edit_order_delivery") else self.DELIVERY)]

    def get_form(self, request, obj=None, **kwargs):
        if request.user.is_superuser:
            kwargs["form"] = OwnerOrderForm
        form = super().get_form(request, obj, **kwargs)
        if request.user.is_superuser or "status" not in form.base_fields:
            return form
        allowed = self.statuses(request)

        class StaffForm(form):  # the status list offers only moves this person may make; posting another is refused
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                self.fields["status"].choices = [(k, label) for k, label in Order.STATUS
                                                 if k in allowed or k == self.instance.status]
        return StaffForm

    def get_fieldsets(self, request, obj=None):
        if not request.user.is_superuser:
            return self.fieldsets
        return [*self.fieldsets, ("Owner override", {"fields": [CONFIRM], "classes": ["haat-danger"],
                                                     "description": OVERRIDE_WARNING})]

    def delete_model(self, request, obj):
        with transaction.atomic():
            if obj.status == "pending":  # its goods are still here: put them back on sale, as cancelling does
                obj.status = "cancelled"
                obj.save(update_fields=["status"])
            obj.delete()

    def delete_queryset(self, request, queryset):
        for order in queryset:
            self.delete_model(request, order)


class OrderInline(admin.TabularInline):
    model = Order
    extra = 0
    show_change_link = True
    fields = readonly_fields = ["created", "total", "status", "city"]
    can_delete = False
    verbose_name_plural = "Orders placed by this customer"

    def has_add_permission(self, request, obj=None):
        return False


def clean_unique_email(form):
    """Admin twin of RegisterSerializer.validate_email: required, lowercased, one account per email."""
    email = form.cleaned_data["email"].lower()
    if User.objects.filter(email__iexact=email).exclude(pk=form.instance.pk).exists():
        raise ValidationError("An account with that email already exists.")
    return email


def no_at_sign(username):
    """Admin twin of RegisterSerializer.validate_username's "@" rule."""
    if "@" in username:
        raise ValidationError("A username can't contain @.")
    return username


class HaatUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        fields = ["username", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True

    clean_email = clean_unique_email

    def clean_username(self):
        return no_at_sign(super().clean_username())


class HaatUserChangeForm(UserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "email" in self.fields:  # absent on view-only pages (e.g. staff opening the owner's account)
            self.fields["email"].required = True  # older accounts without one get it filled on next edit

    clean_email = clean_unique_email

    def clean_username(self):
        return no_at_sign(self.cleaned_data["username"])


class HaatUserAdmin(UserAdmin):
    form = HaatUserChangeForm
    add_form = HaatUserCreationForm
    add_fieldsets = [(None, {"classes": ["wide"], "fields": ["username", "email", "usable_password", "password1", "password2"]})]
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

    # Who may change whom: see shop/staff.py. The owner is set only from .env (manage.py sync_owner).
    def get_fieldsets(self, request, obj=None):
        hidden = {"is_superuser", "password"} if obj and obj.is_superuser else {"is_superuser"}  # owner: .env only
        return [(name, {**opts, "fields": [f for f in opts["fields"] if f not in hidden]})
                for name, opts in super().get_fieldsets(request, obj)]

    def user_change_password(self, request, id, form_url=""):
        if User.objects.filter(pk=id, is_superuser=True).exists():  # the owner's password is set from .env only
            raise PermissionDenied
        return super().user_change_password(request, id, form_url)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and (obj == request.user or obj.is_superuser):  # nobody changes their own access, nor the owner's
            ro += ["is_staff", "is_active", "groups", "user_permissions"]
        return ro

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or outranks(request.user, obj))

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or (not obj.is_superuser and obj != request.user and outranks(request.user, obj)))

    def delete_queryset(self, request, queryset):
        allowed = [u.pk for u in queryset if self.has_delete_permission(request, u)]
        if skipped := queryset.exclude(pk__in=allowed).count():
            self.message_user(request, f"Skipped {skipped} account(s) you can't delete: the owner, yourself, or "
                                       "someone with permissions you don't have.", messages.WARNING)
        super().delete_queryset(request, queryset.filter(pk__in=allowed))

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "user_permissions":
            kwargs["queryset"] = grantable(request.user)
        elif db_field.name == "groups":
            kwargs["queryset"] = Group.objects.filter(
                pk__in=[g.pk for g in Group.objects.prefetch_related("permissions__content_type")
                        if hold(request.user, g.permissions.all())])
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class HaatGroupAdmin(GroupAdmin):
    """Staff can only put permissions they hold into a group, and only change groups that hold nothing more."""

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or hold(request.user, obj.permissions.all()))

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or hold(request.user, obj.permissions.all()))

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "permissions":
            kwargs["queryset"] = grantable(request.user)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


admin.site.unregister(Group)
admin.site.register(Group, HaatGroupAdmin)
admin.site.unregister(User)  # swap Django's stock user admin for the one above with orders
admin.site.register(User, HaatUserAdmin)

"""Who may change whose access, and the Staff page where the owner (or staff allowed to change users) adds staff
by email, picks what each may do, and removes them. Rule everywhere: you can only hand out permissions you hold
yourself, and only change people who hold nothing you don't. The owner holds everything."""
import base64
import hashlib
import logging
import secrets
from datetime import timedelta
from functools import reduce
from operator import or_

from django import forms
from django.contrib import messages
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth.models import Permission, User
from django.contrib.auth.password_validation import validate_password
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice, default_key

from .models import StaffInvite

log = logging.getLogger("shop.security")
ACTIONS = ["view", "add", "change", "delete"]


def grantable(user):
    """The permissions `user` may give to others: all of them for the owner, else only those they hold."""
    qs = Permission.objects.select_related("content_type")
    if user.is_superuser:
        return qs
    held = [p.split(".", 1) for p in user.get_all_permissions()]
    return qs.filter(reduce(or_, (Q(content_type__app_label=a, codename=c) for a, c in held), Q(pk__in=[])))


def outranks(editor, target):
    """`editor` may change `target`'s account: the owner may change anyone; staff only people who aren't the owner
    and hold no permission the editor lacks (else they could take away, or hand out, more than they have)."""
    return editor.is_superuser or (not target.is_superuser and target.get_all_permissions() <= editor.get_all_permissions())


def hold(editor, perms):
    """True when `editor` holds every permission in `perms`."""
    return editor.is_superuser or {f"{p.content_type.app_label}.{p.codename}" for p in perms} <= editor.get_all_permissions()


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def log_change(request, obj, flag, message):
    LogEntry.objects.log_actions(request.user.pk, [obj], flag, change_message=message, single_object=True)


class AcceptForm(forms.Form):
    username = forms.CharField(max_length=150, validators=[User.username_validator])
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="Password again", widget=forms.PasswordInput, strip=False)
    code = forms.CharField(label="6-digit code from the app", max_length=8)

    def __init__(self, *args, email, totp_key, **kwargs):
        super().__init__(*args, **kwargs)
        self.email, self.totp_key = email, totp_key

    def clean_username(self):
        username = self.cleaned_data["username"]
        if "@" in username:
            raise ValidationError("A username can't contain @.")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username is taken.")
        return username

    def clean_code(self):
        code, t = self.cleaned_data["code"].strip(), TOTPDevice(key=self.totp_key)
        if not code.isdigit() or not TOTP(t.bin_key, t.step, t.t0, t.digits).verify(int(code), tolerance=1):
            raise ValidationError("That code is wrong or too old. Type the code the app shows now.")
        return code

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            self.add_error("password2", "The passwords don't match.")
        elif data.get("password1") and data.get("username"):
            try:
                validate_password(data["password1"], User(username=data["username"], email=self.email))
            except ValidationError as e:
                self.add_error("password1", e)
        return data


class StaffViews:
    """URLs under the admin site. Every page but the invite link needs an admin login and `auth.change_user`."""

    def __init__(self, site):
        self.site = site

    def urls(self):
        wrap = self.site.admin_view
        return [
            path("staff/", wrap(self.list_view), name="staff"),
            path("staff/<int:pk>/", wrap(self.edit_view), name="staff_edit"),
            path("staff/invite/<int:pk>/", wrap(self.invite_view), name="staff_invite"),
            path("staff/join/<str:key>/", never_cache(csrf_protect(self.accept_view)), name="staff_accept"),
        ]

    def check(self, request):
        if not request.user.has_perm("auth.change_user"):
            raise PermissionDenied

    def render(self, request, template, **context):
        return TemplateResponse(request, template, {**self.site.each_context(request), **context})

    def perm_grid(self, editor, checked=()):
        """Rows of view/add/change/delete checkboxes, one row per section of the admin the editor may hand out."""
        allowed = {p.pk: p for p in grantable(editor).filter(
            content_type__in=[ContentType.objects.get_for_model(m) for m in self.site._registry])}
        rows = {}
        for p in allowed.values():
            action = p.codename.split("_", 1)[0]
            if action in ACTIONS:
                model = p.content_type.model_class()
                row = rows.setdefault(p.content_type_id, {"label": str(model._meta.verbose_name_plural).capitalize(),
                                                          "app": str(model._meta.app_config.verbose_name),
                                                          "cells": {}})
                row["cells"][action] = {"pk": p.pk, "checked": p.pk in checked, "action": action}
        return [{**r, "cells": [r["cells"].get(a) for a in ACTIONS]}
                for r in sorted(rows.values(), key=lambda r: (r["app"], r["label"]))]

    def picked(self, request):
        """The permissions ticked on the form, kept to the ones the editor may hand out."""
        ids = [i for i in request.POST.getlist("perms") if i.isdigit()]
        return list(grantable(request.user).filter(pk__in=ids))

    def send_invite(self, request, invite):
        key = secrets.token_urlsafe(32)
        invite.key_hash, invite.sent = key_hash(key), timezone.now()
        invite.save()
        link = request.build_absolute_uri(reverse("admin:staff_accept", args=[key]))
        try:
            send_mail("You're invited to help run Haat",
                      f"{request.user.get_username()} invited you to join the Haat shop team.\n\n"
                      f"Open this link within {StaffInvite.DAYS} days to choose a username and password:\n\n{link}\n\n"
                      "You'll also need an authenticator app (like Google Authenticator) on your phone.\n"
                      "If you weren't expecting this, ignore this email.",
                      None, [invite.email])
            return True
        except Exception:
            log.exception("staff invite email failed invite=%s", invite.pk)
            messages.error(request, f"The invite for {invite.email} is saved, but the email couldn't be sent. "
                                    "Check the mail settings, then press Resend.")
            return False

    def list_view(self, request):
        self.check(request)
        if request.method == "POST":
            return self.add(request)
        editor = request.user
        staff = User.objects.filter(is_staff=True, is_superuser=False).prefetch_related(
            "user_permissions__content_type", "groups").order_by("email", "username")
        expiry = timezone.now() - timedelta(days=StaffInvite.DAYS)
        invites = StaffInvite.objects.prefetch_related("permissions__content_type").order_by("-sent")
        return self.render(request, "admin/staff/list.html", title="Staff", grid=self.perm_grid(editor),
                           staff=[{"user": u, "perms": self.describe(u.user_permissions.all()),
                                   "editable": u != editor and outranks(editor, u)} for u in staff],
                           invites=[{"invite": i, "perms": self.describe(i.permissions.all()), "expired": i.sent < expiry,
                                     "editable": hold(editor, i.permissions.all())} for i in invites])

    @staticmethod
    def describe(perms):
        """'Orders: view, change · Products: view' for the staff list."""
        by_model = {}
        for p in perms:
            action = p.codename.split("_", 1)[0]
            model = p.content_type.model_class()
            name = str(model._meta.verbose_name_plural).capitalize() if model else p.content_type.model
            by_model.setdefault(name, []).append(action if action in ACTIONS else p.name)
        return " · ".join(f"{m}: {', '.join(sorted(a, key=lambda x: ACTIONS.index(x) if x in ACTIONS else 9))}"
                          for m, a in sorted(by_model.items())) or "Nothing yet"

    def add(self, request):
        try:
            email = forms.EmailField().clean(request.POST.get("email", "")).lower()
        except ValidationError:
            messages.error(request, "Type a valid email address.")
            return redirect("admin:staff")
        perms = self.picked(request)
        user = User.objects.filter(email__iexact=email).first()
        if user and user.is_superuser:
            messages.error(request, "That's the owner's email. The owner already has every permission.")
        elif user and user.is_staff:
            messages.error(request, f"{email} is already staff. Change what they can do in the list below.")
        elif user and not outranks(request.user, user):
            raise PermissionDenied
        elif user:  # a customer account: it becomes staff now
            with transaction.atomic():
                user.is_staff = True
                user.save(update_fields=["is_staff"])
                user.user_permissions.set(perms)
            log_change(request, user, CHANGE, f"Made staff from the Staff page with: {self.describe(perms)}")
            messages.success(request, f"{user.get_username()} ({email}) is staff now. If they haven't got the "
                                      f"authenticator app set up, run: manage.py admin_totp {user.get_username()}")
        elif StaffInvite.objects.filter(email=email).exists():
            messages.error(request, f"{email} is already invited. Use Resend below if they lost the email.")
        else:
            with transaction.atomic():
                invite = StaffInvite.objects.create(email=email, invited_by=request.user, key_hash="", sent=timezone.now())
                invite.permissions.set(perms)  # send_invite gives it a working link
            if self.send_invite(request, invite):
                messages.success(request, f"Invite sent to {email}. The link works for {StaffInvite.DAYS} days.")
            log_change(request, invite, ADDITION, f"Invited with: {self.describe(perms)}")
        return redirect("admin:staff")

    def edit_view(self, request, pk):
        self.check(request)
        user = get_object_or_404(User, pk=pk, is_staff=True, is_superuser=False)
        if user == request.user or not outranks(request.user, user):
            raise PermissionDenied  # nobody changes their own access, nor someone who holds more than they do
        if request.method == "POST":
            if request.POST.get("action") == "remove":
                with transaction.atomic():
                    user.is_staff = False
                    user.save(update_fields=["is_staff"])
                    user.user_permissions.clear()
                    user.groups.clear()
                log_change(request, user, CHANGE, "Removed from staff from the Staff page")
                messages.success(request, f"{user.get_username()} is no longer staff. Their shop account still works.")
            else:
                perms = self.picked(request)
                user.user_permissions.set(perms)
                log_change(request, user, CHANGE, f"Permissions set from the Staff page: {self.describe(perms)}")
                messages.success(request, f"Saved what {user.get_username()} can do.")
            return redirect("admin:staff")
        checked = set(user.user_permissions.values_list("pk", flat=True))
        return self.render(request, "admin/staff/edit.html", title=f"Staff: {user.get_username()}", member=user,
                           grid=self.perm_grid(request.user, checked),
                           groups=", ".join(g.name for g in user.groups.all()))

    def invite_view(self, request, pk):
        self.check(request)
        invite = get_object_or_404(StaffInvite, pk=pk)
        if request.method != "POST" or not hold(request.user, invite.permissions.all()):
            raise PermissionDenied
        if request.POST.get("action") == "cancel":
            log_change(request, invite, DELETION, "Invite cancelled")
            invite.delete()
            messages.success(request, f"Invite for {invite.email} cancelled. The link no longer works.")
        elif self.send_invite(request, invite):
            log_change(request, invite, CHANGE, "Invite resent")
            messages.success(request, f"New invite sent to {invite.email}. The old link no longer works.")
        return redirect("admin:staff")

    def accept_view(self, request, key):
        invite = StaffInvite.objects.filter(key_hash=key_hash(key)).exclude(key_hash="").first()
        if not invite or invite.sent < timezone.now() - timedelta(days=StaffInvite.DAYS):
            return TemplateResponse(request, "admin/staff/accept.html", {
                **self.site.each_context(request), "title": "Invite link not valid", "invalid": True}, status=404)
        # The authenticator secret lives in the session until they prove the app shows its codes.
        saved = request.session.get("staff_invite")
        if not saved or saved.get("invite") != invite.pk:
            saved = request.session["staff_invite"] = {"invite": invite.pk, "key": default_key()}
        form = AcceptForm(request.POST or None, email=invite.email, totp_key=saved["key"])
        if request.method == "POST" and form.is_valid():
            if User.objects.filter(email__iexact=invite.email).exists():
                form.add_error(None, "An account with this email was made meanwhile. Ask whoever invited you to "
                                     "add it from the Staff page instead.")
            else:
                with transaction.atomic():
                    user = User.objects.create_user(form.cleaned_data["username"], invite.email,
                                                    form.cleaned_data["password1"], is_staff=True)
                    user.user_permissions.set(invite.permissions.all())
                    TOTPDevice.objects.create(user=user, key=saved["key"], name="authenticator", confirmed=True)
                    invite.delete()
                del request.session["staff_invite"]
                log.info("staff invite accepted: %s as %s", invite.email, user.username)
                messages.success(request, "You're in. Log in with your username, password and a code from the app.")
                return redirect("admin:login")
        device = TOTPDevice(user=User(username=invite.email), key=saved["key"])
        return TemplateResponse(request, "admin/staff/accept.html", {
            **self.site.each_context(request), "title": "Join the Haat team", "form": form, "invite": invite,
            "config_url": device.config_url,
            "secret": base64.b32encode(device.bin_key).decode()})  # for typing into the app by hand

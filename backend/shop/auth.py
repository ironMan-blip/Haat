"""API token lifetime, CSRF for the views that act on the session cookie, client IPs and login lockout."""
import ipaddress
import unicodedata
from collections.abc import Mapping
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from oauth2_provider.contrib.rest_framework import authentication as oauth2_drf
from oauth2_provider.models import AccessToken, Grant, RefreshToken
from oauth2_provider.oauth2_validators import validate_resource_as_url_prefix
from rest_framework import exceptions, permissions, throttling
from rest_framework.authentication import CSRFCheck, TokenAuthentication
from rest_framework.authtoken.models import Token


def client_ident(request):
    """The client's IP (honouring NUM_PROXIES), with IPv6 cut to its /64: one home or phone gets a whole
    /64, so counting single IPv6 addresses would let anyone dodge every per-IP limit."""
    ident = throttling.BaseThrottle().get_ident(request)
    try:
        addr = ipaddress.ip_address(ident)
    except ValueError:
        return ident
    if addr.version == 4:
        return ident
    if addr.ipv4_mapped:  # ::ffff:1.2.3.4 is the IPv4 client 1.2.3.4
        return str(addr.ipv4_mapped)
    return str(ipaddress.ip_network(f"{addr}/64", strict=False))


class ClientIdent:
    def get_ident(self, request):
        return client_ident(request)


class AnonThrottle(ClientIdent, throttling.AnonRateThrottle):
    pass


class UserThrottle(ClientIdent, throttling.UserRateThrottle):
    pass


class ScopedThrottle(ClientIdent, throttling.ScopedRateThrottle):
    pass


class GuestOrderThrottle(AnonThrottle):
    """Orders placed without an account, per IP; signed-in buyers and reading orders are not counted."""
    scope = "guest_order"

    def allow_request(self, request, view):
        return request.method != "POST" or super().allow_request(request, view)


class CommentThrottle(UserThrottle):
    """Comments posted per account; reading them is not counted."""
    scope = "comment"

    def allow_request(self, request, view):
        return request.method != "POST" or super().allow_request(request, view)


class CommentActionThrottle(UserThrottle):
    """Edits, deletes, likes and unlikes per account, so a script can't hammer them."""
    scope = "comment_action"


def login_fail_keys(username, request, ip_lock=False):
    """{failure counter: failures allowed}, shared by the API and admin logins so neither is a way round
    the other's lockout. Per account and IP at LOGIN_MAX_FAILS, so one IP can't lock a customer out; per
    account everywhere at LOGIN_MAX_FAILS_PER_ACCOUNT (LOGIN_MAX_FAILS for staff), against many IPs
    guessing; per IP with `ip_lock` (admin only: mobile carriers share IPs).
    Usernames can't differ only by case (see RegisterSerializer), so one counter per lowercased name.
    Both logins strip spaces, the admin also applies NFKC and DRF takes a JSON number, so the key does
    too: else " rahim" or "ｒａｈｉｍ" would be a fresh counter that still guesses rahim's password."""
    if isinstance(username, (str, int)) and not isinstance(username, bool):
        username = unicodedata.normalize("NFKC", str(username)).strip()[:150].lower()
    ip = client_ident(request)
    keys = {f"login-fails:ip:{ip}": settings.LOGIN_MAX_FAILS} if ip_lock else {}
    if isinstance(username, str) and username:
        staff = User.objects.filter(username__iexact=username, is_staff=True).exists()
        keys[f"login-fails:user:{username}"] = settings.LOGIN_MAX_FAILS if staff else settings.LOGIN_MAX_FAILS_PER_ACCOUNT
        keys[f"login-fails:user-ip:{username}:{ip}"] = settings.LOGIN_MAX_FAILS
    return keys


def email_username(email):
    """Username of the account with this email, or "" when there is none (a login with it then fails)."""
    if not isinstance(email, str) or "@" not in email:
        return ""
    return User.objects.filter(email__iexact=email.strip()).values_list("username", flat=True).first() or ""


def locked_out(keys):
    return any(cache.get(k, 0) >= limit for k, limit in keys.items())


def record_login_failure(keys):
    for k in keys:
        cache.add(k, 0, settings.LOGIN_LOCKOUT_SECONDS)
        try:
            cache.incr(k)
        except ValueError:  # the counter expired between add and incr
            cache.set(k, 1, settings.LOGIN_LOCKOUT_SECONDS)


def expired(token):
    return token.created < timezone.now() - timedelta(days=settings.TOKEN_TTL_DAYS)


class ExpiringTokenAuthentication(TokenAuthentication):
    """DRF tokens never expire on their own; these die TOKEN_TTL_DAYS after they were issued."""

    def authenticate_credentials(self, key):
        try:
            user, token = super().authenticate_credentials(key)
        except exceptions.AuthenticationFailed:  # DRF's "Invalid token." means nothing to a buyer
            raise exceptions.AuthenticationFailed("You were signed out. Please log in again.") from None
        if expired(token):
            token.delete()
            raise exceptions.AuthenticationFailed("Your session expired. Please log in again.")
        return user, token


class OAuth2Authentication(oauth2_drf.OAuth2Authentication):
    """AI apps' tokens. DOT reads a bad Bearer token as no sign-in at all; here it fails, so an app whose sign-in
    was revoked can't go on as a guest (guest orders, a guest cart) while it thinks it is the buyer."""

    def authenticate(self, request):
        found = super().authenticate(request)
        if found is None and request.headers.get("Authorization", "").startswith("Bearer "):
            raise exceptions.AuthenticationFailed("This app was signed out. Connect it to your account again.")
        if found and not found[0].is_active:  # DOT doesn't check; DRF's own tokens refuse these too
            raise exceptions.AuthenticationFailed("This account is disabled.")
        return found


def mcp_audience(request_uri, audiences):
    """AI apps get tokens for the MCP server, which spends them on this API for the buyer (RFC 8707 audience)."""
    return settings.MCP_RESOURCE_URL in audiences or validate_resource_as_url_prefix(request_uri, audiences)


def issue_token(user):
    """The user's token, replaced by a fresh one if it has expired."""
    token, created = Token.objects.get_or_create(user=user)
    if not created and expired(token):
        Token.objects.filter(pk=token.pk).delete()
        token, _ = Token.objects.get_or_create(user=user)  # a parallel login may have made it already
    return token


def safe_next(request):
    """Where the app goes after sign-in: a same-site path only ("//host" and "/\\host" are other sites)."""
    nxt = request.data.get("next") if isinstance(request.data, Mapping) else None
    ok = isinstance(nxt, str) and nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts=None)
    return nxt if ok else "/"


@receiver(pre_save, sender=User)
def revoke_tokens_on_password_change(sender, instance, raw=False, **kwargs):
    # A new password must lock out whoever had the old one, on every device.
    if raw or not instance.pk:
        return
    old = User.objects.filter(pk=instance.pk).values_list("password", flat=True).first()
    if old is not None and old != instance.password:
        Token.objects.filter(user_id=instance.pk).delete()
        for model in (RefreshToken, AccessToken, Grant):  # connected AI apps too
            model.objects.filter(user_id=instance.pk).delete()


@receiver(pre_save, sender=User)
def one_owner(sender, instance, raw=False, **kwargs):
    # The shop has one owner (the only superuser), set by `manage.py sync_owner` from .env. This stops a second
    # one from `createsuperuser`, a script or a form; sync_owner demotes the old owner before saving the new.
    if not raw and instance.is_superuser and User.objects.filter(is_superuser=True).exclude(pk=instance.pk).exists():
        raise ValidationError("The shop already has an owner. Change OWNER_* in .env and run manage.py sync_owner.")


class CsrfProtected(permissions.BasePermission):
    """Django's CSRF check for views that change the session cart. DRF only runs it under session
    auth, and this API uses tokens, so without this any site could post to a visitor's cart."""

    def has_permission(self, request, view):
        check = CSRFCheck(lambda req: None)  # same check DRF's SessionAuthentication runs
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF failed: {reason} Reload the page and try again.")
        return True

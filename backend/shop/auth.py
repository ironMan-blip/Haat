"""API token lifetime, CSRF for the views that act on the session cookie, client IPs and login lockout."""
import ipaddress
from collections.abc import Mapping
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
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


def login_fail_keys(username, request=None):
    """Failure counters shared by the API and admin logins, so neither is a way round the other's lockout.
    Usernames can't differ only by case (see RegisterSerializer), so one counter per lowercased name."""
    keys = [f"login-fails:user:{username[:150].lower()}"] if isinstance(username, str) and username else []
    return keys + ([f"login-fails:ip:{client_ident(request)}"] if request else [])


def locked_out(keys):
    return any(cache.get(k, 0) >= settings.LOGIN_MAX_FAILS for k in keys)


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

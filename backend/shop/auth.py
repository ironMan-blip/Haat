"""API token lifetime, and CSRF for the views that act on the session cookie."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework import exceptions, permissions
from rest_framework.authentication import CSRFCheck, TokenAuthentication
from rest_framework.authtoken.models import Token


def expired(token):
    return token.created < timezone.now() - timedelta(days=settings.TOKEN_TTL_DAYS)


class ExpiringTokenAuthentication(TokenAuthentication):
    """DRF tokens never expire on their own; these die TOKEN_TTL_DAYS after they were issued."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if expired(token):
            token.delete()
            raise exceptions.AuthenticationFailed("Your session expired. Please log in again.")
        return user, token


def issue_token(user):
    """The user's token, replaced by a fresh one if it has expired."""
    token, created = Token.objects.get_or_create(user=user)
    if not created and expired(token):
        token.delete()
        token = Token.objects.create(user=user)
    return token


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

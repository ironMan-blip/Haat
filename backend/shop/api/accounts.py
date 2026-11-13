from collections.abc import Mapping

from django.core.cache import cache
from rest_framework import generics
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.response import Response

from ..auth import (AnonThrottle, CsrfProtected, ScopedThrottle, UserThrottle, issue_token, locked_out,
                    login_fail_keys, record_login_failure, safe_next)
from ..serializers import RegisterSerializer
from .checkout import claim_guest_orders


def signed_in(request, user, status=200):
    """Shared end of login and sign-up: move this session's guest orders over and hand out the token."""
    claim_guest_orders(request, user)
    return Response({"token": issue_token(user).key, "username": user.username, "next": safe_next(request)},
                    status=status)


class Login(ObtainAuthToken):
    throttle_classes = [ScopedThrottle]  # the parent sets none at all
    throttle_scope = "auth"  # slows password guessing from one IP; the lockout below covers many IPs

    def post(self, request, *args, **kwargs):
        username = request.data.get("username") if isinstance(request.data, Mapping) else None
        keys = login_fail_keys(username)  # the admin login counts into the same per-user counter
        if locked_out(keys):
            raise Throttled(detail="Too many failed logins for this account. Try again in 15 minutes.")
        serializer = self.serializer_class(data=request.data, context={"request": request})
        if not serializer.is_valid():
            record_login_failure(keys)
            raise ValidationError(serializer.errors)
        cache.delete_many(keys)
        return signed_in(request, serializer.validated_data["user"])


class SignupThrottle(AnonThrottle):
    scope = "signup"  # daily cap per IP, on top of the per-minute "auth" one


class Register(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    throttle_classes = [AnonThrottle, UserThrottle, ScopedThrottle, SignupThrottle]
    throttle_scope = "auth"  # slows bulk sign-ups

    def perform_create(self, serializer):
        self.user = serializer.save()

    def create(self, request, *args, **kwargs):
        super().create(request, *args, **kwargs)
        return signed_in(request, self.user, status=201)


@api_view(["POST"])
@authentication_classes([])  # a stale token must still sign out, not fail with 401
@permission_classes([CsrfProtected])  # it empties the session cart
def logout(request):
    # Revoke the presented token (DRF keeps one per user, so every device signs out), and wipe this
    # device's session (cart and guest orders) under a new key so the next person sees none of it.
    key = request.headers.get("Authorization", "").removeprefix("Token ").strip()
    if key:
        Token.objects.filter(key=key).delete()
    request.session.flush()
    return Response(status=204)

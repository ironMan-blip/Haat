import logging
from collections.abc import Mapping
from datetime import timedelta
from urllib.parse import urlencode

from django.core import signing
from django.core.mail import send_mail
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..auth import AnonThrottle, CsrfProtected, GuestOrderThrottle, UserThrottle, client_ident
from ..cart import Cart, parse_key
from ..models import Order
from ..serializers import CartLineSerializer, OrderSerializer

log = logging.getLogger("shop.security")
GUEST_ORDERS = "guest_orders"  # session key: ids of the orders this session placed without an account
GUEST_ORDERS_KEPT = 20  # bounds the session row
CLAIM_SALT = "claim-guest-orders"
CLAIM_DAYS = 3


def claim_guest_orders(request, user):
    """On login or sign-up, this session's guest orders can join the account, so they don't vanish from its list.
    On a shared browser, anyone can read the session's guest orders, so whatever they show (email, phone) proves
    nothing: an order joins only by proof the account holder doesn't get from the browser.
    - A phone an account order was delivered to: the rider reached that phone, so it is the account's.
    - The account's email: account emails aren't verified, so a link goes to that inbox (claim_by_link)."""
    ids = request.session.pop(GUEST_ORDERS, [])
    if ids:
        guest = Order.objects.filter(user=None, pk__in=ids)
        guest.filter(phone__in=user.orders.filter(status="delivered").values("phone")).update(user=user)
        if user.email:  # a blank email must not match every order that left it blank
            emailed = list(guest.filter(email__iexact=user.email).values_list("pk", flat=True))
            if emailed:
                send_claim_link(request, user, emailed)
    request.session.cycle_key()  # a session cookie planted before sign-in no longer reads this cart


def send_claim_link(request, user, ids):
    token = signing.dumps({"u": user.pk, "e": user.email.lower(), "o": ids}, salt=CLAIM_SALT)
    link = request.build_absolute_uri(f"/orders/claim?{urlencode({'t': token})}")  # Host is checked by ALLOWED_HOSTS
    orders = ", ".join(f"#{pk}" for pk in ids)
    try:
        send_mail(f"Add order {orders} to your Haat account?",
                  f"Someone signed in to the Haat account \"{user.username}\" on the browser that placed order {orders} "
                  f"with this email. To add {'it' if len(ids) == 1 else 'them'} to that account, open this link and "
                  f"log in as \"{user.username}\" within {CLAIM_DAYS} days:\n\n{link}\n\n"
                  "If that isn't your account, ignore this email: the orders stay off it.",
                  None, [user.email])
    except Exception:  # a mail outage must not break signing in; the orders just stay unclaimed
        log.exception("claim email failed user=%s", user.pk)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim_by_link(request):
    """The link from send_claim_link: whoever opened that inbox, signed in as the account the link names."""
    try:
        data = signing.loads(str(request.data.get("token", "")) if isinstance(request.data, Mapping) else "",
                             salt=CLAIM_SALT, max_age=timedelta(days=CLAIM_DAYS))
    except signing.BadSignature:  # SignatureExpired is one too
        raise ValidationError(f"This link is broken or older than {CLAIM_DAYS} days.") from None
    user = request.user
    if data["u"] != user.pk:  # on the inbox owner's own account, or none: nothing joins the account that asked
        raise PermissionDenied("This link is for another account. Log in as the account named in the email.")
    if user.email.lower() != data["e"]:  # the account's email changed since: the old inbox no longer speaks for it
        raise PermissionDenied("This account's email has changed since the link was sent.")
    n = Order.objects.filter(user=None, pk__in=data["o"], email__iexact=data["e"]).update(user=user)
    return Response({"notice": f"✓ {n} order{'' if n == 1 else 's'} added to your account." if n
                     else "These orders are already on an account."})


@ensure_csrf_cookie  # the app loads the cart first, so this hands the frontend its CSRF token
@api_view(["GET", "POST"])
@permission_classes([CsrfProtected])
def cart(request):
    c = Cart(request)
    if request.method == "POST":  # add to cart
        line = CartLineSerializer(data=request.data)
        line.is_valid(raise_exception=True)
        c.add(line.validated_data["product"], line.validated_data["variant"], line.validated_data["quantity"])
        if not c.notes:
            c.notes.append(f"Added to cart: {line.validated_data['product'].name}")
    return Response(c.data())


@api_view(["PATCH", "DELETE"])
@permission_classes([CsrfProtected])
def cart_line(request, key):
    """`key` is the line's id from the cart response (product id plus choices), URL-encoded by the client."""
    c = Cart(request)
    if request.method == "DELETE":
        c.remove(key)
    else:  # set quantity
        if key not in c.items:  # a stale tab must not bring back a removed line
            raise NotFound("That item is no longer in your cart.")
        body = request.data if isinstance(request.data, Mapping) else {}  # a JSON array or number is not a body
        pk, chosen = parse_key(key)
        line = CartLineSerializer(data={"product": pk, "options": chosen, "quantity": body.get("quantity")})
        line.is_valid(raise_exception=True)
        c.set(line.validated_data["product"], line.validated_data["variant"], line.validated_data["quantity"])
    return Response(c.data())


class OrderListCreate(generics.ListCreateAPIView):
    """Signed-in buyers see their account's orders; guests see the orders this session placed."""
    serializer_class = OrderSerializer
    permission_classes = [CsrfProtected]  # orders are built from the session cart, which any site could post with
    throttle_classes = [AnonThrottle, UserThrottle, GuestOrderThrottle]

    def get_queryset(self):
        if self.request.user.is_authenticated:
            orders = self.request.user.orders.all()
        else:  # user=None too, so a session can never list an account's orders
            orders = Order.objects.filter(user=None, pk__in=self.request.session.get(GUEST_ORDERS, []))
        return orders.prefetch_related("items__product")

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data["notice"] = f"✓ Order #{response.data['id']} placed. Keep cash ready for the rider."
        return response

    def perform_create(self, serializer):
        # shortcut: guest phones are never verified, so a script rotating IPs and phones can hoard stock with
        # fake COD orders; require sign-in or an SMS code before deploying.
        user =self.request.user if self.request.user.is_authenticated else None
        order = serializer.save(user=user)
        Cart(self.request).clear()
        if not user:
            session = self.request.session
            session[GUEST_ORDERS] = [*session.get(GUEST_ORDERS, []), order.pk][-GUEST_ORDERS_KEPT:]
            session.cycle_key()  # a session cookie planted by someone else no longer reads this order
            log.info("guest order id=%s ip=%s", order.pk, client_ident(self.request))  # no name, phone or address

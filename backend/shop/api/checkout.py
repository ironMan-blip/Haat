import logging
from collections.abc import Mapping

from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from ..auth import AnonThrottle, CsrfProtected, GuestOrderThrottle, UserThrottle, client_ident
from ..cart import Cart
from ..models import Order
from ..serializers import CartLineSerializer, OrderSerializer

log = logging.getLogger("shop.security")
GUEST_ORDERS = "guest_orders"  # session key: ids of the orders this session placed without an account
GUEST_ORDERS_KEPT = 20  # bounds the session row


@ensure_csrf_cookie  # the app loads the cart first, so this hands the frontend its CSRF token
@api_view(["GET", "POST"])
@permission_classes([CsrfProtected])
def cart(request):
    c = Cart(request)
    if request.method == "POST":  # add to cart
        line = CartLineSerializer(data=request.data)
        line.is_valid(raise_exception=True)
        c.add(line.validated_data["product"], line.validated_data["quantity"])
        if not c.notes:
            c.notes.append(f"Added to cart: {line.validated_data['product'].name}")
    return Response(c.data())


@api_view(["PATCH", "DELETE"])
@permission_classes([CsrfProtected])
def cart_line(request, pk):
    c = Cart(request)
    if request.method == "DELETE":
        c.remove(pk)
    else:  # set quantity
        if str(pk) not in c.items:  # a stale tab must not bring back a removed line
            raise NotFound("That item is no longer in your cart.")
        body = request.data if isinstance(request.data, Mapping) else {}  # a JSON array or number is not a body
        line = CartLineSerializer(data={"product": pk, "quantity": body.get("quantity")})
        line.is_valid(raise_exception=True)
        c.set(line.validated_data["product"], line.validated_data["quantity"])
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
        user = self.request.user if self.request.user.is_authenticated else None
        order = serializer.save(user=user)
        Cart(self.request).clear()
        if not user:
            session = self.request.session
            session[GUEST_ORDERS] = [*session.get(GUEST_ORDERS, []), order.pk][-GUEST_ORDERS_KEPT:]
            session.cycle_key()  # a session cookie planted by someone else no longer reads this order
            log.info("guest order id=%s ip=%s", order.pk, client_ident(self.request))  # no name, phone or address

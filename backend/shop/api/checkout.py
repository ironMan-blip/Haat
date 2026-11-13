from collections.abc import Mapping

from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from ..auth import CsrfProtected
from ..cart import Cart
from ..serializers import CartLineSerializer, OrderSerializer


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
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.request.user.orders.prefetch_related("items__product")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        Cart(self.request).clear()

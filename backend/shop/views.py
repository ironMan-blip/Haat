from django.conf import settings
from django.db.models import Q
from rest_framework import generics, permissions
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import Category, Product
from .serializers import CategorySerializer, OrderSerializer, ProductSerializer, RegisterSerializer


class CategoryList(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = None


class ProductList(generics.ListAPIView):
    # shortcut: no pagination, fine for a few hundred products; add PageNumberPagination beyond that.
    serializer_class = ProductSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Product.objects.select_related("category")
        params = self.request.query_params
        if params.get("category"):
            qs = qs.filter(category__slug=params["category"])
        if params.get("q"):
            q = params["q"][:100]  # bound the LIKE scan
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if params.get("sort") in {"price", "-price", "-rating"}:
            qs = qs.order_by(params["sort"], "id")
        return qs


class ProductDetail(generics.RetrieveAPIView):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductSerializer
    lookup_field = "slug"


class Login(ObtainAuthToken):
    throttle_classes = [ScopedRateThrottle]  # the parent sets none at all
    throttle_scope = "auth"  # slows password guessing


class Register(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    throttle_scope = "auth"  # slows bulk sign-ups

    def perform_create(self, serializer):
        self.user = serializer.save()

    def create(self, request, *args, **kwargs):
        super().create(request, *args, **kwargs)
        token, _ = Token.objects.get_or_create(user=self.user)
        return Response({"token": token.key, "username": self.user.username}, status=201)


class OrderListCreate(generics.ListCreateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return self.request.user.orders.prefetch_related("items__product")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    return Response({"username": request.user.username, "email": request.user.email})


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout(request):
    # DRF keeps one token per user, so this signs out every device.
    Token.objects.filter(user=request.user).delete()
    return Response(status=204)


@api_view(["GET"])
def store_config(request):
    return Response({"free_delivery_min": settings.FREE_DELIVERY_MIN, "delivery_fee": settings.DELIVERY_FEE})

from collections import defaultdict

from django.conf import settings
from django.db.models import Q
from rest_framework import generics, permissions
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .cart import Cart
from .models import Category, Order, Product
from .serializers import (CartLineSerializer, CategorySerializer, OrderSerializer, ProductDetailSerializer,
                          ProductSerializer, RegisterSerializer)

SORTS = {"": "Newest", "price": "Price, low to high", "-price": "Price, high to low", "-rating": "Best rated"}


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
        if params.get("sort") and params["sort"] in SORTS:
            qs = qs.order_by(params["sort"], "id")
        return qs


class ProductDetail(generics.RetrieveAPIView):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductDetailSerializer
    lookup_field = "slug"


@api_view(["GET"])
def home(request):
    # shortcut: ranks every product in Python, fine for a few hundred; move to DB annotations beyond that.
    products = list(Product.objects.select_related("category"))
    best, seen = [], set()
    for p in sorted(products, key=lambda p: p.rank, reverse=True):
        if p.category_id not in seen:  # top item of each category, two categories
            seen.add(p.category_id)
            best.append(p)
        if len(best) == 2:
            break
    by_cat = defaultdict(list)
    for p in products:
        by_cat[p.category_id].append(p)
    ser = lambda items: ProductSerializer(items, many=True).data
    return Response({
        "wall": [{"image": p.image, "price": p.price} for p in products[:48]],
        "deals": ser(sorted(products, key=lambda p: p.discount, reverse=True)[:14]),
        "best": ser(best),
        "menu": [{"name": c.name, "slug": c.slug, "count": len(by_cat[c.pk]), "items": ser(by_cat[c.pk][:6])}
                 for c in Category.objects.all()],
    })


@api_view(["GET", "POST"])
def cart(request):
    c = Cart(request)
    if request.method == "POST":  # add to cart
        line = CartLineSerializer(data=request.data)
        line.is_valid(raise_exception=True)
        c.add(line.validated_data["product"], line.validated_data["quantity"])
    return Response(c.data())


@api_view(["PATCH", "DELETE"])
def cart_line(request, pk):
    c = Cart(request)
    if request.method == "DELETE":
        c.remove(pk)
    else:  # set quantity
        line = CartLineSerializer(data={"product": pk, "quantity": request.data.get("quantity")})
        line.is_valid(raise_exception=True)
        c.set(line.validated_data["product"], line.validated_data["quantity"])
    return Response(c.data())


class Login(ObtainAuthToken):
    throttle_classes = [ScopedRateThrottle]  # the parent sets none at all
    throttle_scope = "auth"  # slows password guessing

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "username": user.username})


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
        Cart(self.request).clear()


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
    return Response({
        "free_delivery_min": settings.FREE_DELIVERY_MIN,
        "delivery_fee": settings.DELIVERY_FEE,
        "cities": [c for c, _ in Order.CITIES],
        "sorts": [{"value": k, "label": v} for k, v in SORTS.items()],
    })

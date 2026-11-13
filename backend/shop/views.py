from collections import defaultdict
from collections.abc import Mapping

from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_texts
from django.core.cache import cache
from django.db.models import Q
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics, permissions
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import NotFound, Throttled, ValidationError
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .auth import (AnonThrottle, CsrfProtected, ScopedThrottle, UserThrottle, issue_token, locked_out,
                   login_fail_keys, record_login_failure, safe_next)
from .cart import Cart
from .display import cdn, num, taka
from .models import Category, Order, Product
from .serializers import (CartLineSerializer, CategorySerializer, OrderSerializer, ProductDetailSerializer,
                          ProductSerializer, RegisterSerializer)

SORTS = {"": "Newest", "price": "Price, low to high", "-price": "Price, high to low", "-rating": "Best rated"}


def first_message(data):
    if isinstance(data, str):  # DRF's ErrorDetail is a str
        return data
    for v in data.values() if isinstance(data, Mapping) else data if isinstance(data, list) else []:
        if msg := first_message(v):
            return msg
    return None


def exception_handler(exc, context):
    """Every API error is an object carrying `message`, the one line the shop shows the buyer."""
    response = drf_exception_handler(exc, context)
    if response is not None:
        if not isinstance(response.data, Mapping):  # ValidationError("...") comes out as a bare list
            response.data = {"non_field_errors": response.data}
        response.data["message"] = first_message(response.data)
    return response


class ProductList(generics.ListAPIView):
    # shortcut: no pagination, fine for a few hundred products; add PageNumberPagination beyond that.
    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = Product.objects.select_related("category")
        params = self.request.query_params
        if params.get("category"):
            qs = qs.filter(category__slug=params["category"])
        if q := params.get("q", "").strip()[:100]:  # bound the LIKE scan; blank means no search
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if params.get("sort") and params["sort"] in SORTS:
            qs = qs.order_by(params["sort"], "id")
        return qs

    def list(self, request, *args, **kwargs):
        # The page's heading, category links and empty-state text come with the results.
        results = self.get_serializer(self.get_queryset(), many=True).data
        cats = list(Category.objects.all())
        slug, q = request.query_params.get("category", ""), request.query_params.get("q", "").strip()[:100]
        cat = next((c for c in cats if c.slug == slug), None)
        if q:
            title, empty = f"Results for “{q}”", f"Nothing matches “{q}”. Try a shorter or different word."
        elif cat:
            title, empty = cat.name, "This category has nothing on sale right now."
        elif slug:
            title, empty = "Category not found", "That category does not exist. The link may be old."
        else:
            title, empty = "Every product", "Nothing is on sale right now."
        return Response({
            "title": title,
            "count_label": f"{len(results)} item{'' if len(results) == 1 else 's'}",
            "empty": empty,
            "categories": CategorySerializer(cats, many=True).data,
            "results": results,
        })


class ProductDetail(generics.RetrieveAPIView):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductDetailSerializer
    lookup_field = "slug"


def wall(products):
    """Brickwork of goods and price tags, like a haat laid out on the ground: 8 rows of 16, every third
    brick a price tag (colour field f1-f3 by column band), the rest photos."""
    if not products:
        return []
    rows = []
    for r in range(8):
        row = []
        for c in range(16):
            p = products[(r * 11 + c * 5) % len(products)]
            row.append({"tag": taka(p.price), "field": f"f{c // 3 % 3 + 1}"} if (r + c) % 3 == 0
                       else {"image": cdn(p.image, 200)})
        rows.append(row)
    return rows


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
        "wall": wall(products[:48]),
        "deals": ser(sorted((p for p in products if p.stock), key=lambda p: p.discount, reverse=True)[:14]),
        "best": [{**d, "panel_name": f"{p.name[:54].rstrip()}…" if len(p.name) > 56 else p.name,
                  "panel_fact": f"{taka(p.price)} · rated {p.rating} by {num(p.reviews)} buyers"}
                 for p, d in zip(best, ser(best))],
        "menu": [{"name": c.name, "slug": c.slug, "count_label": f"{len(by_cat[c.pk])} items",
                  "items": [{**d, "note": f"{p.discount}% below the usual {taka(p.original_price)}" if p.discount else None}
                            for p, d in zip(by_cat[c.pk][:6], ser(by_cat[c.pk][:6]))]}
                 for c in Category.objects.all()],
        "hero": {"head": "Phones to rice, one haat.", "line": "Pay the rider in cash when it reaches your door."},
        "promise": f"Spend {taka(settings.FREE_DELIVERY_MIN)} and delivery is free. Under that it costs "
                   f"{taka(settings.DELIVERY_FEE)}. You pay the rider in cash at the door.",
    })


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
        user = serializer.validated_data["user"]
        token = issue_token(user)
        return Response({"token": token.key, "username": user.username, "next": safe_next(request)})


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
        return Response({"token": issue_token(self.user).key, "username": self.user.username,
                         "next": safe_next(request)}, status=201)


class OrderListCreate(generics.ListCreateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.request.user.orders.prefetch_related("items__product")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        Cart(self.request).clear()


@api_view(["POST"])
@authentication_classes([])  # a stale token must still sign out, not fail with 401
@permission_classes([CsrfProtected])  # it empties the session cart
def logout(request):
    # Revoke the presented token (DRF keeps one per user, so every device signs out),
    # and empty this device's cart so the next person doesn't see it.
    key = request.headers.get("Authorization", "").removeprefix("Token ").strip()
    if key:
        Token.objects.filter(key=key).delete()
    Cart(request).clear()
    return Response(status=204)


@api_view(["GET"])
def store_config(request):
    stamp = Product.objects.order_by("-rating", "id").values_list("image", flat=True).first()  # footer photo
    free = taka(settings.FREE_DELIVERY_MIN)
    return Response({
        "free_delivery_min": settings.FREE_DELIVERY_MIN,
        "delivery_fee": settings.DELIVERY_FEE,
        "cities": [c for c, _ in Order.CITIES],
        "sorts": [{"value": k, "label": v} for k, v in SORTS.items()],
        "password_rules": password_validators_help_texts(),  # the sign-up form's hint
        "stamp": cdn(stamp, 200) if stamp else None,
        "footer_line": f"Order today, pay the rider in cash when the parcel reaches your door. "
                       f"Spend {free} or more and delivery is on us.",
        "perks": ["Cash on delivery, pay when it arrives", f"Free delivery on orders over {free}"],
    })

from collections import defaultdict

from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_texts
from django.db.models import Q
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from ..auth import AnonThrottle, CommentThrottle, UserThrottle
from ..display import cdn, items, num, taka
from ..models import Category, Comment, Order, Product
from ..serializers import CategorySerializer, CommentSerializer, ProductDetailSerializer, ProductSerializer

PAYMENT_HINTS = {"cod": "Pay the rider when it arrives"}
SORTS = {"": "Newest", "price": "Price, low to high", "-price": "Price, high to low", "-rating": "Best rated"}


def search_term(request):
    return request.query_params.get("q", "").strip()[:100]  # bound the LIKE scan; blank means no search


class ProductList(generics.ListAPIView):
    # shortcut: no pagination, fine for a few hundred products; add PageNumberPagination beyond that.
    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = Product.objects.select_related("category")
        params = self.request.query_params
        if params.get("category"):
            qs = qs.filter(category__slug=params["category"])
        if q := search_term(self.request):
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if params.get("sort") and params["sort"] in SORTS:
            qs = qs.order_by(params["sort"], "id")
        return qs

    def list(self, request, *args, **kwargs):
        # The page's heading, category links and empty-state text come with the results.
        results = self.get_serializer(self.get_queryset(), many=True).data
        cats = list(Category.objects.all())
        slug, q = request.query_params.get("category", ""), search_term(request)
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
            "count_label": items(len(results)),
            "empty": empty,
            "categories": CategorySerializer(cats, many=True).data,
            "results": results,
        })


class ProductDetail(generics.RetrieveAPIView):
    queryset = Product.objects.select_related("category").prefetch_related("photos")
    serializer_class = ProductDetailSerializer
    lookup_field = "slug"


class ProductComments(generics.ListCreateAPIView):
    """Anyone reads a product's comments; only signed-in customers post (token auth, so no CSRF)."""
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    throttle_classes = [AnonThrottle, UserThrottle, CommentThrottle]

    def product(self):
        return get_object_or_404(Product, slug=self.kwargs["slug"])

    def get_queryset(self):
        # shortcut: newest 100 threads only, no pagination; add CursorPagination once a product gets more.
        replies = Comment.objects.select_related("user").prefetch_related("likes").order_by("created", "id")
        return (Comment.objects.filter(product=self.product(), parent=None).select_related("user")
                .prefetch_related("likes", Prefetch("replies", queryset=replies)))[:100]

    def list(self, request, *args, **kwargs):
        results = self.get_serializer(self.get_queryset(), many=True).data
        return Response({
            "title": f"Comments ({num(len(results))})" if results else "Comments",
            "empty": "No comments yet. Be the first to share what you think.",
            "login_prompt": "Log in to leave a comment.",
            "placeholder": "What do you think of this product?",
            "reply_placeholder": "Write a reply",
            "delete_confirm": "Delete this comment? This can't be undone.",
            "results": results,
        })

    def perform_create(self, serializer):
        product = self.product()
        parent = serializer.validated_data.get("parent")
        if parent and parent.product_id != product.pk:
            raise ValidationError({"parent": "You can only reply to a comment on this product."})
        serializer.save(product=product, user=self.request.user)


class CommentDetail(generics.UpdateAPIView, generics.DestroyAPIView):
    """Authors edit or delete their own comments; anyone else's is a 404."""
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch", "delete"]

    def get_queryset(self):
        return Comment.objects.filter(user=self.request.user, deleted=False)

    def perform_update(self, serializer):
        serializer.validated_data.pop("parent", None)  # a comment can't be moved to another thread
        serializer.save(edited=True)

    def perform_destroy(self, c):
        if c.replies.exists():  # keep other people's replies: leave a placeholder instead
            c.text, c.deleted = "", True
            c.save(update_fields=["text", "deleted"])
            c.likes.clear()
        else:
            c.delete()


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def like_comment(request, pk):
    """POST likes, DELETE unlikes; both are safe to repeat."""
    c = get_object_or_404(Comment, pk=pk, deleted=False)
    (c.likes.add if request.method == "POST" else c.likes.remove)(request.user)
    return Response(CommentSerializer(c, context={"request": request}).data)


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
    ser = lambda ps: ProductSerializer(ps, many=True).data
    return Response({
        "wall": wall(products[:48]),
        "deals": ser(sorted((p for p in products if p.stock), key=lambda p: p.discount, reverse=True)[:14]),
        "best": [{**d, "panel_name": f"{p.name[:54].rstrip()}…" if len(p.name) > 56 else p.name,
                  "panel_fact": f"{taka(p.price)} · rated {p.rating} by {num(p.reviews)} buyers"}
                 for p, d in zip(best, ser(best))],
        "menu": [{"name": c.name, "slug": c.slug, "count_label": items(len(by_cat[c.pk])),
                  "items": [{**d, "note": f"{p.discount}% below the usual {taka(p.original_price)}" if p.discount else None}
                            for p, d in zip(by_cat[c.pk][:6], ser(by_cat[c.pk][:6]))]}
                 for c in Category.objects.all()],
        "hero": {"head": "Phones to rice, one haat.", "line": "Pay the rider in cash when it reaches your door."},
        "promise": f"Spend {taka(settings.FREE_DELIVERY_MIN)} and delivery is free. Under that it costs "
                   f"{taka(settings.DELIVERY_FEE)}. You pay the rider in cash at the door.",
    })


@api_view(["GET"])
def store_config(request):
    stamp = Product.objects.order_by("-rating", "id").values_list("image", flat=True).first()  # footer photo
    free = taka(settings.FREE_DELIVERY_MIN)
    return Response({
        "cities": [c for c, _ in Order.CITIES],  # the first is the checkout's default
        "payments": [{"value": v, "label": label, "hint": PAYMENT_HINTS.get(v)} for v, label in Order.PAYMENTS],
        "sorts": [{"value": k, "label": v} for k, v in SORTS.items()],
        "password_rules": password_validators_help_texts(),  # the sign-up form's hint
        "stamp": cdn(stamp, 200) if stamp else None,
        "footer_line": f"Order today, pay the rider in cash when the parcel reaches your door. "
                       f"Spend {free} or more and delivery is on us.",
        "perks": ["Cash on delivery, pay when it arrives", f"Free delivery on orders over {free}"],
        "cart_note": "Pay in cash when your order arrives.",  # under the cart's checkout button
    })

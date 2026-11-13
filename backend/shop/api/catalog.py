from collections import defaultdict

from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_texts
from django.db.models import Q
from rest_framework import generics
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..display import cdn, num, taka
from ..models import Category, Order, Product
from ..serializers import CategorySerializer, ProductDetailSerializer, ProductSerializer

SORTS = {"": "Newest", "price": "Price, low to high", "-price": "Price, high to low", "-rating": "Best rated"}


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


@api_view(["GET"])
def store_config(request):
    stamp = Product.objects.order_by("-rating", "id").values_list("image", flat=True).first()  # footer photo
    free = taka(settings.FREE_DELIVERY_MIN)
    return Response({
        "cities": [c for c, _ in Order.CITIES],
        "sorts": [{"value": k, "label": v} for k, v in SORTS.items()],
        "password_rules": password_validators_help_texts(),  # the sign-up form's hint
        "stamp": cdn(stamp, 200) if stamp else None,
        "footer_line": f"Order today, pay the rider in cash when the parcel reaches your door. "
                       f"Spend {free} or more and delivery is on us.",
        "perks": ["Cash on delivery, pay when it arrives", f"Free delivery on orders over {free}"],
    })

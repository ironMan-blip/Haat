import re

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from rest_framework import serializers

from .cart import Cart, delivery_fee, describe, max_qty, pick, unit_price
from .display import cdn, day, images, num, taka
from .models import COMMENT_PAGE, LOW_STOCK, MAX_QTY, Category, Comment, Order, OrderItem, Product, ProductVariant


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class ProductSerializer(serializers.ModelSerializer):
    """What a product tile shows, ready to print; lists send many, so keep it small."""

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "summary", "price", "original_price", "discount",
                  "image", "rating", "reviews", "stock", "stock_level"]

    def to_representation(self, p):
        low, high = p.price_range  # variants may cost more or less than the product's own price
        # The "before discount" price is the product's own: never compare it against a cheaper choice.
        off = p.discount if low == p.price else 0
        return {
            **super().to_representation(p),
            **images(p.image),
            "price_display": taka(low) if low == high else f"From {taka(low)}",
            "original_price_display": taka(p.original_price) if off else None,  # struck-through price
            "discount_label": f"{off}% off" if off else None,
            "badge": "Sold out" if p.stock_level == "out" else f"−{off}%" if off else None,
            "reviews_display": num(p.reviews),
            "rating_label": f"Rated {p.rating} out of 5 by {num(p.reviews)} buyers" if p.reviews else None,
            # Set when the buyer must pick options first: tiles link to the product page instead of adding.
            "choose_label": f"Pick {' and '.join(o.name.lower() for o in opts)}" if (opts := p.options.all()) else None,
        }


class ProductDetailSerializer(ProductSerializer):
    category = CategorySerializer(read_only=True)
    related = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + ["category", "specs", "stock_label", "max_qty", "related"]

    def to_representation(self, p):
        gallery = [images(url) for url in [p.image, *(ph.url for ph in p.photos.all())]]  # main photo first
        return {**super().to_representation(p),
                "gallery": [{**g, "alt": f"{p.name}, photo {i} of {len(gallery)}"} for i, g in enumerate(gallery, 1)],
                "options": [{"name": o.name, "values": o.choices} for o in p.options.all()],
                # The page shows the picked combination's price and stock once every option is chosen.
                "variants": [variant_data(p, v) for v in p.variants.all()]}

    def get_related(self, p):
        others = Product.objects.select_related("category").prefetch_related("options", "variants").filter(category=p.category_id).exclude(pk=p.pk)[:7]
        return ProductSerializer(others, many=True).data


def variant_data(p, v):
    price, off = v.unit_price, p.discount if v.unit_price == p.price else 0  # see ProductSerializer
    return {"choices": v.choices, "price_display": taka(price),
            "original_price_display": taka(p.original_price) if off else None,
            "discount_label": f"{off}% off" if off else None, "max_qty": v.max_qty,
            "stock_level": "out" if not v.stock else "low" if v.stock < LOW_STOCK else "in",
            "stock_label": "Sold out" if not v.stock else f"Only {v.stock} left" if v.stock < LOW_STOCK else "In stock"}


class CommentSerializer(serializers.ModelSerializer):
    text = serializers.CharField(max_length=1000)  # the model allows blank only for deleted placeholders
    # Replies go one level deep, under a live top-level comment; the view checks it is on the same product.
    parent = serializers.PrimaryKeyRelatedField(queryset=Comment.objects.filter(parent=None, deleted=False),
                                                required=False, write_only=True)

    class Meta:
        model = Comment
        fields = ["id", "text", "created", "parent"]

    def to_representation(self, c):
        me = self.context["request"].user.pk  # None for guests
        likers = {u.pk for u in c.likes.all()}
        data = {
            **super().to_representation(c),
            "text": "This comment was deleted." if c.deleted else c.text,
            "author": None if c.deleted else c.user.username,
            "date": day(c.created),
            "edited_label": "edited" if c.edited and not c.deleted else None,
            "deleted": c.deleted,
            "mine": c.user_id == me and not c.deleted,
            "likes": len(likers),
            "liked": me in likers,
            "is_reply": bool(c.parent_id),
        }
        if self.context.get("threads") and not c.parent_id:  # a thread list: first page of replies too
            rs = c.first_replies  # prefetched by the view, one past the page to tell if there are more
            data["replies"] = CommentSerializer(rs[:COMMENT_PAGE], many=True, context=self.context).data
            data["replies_next"] = rs[COMMENT_PAGE - 1].pk if len(rs) > COMMENT_PAGE else None
            data["reply_count"] = c.reply_count  # annotated by the view; the dropdown shows it while closed
        return data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, max_length=128)  # bounds hashing and similarity checks
    # ASCII only: Unicode look-alikes ("rafi" with a Cyrillic "а") would pass as a different user.
    username = serializers.CharField(max_length=150, validators=[ASCIIUsernameValidator()])
    email = serializers.EmailField(max_length=254)  # required: accounts are tracked by email

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def validate_username(self, value):
        # Login reads "@" as an email but tries a username first, so one named after someone's email would block theirs.
        if "@" in value:
            raise serializers.ValidationError("A username can't contain @.")
        # Usernames stay case-sensitive in Django; block "Rafi" when "rafi" exists so people can't mix them up.
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with that email already exists.")
        return value

    def validate(self, attrs):
        # Pass the would-be user so the "too similar to your username/email" check runs.
        validate_password(attrs["password"], User(username=attrs["username"], email=attrs["email"]))
        return attrs

    def create(self, data):
        try:
            with transaction.atomic():
                return User.objects.create_user(**data)
        except IntegrityError:  # a parallel sign-up took the name or email; a case-insensitive index caught it
            if data.get("email") and User.objects.filter(email__iexact=data["email"]).exists():
                raise serializers.ValidationError({"email": "An account with that email already exists."})
            raise serializers.ValidationError({"username": "A user with that username already exists."})


class OrderItemSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(source="product.slug", read_only=True)

    class Meta:
        model = OrderItem
        fields = ["name", "slug", "price", "quantity", "options"]

    def to_representation(self, it):
        return {**super().to_representation(it), "thumb": cdn(it.product.image, 200),
                "price_display": taka(it.price), "qty_line": f"{it.quantity} × {taka(it.price)}"}


class CartLineSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.prefetch_related("options", "variants"))
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QTY)
    # Any choice the admin accepts fits the order's snapshot of the choices; pick() checks the rest.
    options = serializers.DictField(child=serializers.CharField(max_length=OrderItem._meta.get_field("options").max_length),
                                    required=False, default=dict)

    def validate(self, attrs):
        attrs["variant"] = pick(attrs["product"], attrs["options"])
        return attrs


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    # The total the buyer was shown; the order is refused if the cart has changed since.
    expected_total = serializers.IntegerField(write_only=True, min_value=0)

    class Meta:
        model = Order
        fields = ["id", "full_name", "phone", "address", "city", "subtotal", "delivery_fee", "total",
                  "payment", "status", "status_display", "created", "items", "expected_total"]
        read_only_fields = ["subtotal", "delivery_fee", "total", "payment", "status", "created"]

    def to_representation(self, o):
        fee = f"incl. {taka(o.delivery_fee)} delivery" if o.delivery_fee else "free delivery"
        return {**super().to_representation(o), "title": f"Order #{o.id}",
                "meta_line": f"{day(o.created)} · {o.city} · {o.get_payment_display()}",
                "total_line": f"Total {taka(o.total)} ({fee})"}

    def validate_phone(self, value):
        # Bengali (or any) decimal digits become ASCII, so one number has one spelling for the cap and the rider.
        value = "".join(str(int(ch)) if ch.isdecimal() else ch for ch in value.replace(" ", "").replace("-", ""))
        if not re.fullmatch(r"(\+?88)?01[3-9][0-9]{8}", value):
            raise serializers.ValidationError("Enter a Bangladeshi mobile number, e.g. 01712345678.")
        return value[-11:]  # one spelling per number, so the per-phone cap can't be dodged with +88

    @transaction.atomic
    def create(self, data):
        expected = data.pop("expected_total")
        user = data["user"]  # None for a guest: no account to lock or cap, the phone cap still applies
        # Lock the buyer and the phone number so parallel checkouts can't both slip under the caps.
        if user:
            User.objects.select_for_update().get(pk=user.pk)
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["order-phone:" + data["phone"]])
        if user and user.orders.filter(status="pending").count() >= settings.MAX_PENDING_ORDERS:
            raise serializers.ValidationError(
                f"You already have {settings.MAX_PENDING_ORDERS} orders waiting for delivery.")
        # The same cap per phone number, across accounts: new accounts are cheap, phones less so.
        if Order.objects.filter(status="pending", phone=data["phone"]).count() >= settings.MAX_PENDING_ORDERS:
            raise serializers.ValidationError(
                {"phone": f"This number already has {settings.MAX_PENDING_ORDERS} orders waiting for delivery."})
        # The order is built from the buyer's session cart. Lock rows so two orders can't oversell.
        cart = Cart(self.context["request"])
        lines = cart.lines(Product.objects.select_for_update())
        if not lines:  # keep the notes: "X sold out" says more than "empty"
            raise serializers.ValidationError({"cart": " ".join([*cart.notes, "Your cart is empty."])})
        subtotal = 0
        for _, p, v, qty in lines:
            if max_qty(p, v) < qty:
                raise serializers.ValidationError({"cart": f"Only {max_qty(p, v)} left of {describe(p, v)}."})
            subtotal += unit_price(p, v) * qty  # price from DB, never from client
        fee = delivery_fee(subtotal)
        if subtotal + fee != expected:  # another tab, a price edit or a stock drop changed the cart
            raise serializers.ValidationError({"cart": " ".join(
                [*cart.notes, "Your cart changed since you opened checkout. Check the new total and place the order again."])})
        order = Order.objects.create(subtotal=subtotal, delivery_fee=fee, total=subtotal + fee, **data)
        for _, p, v, qty in lines:
            OrderItem.objects.create(order=order, product=p, variant=v, name=p.name, price=unit_price(p, v),
                                     quantity=qty, options=v.label if v else "")
            # Variant rows aren't locked (only products are): take its stock only if it is still there.
            if v and not ProductVariant.objects.filter(pk=v.pk, stock__gte=qty).update(stock=F("stock") - qty):
                raise serializers.ValidationError({"cart": f"{describe(p, v)} just sold out. Check your cart and try again."})
            p.stock -= qty  # the product's total, so it stays the sum of its variants
            p.save(update_fields=["stock"])
        return order

import re

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from .cart import Cart, delivery_fee
from .models import MAX_QTY, Category, Order, OrderItem, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "description", "summary", "price", "original_price", "discount",
                  "image", "rating", "reviews", "stock", "category"]


class ProductDetailSerializer(ProductSerializer):
    related = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + ["specs", "stock_level", "max_qty", "related"]

    def get_related(self, p):
        others = Product.objects.select_related("category").filter(category=p.category_id).exclude(pk=p.pk)[:7]
        return ProductSerializer(others, many=True).data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def validate_username(self, value):
        # Usernames stay case-sensitive in Django; block "Rafi" when "rafi" exists so people can't mix them up.
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate(self, attrs):
        # Pass the would-be user so the "too similar to your username/email" check runs.
        validate_password(attrs["password"], User(username=attrs["username"], email=attrs.get("email", "")))
        return attrs

    def create(self, data):
        return User.objects.create_user(**data)


class OrderItemSerializer(serializers.ModelSerializer):
    image = serializers.URLField(source="product.image", read_only=True)
    slug = serializers.SlugField(source="product.slug", read_only=True)

    class Meta:
        model = OrderItem
        fields = ["name", "slug", "image", "price", "quantity"]


class CartLineSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QTY)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_display = serializers.CharField(source="get_payment_display", read_only=True)
    # The total the buyer was shown; the order is refused if the cart has changed since.
    expected_total = serializers.IntegerField(write_only=True, min_value=0)

    class Meta:
        model = Order
        fields = ["id", "full_name", "phone", "address", "city", "subtotal", "delivery_fee", "total",
                  "payment", "payment_display", "status", "status_display", "created", "items", "expected_total"]
        read_only_fields = ["subtotal", "delivery_fee", "total", "payment", "status", "created"]

    def validate_phone(self, value):
        value = value.replace(" ", "").replace("-", "")
        if not re.fullmatch(r"(\+?88)?01[3-9]\d{8}", value):
            raise serializers.ValidationError("Enter a Bangladeshi mobile number, e.g. 01712345678.")
        return value

    @transaction.atomic
    def create(self, data):
        expected = data.pop("expected_total")
        user = data["user"]
        # Lock the buyer so two parallel checkouts can't both slip under the pending-order cap.
        User.objects.select_for_update().get(pk=user.pk)
        if user.orders.filter(status="pending").count() >= settings.MAX_PENDING_ORDERS:
            raise serializers.ValidationError(
                f"You already have {settings.MAX_PENDING_ORDERS} orders waiting for delivery.")
        # The order is built from the buyer's session cart. Lock rows so two orders can't oversell.
        lines = Cart(self.context["request"]).lines(Product.objects.select_for_update())
        if not lines:
            raise serializers.ValidationError({"cart": "Your cart is empty."})
        subtotal = 0
        for p, qty in lines:
            if p.stock < qty:
                raise serializers.ValidationError({"cart": f"Only {p.stock} left of {p.name}."})
            subtotal += p.price * qty  # price from DB, never from client
        fee = delivery_fee(subtotal)
        if subtotal + fee != expected:  # another tab, a price edit or a stock drop changed the cart
            raise serializers.ValidationError(
                {"cart": "Your cart changed since you opened checkout. Check the new total and place the order again."})
        order = Order.objects.create(subtotal=subtotal, delivery_fee=fee, total=subtotal + fee, **data)
        for p, qty in lines:
            OrderItem.objects.create(order=order, product=p, name=p.name, price=p.price, quantity=qty)
            p.stock -= qty
            p.save(update_fields=["stock"])
        return order

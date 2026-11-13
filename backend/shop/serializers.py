import re

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from .models import Category, Order, OrderItem, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "description", "price", "original_price",
                  "image", "rating", "reviews", "stock", "category"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def validate_password(self, value):
        validate_password(value)
        return value

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
    quantity = serializers.IntegerField(min_value=1, max_value=20)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    lines = CartLineSerializer(many=True, write_only=True)

    class Meta:
        model = Order
        fields = ["id", "full_name", "phone", "address", "city", "subtotal", "delivery_fee",
                  "total", "payment", "status", "created", "items", "lines"]
        read_only_fields = ["subtotal", "delivery_fee", "total", "payment", "status", "created"]

    def validate_phone(self, value):
        value = value.replace(" ", "").replace("-", "")
        if not re.fullmatch(r"(\+?88)?01[3-9]\d{8}", value):
            raise serializers.ValidationError("Enter a Bangladeshi mobile number, e.g. 01712345678.")
        return value

    def validate(self, data):
        user = self.context["request"].user
        if user.orders.filter(status="pending").count() >= settings.MAX_PENDING_ORDERS:
            raise serializers.ValidationError(
                f"You already have {settings.MAX_PENDING_ORDERS} orders waiting for delivery.")
        return data

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Cart is empty.")
        ids = [line["product"].pk for line in lines]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Each product may appear once.")
        return lines

    @transaction.atomic
    def create(self, data):
        lines = data.pop("lines")
        # Lock rows so two orders can't oversell the same stock.
        products = Product.objects.select_for_update().in_bulk([l["product"].pk for l in lines])
        subtotal = 0
        for line in lines:
            p = products[line["product"].pk]
            if p.stock < line["quantity"]:
                raise serializers.ValidationError({"lines": f"Only {p.stock} left of {p.name}."})
            subtotal += p.price * line["quantity"]  # price from DB, never from client
        fee = 0 if subtotal >= settings.FREE_DELIVERY_MIN else settings.DELIVERY_FEE
        order = Order.objects.create(subtotal=subtotal, delivery_fee=fee, total=subtotal + fee, **data)
        for line in lines:
            p = products[line["product"].pk]
            OrderItem.objects.create(order=order, product=p, name=p.name, price=p.price, quantity=line["quantity"])
            p.stock -= line["quantity"]
            p.save(update_fields=["stock"])
        return order

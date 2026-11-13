from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, related_name="products", on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)
    price = models.PositiveIntegerField(help_text="Taka")
    original_price = models.PositiveIntegerField(null=True, blank=True, help_text="Before discount")
    image = models.URLField(max_length=500)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=0)
    reviews = models.PositiveIntegerField(default=0)
    stock = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created", "id"]

    def __str__(self):
        return self.name


class Order(models.Model):
    STATUS = [("pending", "Pending"), ("shipped", "Shipped"), ("delivered", "Delivered"), ("cancelled", "Cancelled")]
    # Delivery cities; frontend/src/pages/Checkout.jsx keeps the same list.
    CITIES = [(c, c) for c in ["Dhaka", "Chattogram", "Sylhet", "Khulna", "Rajshahi", "Barishal", "Rangpur", "Mymensingh"]]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="orders", on_delete=models.CASCADE)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    address = models.TextField(max_length=300)
    city = models.CharField(max_length=60, choices=CITIES)
    subtotal = models.PositiveIntegerField()
    delivery_fee = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    payment = models.CharField(max_length=20, default="cod")  # MVP: cash on delivery only
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"Order #{self.pk}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)  # snapshot, survives product edits
    price = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField()

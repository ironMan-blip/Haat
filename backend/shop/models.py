import math

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F

MAX_QTY = 20  # most of one product per cart line or order
LOW_STOCK = 10  # below this the shop says "only N left"


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
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=0,
                                 validators=[MinValueValidator(0), MaxValueValidator(5)])
    reviews = models.PositiveIntegerField(default=0)
    stock = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created", "id"]

    def __str__(self):
        return self.name

    @property
    def discount(self):
        """Percent off the original price, rounded half up."""
        if not self.original_price or self.original_price <= self.price:
            return 0
        return math.floor((1 - self.price / self.original_price) * 100 + 0.5)

    @property
    def max_qty(self):
        return min(self.stock, MAX_QTY)

    @property
    def stock_level(self):
        return "out" if not self.stock else "low" if self.stock < LOW_STOCK else "in"

    @property
    def specs(self):
        return [line.strip() for line in self.description.splitlines() if line.strip()]

    @property
    def summary(self):
        return " · ".join(self.specs[:2]) or self.category.name

    @property
    def rank(self):
        """Best-rated score: many reviews outweigh a few perfect ones."""
        return float(self.rating) * math.log(self.reviews + 2)


class Order(models.Model):
    PAYMENTS = [("cod", "Cash on delivery")]  # MVP: cash on delivery only
    STATUS = [("pending", "Pending"), ("shipped", "Shipped"), ("delivered", "Delivered"), ("cancelled", "Cancelled")]
    # Delivery cities; the checkout form reads them from /api/config/.
    CITIES = [(c, c) for c in ["Dhaka", "Chattogram", "Sylhet", "Khulna", "Rajshahi", "Barishal", "Rangpur", "Mymensingh"]]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="orders", on_delete=models.CASCADE)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    address = models.TextField(max_length=300)
    city = models.CharField(max_length=60, choices=CITIES)
    subtotal = models.PositiveIntegerField()
    delivery_fee = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    payment = models.CharField(max_length=20, choices=PAYMENTS, default="cod")
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"Order #{self.pk}"

    REOPEN_ERROR = {"status": "A cancelled order can't be reopened: its stock is already back on sale."}

    def clean(self):  # friendly form error; save() enforces the same rule under the row lock
        was = Order.objects.filter(pk=self.pk).values_list("status", flat=True).first() if self.pk else None
        if was == "cancelled" and self.status != "cancelled":
            raise ValidationError(self.REOPEN_ERROR)

    def save(self, *args, **kwargs):
        # Cancelling puts the items back in stock, once.
        with transaction.atomic():
            was = Order.objects.select_for_update().filter(pk=self.pk).values_list("status", flat=True).first() \
                if self.pk else None
            if was == "cancelled" and self.status != "cancelled":  # e.g. two admins racing
                raise ValidationError(self.REOPEN_ERROR)
            super().save(*args, **kwargs)
            if self.status == "cancelled" and was not in (None, "cancelled"):
                for item in self.items.all():
                    Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)  # snapshot, survives product edits
    price = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField()

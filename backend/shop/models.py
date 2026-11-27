import itertools
import math
from urllib.parse import parse_qsl, urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

MAX_QTY = 20  # most of one product per cart line or order
LOW_STOCK = 10  # below this the shop says "only N left"
COMMENT_PAGE = 10  # comments, and replies per comment, sent per page
MAX_VARIANTS = 100  # most option combinations per product: each is a row staff must stock and price


def percent_off(price, original):
    """Percent off the original price, rounded half up; 0 when there is no real discount."""
    if not original or original <= price:
        return 0
    return math.floor((1 - price / original) * 100 + 0.5)


def choice_key(chosen):
    """One spelling per set of choices, whatever order they came in: "Color=Blue&Size=M"."""
    return urlencode(sorted(chosen.items()))


def options_error(options):
    """Why options, as (name, choices) pairs, can't be sold as variants, or None. The admin form asks first;
    sync_variants() enforces it. Long or Bengali text (9 characters per letter once URL-encoded) can overflow
    the variant key or the order's snapshot of the choices."""
    if not all(c for _, c in options):  # ProductOption.clean() reports an option without choices
        return None
    if (n := math.prod(len(c) for _, c in options)) > MAX_VARIANTS:
        return (f"These options make {n} combinations; the most is {MAX_VARIANTS}. "
                "Use fewer choices, or sell some as separate products.")
    longest_key = choice_key({name: max(c, key=lambda v: len(choice_key({name: v}))) for name, c in options})
    longest_label = " · ".join(f"{name}: {max(c, key=len)}" for name, c in options)
    if len(longest_key) > ProductVariant._meta.get_field("key").max_length \
            or len(longest_label) > OrderItem._meta.get_field("options").max_length:
        return "These option names and choices are too long to save together. Shorten them or use fewer options."
    return None


def variant_keys(options):
    """The key of every combination of options given as (name, choices) pairs; none without options."""
    names = [name for name, _ in options]
    return {choice_key(dict(zip(names, combo))) for combo in itertools.product(*(c for _, c in options))} \
        if options else set()


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
    price = models.PositiveIntegerField(help_text="Taka", validators=[MinValueValidator(1)])  # ৳0 = free order + free delivery
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
        return percent_off(self.price, self.original_price)

    @property
    def price_range(self):
        """Lowest and highest price a buyer can pay: variants may cost more or less. Prefetch variants for lists."""
        prices = [v.price or self.price for v in self.variants.all()] or [self.price]
        return min(prices), max(prices)

    @property
    def max_qty(self):
        return min(self.stock, MAX_QTY)

    @property
    def stock_level(self):
        return "out" if not self.stock else "low" if self.stock < LOW_STOCK else "in"

    @property
    def stock_label(self):
        return {"out": "Sold out", "low": f"Only {self.stock} left", "in": "In stock"}[self.stock_level]

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

    def clean(self):
        # A product with options sells its variants; its stock is their total, kept by sync_stock().
        # Refuse only an edited number: a stored total that is already wrong is fixed on save, not a reason to refuse.
        if self.pk and self.variants.exists() and self.stock != Product.objects.get(pk=self.pk).stock:
            total = self.variants.aggregate(s=Sum("stock"))["s"]
            if self.stock != total:
                raise ValidationError({"stock": f"This product's stock is the total of its option combinations "
                                                f"({total}). Change it on the product page, per combination."})

    def sync_stock(self):
        """Stock of a product with variants = their total. Checkout holds the product's row lock while it takes
        variant stock, so wait for that lock first: the total is then summed after any running order commits."""
        if self.variants.exists():
            with transaction.atomic():
                list(Product.objects.select_for_update().filter(pk=self.pk).values_list("pk", flat=True))
                total = ProductVariant.objects.filter(product=OuterRef("pk")).values("product").annotate(s=Sum("stock")).values("s")
                Product.objects.filter(pk=self.pk).update(stock=Coalesce(Subquery(total), 0))
            self.refresh_from_db(fields=["stock"])

    def sync_variants(self, stock=0):
        """One variant per combination of option choices: adds missing ones with `stock`, drops ones no longer
        possible, then re-totals stock. Returns how many were added."""
        options = [(o.name, o.choices) for o in self.options.all()]
        if error := options_error(options):
            raise ValidationError(error)
        keys = variant_keys(options)
        self.variants.exclude(key__in=keys).delete()
        new = keys - set(self.variants.values_list("key", flat=True))
        ProductVariant.objects.bulk_create(ProductVariant(product=self, key=k, stock=stock) for k in new)
        self.sync_stock()
        return len(new)


class ProductImage(models.Model):
    """Extra photos on the product page; Product.image stays the main photo used everywhere else."""
    product = models.ForeignKey(Product, related_name="photos", on_delete=models.CASCADE)
    url = models.URLField(max_length=500)
    position = models.PositiveSmallIntegerField(default=0, help_text="Lower shows first")

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.url


class ProductOption(models.Model):
    """A choice the buyer must make when ordering, e.g. Size: S, M, L or Color: Black, Blue.
    Each combination of choices is a ProductVariant with its own stock and price."""
    product = models.ForeignKey(Product, related_name="options", on_delete=models.CASCADE)
    name = models.CharField(max_length=40, help_text="e.g. Size or Color")
    values = models.CharField(max_length=300, help_text="Comma-separated, e.g. S, M, L, XL")
    position = models.PositiveSmallIntegerField(default=0, help_text="Lower shows first")

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(fields=["product", "name"], name="unique_option_name")]

    def __str__(self):
        return f"{self.name}: {self.values}"

    @property
    def choices(self):
        return list(dict.fromkeys(v.strip() for v in self.values.split(",") if v.strip()))

    def clean(self):
        if not self.choices:
            raise ValidationError({"values": "List at least one choice."})


class ProductVariant(models.Model):
    """One combination of option choices (e.g. Size M, Color Blue), with its own stock and, if it differs,
    its own price. Made by Product.sync_variants() whenever the options change; staff set stock and price."""
    product = models.ForeignKey(Product, related_name="variants", on_delete=models.CASCADE)
    key = models.CharField(max_length=500, editable=False)  # choice_key() of its choices
    price = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)],
                                        help_text="Taka. Blank: the product's price")
    stock = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["product", "key"], name="unique_variant")]

    def __str__(self):
        return f"{self.product} ({self.label})"

    @property
    def choices(self):
        return dict(parse_qsl(self.key))

    @property
    def label(self):
        """"Size: M · Color: Blue", in the product's option order."""
        chosen = self.choices
        return " · ".join(f"{o.name}: {chosen[o.name]}" for o in self.product.options.all() if o.name in chosen)

    @property
    def unit_price(self):
        return self.price or self.product.price

    @property
    def max_qty(self):
        return min(self.stock, MAX_QTY)


class Comment(models.Model):
    """A signed-in customer's comment on a product page; staff remove abuse in the admin."""
    product = models.ForeignKey(Product, related_name="comments", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="comments", on_delete=models.CASCADE)
    parent = models.ForeignKey("self", related_name="replies", on_delete=models.CASCADE, null=True, blank=True,
                               help_text="Set on replies; replies are one level deep")
    text = models.TextField(max_length=1000, blank=True)  # blank only once deleted
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="liked_comments", blank=True)
    edited = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False, help_text="Kept as a placeholder so its replies stay")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return f"{self.user} on {self.product}"


class Order(models.Model):
    PAYMENTS = [("cod", "Cash on delivery")]  # MVP: cash on delivery only
    STATUS = [("pending", "Pending"), ("shipped", "Shipped"), ("delivered", "Delivered"), ("cancelled", "Cancelled")]
    # Delivery cities; the checkout form reads them from /api/config/.
    CITIES = [(c, c) for c in ["Dhaka", "Chattogram", "Sylhet", "Khulna", "Rajshahi", "Barishal", "Rangpur", "Mymensingh"]]

    # Empty for guest orders; those are found only through the session that placed them.
    # SET_NULL: deleting a user must not delete their orders (and the stock they took) with them.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="orders", on_delete=models.SET_NULL,
                             null=True, blank=True)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    email = models.EmailField(max_length=254, blank=True)  # optional; lets a guest order join the account with this email
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
    UNSHIP_ERROR = {"status": "A shipped order can't go back to pending: its goods have left the shelf."}

    def refusal(self, was):
        """Why the status can't change from `was`, or None. Only pending -> cancelled restocks, so an order
        must never re-enter pending: shipped -> pending -> cancelled would restock goods already sent."""
        if was == "cancelled" and self.status != "cancelled":
            return self.REOPEN_ERROR
        if was in ("shipped", "delivered") and self.status == "pending":
            return self.UNSHIP_ERROR
        return None

    def clean(self):  # friendly form error; save() enforces the same rule under the row lock
        was = Order.objects.filter(pk=self.pk).values_list("status", flat=True).first() if self.pk else None
        if error := self.refusal(was):
            raise ValidationError(error)

    def save(self, *args, **kwargs):
        # Cancelling a pending order puts its items back in stock, once; shipped goods are not on the shelf.
        with transaction.atomic():
            was = Order.objects.select_for_update().filter(pk=self.pk).values_list("status", flat=True).first() \
                if self.pk else None
            if error := self.refusal(was):  # e.g. two admins racing
                raise ValidationError(error)
            super().save(*args, **kwargs)
            if self.status == "cancelled" and was == "pending":
                for item in self.items.all():
                    if item.variant_id:
                        ProductVariant.objects.filter(pk=item.variant_id).update(stock=F("stock") + item.quantity)
                    elif ProductVariant.objects.filter(product_id=item.product_id).exists():
                        continue  # its variant was removed: the product's stock is its other variants' total
                    Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)  # snapshot, survives product edits
    price = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField()
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL)
    options = models.CharField(max_length=300, blank=True)  # snapshot of the buyer's choices, e.g. "Size: M · Color: Blue"

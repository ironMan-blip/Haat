import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from shop.cart import delivery_fee
from shop.models import Comment, Order, OrderItem, Product, ProductVariant

PASSWORD = "haat-demo-2026"  # every demo_* account; local testing only
NAMES = ["buyer", "rahim", "karim", "nusrat", "tanvir", "farzana", "sabbir", "jannat", "arif",
         "mitu", "rakib", "sumaiya", "hasan", "tania", "fahim"]
STREETS = ["House 12, Road 5, Dhanmondi", "Flat 3B, Mirpur DOHS", "22 Agrabad C/A", "Zindabazar, Lane 4",
           "Sonadanga R/A, Block C", "Shaheb Bazar, Ward 9", "Band Road, House 7", "Jail Road, Flat 2A"]
LINES = ["Got it in 2 days, works fine.", "Is this original?", "Packaging was damaged but product ok.",
         "Size runs small, order one up.", "Worth the price.", "Color looks different from the photo.",
         "Does it come with warranty?", "Second time buying, still happy.", "Delivery to Sylhet took a week.",
         "Battery lasts about a day.", "Seller replied fast.", "Not as described, returned it.",
         "Good quality for this price range.", "Any discount for 3 pieces?", "Stitching came loose after a month."]
REPLIES = ["Same here.", "Thanks, that helps.", "Mine was fine.", "Yes, 6 months warranty.",
           "Agree", "Which color did you get?", "Contact support, they fixed mine."]


class Command(BaseCommand):
    help = (f"Fill the database with demo users, orders in every status, guest orders to claim, comment threads "
            f"and low/out-of-stock products. Run after `seed`. demo_* accounts use the password {PASSWORD!r}.")

    def add_arguments(self, parser):
        parser.add_argument("--orders", type=int, default=6, help="orders per demo user (default 6)")
        parser.add_argument("--comments", type=int, default=5, help="top-level comments per product (default 5)")

    @transaction.atomic
    def handle(self, orders, comments, **opts):
        if not settings.DEBUG:  # fake accounts with a known password must never reach a real shop
            raise SystemExit("demo_data runs only with DJANGO_DEBUG=1.")
        if not Product.objects.exists():
            call_command("seed")
        rnd = random.Random()
        users = []
        for n in NAMES:
            u, _ = User.objects.get_or_create(username=f"demo_{n}", defaults={"email": f"demo_{n}@example.com",
                                                                               "first_name": n.title()})
            u.set_password(PASSWORD)
            u.save()
            users.append(u)

        made = sum(self.order(rnd, u, i) for u in users[:-3] for i in range(orders))  # last 3: accounts with no orders
        # Guest orders: some carry a demo user's email, so logging in as that user sends a claim link (console mail).
        for u in users[-6:]:
            made += self.order(rnd, None, 0, email=u.email) + self.order(rnd, None, 1)

        products = list(Product.objects.all())
        new = 0
        for p in products:
            for _ in range(comments):
                c = Comment.objects.create(product=p, user=rnd.choice(users), text=rnd.choice(LINES),
                                           edited=rnd.random() < .15)
                c.likes.set(rnd.sample(users, rnd.randint(0, 8)))
                for _ in range(rnd.choice([0, 0, 1, 2, 4, 12])):  # 12 > a page of replies
                    Comment.objects.create(product=p, user=rnd.choice(users), parent=c, text=rnd.choice(REPLIES))
                if rnd.random() < .05:  # deleted parent stays as a placeholder for its replies
                    Comment.objects.filter(pk=c.pk).update(deleted=True, text="")
                new += 1

        # Stock edge cases on products without options (with options, stock is the variants' total).
        plain = [p for p in products if not p.variants.exists()]
        for p, stock in zip(rnd.sample(plain, min(4, len(plain))), [0, 0, 3, 7]):
            Product.objects.filter(pk=p.pk).update(stock=stock)

        self.stdout.write(self.style.SUCCESS(
            f"{len(users)} demo users, {made} orders, {new} comment threads, 2 sold out + 2 low-stock products"))

    def order(self, rnd, user, i, email=""):
        """One order built like checkout's: stock taken, prices from the DB. Returns 1 if made, 0 if nothing left."""
        lines = []
        for p in Product.objects.filter(stock__gt=0).order_by("?")[:rnd.randint(1, 4)]:
            v = p.variants.filter(stock__gt=0).order_by("?").first() if p.variants.exists() else None
            if p.variants.exists() and not v:
                continue
            lines.append((p, v, rnd.randint(1, min(3, (v or p).stock))))
        if not lines:
            return 0
        subtotal = sum((v.unit_price if v else p.price) * q for p, v, q in lines)
        fee = delivery_fee(subtotal)
        name = user.first_name if user else rnd.choice(["Guest Shopper", "Rina Akter", "Jamal Uddin"])
        # One phone per buyer, as in real life; the pending cap (MAX_PENDING_ORDERS) is per phone.
        phone = f"017{(user.pk if user else rnd.randint(1000, 9999)):08d}"
        order = Order.objects.create(user=user, full_name=name, phone=phone, email=email or (user.email if user else ""),
                                     address=rnd.choice(STREETS), city=rnd.choice(Order.CITIES)[0],
                                     subtotal=subtotal, delivery_fee=fee, total=subtotal + fee)
        for p, v, q in lines:
            OrderItem.objects.create(order=order, product=p, variant=v, name=p.name,
                                     price=v.unit_price if v else p.price, quantity=q, options=v.label if v else "")
            if v:
                ProductVariant.objects.filter(pk=v.pk).update(stock=F("stock") - q)
            Product.objects.filter(pk=p.pk).update(stock=F("stock") - q)
        # Statuses by age: newest pending, older shipped/delivered, some cancelled (save() restocks those).
        status = ["pending", "pending", "shipped", "delivered", "cancelled", "delivered"][i % 6]
        if status == "cancelled":
            order.status = "cancelled"
            order.save()
        elif status != "pending":
            Order.objects.filter(pk=order.pk).update(status=status)
        Order.objects.filter(pk=order.pk).update(created=timezone.now() - timedelta(days=i * 4, hours=rnd.randint(0, 23)))
        return 1

import io
from datetime import timedelta
from unittest import mock

from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from .admin import change
from .cart import MAX_LINES
from .display import cdn, day, num, taka
from .models import Category, Comment, Order, Product, ProductImage, ProductVariant, StaffInvite
from .serializers import RegisterSerializer
from .api.accounts import SignupThrottle
from .auth import CommentActionThrottle, GuestOrderThrottle, ScopedThrottle

ADDR = {"full_name": "Rahim", "phone": "01712345678", "address": "House 1, Road 2", "city": "Dhaka"}


class ShopApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters live in the cache
        cat = Category.objects.create(name="Mobiles", slug="mobiles")
        self.phone = Product.objects.create(category=cat, name="Phone", slug="phone", price=15000, image="https://x.y/a.jpg", stock=3)
        self.case = Product.objects.create(category=cat, name="Case", slug="case", price=100, image="https://x.y/b.jpg", stock=10)
        self.user = User.objects.create_user("rahim", password="pass-1234-word")
        self.client.force_authenticate(self.user)

    def add(self, product, qty):
        return self.client.post("/api/cart/", {"product": product.pk, "quantity": qty}, format="json")

    def checkout(self, **addr):
        """Place an order for the total the cart shows right now, as the checkout page does."""
        total = self.client.get("/api/cart/").data["total"]
        return self.client.post("/api/orders/", {**ADDR, "expected_total": total, **addr}, format="json")

    def order(self, *lines, **addr):
        for p, q in lines:
            self.add(p, q)
        return self.checkout(**addr)

    def test_order_uses_db_prices_decrements_stock_and_empties_cart(self):
        self.client.post("/api/cart/", {"product": self.phone.pk, "quantity": 2, "price": 1}, format="json")
        r = self.checkout()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["subtotal"], r.data["delivery_fee"], r.data["total"]), (30000, 0, 30000))
        self.assertEqual((r.data["status_display"], r.data["payment"]), ("Pending", "cod"))
        self.phone.refresh_from_db()
        self.assertEqual(self.phone.stock, 1)
        self.assertEqual(self.client.get("/api/cart/").data["lines"], [])

    def test_delivery_fee_below_threshold(self):
        r = self.order((self.case, 2))
        self.assertEqual((r.data["subtotal"], r.data["delivery_fee"], r.data["total"]), (200, 60, 260))

    def test_oversell_rejected_and_nothing_saved(self):
        self.add(self.case, 1)
        self.add(self.phone, 3)
        shown = self.client.get("/api/cart/").data["total"]
        Product.objects.filter(pk=self.phone.pk).update(stock=2)  # someone else bought one meanwhile
        r = self.client.post("/api/orders/", {**ADDR, "expected_total": shown}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cart", r.data)
        self.assertEqual(Order.objects.count(), 0)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 10)
        self.assertEqual(self.client.get("/api/cart/").data["lines"][1]["quantity"], 2)  # cart lowered to stock

    def test_order_refused_when_cart_changed_after_checkout_opened(self):
        self.add(self.case, 1)
        shown = self.client.get("/api/cart/").data["total"]
        self.add(self.phone, 1)  # another tab
        r = self.client.post("/api/orders/", {**ADDR, "expected_total": shown}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cart", r.data)
        self.assertEqual(Order.objects.count(), 0)

    def test_cart_drops_sold_out_and_lowers_to_stock_with_notice(self):
        self.add(self.case, 5)
        self.add(self.phone, 3)
        Product.objects.filter(pk=self.case.pk).update(stock=0)
        Product.objects.filter(pk=self.phone.pk).update(stock=1)
        c = self.client.get("/api/cart/").data
        self.assertEqual([(l["slug"], l["quantity"]) for l in c["lines"]], [("phone", 1)])
        self.assertIn("Case sold out", c["notice"])
        self.assertIsNone(self.client.get("/api/cart/").data["notice"])  # said once, then fixed

    def test_cancelling_restores_stock_once_and_cannot_reopen(self):
        from django.core.exceptions import ValidationError
        self.order((self.case, 4))
        o = Order.objects.get()
        o.status = "cancelled"
        o.save()
        o.save()  # saving again must not add stock twice
        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 10)
        o.status = "pending"
        with self.assertRaises(ValidationError):
            o.full_clean()

    def test_cancelling_shipped_order_does_not_restock(self):
        self.order((self.case, 4))
        o = Order.objects.get()
        o.status = "delivered"
        o.save()
        o.status = "cancelled"
        o.save()
        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 6)  # the goods are with the buyer, not on the shelf

    def test_shipped_order_cannot_go_back_to_pending_and_restock(self):
        self.order((self.case, 4))
        o = Order.objects.get()
        o.status = "shipped"
        o.save()
        o.status = "pending"
        with self.assertRaises(DjangoValidationError):
            o.full_clean()
        with self.assertRaises(DjangoValidationError):
            o.save()  # enforced without clean() too, e.g. the bulk actions
        o.status = "cancelled"
        o.save()
        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 6)

    def test_patch_on_removed_line_does_not_bring_it_back(self):
        self.add(self.case, 1)
        self.client.delete(f"/api/cart/{self.case.pk}/")
        r = self.client.patch(f"/api/cart/{self.case.pk}/", {"quantity": 2}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.get("/api/cart/").data["lines"], [])

    def test_blank_search_is_no_search(self):
        r = self.client.get("/api/products/", {"q": "   "})
        self.assertEqual((r.data["title"], len(r.data["results"])), ("Every product", 2))

    def test_checkout_mismatch_says_what_changed(self):
        self.add(self.phone, 3)
        shown = self.client.get("/api/cart/").data["total"]
        Product.objects.filter(pk=self.phone.pk).update(stock=2)
        r = self.client.post("/api/orders/", {**ADDR, "expected_total": shown}, format="json")
        self.assertIn("Only 2 of Phone left", r.data["message"])

    def test_issue_token_survives_parallel_refresh(self):
        from .auth import issue_token
        stale = Token(key="stale", user=self.user, created=timezone.now() - timedelta(days=365))
        fresh = Token.objects.create(user=self.user)  # the other login already replaced it
        real = Token.objects.get_or_create
        calls = iter([lambda **kw: (stale, False), real])
        with mock.patch("shop.auth.Token.objects.get_or_create", side_effect=lambda **kw: next(calls)(**kw)):
            self.assertEqual(issue_token(self.user), fresh)

    def test_logout_with_stale_token_still_empties_cart(self):
        self.client.force_authenticate(None)
        self.add(self.case, 1)
        self.client.credentials(HTTP_AUTHORIZATION="Token stale")
        self.assertEqual(self.client.get("/api/orders/").data["message"], "You were signed out. Please log in again.")
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.client.credentials()
        self.assertEqual(self.client.get("/api/cart/").data["count"], 0)

    def test_register_blocks_case_twin_and_username_like_password(self):
        self.client.force_authenticate(None)
        r = self.client.post("/api/auth/register/", {"username": "Rahim", "password": "pass-1234-word"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("username", r.data)
        r = self.client.post("/api/auth/register/", {"username": "shopkeeper77", "password": "shopkeeper77"})
        self.assertEqual(r.status_code, 400)

    def test_bad_phone_rejected(self):
        r = self.order((self.case, 1), phone="12345")
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.data)

    def test_empty_cart_rejected(self):
        r = self.checkout()
        self.assertEqual(r.status_code, 400)
        self.assertIn("cart", r.data)

    def shirt(self):
        shirt = Product.objects.create(category=self.phone.category, name="Shirt", slug="shirt", price=500,
                                       image="https://x.y/c.jpg")
        shirt.options.create(name="Size", values="S, M", position=0)
        shirt.options.create(name="Color", values="Red, Blue / Navy", position=1)
        self.assertEqual(shirt.sync_variants(stock=2), 4)
        return shirt

    def test_option_text_too_long_to_store_is_refused_and_long_choices_still_sell(self):
        p = Product.objects.create(category=self.phone.category, name="Kurta", slug="kurta", price=500,
                                   image="https://x.y/d.jpg")
        # Bengali is 9 characters per letter once URL-encoded: these overflowed the variant key.
        p.options.create(name="সাইজ বাছাই করুন", values="অতিরিক্ত বড় মাপের", position=0)
        p.options.create(name="রঙ বাছাই করুন", values="গাঢ় নীল রঙের জামা", position=1)
        with self.assertRaisesMessage(DjangoValidationError, "too long"):
            p.sync_variants()
        p.options.all().delete()
        p.options.create(name="Size", values="X" * 150)  # fits the order snapshot, so the cart takes it
        p.sync_variants(stock=2)
        r = self.client.post("/api/cart/", {"product": p.pk, "quantity": 1, "options": {"Size": "X" * 150}}, format="json")
        self.assertEqual(r.status_code, 200)
        total = self.client.get("/api/cart/").data["total"]
        self.assertEqual(self.client.post("/api/orders/", {**ADDR, "expected_total": total}, format="json").status_code, 201)

    def test_product_options_pick_a_variant_with_its_own_stock_and_price(self):
        from urllib.parse import quote
        shirt = self.shirt()
        self.assertEqual(shirt.stock, 8)  # the total of its 4 combinations
        m_red = shirt.variants.get(key="Color=Red&Size=M")
        m_red.price, m_red.stock = 650, 3
        m_red.save()
        shirt.sync_stock()
        d = self.client.get("/api/products/shirt/").data
        self.assertEqual(d["options"], [{"name": "Size", "values": ["S", "M"]}, {"name": "Color", "values": ["Red", "Blue / Navy"]}])
        self.assertEqual({v["price_display"] for v in d["variants"] if v["choices"] == {"Size": "M", "Color": "Red"}}, {taka(650)})
        post = lambda opts, q=1: self.client.post("/api/cart/", {"product": shirt.pk, "quantity": q, "options": opts}, format="json")
        self.assertEqual(self.add(shirt, 1).status_code, 400)  # nothing picked
        self.assertEqual(post({"Size": "XL", "Color": "Red"}).status_code, 400)
        self.assertEqual(post({"Size": "S", "Color": "Red", "Fit": "Slim"}).status_code, 400)
        post({"Size": "M", "Color": "Red"}, 3)
        c = post({"Size": "S", "Color": "Blue / Navy"}, 5).data  # that combination has 2
        self.assertEqual([(l["options_line"], l["quantity"], l["each_line"]) for l in c["lines"]],
                         [("Size: M · Color: Red", 3, f"{taka(650)} each"), ("Size: S · Color: Blue / Navy", 2, f"{taka(500)} each")])
        self.assertIn("Only 2 of Shirt (Size: S · Color: Blue / Navy)", c["notice"])
        blue = c["lines"][1]["id"]
        self.assertEqual(self.client.patch(f"/api/cart/{quote(blue, safe='')}/", {"quantity": 1}, format="json").status_code, 200)
        r = self.checkout()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["subtotal"], 3 * 650 + 500)
        self.assertEqual(sorted(i["options"] for i in r.data["items"]), ["Size: M · Color: Red", "Size: S · Color: Blue / Navy"])
        shirt.refresh_from_db()
        self.assertEqual((shirt.stock, shirt.variants.get(pk=m_red.pk).stock), (5, 0))
        self.assertEqual(post({"Size": "M", "Color": "Red"}).status_code, 400)  # that combination sold out
        # Cancelling puts stock back on the variants it came from, and the product total follows.
        order = Order.objects.get(pk=r.data["id"])
        order.status = "cancelled"
        order.save()
        shirt.refresh_from_db()
        self.assertEqual((shirt.stock, shirt.variants.get(pk=m_red.pk).stock), (9, 3))
        # Staff drop a choice someone has in their cart: the line goes, with a note.
        post({"Size": "M", "Color": "Red"})
        shirt.options.filter(name="Color").update(values="Blue / Navy")
        shirt.sync_variants()
        self.assertEqual(shirt.variants.count(), 2)
        c = self.client.get("/api/cart/").data
        self.assertEqual(c["lines"], [])
        self.assertIn("choices for Shirt changed", c["notice"])

    def test_stock_of_a_product_with_options_is_not_edited_directly(self):
        shirt = self.shirt()
        shirt.stock = 50
        with self.assertRaises(DjangoValidationError):
            shirt.full_clean()

    def test_seed_keeps_options_staff_edited(self):
        call_command("seed", stdout=io.StringIO())
        p = Product.objects.filter(options__name="Size").first()
        p.options.filter(name="Size").update(values="Free size")
        p.sync_variants()
        edited = list(p.options.values_list("name", "values"))
        call_command("seed", stdout=io.StringIO())
        self.assertEqual(list(p.options.values_list("name", "values")), edited)
        p.refresh_from_db()
        self.assertEqual(p.stock, sum(p.variants.values_list("stock", flat=True)))
        # Choices that cost more get their own price, and a reworded title keeps its old slug (links, orders).
        phone = Product.objects.get(slug="realme-note-80-464-6300mah-battery-official-warranty-1")
        self.assertEqual(phone.name, "realme Note 80 | 6300mAh Battery | Official Warranty")
        prices = {v.label: v.unit_price for v in phone.variants.all()}
        self.assertEqual(prices["Storage: 4GB + 64GB · Color: Storm Black"], phone.price)
        self.assertEqual(prices["Storage: 4GB + 128GB · Color: Storm Black"], phone.price + 2000)

    def test_tiles_show_from_price_and_sort_by_it(self):
        shirt = self.shirt()
        shirt.variants.update(price=90)  # every combination costs less than the product's 500
        shirt.variants.filter(key="Color=Red&Size=M").update(price=700)
        tile = next(t for t in self.client.get("/api/products/").data["results"] if t["slug"] == "shirt")
        self.assertEqual(tile["price_display"], f"From {taka(90)}")
        cheapest = self.client.get("/api/products/?sort=price").data["results"][0]
        self.assertEqual(cheapest["slug"], "shirt")

    def test_cart_totals_meter_and_clamping(self):
        self.client.force_authenticate(None)  # guests can use the cart
        c = self.add(self.case, 2).data
        self.assertEqual((c["subtotal"], c["delivery_fee"], c["total"], c["count"]), (200, 60, 260, 2))
        self.assertEqual(c["free_delivery_progress"], 67)
        self.assertEqual(c["lines"][0]["line_total_display"], "৳200")
        c = self.add(self.phone, 5).data  # only 3 in stock
        self.assertEqual(c["lines"][1]["quantity"], 3)
        self.assertIn("Only 3", c["notice"])
        c = self.client.patch(f"/api/cart/{self.case.pk}/", {"quantity": 1}, format="json").data
        self.assertEqual(c["lines"][0]["quantity"], 1)
        c = self.client.delete(f"/api/cart/{self.phone.pk}/").data
        self.assertEqual(c["count"], 1)
        self.client.delete(f"/api/cart/{self.case.pk}/")
        self.assertEqual(self.client.get("/api/cart/").data["delivery_fee"], 0)  # empty cart owes nothing

    def test_sold_out_cannot_be_added(self):
        Product.objects.filter(pk=self.case.pk).update(stock=0)
        r = self.add(self.case, 1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("product", r.data)

    def test_orders_are_private(self):
        self.order((self.case, 1))
        other = User.objects.create_user("karim", password="pass-1234-word")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get("/api/orders/").data, [])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/orders/").data, [])  # a guest session sees no account's orders

    def test_register_then_login(self):
        self.client.force_authenticate(None)
        r = self.client.post("/api/auth/register/", {"username": "new", "email": "n@x.com", "password": "pass-1234-word"})
        self.assertEqual(r.status_code, 201)
        r = self.client.post("/api/auth/login/", {"username": "new", "password": "pass-1234-word"})
        self.assertIn("token", r.data)

    def test_login_by_email(self):
        self.client.force_authenticate(None)
        self.client.post("/api/auth/register/", {"username": "mail", "email": "mail@x.com", "password": "pass-1234-word"})
        r = self.client.post("/api/auth/login/", {"username": "MAIL@x.com", "password": "pass-1234-word"})
        self.assertEqual(r.data["username"], "mail")
        r = self.client.post("/api/auth/login/", {"username": "mail@x.com", "password": "wrong"})
        self.assertEqual(r.status_code, 400)

    def test_register_requires_unique_email(self):
        self.client.force_authenticate(None)
        r = self.client.post("/api/auth/register/", {"username": "noemail", "password": "pass-1234-word"})
        self.assertIn("email", r.data)
        r = self.client.post("/api/auth/register/", {"username": "first", "email": "Same@x.com", "password": "pass-1234-word"})
        self.assertEqual(r.status_code, 201)
        r = self.client.post("/api/auth/register/", {"username": "second", "email": "same@X.com", "password": "pass-1234-word"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("third", email="SAME@x.com")

    def test_bad_city_and_long_address_rejected(self):
        r = self.order((self.case, 1), city="Atlantis", address="x" * 301)
        self.assertEqual(r.status_code, 400)
        self.assertIn("city", r.data)
        self.assertIn("address", r.data)

    def test_pending_orders_capped(self):
        for _ in range(5):
            self.assertEqual(self.order((self.case, 1)).status_code, 201)
        r = self.order((self.case, 1))
        self.assertEqual(r.status_code, 400)
        Order.objects.update(status="shipped")  # shipped orders no longer count
        self.assertEqual(self.order((self.case, 1)).status_code, 201)

    def test_logout_revokes_token(self):
        self.client.force_authenticate(None)
        r = self.client.post("/api/auth/login/", {"username": "rahim", "password": "pass-1234-word"})
        self.assertEqual(r.data["username"], "rahim")
        token = r.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/orders/").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/orders/").status_code, 401)

    def test_login_is_throttled(self):
        self.client.force_authenticate(None)
        codes = [self.client.post("/api/auth/login/", {"username": "rahim", "password": "wrong"}).status_code
                 for _ in range(6)]
        self.assertEqual(codes, [400] * 5 + [429])

    def test_spoofed_forwarded_for_does_not_dodge_throttle(self):
        self.client.force_authenticate(None)
        codes = [self.client.post("/api/auth/login/", {"username": "rahim", "password": "wrong"},
                                  HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code for i in range(6)]
        self.assertEqual(codes[-1], 429)

    def test_product_filters(self):
        r = self.client.get("/api/products/?q=case").data
        self.assertEqual((len(r["results"]), r["title"], r["count_label"]), (1, "Results for “case”", "1 item"))
        r = self.client.get("/api/products/?category=mobiles").data
        self.assertEqual((len(r["results"]), r["title"]), (2, "Mobiles"))
        self.assertEqual(self.client.get("/api/products/?sort=price").data["results"][0]["slug"], "case")
        r = self.client.get("/api/products/?category=nope").data
        self.assertEqual((r["results"], r["title"]), ([], "Category not found"))

    def test_errors_carry_one_message(self):
        r = self.client.post("/api/cart/", {"product": 999999, "quantity": 1})
        self.assertIn("product", r.data)
        self.assertIsInstance(r.data["message"], str)
        r = self.client.post("/api/auth/login/", {"username": "rahim", "password": "wrong"})
        self.assertEqual(r.data["message"], r.data["non_field_errors"][0])

    def test_login_next_stays_on_site(self):
        nexts = [self.client.post("/api/auth/login/", {"username": "rahim", "password": "pass-1234-word", "next": n}
                                  ).data["next"] for n in ["/checkout", "//evil.com", "/\\evil.com", "https://evil.com", ""]]
        self.assertEqual(nexts, ["/checkout", "/", "/", "/", "/"])

    def test_product_derived_fields(self):
        Product.objects.filter(pk=self.phone.pk).update(original_price=20000, description="6GB RAM\n\n128GB\n5000mAh")
        p = self.client.get("/api/products/phone/").data
        self.assertEqual((p["discount"], p["stock_level"], p["stock_label"], p["max_qty"]), (25, "low", "Only 3 left", 3))
        self.assertEqual(p["specs"], ["6GB RAM", "128GB", "5000mAh"])
        self.assertEqual(p["summary"], "6GB RAM · 128GB")
        self.assertEqual([r["slug"] for r in p["related"]], ["case"])
        self.assertEqual(p["category"]["slug"], "mobiles")
        self.assertEqual(p["related_title"], f"More in {self.phone.category.name}")
        cats = self.client.get("/api/products/?category=mobiles").data["categories"]
        self.assertEqual([(c["slug"], c["current"]) for c in cats], [("", False), ("mobiles", True)])  # "All" first
        # List payloads carry tiles only: no long description or nested category per product.
        tile = self.client.get("/api/products/").data["results"][0]
        self.assertFalse({"description", "category"} & tile.keys())

    def test_product_gallery(self):
        # Main image first, then extra photos by position; one photo means a one-item gallery.
        self.assertEqual([g["image_large"] for g in self.client.get("/api/products/phone/").data["gallery"]],
                         ["https://x.y/a.jpg"])
        ProductImage.objects.create(product=self.phone, url="https://x.y/late.jpg", position=2)
        ProductImage.objects.create(product=self.phone, url="https://x.y/early.jpg", position=1)
        g = self.client.get("/api/products/phone/").data["gallery"]
        self.assertEqual([x["image_large"] for x in g], ["https://x.y/a.jpg", "https://x.y/early.jpg", "https://x.y/late.jpg"])
        self.assertEqual(g[1]["alt"], "Phone, photo 2 of 3")

    def test_home_sections(self):
        other = Category.objects.create(name="Rice", slug="rice")
        Product.objects.create(category=other, name="Rice", slug="rice", price=500, original_price=1000,
                               image="https://x.y/c.jpg", rating=4.5, reviews=100, stock=5)
        Product.objects.filter(pk=self.case.pk).update(rating=5, reviews=10)
        Product.objects.create(category=other, name="Gone", slug="gone", price=1, original_price=100,
                               image="https://x.y/d.jpg", stock=0)
        h = self.client.get("/api/home/").data
        self.assertEqual(h["deals"][0]["slug"], "rice")  # the sold-out 99% deal is skipped
        self.assertEqual([p["slug"] for p in h["best"]], ["rice", "case"])  # one per category
        self.assertEqual({m["slug"]: m["count_label"] for m in h["menu"]}, {"mobiles": "2 items", "rice": "2 items"})

    def test_server_writes_every_display_string(self):
        self.assertEqual((num(999), num(1234), num(1234567), taka(0), taka(None)), ("999", "1,234", "12,34,567", "৳0", "৳0"))
        self.assertEqual(cdn("https://x.slatic.net/a.jpg", 200), "https://x.slatic.net/a.jpg_200x200q75.jpg")
        self.assertEqual(cdn("https://x.y/a.jpg", 200), "https://x.y/a.jpg")
        Product.objects.filter(pk=self.phone.pk).update(original_price=20000, reviews=12345, rating=4.5)
        p = self.client.get("/api/products/phone/").data
        self.assertEqual((p["price_display"], p["original_price_display"], p["badge"]), ("৳15,000", "৳20,000", "−25%"))
        self.assertEqual((p["reviews_display"], p["rating_label"]), ("12,345", "Rated 4.5 out of 5 by 12,345 buyers"))
        self.assertIsNone(self.client.get("/api/products/case/").data["rating_label"])  # no reviews, no rating line
        c = self.add(self.case, 2).data
        self.assertEqual((c["total_display"], c["delivery_display"], c["meter"]),
                         ("৳260", "৳60", "Add ৳99 more for free delivery."))
        self.assertEqual(c["lines"][0]["each_line"], "৳100 each")
        self.assertEqual(c["count_label"], "Cart, 2 items")
        o = self.checkout().data
        self.assertEqual(o["total_line"], "Total ৳260 (incl. ৳60 delivery)")
        self.assertEqual((o["title"], o["items"][0]["qty_line"]), (f"Order #{o['id']}", "2 × ৳100"))
        self.assertEqual(o["notice"], f"✓ Order #{o['id']} placed. Keep cash ready for the rider.")
        self.assertTrue(o["meta_line"].endswith(" · Dhaka · Cash on delivery"))
        self.assertEqual(p["discount_label"], "25% off")
        self.assertTrue(o["meta_line"].startswith(day(Order.objects.get(pk=o["id"]).created) + " · "))
        self.assertEqual(self.client.get("/api/home/").data["wall"][0][0].keys(), {"tag", "field"})

    def test_comments_need_login_to_post_but_anyone_reads(self):
        url = "/api/products/phone/comments/"
        r = self.client.post(url, {"text": "  Great phone  "}, format="json")
        self.assertEqual((r.status_code, r.data["author"], r.data["text"]), (201, "rahim", "Great phone"))
        self.assertEqual(self.client.post(url, {"text": "   "}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"text": "x" * 1001}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/products/nope/comments/", {"text": "hi"}, format="json").status_code, 404)
        guest = APIClient()
        self.assertEqual(guest.post(url, {"text": "spam"}, format="json").status_code, 401)
        listed = guest.get(url).data
        self.assertEqual((listed["title"], [c["text"] for c in listed["results"]]), ("Comments (1)", ["Great phone"]))
        self.assertEqual(guest.get("/api/products/case/comments/").data["results"], [])

    def test_comment_edit_delete_reply_and_like(self):
        url = "/api/products/phone/comments/"
        t0 = self.client.post(url, {"text": "Battery?"}, format="json").data
        top = t0["id"]
        self.assertEqual((t0["replies"], t0["reply_count"], t0["replies_label"]), ([], 0, None))  # a new, empty thread
        other = User.objects.create_user("karim", password="pass-1234-word")
        karim = APIClient()
        karim.force_authenticate(other)
        r = karim.post(url, {"text": "Lasts a day", "parent": top}, format="json").data
        reply = r["id"]
        self.assertEqual(r["thread"], {"id": top, "reply_count": 1, "replies_label": "View replies (1)"})
        extra = karim.post(url, {"text": "Two days", "parent": top}, format="json").data
        self.assertEqual(extra["thread"]["replies_label"], "View replies (2)")
        self.assertEqual(karim.delete(f"/api/comments/{extra['id']}/").data["thread"]["replies_label"], "View replies (1)")
        self.assertEqual(karim.post(url, {"text": "x", "parent": reply}, format="json").status_code, 400)  # one level
        self.assertEqual(karim.post("/api/products/case/comments/", {"text": "x", "parent": top},
                                    format="json").status_code, 400)  # another product's thread
        self.assertEqual(karim.patch(f"/api/comments/{top}/", {"text": "hacked"}, format="json").status_code, 404)
        self.assertEqual(karim.delete(f"/api/comments/{top}/").status_code, 404)
        for body in [{}, {"text": Comment.objects.get(pk=top).text}]:  # nothing changed: not "edited"
            self.assertIsNone(self.client.patch(f"/api/comments/{top}/", body, format="json").data["edited_label"])
        self.assertEqual(self.client.patch(f"/api/comments/{top}/", {"text": "Battery life?"}, format="json").status_code, 200)
        for _ in range(2):  # liking twice still counts once
            self.assertEqual(karim.post(f"/api/comments/{top}/like/").data["likes"], 1)
        self.assertEqual(APIClient().post(f"/api/comments/{top}/like/").status_code, 401)
        t = karim.get(url).data["results"][0]
        self.assertEqual((t["text"], t["edited_label"], t["liked"], t["mine"]), ("Battery life?", "edited", True, False))
        self.assertEqual([(r["text"], r["mine"]) for r in t["replies"]], [("Lasts a day", True)])
        gone = self.client.delete(f"/api/comments/{top}/").data  # has a reply: placeholder
        self.assertEqual((gone["removed"], gone["comment"]["deleted"]), ([], True))
        t = karim.get(url).data["results"][0]
        self.assertEqual((t["deleted"], t["author"], t["likes"], len(t["replies"])), (True, None, 0, 1))
        self.assertEqual(karim.delete(f"/api/comments/{reply}/").data["removed"], [reply, top])  # placeholder too
        self.assertEqual(karim.post(url, {"text": "x", "parent": top}, format="json").status_code, 400)  # deleted parent
        self.assertEqual(karim.get(url).data["results"], [])  # last reply gone: the placeholder goes too

    def test_comments_and_replies_come_ten_at_a_time(self):
        top = [Comment.objects.create(product=self.phone, user=self.user, text=f"c{i}").pk for i in range(12)]
        for i in range(12):
            Comment.objects.create(product=self.phone, user=self.user, parent_id=top[-1], text=f"r{i}")
        url = "/api/products/phone/comments/"
        first = self.client.get(url).data
        self.assertEqual(([c["text"] for c in first["results"]], first["title"]),
                         ([f"c{i}" for i in range(11, 1, -1)], "Comments (12)"))  # newest first, no cap
        newest = first["results"][0]
        self.assertEqual([r["text"] for r in newest["replies"]], [f"r{i}" for i in range(10)])  # oldest first
        self.assertEqual((newest["reply_count"], first["results"][1]["reply_count"]), (12, 0))
        self.assertEqual((newest["replies_label"], first["results"][1]["replies_label"]), ("View replies (12)", None))
        Comment.objects.create(product=self.phone, user=self.user, text="new")  # arrives mid-paging
        second = self.client.get(f"{url}?before={first['next']}").data
        self.assertEqual(([c["text"] for c in second["results"]], second["next"]), (["c1", "c0"], None))
        more = self.client.get(f"/api/comments/{newest['id']}/replies/?after={newest['replies_next']}").data
        self.assertEqual(([r["text"] for r in more["results"]], more["next"]), (["r10", "r11"], None))
        self.assertEqual(self.client.get(f"{url}?before=x").status_code, 400)

    def test_comment_edits_and_likes_are_throttled(self):
        c = self.client.post("/api/products/phone/comments/", {"text": "Hi"}, format="json").data["id"]
        with mock.patch.object(CommentActionThrottle, "THROTTLE_RATES", {"comment_action": "2/hour"}):
            self.assertEqual(self.client.post(f"/api/comments/{c}/like/").status_code, 200)
            self.assertEqual(self.client.patch(f"/api/comments/{c}/", {"text": "Hey"}, format="json").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/comments/{c}/like/").status_code, 429)

    def test_config_lists_cities_and_sorts(self):
        c = self.client.get("/api/config/").data
        self.assertEqual(c["cities"][0], "Dhaka")  # the checkout's default
        self.assertEqual(c["payments"], [{"value": "cod", "label": "Cash on delivery", "hint": "Pay the rider when it arrives"}])
        self.assertEqual(c["sorts"][0], {"value": "", "label": "Newest"})
        self.assertEqual(c["cart_note"], "Pay in cash when your order arrives.")
        Product.objects.filter(pk=self.case.pk).update(rating=4)
        self.assertEqual(self.client.get("/api/config/").data["stamp"], self.case.image)  # best-rated photo


class SecurityTests(APITestCase):
    def setUp(self):
        cache.clear()
        cat = Category.objects.create(name="Mobiles", slug="mobiles")
        self.case = Product.objects.create(category=cat, name="Case", slug="case", price=100, image="https://x.y/b.jpg", stock=50)
        self.user = User.objects.create_user("rahim", password="pass-1234-word")

    def token_client(self, key):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        return c

    def login(self, password, ip, username="rahim"):
        return self.client.post("/api/auth/login/", {"username": username, "password": password}, REMOTE_ADDR=ip)

    def test_login_locks_the_account_whatever_ip_guesses(self):
        n = settings.LOGIN_MAX_FAILS_PER_ACCOUNT
        codes = [self.login("wrong", f"10.0.{i // 250}.{i % 250}").status_code for i in range(n)]
        self.assertEqual(codes, [400] * n)  # each IP is under its own per-minute throttle
        self.assertEqual(self.login("pass-1234-word", "10.1.0.1").status_code, 429)  # even the right password waits
        self.assertEqual(self.login("pass-1234-word", "10.1.0.2", username="RAHIM").status_code, 429)

    @mock.patch.dict(ScopedThrottle.THROTTLE_RATES, {"auth": "100/min"})  # only the lockout may refuse here
    def test_one_ip_cannot_lock_a_customer_out(self):
        codes = [self.login("wrong", "10.0.0.1").status_code for _ in range(6)]
        self.assertEqual(codes, [400] * 5 + [429])
        self.assertEqual(self.login("pass-1234-word", "10.0.0.1").status_code, 429)
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1").status_code, 200)  # the owner, elsewhere

    def test_staff_lock_after_few_failures_from_anywhere(self):
        User.objects.filter(pk=self.user.pk).update(is_staff=True)
        for i in range(settings.LOGIN_MAX_FAILS):
            self.login("wrong", f"10.0.0.{i}")
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1").status_code, 429)

    def test_successful_login_resets_the_failure_count(self):
        for i in range(4):
            self.login("wrong", f"10.0.0.{i}")
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1").status_code, 200)
        self.assertEqual(self.login("wrong", "10.0.1.2").status_code, 400)  # counting starts again

    @override_settings(LOGIN_MAX_FAILS_PER_ACCOUNT=5)  # one counter per account, whatever the spelling
    def test_padded_or_unicode_spellings_share_the_lockout(self):
        # Both logins strip spaces (and the admin applies NFKC) before checking, so these all guess "rahim".
        for i, name in enumerate([" rahim", "rahim ", "\trahim", "ｒａｈｉｍ", "  rahim  "]):
            self.login("wrong", f"10.0.0.{i}", username=name)
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1").status_code, 429)

    def test_username_cannot_look_like_an_email(self):
        # Login tries a username before an email, so "victim@x.com" as a username would block the victim's email login.
        User.objects.filter(pk=self.user.pk).update(email="rahim@x.com")
        r = self.client.post("/api/auth/register/", {"username": "rahim@x.com", "email": "e@x.com", "password": "pass-1234-word"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("username", r.data)
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1", username="rahim@x.com").status_code, 200)

    def test_cart_lines_are_capped(self):
        # Each line costs session space and work on every cart read, and lets one order hoard everything.
        cat = self.case.category
        for i in range(MAX_LINES + 1):
            p = Product.objects.create(category=cat, name=f"P{i}", slug=f"p{i}", price=10, image="https://x.y/b.jpg", stock=5)
            r = self.client.post("/api/cart/", {"product": p.pk, "quantity": 1}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/cart/").data["count"], MAX_LINES)
        self.assertEqual(self.client.post("/api/cart/", {"product": p.pk - 1, "quantity": 1}, format="json").status_code, 200)  # more of a line already in

    @override_settings(LOGIN_MAX_FAILS_PER_ACCOUNT=5)  # one counter per account, whatever the spelling
    def test_numeric_username_shares_the_lockout(self):
        User.objects.create_user("12345", password="pass-1234-word")
        for i in range(5):
            self.client.post("/api/auth/login/", {"username": 12345, "password": "wrong"}, format="json",
                             REMOTE_ADDR=f"10.0.0.{i}")
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1", username="12345").status_code, 429)

    def test_ipv6_clients_are_counted_by_their_64(self):
        # Fresh usernames, so only the per-IP throttle can trip.
        codes = [self.login("wrong", f"2001:db8:1:2::{i}", username=f"u{i}").status_code for i in range(1, 7)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.login("wrong", "2001:db8:1:3::1", username="u9").status_code, 400)  # next /64

    def test_cart_changes_need_csrf_token(self):
        c = APIClient(enforce_csrf_checks=True)
        body = {"product": self.case.pk, "quantity": 1}
        self.assertEqual(c.post("/api/cart/", body, format="json").status_code, 403)  # cross-site form or fetch
        self.assertEqual(c.post("/api/auth/logout/").status_code, 403)
        token = c.get("/api/cart/").cookies["csrftoken"].value  # the app's first call hands it out
        self.assertEqual(c.post("/api/cart/", body, format="json", HTTP_X_CSRFTOKEN=token).status_code, 200)
        r = c.patch(f"/api/cart/{self.case.pk}/", {"quantity": 2}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.data["count"], 2)
        self.assertEqual(c.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code, 204)

    def test_cart_patch_with_non_object_body_is_400_not_500(self):
        self.client.post("/api/cart/", {"product": self.case.pk, "quantity": 1}, format="json")
        self.assertEqual(self.client.patch(f"/api/cart/{self.case.pk}/", [1], format="json").status_code, 400)

    def test_expired_token_is_refused_and_login_issues_a_new_one(self):
        old = Token.objects.create(user=self.user)
        Token.objects.filter(pk=old.pk).update(created=timezone.now() - timedelta(days=31))
        self.assertEqual(self.token_client(old.key).get("/api/orders/").status_code, 401)
        self.assertFalse(Token.objects.filter(pk=old.pk).exists())
        Token.objects.create(user=self.user)
        Token.objects.filter(user=self.user).update(created=timezone.now() - timedelta(days=31))
        new = self.client.post("/api/auth/login/", {"username": "rahim", "password": "pass-1234-word"}).data["token"]
        self.assertNotEqual(new, old.key)
        self.assertEqual(self.token_client(new).get("/api/orders/").status_code, 200)

    def test_password_change_revokes_tokens(self):
        token = Token.objects.create(user=self.user)
        self.user.last_login = timezone.now()
        self.user.save()  # an unrelated save keeps the token
        self.assertEqual(self.token_client(token.key).get("/api/orders/").status_code, 200)
        self.user.set_password("new-pass-9876-x")
        self.user.save()
        self.assertEqual(self.token_client(token.key).get("/api/orders/").status_code, 401)

    def test_register_rejects_huge_password_and_lookalike_username(self):
        r = self.client.post("/api/auth/register/", {"username": "longpw", "password": "ab" * 100}, format="json")
        self.assertIn("password", r.data)
        r = self.client.post("/api/auth/register/", {"username": "rаhim", "password": "pass-1234-word"}, format="json")
        self.assertIn("username", r.data)  # Cyrillic "а"

    def test_case_twins_blocked_by_database_too(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("RAHIM")
        # The serializer turns the race into a normal error, not a 500.
        ser = RegisterSerializer()
        with self.assertRaises(ValidationError):
            ser.create({"username": "Rahim", "password": "pass-1234-word"})

    def test_signup_has_a_daily_cap_per_ip(self):
        with mock.patch.object(SignupThrottle, "THROTTLE_RATES", {"signup": "2/day"}):
            codes = [self.client.post("/api/auth/register/", {"username": f"u{i}", "email": f"u{i}@x.com", "password": "pass-1234-word"}).status_code
                     for i in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    def test_pending_cap_counts_the_phone_across_accounts(self):
        for i in range(5):
            u = User.objects.create_user(f"buyer{i}")
            Order.objects.create(user=u, full_name="X", phone="01712345678", address="A", city="Dhaka",
                                 subtotal=100, delivery_fee=60, total=160)
        self.client.force_authenticate(self.user)
        self.client.post("/api/cart/", {"product": self.case.pk, "quantity": 1}, format="json")
        total = self.client.get("/api/cart/").data["total"]
        r = self.client.post("/api/orders/", {**ADDR, "phone": "+8801712345678", "expected_total": total}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.data)  # "+88" spelling counts as the same number
        r = self.client.post("/api/orders/", {**ADDR, "phone": "01812345678", "expected_total": total}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_cancelled_order_cannot_be_reopened_even_without_clean(self):
        o = Order.objects.create(user=self.user, full_name="X", phone="01712345678", address="A", city="Dhaka",
                                 subtotal=100, delivery_fee=60, total=160, status="cancelled")
        o.status = "pending"
        with self.assertRaises(DjangoValidationError):
            o.save()


class AdminSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("boss", password="pass-1234-word")
        call_command("admin_totp", "boss", stdout=io.StringIO())
        self.device = TOTPDevice.objects.get(user=self.admin)

    def login(self, password="pass-1234-word", code=None):
        return self.client.post("/admin/login/", {"username": "boss", "password": password, "otp_token": code or "",
                                                  "otp_device": self.device.persistent_id})

    def code(self):
        d = self.device
        return format(TOTP(d.bin_key, d.step, d.t0, d.digits).token(), f"0{d.digits}d")

    def test_admin_needs_authenticator_code(self):
        self.assertEqual(self.login().status_code, 200)  # password alone: form shown again
        self.assertEqual(self.login(code=self.code()).status_code, 302)

    def test_admin_login_uses_the_only_device_without_a_pick(self):
        r = self.client.post("/admin/login/", {"username": "boss", "password": "pass-1234-word", "otp_token": self.code()})
        self.assertEqual(r.status_code, 302)

    def test_admin_login_explains_a_missing_authenticator(self):
        User.objects.create_user("newstaff", password="pass-1234-word", is_staff=True)
        r = self.client.post("/admin/login/", {"username": "newstaff", "password": "pass-1234-word", "otp_token": "123456"})
        self.assertContains(r, "manage.py admin_totp newstaff")

    def test_admin_locks_out_after_failed_logins(self):
        codes = [self.login(password="wrong").status_code for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])
        self.assertEqual(self.login(code=self.code()).status_code, 429)  # even the right password waits

    def test_api_login_cannot_guess_admin_passwords_past_the_lockout(self):
        api = APIClient()
        for i in range(5):
            api.post("/api/auth/login/", {"username": "boss", "password": "wrong"}, REMOTE_ADDR=f"10.0.0.{i}")
        self.assertEqual(self.login(code=self.code()).status_code, 429)  # admin login shares the count
        r = api.post("/api/auth/login/", {"username": "boss", "password": "pass-1234-word"}, REMOTE_ADDR="10.0.1.1")
        self.assertEqual(r.status_code, 429)  # no oracle: the right password isn't confirmed either


    def test_admin_totp_refuses_to_replace_a_device_silently(self):
        with self.assertRaises(CommandError):
            call_command("admin_totp", "boss", stdout=io.StringIO())
        call_command("admin_totp", "boss", "--reset", stdout=io.StringIO())
        self.assertNotEqual(TOTPDevice.objects.get(user=self.admin).key, self.device.key)


class AdminPanelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", password="pass-1234-word")
        cache.clear()
        call_command("admin_totp", "boss", stdout=io.StringIO())
        d = TOTPDevice.objects.get(user=self.admin)
        code = format(TOTP(d.bin_key, d.step, d.t0, d.digits).token(), f"0{d.digits}d")
        self.client.post("/admin/login/", {"username": "boss", "password": "pass-1234-word", "otp_token": code,
                                           "otp_device": d.persistent_id})
        self.get, self.post = self.client.get, self.client.post
        cat = Category.objects.create(name="Mobiles", slug="mobiles")
        self.phone = Product.objects.create(category=cat, name="Phone", slug="phone", price=100,
                                            image="https://x.y/a.jpg", stock=2)
        self.order = Order.objects.create(user=self.admin, subtotal=200, delivery_fee=60, total=260, **ADDR)
        self.order.items.create(product=self.phone, name="Phone", price=100, quantity=2)

    def test_admin_user_needs_unique_email(self):
        User.objects.create_user("taken", email="taken@x.com")
        form = {"username": "staffer", "usable_password": "true", "password1": "pass-1234-word", "password2": "pass-1234-word",
                "orders-TOTAL_FORMS": "0", "orders-INITIAL_FORMS": "0"}  # the orders inline
        self.assertContains(self.post("/admin/auth/user/add/", form), "This field is required")
        self.assertContains(self.post("/admin/auth/user/add/", {**form, "email": "TAKEN@x.com"}), "already exists")
        r = self.post("/admin/auth/user/add/", {**form, "email": "Staff@x.com"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(User.objects.get(username="staffer").email, "staff@x.com")

    def test_dashboard_shows_sales_and_low_stock(self):
        r = self.get("/admin/")
        self.assertContains(r, "Pending orders")
        self.assertContains(r, "৳260")
        self.assertContains(r, "2 left")
        chart = r.context["chart"]
        self.assertEqual(len(chart), 14)
        self.assertEqual((chart[-1]["sales"], chart[-1]["pct"], chart[-1]["today"]), ("৳260", 100, True))
        self.assertEqual([(t["product__name"], t["qty"]) for t in r.context["top_sellers"]], [("Phone", 2)])
        self.assertEqual({m["key"]: m["n"] for m in r.context["status_mix"]}["pending"], 1)

    def test_dashboard_compares_with_previous_period(self):
        self.assertIsNone(change(100, 0, "yesterday"))
        self.assertEqual(change(150, 100, "yesterday"), ("up", "+50% vs yesterday"))
        self.assertEqual(change(50, 100, "yesterday"), ("down", "-50% vs yesterday"))

    def test_order_page_shows_progress(self):
        self.assertContains(self.get(f"/admin/shop/order/{self.order.pk}/change/"), 'class="is-now">Placed')
        self.order.status = "cancelled"
        self.order.save()
        self.assertContains(self.get(f"/admin/shop/order/{self.order.pk}/change/"), 'class="is-now">Cancelled')

    def test_product_page_lists_its_comments(self):
        top = Comment.objects.create(product=self.phone, user=self.admin, text="Battery lasts all day")
        top.likes.add(self.admin)
        Comment.objects.create(product=self.phone, user=self.admin, parent=top, text="Agreed")
        r = self.get(f"/admin/shop/product/{self.phone.pk}/change/")
        self.assertContains(r, "Battery lasts all day")
        self.assertContains(r, "boss: Battery lasts all day")  # the reply says what it answers
        self.assertEqual(self.get("/admin/shop/comment/").status_code, 404)  # no separate comments page

    def test_product_page_shows_comments_ten_at_a_time(self):
        for i in range(12):
            Comment.objects.create(product=self.phone, user=self.admin, text=f"note-{i:02}")
        page = lambda q="": self.get(f"/admin/shop/product/{self.phone.pk}/change/{q}").content.decode()
        first = page()
        self.assertEqual([f"note-{i:02}" in first for i in range(12)], [False] * 2 + [True] * 10)  # newest 10
        self.assertIn("?comments=20#comments-group", first)
        rest = page("?comments=20")
        self.assertTrue(all(f"note-{i:02}" in rest for i in range(12)))
        self.assertNotIn("Show 10 more", rest)
        self.assertIn("note-11", page("?comments=junk"))  # a bad count falls back to the first page

    def test_staff_edit_and_delete_comments_from_the_product_page(self):
        cs = [Comment.objects.create(product=self.phone, user=self.admin, text=f"note-{i}") for i in range(12)]
        shown = cs[:1:-1]  # the 10 newest, as the page lists them
        Comment.objects.create(product=self.phone, user=self.admin, text="arrived while editing")
        p = self.phone
        form = {"name": p.name, "slug": p.slug, "category": p.category_id, "description": "", "price": p.price,
                "original_price": "", "stock": p.stock, "image": "https://example.com/a.jpg", "rating": "0", "reviews": 0,
                "photos-TOTAL_FORMS": 0, "photos-INITIAL_FORMS": 0, "options-TOTAL_FORMS": 0, "options-INITIAL_FORMS": 0,
                "variants-TOTAL_FORMS": 0, "variants-INITIAL_FORMS": 0,
                "comments-TOTAL_FORMS": len(shown), "comments-INITIAL_FORMS": len(shown)}
        for i, c in enumerate(shown):
            form.update({f"comments-{i}-id": c.pk, f"comments-{i}-product": p.pk, f"comments-{i}-text": c.text})
        form["comments-0-text"] = "fixed by staff"
        form["comments-1-DELETE"] = "on"
        # A comment arrived after the page loaded, so the 10 newest changed: saving must still find every row.
        self.assertEqual(self.post(f"/admin/shop/product/{p.pk}/change/", form).status_code, 302)
        self.assertEqual(Comment.objects.get(pk=shown[0].pk).text, "fixed by staff")
        self.assertFalse(Comment.objects.filter(pk=shown[1].pk).exists())

    def test_options_making_too_many_combinations_are_refused(self):
        p = self.phone
        form = {"name": p.name, "slug": p.slug, "category": p.category_id, "description": "", "price": p.price,
                "original_price": "", "stock": p.stock, "image": "https://example.com/a.jpg", "rating": "0", "reviews": 0,
                "photos-TOTAL_FORMS": 0, "photos-INITIAL_FORMS": 0, "variants-TOTAL_FORMS": 0, "variants-INITIAL_FORMS": 0,
                "comments-TOTAL_FORMS": 0, "comments-INITIAL_FORMS": 0, "options-TOTAL_FORMS": 3, "options-INITIAL_FORMS": 0}
        many = ", ".join(str(i) for i in range(5))
        for i, name in enumerate(["A", "B", "C"]):  # 5 x 5 x 5 = 125
            form.update({f"options-{i}-name": name, f"options-{i}-values": many, f"options-{i}-position": i})
        r = self.post(f"/admin/shop/product/{p.pk}/change/", form)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "make 125 combinations")
        self.assertFalse(p.options.exists())

    def test_saving_options_makes_their_combinations(self):
        p = self.phone
        form = {"name": p.name, "slug": p.slug, "category": p.category_id, "description": "", "price": p.price,
                "original_price": "", "stock": p.stock, "image": "https://example.com/a.jpg", "rating": "0", "reviews": 0,
                "photos-TOTAL_FORMS": 0, "photos-INITIAL_FORMS": 0, "variants-TOTAL_FORMS": 0, "variants-INITIAL_FORMS": 0,
                "comments-TOTAL_FORMS": 0, "comments-INITIAL_FORMS": 0,
                "options-TOTAL_FORMS": 1, "options-INITIAL_FORMS": 0,
                "options-0-name": "Color", "options-0-values": "Black, Blue", "options-0-position": 0}
        self.assertEqual(self.post(f"/admin/shop/product/{p.pk}/change/", form).status_code, 302)
        p.refresh_from_db()
        self.assertEqual(sorted(v.label for v in p.variants.all()), ["Color: Black", "Color: Blue"])
        self.assertEqual(p.stock, 0)  # new combinations start empty until staff set their stock

    def test_option_change_that_drops_stocked_combinations_is_refused(self):
        p = self.phone
        opt = p.options.create(name="Colour", values="Black, Blue")
        p.sync_variants(stock=3)
        p.variants.filter(key="Colour=Blue").update(stock=0)
        form = {"name": p.name, "slug": p.slug, "category": p.category_id, "description": "", "price": p.price,
                "original_price": "", "image": "https://example.com/a.jpg", "rating": "0", "reviews": 0,
                "photos-TOTAL_FORMS": 0, "photos-INITIAL_FORMS": 0, "variants-TOTAL_FORMS": 0, "variants-INITIAL_FORMS": 0,
                "comments-TOTAL_FORMS": 0, "comments-INITIAL_FORMS": 0, "options-TOTAL_FORMS": 1, "options-INITIAL_FORMS": 1,
                "options-0-id": opt.pk, "options-0-product": p.pk, "options-0-name": "Color",
                "options-0-values": "Black, Blue", "options-0-position": 0}
        url = f"/admin/shop/product/{p.pk}/change/"
        r = self.post(url, form)  # a rename would delete Black's 3 in stock
        self.assertContains(r, "still have stock: Colour: Black.")  # Blue has none, so it isn't named
        self.assertEqual(sorted(p.variants.values_list("key", flat=True)), ["Colour=Black", "Colour=Blue"])
        p.variants.update(stock=0)  # the product's stored total (3) is now wrong: saving must fix, not refuse
        self.assertEqual(self.post(url, form).status_code, 302)  # nothing in stock is lost now
        self.assertEqual(sorted(p.variants.values_list("key", flat=True)), ["Color=Black", "Color=Blue"])
        p.refresh_from_db()
        self.assertEqual(p.stock, 0)

    def test_list_page_cannot_overwrite_stock_of_a_product_with_options(self):
        p = self.phone
        p.options.create(name="Color", values="Black, Blue")
        p.sync_variants(stock=3)  # stock 6
        price = p.price + 1
        form = {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1, "form-0-id": p.pk, "form-0-price": price,
                "form-0-original_price": "", "form-0-stock": 99, "_save": "Save"}
        self.assertEqual(self.post("/admin/shop/product/", form).status_code, 302)
        p.refresh_from_db()
        self.assertEqual((p.price, p.stock), (price, 6))  # the price changed; the typed stock was ignored

    def test_editing_a_product_keeps_stock_sold_since_the_page_loaded(self):
        p = self.phone  # the page showed stock 2
        form = {"name": "Phone v2", "slug": p.slug, "category": p.category_id, "description": "", "price": p.price,
                "original_price": "", "stock": 2, "initial-stock": 2, "image": "https://example.com/a.jpg", "rating": "0",
                "reviews": 0, "photos-TOTAL_FORMS": 0, "photos-INITIAL_FORMS": 0, "options-TOTAL_FORMS": 0,
                "options-INITIAL_FORMS": 0, "variants-TOTAL_FORMS": 0, "variants-INITIAL_FORMS": 0,
                "comments-TOTAL_FORMS": 0, "comments-INITIAL_FORMS": 0}
        Product.objects.filter(pk=p.pk).update(stock=1)  # a buyer took one meanwhile
        self.assertEqual(self.post(f"/admin/shop/product/{p.pk}/change/", form).status_code, 302)
        p.refresh_from_db()
        self.assertEqual((p.name, p.stock), ("Phone v2", 1))
        self.assertContains(self.get(f"/admin/shop/product/{p.pk}/change/"), 'name="initial-stock"')
        self.post(f"/admin/shop/product/{p.pk}/change/", {**form, "stock": 9})  # staff restock: that one is written
        p.refresh_from_db()
        self.assertEqual(p.stock, 9)
        list_form = {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1, "form-0-id": p.pk, "form-0-price": p.price + 1,
                     "form-0-original_price": "", "form-0-stock": 2, "initial-form-0-stock": 2,
                     "_save": "Save"}  # a stale list page
        Product.objects.filter(pk=p.pk).update(stock=0)
        self.assertEqual(self.post("/admin/shop/product/", list_form).status_code, 302)
        p.refresh_from_db()
        self.assertEqual((p.price, p.stock), (101, 0))

    def test_editing_a_combinations_price_keeps_stock_sold_since_the_page_loaded(self):
        p = self.phone
        p.options.create(name="Color", values="Black")
        p.sync_variants(stock=3)
        v = p.variants.get()
        form = {"name": p.name, "slug": p.slug, "category": p.category_id, "description": "", "price": p.price,
                "original_price": "", "image": "https://example.com/a.jpg", "rating": "0", "reviews": 0,
                "photos-TOTAL_FORMS": 0, "photos-INITIAL_FORMS": 0, "comments-TOTAL_FORMS": 0, "comments-INITIAL_FORMS": 0,
                "options-TOTAL_FORMS": 1, "options-INITIAL_FORMS": 1, "options-0-id": p.options.get().pk,
                "options-0-product": p.pk, "options-0-name": "Color", "options-0-values": "Black", "options-0-position": 0,
                "variants-TOTAL_FORMS": 1, "variants-INITIAL_FORMS": 1, "variants-0-id": v.pk,
                "variants-0-product": p.pk, "variants-0-price": 150, "variants-0-stock": 3, "initial-variants-0-stock": 3}
        ProductVariant.objects.filter(pk=v.pk).update(stock=2)  # a buyer took one meanwhile
        self.assertEqual(self.post(f"/admin/shop/product/{p.pk}/change/", form).status_code, 302)
        v.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual((v.price, v.stock, p.stock), (150, 2, 2))

    def test_lists_show_status_pills_and_theme(self):
        self.assertContains(self.get("/admin/shop/order/"), 'haat-badge haat-pending')
        r = self.get("/admin/shop/product/")
        self.assertContains(r, "Only 2 left")
        self.assertContains(r, "shop/admin.css")

    def test_every_admin_list_loads(self):
        for model in ["shop/product", "shop/category", "shop/order", "auth/user", f"auth/user/{self.admin.pk}/change"]:
            self.assertEqual(self.get(f"/admin/{model}/").status_code, 200, model)

    def test_bulk_cancel_restocks_once_and_never_reopens(self):
        act = lambda a: self.post("/admin/shop/order/", {"action": a, "_selected_action": [self.order.pk]})
        act("mark_cancelled")
        self.phone.refresh_from_db()
        self.assertEqual(self.phone.stock, 4)
        act("mark_cancelled")
        act("mark_shipped")
        self.order.refresh_from_db()
        self.phone.refresh_from_db()
        self.assertEqual((self.order.status, self.phone.stock), ("cancelled", 4))

    def test_order_money_is_read_only_for_staff(self):
        clerk = User.objects.create_user("clerk", "c@x.com", "pass-1234-word", is_staff=True)
        clerk.user_permissions.set([perm("shop.view_order"), perm("shop.change_order")])
        self.client.logout()
        admin_login(self.client, clerk)
        self.post(f"/admin/shop/order/{self.order.pk}/change/",
                  {**ADDR, "status": "shipped", "total": 1, "items-TOTAL_FORMS": 1, "items-INITIAL_FORMS": 1,
                   "items-0-id": self.order.items.get().pk, "items-0-order": self.order.pk})
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.total), ("shipped", 260))


class GuestCheckoutTests(APITestCase):
    """Ordering without an account: the order lives on the session, which is the only key to it."""

    def setUp(self):
        cache.clear()
        cat = Category.objects.create(name="Mobiles", slug="mobiles")
        self.case = Product.objects.create(category=cat, name="Case", slug="case", price=100, image="https://x.y/b.jpg", stock=50)
        self.user = User.objects.create_user("rahim", password="pass-1234-word")

    def order(self, client=None, **body):
        c = client or self.client
        c.post("/api/cart/", {"product": self.case.pk, "quantity": 1}, format="json")
        total = c.get("/api/cart/").data["total"]
        return c.post("/api/orders/", {**ADDR, "expected_total": total, **body}, format="json")

    def test_guest_can_order_and_see_it(self):
        r = self.order()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Order.objects.get().user, None)
        self.assertEqual(self.client.get("/api/cart/").data["lines"], [])
        self.assertEqual([o["id"] for o in self.client.get("/api/orders/").data], [r.data["id"]])

    def test_guest_sees_only_own_session_orders(self):
        self.order()
        self.assertEqual(APIClient().get("/api/orders/").data, [])

    def test_session_list_never_shows_account_orders(self):
        mine = Order.objects.create(user=self.user, full_name="X", phone="01712345678", address="A", city="Dhaka",
                                    subtotal=100, delivery_fee=60, total=160)
        s = self.client.session
        s["guest_orders"] = [mine.pk]
        s.save()
        self.assertEqual(self.client.get("/api/orders/").data, [])

    def test_guest_cannot_set_owner_status_or_money(self):
        r = self.order(user=self.user.pk, status="delivered", total=1, subtotal=1, payment="card")
        self.assertEqual(r.status_code, 201, r.data)
        o = Order.objects.get()
        self.assertEqual((o.user, o.status, o.total, o.payment), (None, "pending", 160, "cod"))

    def test_orders_need_csrf_token_for_guests_and_users(self):
        for user in [None, self.user]:
            c = APIClient(enforce_csrf_checks=True)
            c.force_authenticate(user)
            token = c.get("/api/cart/").cookies["csrftoken"].value
            c.post("/api/cart/", {"product": self.case.pk, "quantity": 1}, format="json", HTTP_X_CSRFTOKEN=token)
            body = {**ADDR, "expected_total": c.get("/api/cart/").data["total"]}
            self.assertEqual(c.post("/api/orders/", body, format="json").status_code, 403)  # cross-site post
            self.assertEqual(c.post("/api/orders/", body, format="json", HTTP_X_CSRFTOKEN=token).status_code, 201)

    def test_guest_order_rotates_session_key(self):
        self.client.get("/api/cart/")
        planted = self.client.session.session_key
        self.order()
        self.assertNotEqual(self.client.session.session_key, planted)
        other = APIClient()
        other.cookies["sessionid"] = planted  # whoever planted the old cookie
        self.assertEqual(other.get("/api/orders/").data, [])

    def test_logout_forgets_guest_orders(self):
        self.order()
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/orders/").data, [])

    def test_login_shows_account_orders_only(self):
        self.order()
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/orders/").data, [])

    def test_phone_cap_applies_to_guests(self):
        for _ in range(5):
            self.assertEqual(self.order().status_code, 201)
        r = self.order()
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.data)

    def test_guest_orders_throttled_users_not(self):
        with mock.patch.object(GuestOrderThrottle, "THROTTLE_RATES", {"guest_order": "2/hour"}):
            codes = [self.order(phone=f"0171234567{i}").status_code for i in range(3)]
            self.assertEqual(codes, [201, 201, 429])
            self.assertEqual(self.client.get("/api/orders/").status_code, 200)  # reading is not throttled
            self.client.force_authenticate(self.user)
            self.assertEqual(self.order(phone="01812345678").status_code, 201)

    def login(self):
        r = self.client.post("/api/auth/login/", {"username": "rahim", "password": "pass-1234-word"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_login_claims_guest_orders_to_the_accounts_phones(self):
        Order.objects.create(user=self.user, full_name="Rahim", phone=ADDR["phone"], address="A", city="Dhaka",
                             subtotal=100, delivery_fee=60, total=160, status="delivered")
        r = self.order()
        self.login()
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, self.user)
        self.assertNotIn("guest_orders", self.client.session)

    def test_login_on_shared_browser_leaves_others_guest_orders(self):
        r = self.order()  # someone else ordered as a guest on this browser
        self.login()
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, None)

    def test_pending_order_to_a_phone_claims_nothing(self):
        # Anyone can place an order to a phone they read off the browser's guest list; only a delivery proves it.
        Order.objects.create(user=self.user, full_name="R", phone=ADDR["phone"], address="A", city="Dhaka",
                             subtotal=100, delivery_fee=60, total=160, status="pending")
        r = self.order()
        self.login()
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, None)

    def register(self, email, username="karim"):
        r = self.client.post("/api/auth/register/", {"username": username, "email": email, "password": "pass-1234-word"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return User.objects.get(username=username), r.data["token"]

    def claim(self, token, link=None):
        link = link or mail.outbox[-1].body.split("\n\n")[1]
        return self.client.post("/api/orders/claim/", {"token": parse_qs(urlparse(link).query)["t"][0]},
                                format="json", HTTP_AUTHORIZATION=f"Token {token}")

    def test_new_account_claims_guest_orders_with_its_email_by_link(self):
        mine = self.order(email="Karim@X.com").data["id"]
        other = self.order(email="someone@x.com").data["id"]  # another person on this browser
        blank = self.order().data["id"]  # no email, and a new account has no past phone
        karim, token = self.register("karim@x.com")
        self.assertFalse(karim.orders.exists())  # nothing joins before the inbox answers
        self.assertEqual(mail.outbox[-1].to, ["karim@x.com"])
        self.assertIn("/orders/claim?t=", mail.outbox[-1].body)
        r = self.claim(token)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(list(karim.orders.values_list("pk", flat=True)), [mine])
        self.assertEqual(Order.objects.filter(pk__in=[other, blank], user=None).count(), 2)
        self.assertIn("already", self.claim(token).data["notice"])  # a second click adds nothing

    def test_shared_browser_cant_claim_by_typing_the_orders_email(self):
        victim = self.order(email="victim@x.com").data["id"]
        seen = self.client.get("/api/orders/").data[0]["email"]  # the next person on this browser reads it
        _, token = self.register(seen, username="taker")
        link = mail.outbox[-1].body.split("\n\n")[1]  # went to the victim's inbox, not the taker's
        self.assertEqual(Order.objects.get(pk=victim).user, None)
        # The victim opening it, signed in as themselves, adds nothing to either account.
        _, own = self.register("other@x.com", username="victim")
        self.assertEqual(self.claim(own, link).status_code, 403)
        self.assertEqual(Order.objects.get(pk=victim).user, None)

    def test_claim_link_refuses_tampering_age_and_changed_email(self):
        r = self.order(email="karim@x.com")
        karim, token = self.register("karim@x.com")
        link = mail.outbox[-1].body.split("\n\n")[1]
        self.assertEqual(self.claim(token, link.replace("t=", "t=x")).status_code, 400)
        self.assertEqual(self.client.post("/api/orders/claim/", {"token": 5}, format="json").status_code, 401)
        with mock.patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 4 * 86400):
            self.assertEqual(self.claim(token, link).status_code, 400)
        User.objects.filter(pk=karim.pk).update(email="new@x.com")
        self.assertEqual(self.claim(token, link).status_code, 403)
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, None)

    def test_mail_outage_does_not_break_sign_in(self):
        self.order(email="karim@x.com")
        with mock.patch("shop.api.checkout.send_mail", side_effect=OSError("smtp down")), self.assertLogs("shop.security"):
            self.register("karim@x.com")

    def test_login_claims_guest_orders_with_the_accounts_email_by_link(self):
        self.user.email = "rahim@x.com"
        self.user.save()
        r = self.order(email="rahim@x.com")
        self.login()
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, None)
        self.assertEqual(self.claim(Token.objects.get(user=self.user).key).status_code, 200)
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, self.user)

    def test_blank_account_email_matches_no_blank_order_email(self):
        r = self.order()  # self.user has no email, the order none either
        self.login()
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, None)

    def test_login_rotates_session_key(self):
        self.client.get("/api/cart/")
        planted = self.client.session.session_key
        self.login()
        self.assertNotEqual(self.client.session.session_key, planted)

    def test_bengali_digit_phone_is_stored_ascii_and_capped(self):
        r = self.order(phone="০১৭১২৩৪৫৬৭৮")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Order.objects.get().phone, "01712345678")

    def test_all_sold_out_says_which(self):
        self.client.post("/api/cart/", {"product": self.case.pk, "quantity": 1}, format="json")
        Product.objects.filter(pk=self.case.pk).update(stock=0)
        r = self.client.post("/api/orders/", {**ADDR, "expected_total": 160}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Case sold out", str(r.data["cart"]))

    def test_deleting_user_keeps_their_orders(self):
        self.client.force_authenticate(self.user)
        self.order()
        self.user.delete()
        self.assertEqual(Order.objects.get().user, None)

    def test_zero_price_rejected(self):
        self.case.price = 0
        with self.assertRaises(DjangoValidationError):
            self.case.full_clean()

    def test_guest_order_logged_without_personal_data(self):
        with self.assertLogs("shop.security", "INFO") as logs:
            r = self.order()
        self.assertIn(f"guest order id={r.data['id']}", logs.output[0])
        self.assertNotIn(ADDR["phone"], logs.output[0])
        self.assertNotIn(ADDR["address"], logs.output[0])


def admin_login(client, user, password="pass-1234-word"):
    """Logs `user` in to the admin with password and authenticator code, giving them a device if needed."""
    d = TOTPDevice.objects.filter(user=user).first() or TOTPDevice.objects.create(user=user, name="a", confirmed=True)
    code = format(TOTP(d.bin_key, d.step, d.t0, d.digits).token(), f"0{d.digits}d")
    r = client.post("/admin/login/", {"username": user.username, "password": password, "otp_token": code,
                                      "otp_device": d.persistent_id})
    assert r.status_code == 302, "admin login failed"


def perm(code):
    app, codename = code.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class OwnerAndStaffTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_superuser("boss", "boss@x.com", "pass-1234-word")
        self.clerk = User.objects.create_user("clerk", "clerk@x.com", "pass-1234-word", is_staff=True)
        self.clerk.user_permissions.set([perm("shop.view_order"), perm("shop.change_order"),
                                         perm("auth.view_user"), perm("auth.change_user")])
        self.order = Order.objects.create(user=None, subtotal=100, delivery_fee=60, total=160, **ADDR)

    def as_owner(self):
        admin_login(self.client, self.owner)

    def as_clerk(self):
        admin_login(self.client, self.clerk)

    # The one owner

    def test_staff_can_open_the_owners_account_read_only(self):
        self.as_clerk()
        r = self.client.get(f"/admin/auth/user/{self.owner.pk}/change/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("email", r.context["adminform"].form.fields)

    def test_owner_password_cannot_be_changed_on_the_site(self):
        self.as_owner()
        self.assertNotContains(self.client.get("/admin/"), "/admin/password_change/")
        self.assertEqual(self.client.get("/admin/password_change/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/auth/user/{self.owner.pk}/password/").status_code, 403)
        self.assertNotContains(self.client.get(f"/admin/auth/user/{self.owner.pk}/change/"), "../password/")
        self.assertContains(self.client.get(f"/admin/auth/user/{self.clerk.pk}/change/"), "../password/")
        self.assertEqual(self.client.get(f"/admin/auth/user/{self.clerk.pk}/password/").status_code, 200)
        self.as_clerk()  # staff keep their own change-password page
        self.assertEqual(self.client.get("/admin/password_change/").status_code, 200)

    def test_only_one_owner_can_exist(self):
        with self.assertRaises(DjangoValidationError):
            User.objects.create_superuser("second", "s@x.com", "pass-1234-word")
        self.clerk.is_superuser = True
        with self.assertRaises(DjangoValidationError):
            self.clerk.save()

    def test_sync_owner_creates_owner_from_env_and_demotes_the_old_one(self):
        env = {"OWNER_USERNAME": "rafi", "OWNER_EMAIL": "Rafi@X.com", "OWNER_PASSWORD": "a-long-owner-pass-77"}
        with mock.patch.dict("os.environ", env):
            call_command("sync_owner", stdout=io.StringIO())
        rafi = User.objects.get(username="rafi")
        self.assertTrue(rafi.is_superuser and rafi.is_staff and rafi.check_password("a-long-owner-pass-77"))
        self.assertEqual(rafi.email, "rafi@x.com")
        boss = User.objects.get(username="boss")
        self.assertFalse(boss.is_superuser or boss.is_staff)  # the new owner adds them as staff if they want
        # Run again with a new password: kept unless --reset-password, so OWNER_PASSWORD can leave .env after setup.
        with mock.patch.dict("os.environ", {**env, "OWNER_PASSWORD": "another-owner-pass-88"}):
            call_command("sync_owner", stdout=io.StringIO())
            self.assertTrue(User.objects.get(username="rafi").check_password("a-long-owner-pass-77"))
            call_command("sync_owner", "--reset-password", stdout=io.StringIO())
        self.assertTrue(User.objects.get(username="rafi").check_password("another-owner-pass-88"))

    def test_sync_owner_refuses_weak_password_and_taken_email(self):
        with mock.patch.dict("os.environ", {"OWNER_USERNAME": "rafi", "OWNER_EMAIL": "r@x.com", "OWNER_PASSWORD": "123"}):
            with self.assertRaises(CommandError):
                call_command("sync_owner", stdout=io.StringIO())
        with mock.patch.dict("os.environ", {"OWNER_USERNAME": "rafi", "OWNER_EMAIL": "clerk@x.com",
                                            "OWNER_PASSWORD": "a-long-owner-pass-77"}):
            with self.assertRaises(CommandError):
                call_command("sync_owner", stdout=io.StringIO())
        self.assertTrue(User.objects.get(username="boss").is_superuser)

    # Users admin: nobody climbs above their own permissions

    def test_superuser_box_is_never_shown(self):
        self.as_owner()
        r = self.client.get(f"/admin/auth/user/{self.clerk.pk}/change/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("is_superuser", r.context["adminform"].form.fields)

    def test_staff_cannot_edit_or_delete_the_owner(self):
        self.clerk.user_permissions.add(perm("auth.delete_user"))
        self.as_clerk()
        r = self.client.post(f"/admin/auth/user/{self.owner.pk}/change/", {"username": "boss", "email": "evil@x.com"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post(f"/admin/auth/user/{self.owner.pk}/delete/", {"post": "yes"}).status_code, 403)
        self.assertEqual(User.objects.get(pk=self.owner.pk).email, "boss@x.com")

    def test_staff_can_only_hand_out_permissions_they_hold(self):
        self.as_clerk()
        r = self.client.get(f"/admin/auth/user/{self.clerk.pk}/change/")
        self.assertNotIn("user_permissions", r.context["adminform"].form.fields)  # not even their own
        customer = User.objects.create_user("cust", "cust@x.com")
        r = self.client.get(f"/admin/auth/user/{customer.pk}/change/")
        choices = r.context["adminform"].form.fields["user_permissions"].queryset
        self.assertIn(perm("shop.change_order"), choices)
        self.assertNotIn(perm("shop.delete_product"), choices)

    def test_only_staff_added_on_the_staff_page_can_log_in_to_the_admin(self):
        customer = User.objects.create_user("cust", "cust@x.com", "pass-1234-word")
        with self.assertRaises(AssertionError):
            admin_login(self.client, customer)  # right password and code, but not staff
        self.as_owner()
        r = self.client.post(f"/admin/auth/user/{customer.pk}/change/", {
            "username": "cust", "email": "cust@x.com", "is_staff": "on", "is_active": "on",
            "date_joined_0": "2026-01-01", "date_joined_1": "00:00:00", "orders-TOTAL_FORMS": "0",
            "orders-INITIAL_FORMS": "0"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.get(pk=customer.pk).is_staff)  # the Users page can't make staff
        self.client.post("/admin/staff/", {"email": "cust@x.com"})
        self.assertTrue(User.objects.get(pk=customer.pk).is_staff)
        self.client.logout()
        admin_login(self.client, customer)

    # Staff page

    def test_staff_page_needs_permission_to_change_users(self):
        helper = User.objects.create_user("helper", "h@x.com", "pass-1234-word", is_staff=True)
        admin_login(self.client, helper)
        self.assertEqual(self.client.get("/admin/staff/").status_code, 403)
        self.client.logout()
        self.as_owner()
        self.assertContains(self.client.get("/admin/staff/"), "clerk@x.com")

    def test_every_permission_box_explains_itself(self):
        from .staff import GENERIC_HELP, PERM_HELP
        self.as_owner()
        page = self.client.get("/admin/staff/")
        boxes = [c for row in page.context["grid"] for c in [*row["cells"], *row["parts"]] if c]
        self.assertTrue(boxes)
        self.assertFalse([c for c in boxes if c["help"] in GENERIC_HELP.values()])  # every section has its own text
        self.assertContains(page, 'role="tooltip"', count=len(boxes))
        self.assertContains(page, PERM_HELP[("shop", "order")]["delete"])
        orders = next(r for r in page.context["grid"] if r["label"] == "Orders")
        self.assertEqual([c["label"] for c in orders["parts"]], ["Mark shipped or delivered", "Cancel", "Fix delivery details"])

    # Parts of "change": each can be given alone

    def as_staff_with(self, *codes):
        self.clerk.user_permissions.set([perm(c) for c in codes])
        self.as_clerk()

    def test_shipping_only_staff_ship_but_cannot_cancel_or_edit_delivery(self):
        self.as_staff_with("shop.view_order", "shop.ship_order")
        url = f"/admin/shop/order/{self.order.pk}/change/"
        form = self.client.get(url).context["adminform"].form
        self.assertNotIn("address", form.fields)
        self.assertEqual([k for k, _ in form.fields["status"].choices], ["pending", "shipped", "delivered"])
        self.assertContains(self.client.post(url, self.order_form(status="cancelled")), "Select a valid choice")
        act = lambda a: self.client.post("/admin/shop/order/", {"action": a, "_selected_action": [self.order.pk]})
        act("mark_cancelled")  # not offered to them: refused
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "pending")
        act("mark_shipped")
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "shipped")

    def test_cancel_only_staff_can_only_cancel(self):
        self.as_staff_with("shop.view_order", "shop.cancel_order")
        url = f"/admin/shop/order/{self.order.pk}/change/"
        form = self.client.get(url).context["adminform"].form
        self.assertEqual([k for k, _ in form.fields["status"].choices], ["pending", "cancelled"])
        self.assertEqual(self.client.post(url, self.order_form(status="cancelled")).status_code, 302)
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "cancelled")

    def test_delivery_only_staff_fix_the_address_but_not_the_status(self):
        self.as_staff_with("shop.edit_order_delivery")
        url = f"/admin/shop/order/{self.order.pk}/change/"
        self.assertNotIn("status", self.client.get(url).context["adminform"].form.fields)
        self.assertEqual(self.client.post(url, self.order_form(address="New road 9")).status_code, 302)
        self.assertEqual(Order.objects.get(pk=self.order.pk).address, "New road 9")

    def test_staff_who_see_orders_see_their_items(self):
        p = Product.objects.create(category=Category.objects.create(name="C", slug="c"), name="P", slug="p",
                                   price=50, image="https://x.y/a.jpg", stock=3)
        self.order.items.create(product=p, name="P", price=50, quantity=2)
        self.as_staff_with("shop.view_order")
        self.assertContains(self.client.get(f"/admin/shop/order/{self.order.pk}/change/"), "Line total")

    def test_price_only_staff_change_prices_and_nothing_else(self):
        p = Product.objects.create(category=Category.objects.create(name="C", slug="c"), name="P", slug="p",
                                   price=50, image="https://x.y/a.jpg", stock=3)
        self.as_staff_with("shop.view_product", "shop.edit_product_price")
        page = self.client.get(f"/admin/shop/product/{p.pk}/change/")
        self.assertEqual(set(page.context["adminform"].form.fields), {"price", "original_price"})
        inlines = {f.formset.prefix: f for f in page.context["inline_admin_formsets"]}
        self.assertFalse(inlines["photos"].has_change_permission)
        self.assertFalse(inlines["comments"].has_delete_permission)
        self.assertTrue(inlines["variants"].has_change_permission)
        mgmt = {f"{k}-{n}": 0 for k in ("photos", "options", "variants", "comments") for n in ("TOTAL_FORMS", "INITIAL_FORMS")}
        r = self.client.post(f"/admin/shop/product/{p.pk}/change/", {**mgmt, "price": 40, "name": "Hacked"})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual((p.price, p.name, p.stock), (40, "P", 3))
        r = self.client.post("/admin/shop/product/", {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1, "form-0-id": p.pk,
                                                      "form-0-price": 30, "form-0-stock": 99, "_save": "Save"})
        p.refresh_from_db()
        self.assertEqual((p.price, p.stock), (30, 3))  # the list page's stock column is locked too

    def test_part_shows_in_the_staff_list(self):
        self.as_staff_with("shop.view_order", "shop.cancel_order", "auth.change_user")
        self.assertContains(self.client.get("/admin/staff/"), "Orders: view, cancel")

    def test_invite_by_email_then_accept_makes_staff_with_those_permissions(self):
        self.as_owner()
        r = self.client.post("/admin/staff/", {"email": "New@X.com", "perms": [perm("shop.view_product").pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(mail.outbox[0].to, ["new@x.com"])
        link = urlparse(next(w for w in mail.outbox[0].body.split() if "/admin/staff/join/" in w)).path
        self.client.logout()
        page = self.client.get(link)
        self.assertContains(page, "new@x.com")
        key = self.client.session["staff_invite"]["key"]
        t = TOTPDevice(key=key)
        code = format(TOTP(t.bin_key, t.step, t.t0, t.digits).token(), "06d")
        form = {"username": "newbie", "password1": "a-good-pass-1234", "password2": "a-good-pass-1234"}
        self.assertContains(self.client.post(link, {**form, "code": "000000" if code != "000000" else "111111"}), "wrong")
        r = self.client.post(link, {**form, "code": code})
        self.assertEqual(r.status_code, 302)
        newbie = User.objects.get(username="newbie")
        self.assertTrue(newbie.is_staff and not newbie.is_superuser)
        self.assertEqual(newbie.get_all_permissions(), {"shop.view_product"})
        self.assertFalse(StaffInvite.objects.exists())
        self.assertEqual(self.client.get(link).status_code, 404)  # single use
        admin_login(self.client, newbie, "a-good-pass-1234")  # the device from the invite works

    def test_invite_link_expires(self):
        self.as_owner()
        self.client.post("/admin/staff/", {"email": "late@x.com"})
        link = urlparse(next(w for w in mail.outbox[0].body.split() if "/admin/staff/join/" in w)).path
        StaffInvite.objects.update(sent=timezone.now() - timedelta(days=4))
        self.assertEqual(self.client.get(link).status_code, 404)

    def test_resend_replaces_the_old_link(self):
        self.as_owner()
        self.client.post("/admin/staff/", {"email": "again@x.com"})
        invite = StaffInvite.objects.get()
        self.client.post(f"/admin/staff/invite/{invite.pk}/", {"action": "resend"})
        old, new = [urlparse(next(w for w in m.body.split() if "/admin/staff/join/" in w)).path for m in mail.outbox]
        self.assertEqual(self.client.get(old).status_code, 404)
        self.assertEqual(self.client.get(new).status_code, 200)

    def test_existing_customer_email_becomes_staff_at_once(self):
        customer = User.objects.create_user("cust", "cust@x.com")
        self.as_owner()
        self.client.post("/admin/staff/", {"email": "CUST@x.com", "perms": [perm("shop.view_order").pk]})
        customer.refresh_from_db()
        self.assertTrue(customer.is_staff)
        self.assertEqual(customer.get_all_permissions(), {"shop.view_order"})
        self.assertEqual(mail.outbox, [])

    @override_settings(DEBUG=True)
    def test_in_development_new_email_becomes_staff_without_invite(self):
        User.objects.create_user("new", "other@x.com")
        self.as_owner()
        self.client.post("/admin/staff/", {"email": "New@X.com", "perms": [perm("shop.view_product").pk]})
        user = User.objects.get(email="new@x.com")
        self.assertEqual(user.username, "new2")  # "new" is taken
        self.assertTrue(user.is_staff and not user.is_superuser and user.has_usable_password())
        self.assertEqual(user.get_all_permissions(), {"shop.view_product"})
        self.assertEqual(mail.outbox, [])
        self.assertFalse(StaffInvite.objects.exists())

    def test_staff_manager_cannot_grant_more_than_they_hold(self):
        self.as_clerk()
        self.client.post("/admin/staff/", {"email": "pal@x.com",
                                           "perms": [perm("shop.view_order").pk, perm("shop.delete_product").pk]})
        self.assertEqual({f"{p.content_type.app_label}.{p.codename}" for p in StaffInvite.objects.get().permissions.all()},
                         {"shop.view_order"})

    def test_staff_cannot_change_their_own_access_or_someone_above_them(self):
        boss2 = User.objects.create_user("lead", "lead@x.com", is_staff=True)
        boss2.user_permissions.set([perm("shop.delete_product")])
        self.as_clerk()
        self.assertEqual(self.client.post(f"/admin/staff/{self.clerk.pk}/", {"action": "remove"}).status_code, 403)
        self.assertEqual(self.client.post(f"/admin/staff/{boss2.pk}/", {"action": "remove"}).status_code, 403)
        self.assertEqual(self.client.post(f"/admin/staff/{self.owner.pk}/", {"action": "remove"}).status_code, 404)

    def test_owner_edits_and_removes_staff(self):
        self.as_owner()
        self.client.post(f"/admin/staff/{self.clerk.pk}/", {"perms": [perm("shop.view_order").pk]})
        self.assertEqual(User.objects.get(pk=self.clerk.pk).get_all_permissions(), {"shop.view_order"})
        self.client.post(f"/admin/staff/{self.clerk.pk}/", {"action": "remove"})
        clerk = User.objects.get(pk=self.clerk.pk)
        self.assertFalse(clerk.is_staff)
        self.assertEqual(clerk.get_all_permissions(), set())

    # Orders: the owner may break the rules, after a warning

    def order_form(self, **changes):
        o = self.order
        data = {"status": o.status, "full_name": o.full_name, "phone": o.phone, "email": o.email,
                "address": o.address, "city": o.city, "items-TOTAL_FORMS": "0", "items-INITIAL_FORMS": "0"}
        if self.client.session.get("_auth_user_id") == str(self.owner.pk):
            data.update(user="", payment=o.payment, subtotal=o.subtotal, delivery_fee=o.delivery_fee, total=o.total)
        return {**data, **changes}

    def test_staff_still_cannot_delete_orders(self):
        self.clerk.user_permissions.add(perm("shop.delete_order"))
        self.as_clerk()
        self.assertEqual(self.client.post(f"/admin/shop/order/{self.order.pk}/delete/", {"post": "yes"}).status_code, 403)
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())

    def test_owner_deleting_a_pending_order_puts_stock_back(self):
        cat = Category.objects.create(name="C", slug="c")
        p = Product.objects.create(category=cat, name="P", slug="p", price=50, image="https://x.y/a.jpg", stock=3)
        self.order.items.create(product=p, name="P", price=50, quantity=2)
        self.as_owner()
        self.assertContains(self.client.get(f"/admin/shop/order/{self.order.pk}/delete/"), "Owner only")
        self.client.post(f"/admin/shop/order/{self.order.pk}/delete/", {"post": "yes"})
        self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())
        self.assertEqual(Product.objects.get(pk=p.pk).stock, 5)

    def test_owner_edits_money_only_after_ticking_the_warning(self):
        self.as_owner()
        url = f"/admin/shop/order/{self.order.pk}/change/"
        self.assertContains(self.client.post(url, self.order_form(total=999)), "breaks the order rules")
        self.assertEqual(Order.objects.get(pk=self.order.pk).total, 160)
        self.assertEqual(self.client.post(url, self.order_form(total=999, confirm_override="on")).status_code, 302)
        self.assertEqual(Order.objects.get(pk=self.order.pk).total, 999)

    def test_owner_can_reopen_a_cancelled_order_after_the_warning(self):
        Order.objects.filter(pk=self.order.pk).update(status="cancelled")
        self.order.refresh_from_db()
        self.as_owner()
        url = f"/admin/shop/order/{self.order.pk}/change/"
        self.assertContains(self.client.post(url, self.order_form(status="pending")), "breaks the order rules")
        self.assertEqual(self.client.post(url, self.order_form(status="pending", confirm_override="on")).status_code, 302)
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "pending")

    def test_plain_status_change_needs_no_tick(self):
        self.as_owner()
        r = self.client.post(f"/admin/shop/order/{self.order.pk}/change/", self.order_form(status="shipped"))
        self.assertEqual(r.status_code, 302)

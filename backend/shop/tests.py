import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from .admin import change
from .display import cdn, day, num, taka
from .models import Category, Order, Product
from .serializers import RegisterSerializer
from .api.accounts import SignupThrottle
from .auth import GuestOrderThrottle

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
        self.assertEqual((r.data["status_display"], r.data["payment_display"]), ("Pending", "Cash on delivery"))
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
        # List payloads carry tiles only: no long description or nested category per product.
        tile = self.client.get("/api/products/").data["results"][0]
        self.assertFalse({"description", "category"} & tile.keys())

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
        o = self.checkout().data
        self.assertEqual(o["total_line"], "Total ৳260 (incl. ৳60 delivery)")
        self.assertEqual((o["title"], o["items"][0]["qty_line"]), (f"Order #{o['id']}", "2 × ৳100"))
        self.assertEqual(o["notice"], f"✓ Order #{o['id']} placed. Keep cash ready for the rider.")
        self.assertTrue(o["meta_line"].endswith(" · Dhaka · Cash on delivery"))
        self.assertEqual(p["discount_label"], "25% off")
        self.assertEqual(o["created_display"], day(Order.objects.get(pk=o["id"]).created))
        self.assertEqual(self.client.get("/api/home/").data["wall"][0][0].keys(), {"tag", "field"})

    def test_config_lists_cities_and_sorts(self):
        c = self.client.get("/api/config/").data
        self.assertEqual(c["cities"][0], "Dhaka")  # the checkout's default
        self.assertEqual(c["payments"], [{"value": "cod", "label": "Cash on delivery", "hint": "Pay the rider when it arrives"}])
        self.assertEqual(c["sorts"][0], {"value": "", "label": "Newest"})
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
        codes = [self.login("wrong", f"10.0.0.{i}").status_code for i in range(5)]
        self.assertEqual(codes, [400] * 5)  # each IP is under its own per-minute throttle
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1").status_code, 429)  # even the right password waits
        self.assertEqual(self.login("pass-1234-word", "10.0.1.2", username="RAHIM").status_code, 429)

    def test_successful_login_resets_the_failure_count(self):
        for i in range(4):
            self.login("wrong", f"10.0.0.{i}")
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1").status_code, 200)
        self.assertEqual(self.login("wrong", "10.0.1.2").status_code, 400)  # counting starts again

    def test_padded_or_unicode_spellings_share_the_lockout(self):
        # Both logins strip spaces (and the admin applies NFKC) before checking, so these all guess "rahim".
        for i, name in enumerate([" rahim", "rahim ", "\trahim", "ｒａｈｉｍ", "  rahim  "]):
            self.login("wrong", f"10.0.0.{i}", username=name)
        self.assertEqual(self.login("pass-1234-word", "10.0.1.1").status_code, 429)

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
            codes = [self.client.post("/api/auth/register/", {"username": f"u{i}", "password": "pass-1234-word"}).status_code
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

    def test_orders_cannot_be_deleted_in_admin(self):
        self.login(code=self.code())
        o = Order.objects.create(user=self.admin, full_name="X", phone="01712345678", address="A", city="Dhaka",
                                 subtotal=100, delivery_fee=60, total=160)
        self.assertEqual(self.client.post(f"/admin/shop/order/{o.pk}/delete/", {"post": "yes"}).status_code, 403)
        self.assertTrue(Order.objects.filter(pk=o.pk).exists())

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

    def test_order_money_is_read_only(self):
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

    def test_new_account_claims_no_guest_orders(self):
        r = self.order()
        reg = self.client.post("/api/auth/register/", {"username": "karim", "password": "pass-1234-word"}, format="json")
        self.assertEqual(reg.status_code, 201, reg.data)
        self.assertEqual(Order.objects.get(pk=r.data["id"]).user, None)  # no past phone to match yet

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

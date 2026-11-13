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

from .models import Category, Order, Product
from .serializers import RegisterSerializer
from .views import SignupThrottle

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
        self.assertEqual((c["free_delivery_left"], c["free_delivery_progress"]), (99, 67))
        self.assertEqual(c["lines"][0]["line_total"], 200)
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

    def test_orders_need_login_and_are_private(self):
        self.order((self.case, 1))
        other = User.objects.create_user("karim", password="pass-1234-word")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get("/api/orders/").data, [])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/orders/").status_code, 401)

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
        self.assertEqual({m["slug"]: m["count"] for m in h["menu"]}, {"mobiles": 2, "rice": 2})

    def test_config_lists_cities_and_sorts(self):
        c = self.client.get("/api/config/").data
        self.assertIn("Dhaka", c["cities"])
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

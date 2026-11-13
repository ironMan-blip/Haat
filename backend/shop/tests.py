from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import Category, Order, Product

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

    def order(self, *lines, **addr):
        for p, q in lines:
            self.add(p, q)
        return self.client.post("/api/orders/", {**ADDR, **addr}, format="json")

    def test_order_uses_db_prices_decrements_stock_and_empties_cart(self):
        self.client.post("/api/cart/", {"product": self.phone.pk, "quantity": 2, "price": 1}, format="json")
        r = self.client.post("/api/orders/", ADDR, format="json")
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
        Product.objects.filter(pk=self.phone.pk).update(stock=2)  # someone else bought one meanwhile
        r = self.client.post("/api/orders/", ADDR, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cart", r.data)
        self.assertEqual(Order.objects.count(), 0)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 10)

    def test_bad_phone_rejected(self):
        r = self.order((self.case, 1), phone="12345")
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.data)

    def test_empty_cart_rejected(self):
        r = self.client.post("/api/orders/", ADDR, format="json")
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
        self.assertEqual(len(self.client.get("/api/products/?q=case").data), 1)
        self.assertEqual(len(self.client.get("/api/products/?category=mobiles").data), 2)
        self.assertEqual(self.client.get("/api/products/?sort=price").data[0]["slug"], "case")

    def test_product_derived_fields(self):
        Product.objects.filter(pk=self.phone.pk).update(original_price=20000, description="6GB RAM\n\n128GB\n5000mAh")
        p = self.client.get("/api/products/phone/").data
        self.assertEqual((p["discount"], p["stock_level"], p["max_qty"]), (25, "low", 3))
        self.assertEqual(p["specs"], ["6GB RAM", "128GB", "5000mAh"])
        self.assertEqual(p["summary"], "6GB RAM · 128GB")
        self.assertEqual([r["slug"] for r in p["related"]], ["case"])

    def test_home_sections(self):
        other = Category.objects.create(name="Rice", slug="rice")
        Product.objects.create(category=other, name="Rice", slug="rice", price=500, original_price=1000,
                               image="https://x.y/c.jpg", rating=4.5, reviews=100, stock=5)
        Product.objects.filter(pk=self.case.pk).update(rating=5, reviews=10)
        h = self.client.get("/api/home/").data
        self.assertEqual(h["deals"][0]["slug"], "rice")
        self.assertEqual([p["slug"] for p in h["best"]], ["rice", "case"])  # one per category
        self.assertEqual({m["slug"]: m["count"] for m in h["menu"]}, {"mobiles": 2, "rice": 1})

    def test_config_lists_cities_and_sorts(self):
        c = self.client.get("/api/config/").data
        self.assertIn("Dhaka", c["cities"])
        self.assertEqual(c["sorts"][0], {"value": "", "label": "Newest"})
        Product.objects.filter(pk=self.case.pk).update(rating=4)
        self.assertEqual(self.client.get("/api/config/").data["stamp"], self.case.image)  # best-rated photo

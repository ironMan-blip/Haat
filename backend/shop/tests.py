from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import Category, Order, Product

ADDR = {"full_name": "Rahim", "phone": "01712345678", "address": "House 1, Road 2", "city": "Dhaka"}


class ShopApiTests(APITestCase):
    def setUp(self):
        cat = Category.objects.create(name="Mobiles", slug="mobiles")
        self.phone = Product.objects.create(category=cat, name="Phone", slug="phone", price=15000, image="https://x.y/a.jpg", stock=3)
        self.case = Product.objects.create(category=cat, name="Case", slug="case", price=100, image="https://x.y/b.jpg", stock=10)
        self.user = User.objects.create_user("rahim", password="pass-1234-word")
        self.client.force_authenticate(self.user)

    def order(self, *lines):
        return self.client.post("/api/orders/", {**ADDR, "lines": [{"product": p.pk, "quantity": q} for p, q in lines]}, format="json")

    def test_order_uses_db_prices_and_decrements_stock(self):
        r = self.client.post("/api/orders/", {**ADDR, "lines": [{"product": self.phone.pk, "quantity": 2, "price": 1}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["subtotal"], r.data["delivery_fee"], r.data["total"]), (30000, 0, 30000))
        self.phone.refresh_from_db()
        self.assertEqual(self.phone.stock, 1)

    def test_delivery_fee_below_threshold(self):
        r = self.order((self.case, 2))
        self.assertEqual((r.data["subtotal"], r.data["delivery_fee"], r.data["total"]), (200, 60, 260))

    def test_oversell_rejected_and_nothing_saved(self):
        r = self.order((self.case, 1), (self.phone, 4))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.case.refresh_from_db()
        self.assertEqual(self.case.stock, 10)

    def test_bad_phone_and_empty_cart_rejected(self):
        r = self.client.post("/api/orders/", {**ADDR, "phone": "12345", "lines": []}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.data)
        self.assertIn("lines", r.data)

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

    def test_product_filters(self):
        self.assertEqual(len(self.client.get("/api/products/?q=case").data), 1)
        self.assertEqual(len(self.client.get("/api/products/?category=mobiles").data), 2)
        self.assertEqual(self.client.get("/api/products/?sort=price").data[0]["slug"], "case")

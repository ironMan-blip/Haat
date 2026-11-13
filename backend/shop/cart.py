"""Cart kept in the Django session, so guests can fill it before they log in."""
from django.conf import settings
from rest_framework import serializers

from .models import Product

KEY = "cart"


def delivery_fee(subtotal):
    return 0 if subtotal == 0 or subtotal >= settings.FREE_DELIVERY_MIN else settings.DELIVERY_FEE


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.items = self.session.get(KEY, {})  # {"<product pk>": qty}; session JSON keys are strings

    def _save(self):
        self.session[KEY] = self.items
        self.session.modified = True

    def set(self, product, qty):
        if product.max_qty < 1:
            raise serializers.ValidationError({"product": f"{product.name} is sold out."})
        self.items[str(product.pk)] = max(1, min(qty, product.max_qty))
        self._save()

    def add(self, product, qty):
        self.set(product, self.items.get(str(product.pk), 0) + qty)

    def remove(self, pk):
        self.items.pop(str(pk), None)
        self._save()

    def clear(self):
        self.items = {}
        self._save()

    def lines(self, products=Product.objects):
        """(product, qty) pairs, skipping products deleted since they were added."""
        found = products.in_bulk([int(pk) for pk in self.items])
        return [(found[int(pk)], qty) for pk, qty in self.items.items() if int(pk) in found]

    def data(self):
        lines = self.lines()
        subtotal = sum(p.price * q for p, q in lines)
        fee = delivery_fee(subtotal)
        free_min = settings.FREE_DELIVERY_MIN
        return {
            "lines": [{"id": p.pk, "slug": p.slug, "name": p.name, "image": p.image, "price": p.price,
                       "quantity": q, "max_qty": p.max_qty, "line_total": p.price * q} for p, q in lines],
            "count": sum(q for _, q in lines),
            "subtotal": subtotal,
            "delivery_fee": fee,
            "total": subtotal + fee,
            "free_delivery_left": max(0, free_min - subtotal),
            "free_delivery_progress": min(100, round(subtotal * 100 / free_min)),
        }

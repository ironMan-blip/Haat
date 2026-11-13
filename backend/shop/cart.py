"""Cart kept in the Django session, so guests can fill it before they log in."""
from django.conf import settings
from rest_framework import serializers

from .display import cdn, taka
from .models import Product

KEY = "cart"


def delivery_fee(subtotal):
    return 0 if subtotal == 0 or subtotal >= settings.FREE_DELIVERY_MIN else settings.DELIVERY_FEE


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.items = self.session.get(KEY, {})  # {"<product pk>": qty}; session JSON keys are strings
        self.notes = []  # what the cart changed on its own, shown to the buyer

    def _save(self):
        self.session[KEY] = self.items
        self.session.modified = True

    def set(self, product, qty):
        if product.max_qty < 1:
            raise serializers.ValidationError({"product": f"{product.name} is sold out."})
        if qty > product.max_qty:
            self.notes.append(f"Only {product.max_qty} of {product.name} can be in your cart.")
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
        """(product, qty) pairs. Stock may have dropped since the buyer added things, so this drops
        deleted or sold-out products and lowers quantities to what is left, noting each change."""
        found = products.in_bulk([int(pk) for pk in self.items])
        lines, before = [], dict(self.items)
        for pk, qty in before.items():
            p = found.get(int(pk))
            if p is None:  # deleted product
                del self.items[pk]
            elif p.max_qty < 1:
                del self.items[pk]
                self.notes.append(f"{p.name} sold out and was taken out of your cart.")
            else:
                if qty > p.max_qty:
                    qty = self.items[pk] = p.max_qty
                    self.notes.append(f"Only {qty} of {p.name} left, so your cart now has {qty}.")
                lines.append((p, qty))
        if self.items != before:
            self._save()
        return lines

    def data(self):
        lines = self.lines()
        subtotal = sum(p.price * q for p, q in lines)
        fee = delivery_fee(subtotal)
        free_min = settings.FREE_DELIVERY_MIN
        left = max(0, free_min - subtotal)
        return {
            "lines": [{"id": p.pk, "slug": p.slug, "name": p.name, "thumb": cdn(p.image, 200), "price": p.price,
                       "price_display": taka(p.price), "quantity": q, "max_qty": p.max_qty, "line_total": p.price * q,
                       "line_total_display": taka(p.price * q)} for p, q in lines],
            "count": sum(q for _, q in lines),
            "subtotal": subtotal,
            "subtotal_display": taka(subtotal),
            "delivery_fee": fee,
            "delivery_display": taka(fee) if fee else "Free",
            "total": subtotal + fee,
            "total_display": taka(subtotal + fee),
            "free_delivery_left": left,
            "free_delivery_progress": min(100, round(subtotal * 100 / free_min)) if free_min else 100,
            "meter": f"Add {taka(left)} more for free delivery." if left else "Delivery is free on this order.",
            "notice": " ".join(self.notes) or None,
        }

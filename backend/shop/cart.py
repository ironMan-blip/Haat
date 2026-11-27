"""Cart kept in the Django session, so guests can fill it before they log in."""
from urllib.parse import parse_qsl

from django.conf import settings
from rest_framework import serializers

from .display import cdn, items, taka
from .models import Product, choice_key

KEY = "cart"
MAX_LINES = 30  # bounds the session row, the work on every cart read and how much one order can hold


def delivery_fee(subtotal):
    return 0 if subtotal == 0 or subtotal >= settings.FREE_DELIVERY_MIN else settings.DELIVERY_FEE


def line_key(product, variant):
    """One cart line per product, or per variant: "12" or "12?Color=Blue&Size=M"."""
    return f"{product.pk}?{variant.key}" if variant else str(product.pk)


def parse_key(key):
    pk, _, query = key.partition("?")
    return int(pk), dict(parse_qsl(query))


def pick(product, chosen):
    """The variant the buyer's choices name, checked against the product's options (one valid value for
    each, nothing else); None for a product without options. Needs options and variants prefetched."""
    options = product.options.all()
    if extra := set(chosen) - {o.name for o in options}:
        raise serializers.ValidationError({"options": f"{product.name} has no {', '.join(sorted(extra))} option."})
    for o in options:
        if (value := chosen.get(o.name)) is None:
            raise serializers.ValidationError({"options": f"Pick a {o.name.lower()} for {product.name}."})
        if value not in o.choices:
            raise serializers.ValidationError({"options": f"{value} is not a {o.name.lower()} of {product.name}."})
    if not options:
        return None
    key = choice_key(chosen)
    if variant := next((v for v in product.variants.all() if v.key == key), None):
        return variant
    raise serializers.ValidationError({"options": f"That choice of {product.name} isn't sold."})


def unit_price(product, variant):
    return variant.unit_price if variant else product.price


def max_qty(product, variant):
    return variant.max_qty if variant else product.max_qty


def describe(product, variant):
    return f"{product.name} ({variant.label})" if variant else product.name


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.items = self.session.get(KEY, {})  # {line_key: qty}; see line_key
        self.notes = []  # what the cart changed on its own, shown to the buyer

    def _save(self):
        self.session[KEY] = self.items
        self.session.modified = True

    def set(self, product, variant, qty):
        cap, name = max_qty(product, variant), describe(product, variant)
        if cap < 1:
            raise serializers.ValidationError({"product": f"{name} is sold out."})
        if line_key(product, variant) not in self.items and len(self.items) >= MAX_LINES:
            raise serializers.ValidationError({"product": f"Your cart holds at most {MAX_LINES} different items."})
        if qty > cap:
            self.notes.append(f"Only {cap} of {name} can be in your cart.")
        self.items[line_key(product, variant)] = max(1, min(qty, cap))
        self._save()

    def add(self, product, variant, qty):
        self.set(product, variant, self.items.get(line_key(product, variant), 0) + qty)

    def remove(self, key):
        self.items.pop(key, None)
        self._save()

    def clear(self):
        self.items = {}
        self._save()

    def lines(self, products=Product.objects):
        """(key, product, variant, qty) per line. Stock or options may have changed since the buyer added
        things, so this drops deleted or sold-out products and lines whose choices no longer exist, and
        lowers quantities to what is left, noting each change."""
        found = products.prefetch_related("options", "variants").in_bulk({parse_key(k)[0] for k in self.items})
        lines, before = [], dict(self.items)
        for key, qty in before.items():
            pk, chosen = parse_key(key)
            p = found.get(pk)
            if p is None:  # deleted product
                del self.items[key]
                continue
            try:
                v = pick(p, chosen)
            except serializers.ValidationError:
                del self.items[key]
                self.notes.append(f"The choices for {p.name} changed, so it was taken out of your cart. Pick them again.")
                continue
            cap, name = max_qty(p, v), describe(p, v)
            if cap < 1:
                del self.items[key]
                self.notes.append(f"{name} sold out and was taken out of your cart.")
                continue
            if qty > cap:
                qty = self.items[key] = cap
                self.notes.append(f"Only {qty} of {name} left, so your cart now has {qty}.")
            lines.append((key, p, v, qty))
        if self.items != before:
            self._save()
        return lines

    def data(self):
        lines = self.lines()
        subtotal = sum(unit_price(p, v) * q for _, p, v, q in lines)
        fee = delivery_fee(subtotal)
        free_min = settings.FREE_DELIVERY_MIN
        left = max(0, free_min - subtotal)
        count = sum(q for *_, q in lines)
        return {
            "lines": [{"id": key, "slug": p.slug, "name": p.name, "thumb": cdn(p.image, 200),
                       "options_line": v.label if v else None,
                       "each_line": f"{taka(unit_price(p, v))} each", "quantity": q, "max_qty": max_qty(p, v),
                       "line_total_display": taka(unit_price(p, v) * q),
                       "qty_label": f"Quantity of {p.name}", "remove_label": f"Remove {p.name}"} for key, p, v, q in lines],
            "count": count,
            "count_label": f"Cart, {items(count)}",  # the header's cart link
            "subtotal": subtotal,
            "subtotal_display": taka(subtotal),
            "delivery_fee": fee,
            "delivery_display": taka(fee) if fee else "Free",
            "total": subtotal + fee,
            "total_display": taka(subtotal + fee),
            "free_delivery_progress": min(100, round(subtotal * 100 / free_min)) if free_min else 100,
            "meter": f"Add {taka(left)} more for free delivery." if left else "Delivery is free on this order.",
            "notice": " ".join(self.notes) or None,
        }

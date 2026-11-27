"""Cart kept in the Django session, so guests can fill it before they log in."""
from urllib.parse import parse_qsl, urlencode

from django.conf import settings
from rest_framework import serializers

from .display import cdn, items, taka
from .models import Product

KEY = "cart"


def delivery_fee(subtotal):
    return 0 if subtotal == 0 or subtotal >= settings.FREE_DELIVERY_MIN else settings.DELIVERY_FEE


def line_key(product, chosen):
    """One cart line per product and set of choices: "12" or "12?Color=Blue&Size=M"."""
    return f"{product.pk}?{urlencode(sorted(chosen.items()))}" if chosen else str(product.pk)


def parse_key(key):
    pk, _, query = key.partition("?")
    return int(pk), dict(parse_qsl(query))


def pick(product, chosen):
    """The buyer's choices, checked against the product's options: one valid value for each, nothing else."""
    options = product.options.all()
    if extra := set(chosen) - {o.name for o in options}:
        raise serializers.ValidationError({"options": f"{product.name} has no {', '.join(sorted(extra))} option."})
    for o in options:
        if (value := chosen.get(o.name)) is None:
            raise serializers.ValidationError({"options": f"Pick a {o.name.lower()} for {product.name}."})
        if value not in o.choices:
            raise serializers.ValidationError({"options": f"{value} is not a {o.name.lower()} of {product.name}."})
    return dict(chosen)


def options_line(product, chosen):
    """What the buyer chose, in the product's option order: "Size: M · Color: Blue"."""
    return " · ".join(f"{o.name}: {chosen[o.name]}" for o in product.options.all() if o.name in chosen)


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.items = self.session.get(KEY, {})  # {line_key: qty}; see line_key
        self.notes = []  # what the cart changed on its own, shown to the buyer

    def _save(self):
        self.session[KEY] = self.items
        self.session.modified = True

    def room(self, product, key):
        """How many more of this product this line may hold: the stock cap is per product, across its lines."""
        others = sum(q for k, q in self.items.items() if k != key and parse_key(k)[0] == product.pk)
        return product.max_qty - others

    def set(self, product, chosen, qty):
        key = line_key(product, chosen)
        if product.max_qty < 1:
            raise serializers.ValidationError({"product": f"{product.name} is sold out."})
        room = self.room(product, key)
        if room < 1:
            raise serializers.ValidationError(
                {"product": f"Only {product.max_qty} of {product.name} can be in your cart, and they already are."})
        if qty > room:
            self.notes.append(f"Only {product.max_qty} of {product.name} can be in your cart.")
        self.items[key] = max(1, min(qty, room))
        self._save()

    def add(self, product, chosen, qty):
        self.set(product, chosen, self.items.get(line_key(product, chosen), 0) + qty)

    def remove(self, key):
        self.items.pop(key, None)
        self._save()

    def clear(self):
        self.items = {}
        self._save()

    def lines(self, products=Product.objects):
        """(key, product, choices, qty, room) per line. Stock or options may have changed since the buyer
        added things, so this drops deleted or sold-out products and lines whose choices no longer exist,
        and lowers quantities to what is left, noting each change."""
        found = products.prefetch_related("options").in_bulk({parse_key(k)[0] for k in self.items})
        lines, before, used = [], dict(self.items), {}
        for key, qty in before.items():
            pk, chosen = parse_key(key)
            p = found.get(pk)
            if p is None:  # deleted product
                del self.items[key]
                continue
            try:
                pick(p, chosen)
            except serializers.ValidationError:
                del self.items[key]
                self.notes.append(f"The choices for {p.name} changed, so it was taken out of your cart. Pick them again.")
                continue
            room = p.max_qty - used.get(pk, 0)
            if room < 1:
                del self.items[key]
                self.notes.append(f"{p.name} sold out and was taken out of your cart.")
                continue
            if qty > room:
                qty = self.items[key] = room
                self.notes.append(f"Only {qty} of {p.name} left, so your cart now has {qty}.")
            used[pk] = used.get(pk, 0) + qty
            lines.append((key, p, chosen, qty, room))
        if self.items != before:
            self._save()
        return lines

    def data(self):
        lines = self.lines()
        subtotal = sum(p.price * q for _, p, _, q, _ in lines)
        fee = delivery_fee(subtotal)
        free_min = settings.FREE_DELIVERY_MIN
        left = max(0, free_min - subtotal)
        count = sum(q for *_, q, _ in lines)
        return {
            "lines": [{"id": key, "slug": p.slug, "name": p.name, "thumb": cdn(p.image, 200),
                       "options_line": options_line(p, chosen) or None,
                       "each_line": f"{taka(p.price)} each", "quantity": q, "max_qty": room,
                       "line_total_display": taka(p.price * q)} for key, p, chosen, q, room in lines],
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

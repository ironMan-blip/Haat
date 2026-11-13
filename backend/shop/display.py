"""How the shop writes numbers, money, dates and image links. The API and the admin both use these,
so the React app only shows what it is sent."""
import re

from django.utils import timezone

DARAZ = re.compile(r"^https://[^/]+\.(slatic\.net|daraz\.com\.bd)/")


def num(n):
    """Bangladeshi digit grouping: 1234567 -> "12,34,567"."""
    return re.sub(r"\B(?=(\d{2})*\d{3}$)", ",", str(n or 0))


def taka(n):
    return f"৳{num(n)}"


def cdn(url, size):
    """Daraz CDN serves resized copies via a filename suffix; other hosts get the original."""
    return f"{url}_{size}x{size}q75.jpg" if DARAZ.match(url or "") else url


def day(dt):
    """"13 Nov 2026", in the shop's time zone."""
    dt = timezone.localtime(dt)
    return f"{dt.day} {dt:%b %Y}"


def images(url):
    """The sizes the shop's pages show: thumb in lists and the cart, image on tiles, image_large on big panels."""
    return {"thumb": cdn(url, 200), "image": cdn(url, 400), "image_large": cdn(url, 800)}

import html
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from shop.models import Category, Product

DATA = Path(__file__).resolve().parents[2] / "fixtures" / "daraz_products.json"
# Daraz copy is full of emoji, HTML entities, markdown and escaped unicode; the store shows plain text.
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def clean(text):
    text = html.unescape(text)
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"<[^>]+>|[\w.-]+\s*\{[^}]*\}|[*#]+", "", EMOJI.sub("", text))  # tags, leaked CSS, markdown
    return re.sub(r"[ \t]{2,}", " ", text).strip(" -•\t")


class Command(BaseCommand):
    help = "Sync sample products (Daraz listings, images hotlinked) into the catalogue."

    @transaction.atomic
    def handle(self, *args, **opts):
        rows = json.loads(DATA.read_text())
        seen, slugs = set(), []
        for i, row in enumerate(rows, 1):
            name = clean(row["name"])
            if name.lower() in seen:
                continue  # Daraz search often repeats the same listing
            seen.add(name.lower())
            cat, _ = Category.objects.get_or_create(name=row["category"], defaults={"slug": slugify(row["category"])})
            slug = f"{slugify(name)[:200].strip('-')}-{i}"
            slugs.append(slug)
            Product.objects.update_or_create(slug=slug, defaults={
                "category": cat, "name": name,
                "description": "\n".join(filter(None, map(clean, re.split(r"\n|•|\\u2022", row["description"])))),
                "price": row["price"], "original_price": row["original_price"], "image": row["image"],
                "rating": row["rating"], "reviews": row["reviews"], "stock": row["stock"],
            })
        # Drop old seed products that are gone from the file, unless someone ordered them.
        stale = Product.objects.exclude(slug__in=slugs).filter(orderitem__isnull=True)
        removed = stale.count()
        stale.delete()
        self.stdout.write(self.style.SUCCESS(f"{len(slugs)} products synced, {removed} stale removed"))

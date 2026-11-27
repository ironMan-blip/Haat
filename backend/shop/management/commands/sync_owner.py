import os

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

KEYS = ["OWNER_USERNAME", "OWNER_EMAIL", "OWNER_PASSWORD"]


def read_env(path):
    """KEY=VALUE lines of a .env file; blank lines and # comments skipped, surrounding quotes removed."""
    if not path.exists():
        return {}
    pairs = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key.strip()] = value.strip().strip("'\"")
    return pairs


class Command(BaseCommand):
    help = ("Make the account in OWNER_USERNAME/OWNER_EMAIL/OWNER_PASSWORD (backend/.env, or the environment) "
            "the shop's only owner. Any other owner loses owner powers. The password is only set when the "
            "account is new, or with --reset-password.")

    def add_arguments(self, parser):
        parser.add_argument("--reset-password", action="store_true", help="set the password from .env again")

    def handle(self, reset_password, **options):
        env = {**read_env(settings.BASE_DIR / ".env"), **{k: os.environ[k] for k in KEYS if k in os.environ}}
        username, email, password = (env.get(k, "").strip() for k in KEYS)
        if not username or not email:
            raise CommandError("Set OWNER_USERNAME and OWNER_EMAIL in backend/.env.")
        email = email.lower()
        if User.objects.filter(email__iexact=email).exclude(username=username).exists():
            raise CommandError(f"Another account already uses {email}.")
        user = User.objects.filter(username=username).first() or User(username=username)
        new = user.pk is None
        if new or reset_password:
            if not password:
                raise CommandError("Set OWNER_PASSWORD in backend/.env.")
            try:
                validate_password(password, User(username=username, email=email))
            except ValidationError as e:
                raise CommandError(" ".join(e.messages)) from None
            user.set_password(password)
        with transaction.atomic():
            # update() skips the one-owner check on purpose: the old owner goes before the new one is saved.
            demoted = list(User.objects.filter(is_superuser=True).exclude(username=username).values_list("username", flat=True))
            User.objects.filter(username__in=demoted).update(is_superuser=False, is_staff=False)  # back in only if the new owner adds them on the Staff page
            user.email, user.is_superuser, user.is_staff, user.is_active = email, True, True, True
            user.save()
        self.stdout.write(f"{'Created' if new else 'Updated'} owner {username!r}.")
        if demoted:
            self.stdout.write(f"No longer owner or staff (add them on the Staff page to let them back in):{', '.join(demoted)}.")
        if new:
            self.stdout.write("Next: you may delete OWNER_PASSWORD from .env.")

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Give a staff user an authenticator-app device; admin login requires its code."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--reset", action="store_true", help="replace an existing device (lost phone)")

    def handle(self, username, reset, **options):
        user = User.objects.filter(username=username, is_staff=True).first()
        if not user:
            raise CommandError(f"No staff user {username!r}.")
        devices = TOTPDevice.objects.filter(user=user)
        if devices.exists() and not reset:
            raise CommandError("This user already has a device. Pass --reset to replace it.")
        devices.delete()
        device = TOTPDevice.objects.create(user=user, name="authenticator", confirmed=True)
        self.stdout.write("Add this to an authenticator app (most accept the URL as a QR code or link):")
        self.stdout.write(device.config_url)
        self.stdout.write("Shown once. Anyone who sees it can generate this user's codes.")

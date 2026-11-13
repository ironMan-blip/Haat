from django.apps import AppConfig


class ShopConfig(AppConfig):
    name = 'shop'

    def ready(self):
        from . import auth  # noqa: F401 -- connects the password-change token revoke

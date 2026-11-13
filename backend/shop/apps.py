from django.apps import AppConfig


class ShopConfig(AppConfig):
    name = 'shop'
    verbose_name = 'Store'  # section title in the admin sidebar and dashboard

    def ready(self):
        from . import auth  # noqa: F401 -- connects the password-change token revoke

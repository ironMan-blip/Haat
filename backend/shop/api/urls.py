from django.urls import path

from . import accounts, catalog, checkout

urlpatterns = [
    path("config/", catalog.store_config),
    path("home/", catalog.home),
    path("products/", catalog.ProductList.as_view()),
    path("products/<slug:slug>/", catalog.ProductDetail.as_view()),
    path("cart/", checkout.cart),
    path("cart/<int:pk>/", checkout.cart_line),
    path("orders/", checkout.OrderListCreate.as_view()),
    path("auth/register/", accounts.Register.as_view()),
    path("auth/login/", accounts.Login.as_view()),
    path("auth/logout/", accounts.logout),
]

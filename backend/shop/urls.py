from django.urls import path

from . import views

urlpatterns = [
    path("config/", views.store_config),
    path("home/", views.home),
    path("cart/", views.cart),
    path("cart/<int:pk>/", views.cart_line),
    path("categories/", views.CategoryList.as_view()),
    path("products/", views.ProductList.as_view()),
    path("products/<slug:slug>/", views.ProductDetail.as_view()),
    path("auth/register/", views.Register.as_view()),
    path("auth/login/", views.Login.as_view()),
    path("auth/logout/", views.logout),
    path("auth/me/", views.me),
    path("orders/", views.OrderListCreate.as_view()),
]

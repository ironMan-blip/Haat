from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from . import views

urlpatterns = [
    path("config/", views.store_config),
    path("categories/", views.CategoryList.as_view()),
    path("products/", views.ProductList.as_view()),
    path("products/<slug:slug>/", views.ProductDetail.as_view()),
    path("auth/register/", views.Register.as_view()),
    path("auth/login/", obtain_auth_token),
    path("auth/me/", views.me),
    path("orders/", views.OrderListCreate.as_view()),
]

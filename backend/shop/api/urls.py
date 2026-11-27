from django.urls import path

from . import accounts, catalog, checkout

urlpatterns = [
    path("config/", catalog.store_config),
    path("home/", catalog.home),
    path("products/", catalog.ProductList.as_view()),
    path("products/<slug:slug>/", catalog.ProductDetail.as_view()),
    path("products/<slug:slug>/comments/", catalog.ProductComments.as_view()),
    path("comments/<int:pk>/", catalog.CommentDetail.as_view()),
    path("comments/<int:pk>/like/", catalog.like_comment),
    path("comments/<int:pk>/replies/", catalog.comment_replies),
    path("cart/", checkout.cart),
    path("cart/<path:key>/", checkout.cart_line),  # path: a chosen value may hold any character
    path("orders/", checkout.OrderListCreate.as_view()),
    path("auth/register/", accounts.Register.as_view()),
    path("auth/login/", accounts.Login.as_view()),
    path("auth/logout/", accounts.logout),
]

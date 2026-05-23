"""
JWT 认证端点：基于 django-rest-framework-simplejwt。

- POST /auth/token/ — 用户名+密码换取 access + refresh token
- POST /auth/token/refresh/ — 用 refresh token 获取新 access token
- POST /auth/token/verify/ — 验证 token 是否有效
"""

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

urlpatterns = [
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
]

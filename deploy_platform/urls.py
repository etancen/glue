"""根 URL 路由 — 所有 REST API 统一挂载到 /api/v1/ 前缀下。"""
from django.urls import path, include

urlpatterns = [
    path("api/v1/", include("core.urls")),       # DRF ViewSet 路由（plans, plugins, system）
    path("api/v1/", include("core.auth_urls")),  # JWT 认证端点（token, refresh, verify）
]

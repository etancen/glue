"""
REST API 路由配置：通过 DRF DefaultRouter 自动注册 ViewSet。

生成的路由：
- /api/plans/ — 部署计划 CRUD + 子资源
- /api/plugins/ — 插件列表 + 扫描
- /api/system/ — 健康检查 + Worker 状态
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import DeploymentPlanViewSet, PluginViewSet, SystemViewSet

router = DefaultRouter()
router.register(r"plans", DeploymentPlanViewSet, basename="plan")
router.register(r"plugins", PluginViewSet, basename="plugin")
router.register(r"system", SystemViewSet, basename="system")

urlpatterns = [
    path("", include(router.urls)),
]

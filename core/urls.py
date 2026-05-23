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

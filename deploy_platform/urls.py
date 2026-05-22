from django.urls import path, include

urlpatterns = [
    path("api/v1/", include("core.urls")),
    path("api/v1/", include("core.auth_urls")),
]

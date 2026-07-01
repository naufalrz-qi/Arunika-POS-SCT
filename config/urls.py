from django.urls import include, path

urlpatterns = [
    path("", include("apps.auth_app.urls")),
    path("admin-panel/", include("apps.monitoring.urls")),
    path("admin-panel/", include("apps.connections.urls")),
]

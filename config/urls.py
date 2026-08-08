from django.urls import include, path

urlpatterns = [
    path("", include("apps.auth_app.urls")),
    # Prefix terpisah dari admin-panel: lihat POS_PREFIX di apps/core/middleware.py.
    path("kasir/", include("apps.monitoring.urls_kasir")),
    path("admin-panel/", include("apps.monitoring.urls")),
    path("admin-panel/", include("apps.connections.urls")),
]

"""Rute /kasir/* — halaman harian kasir & supervisor."""
from django.urls import path

from apps.monitoring import views_kasir as v

urlpatterns = [
    path("stok", v.cek_stok, name="kasir_stok"),
]

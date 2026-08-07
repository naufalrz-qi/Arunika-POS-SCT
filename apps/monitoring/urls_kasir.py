"""Rute /kasir/* — halaman harian kasir & supervisor."""
from django.urls import path

from apps.monitoring import views_kasir as v

urlpatterns = [
    path("stok", v.cek_stok, name="kasir_stok"),
    path("penjualan", v.penjualan, name="kasir_penjualan"),
    path("penjualan/save", v.penjualan_save, name="kasir_penjualan_save"),
]

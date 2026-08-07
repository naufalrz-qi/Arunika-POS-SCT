"""Rute /kasir/* — halaman harian kasir & supervisor."""
from django.urls import path

from apps.monitoring import views_kasir as v

urlpatterns = [
    path("stok", v.cek_stok, name="kasir_stok"),
    path("pelanggan", v.pelanggan, name="kasir_pelanggan"),
    path("pelanggan/save", v.pelanggan_save, name="kasir_pelanggan_save"),
    path("supplier", v.supplier, name="kasir_supplier"),
    path("supplier/save", v.supplier_save, name="kasir_supplier_save"),
]

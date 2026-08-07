"""Rute /kasir/* — halaman harian kasir & supervisor."""
from django.urls import path

from apps.monitoring import views_kasir as v

urlpatterns = [
    path("stok", v.cek_stok, name="kasir_stok"),
    path("penjualan", v.penjualan, name="kasir_penjualan"),
    path("penjualan/save", v.penjualan_save, name="kasir_penjualan_save"),
    # Di bawah /kasir/penjualan supaya mewarisi kunci menu lewat pencocokan
    # prefix di menu_key_for_path — path yang tak cocok menu mana pun dianggap
    # bebas, dan keduanya membocorkan nama barang, harga, serta isi nota.
    path("penjualan/cari-barang", v.cari_barang_json, name="kasir_cari_barang"),
    path("penjualan/cari-customer", v.cari_customer_json, name="kasir_cari_customer"),
    path("penjualan/<str:no_transaksi>/cetak", v.nota_cetak, name="kasir_nota_cetak"),
    path("penjualan-retur", v.retur_penjualan, name="kasir_retur_penjualan"),
    path("penjualan-retur/save", v.retur_penjualan_save, name="kasir_retur_penjualan_save"),
    path("pembelian", v.pembelian, name="kasir_pembelian"),
    path("pembelian/save", v.pembelian_save, name="kasir_pembelian_save"),
    path("pembelian-retur", v.retur_pembelian, name="kasir_retur_pembelian"),
    path("pembelian-retur/save", v.retur_pembelian_save, name="kasir_retur_pembelian_save"),
]

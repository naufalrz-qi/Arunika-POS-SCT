"""Rute /kasir/* — halaman harian kasir & supervisor."""
from django.urls import path

from apps.monitoring import views_kasir as v

urlpatterns = [
    path("stok", v.cek_stok, name="kasir_stok"),
    path("faktur", v.faktur, name="kasir_faktur"),
    path("penjualan", v.penjualan, name="kasir_penjualan"),
    path("penjualan/save", v.penjualan_save, name="kasir_penjualan_save"),
    path("penjualan/order", v.order_json, name="kasir_order"),
    path("penjualan/<str:no_transaksi>/cetak", v.nota_cetak, name="kasir_nota_cetak"),
    path("penjualan-order", v.penjualan_order, name="kasir_penjualan_order"),
    path("penjualan-order/save", v.penjualan_order_save, name="kasir_penjualan_order_save"),
    path("penjualan-retur", v.retur_penjualan, name="kasir_retur_penjualan"),
    path("penjualan-retur/save", v.retur_penjualan_save, name="kasir_retur_penjualan_save"),
    path("pembelian", v.pembelian, name="kasir_pembelian"),
    path("pembelian/save", v.pembelian_save, name="kasir_pembelian_save"),
    path("pembelian-retur", v.retur_pembelian, name="kasir_retur_pembelian"),
    path("pembelian-retur/save", v.retur_pembelian_save, name="kasir_retur_pembelian_save"),
]

# Pencarian barang/pelanggan dipasang ULANG di bawah setiap layar yang memakainya,
# bukan sekali di satu tempat bersama. Dua alasan, keduanya sudah pernah menggigit:
#
# 1. Izin diberikan per-prefix oleh menu_key_for_path. Satu endpoint bersama
#    di bawah /kasir/penjualan berarti orang yang cuma dapat menu Penjualan
#    Order (atau Retur) terpental saat mengetik di kotak carinya sendiri.
# 2. Path yang tak cocok menu mana pun dianggap BEBAS — dan endpoint ini
#    membocorkan nama barang, harga, serta isi nota.
for _layar in ("penjualan", "penjualan-order", "penjualan-retur",
               "pembelian", "pembelian-retur"):
    urlpatterns += [
        path(f"{_layar}/cari-barang", v.cari_barang_json,
             name=f"kasir_cari_barang_{_layar}"),
        path(f"{_layar}/satuan", v.satuan_json, name=f"kasir_satuan_{_layar}"),
    ]
for _layar in ("penjualan", "penjualan-order"):
    urlpatterns.append(
        path(f"{_layar}/cari-customer", v.cari_customer_json,
             name=f"kasir_cari_customer_{_layar}"))

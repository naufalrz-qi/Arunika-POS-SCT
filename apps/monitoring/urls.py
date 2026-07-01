from django.urls import path

from . import views

urlpatterns = [
    path("dashboard", views.dashboard, name="dashboard"),
    path("users", views.users_index, name="users"),
    path("users/save", views.users_save, name="users_save"),
    path("users/<int:user_id>/delete", views.users_delete, name="users_delete"),
    path("master/products", views.products_index, name="products"),
    path("master/products/save", views.products_save, name="products_save"),
    path("master/customers", views.customers_index, name="customers"),
    path("master/customers/save", views.customers_save, name="customers_save"),
    path("master/update-barang", views.update_barang_index, name="update_barang"),
    path("master/update-barang/harga", views.update_barang_harga, name="update_barang_harga"),
    path("master/update-barang/status", views.update_barang_status, name="update_barang_status"),
    path("master/sync-harga", views.sync_harga_index, name="sync_harga"),
    path("master/sync-harga/apply", views.sync_harga_apply, name="sync_harga_apply"),
    path("logs", views.logs_index, name="logs"),
    # Inventory
    path("inventory/stock", views.stock_index, name="stock"),
    path("inventory/histori", views.barang_histori_index, name="barang_histori"),
    path("inventory/stok-divisi", views.stok_divisi, name="stok_divisi"),
    path("inventory/stok-akhir", views.stok_akhir, name="stok_akhir"),
    path("inventory/opname", views.opname, name="opname"),
    # Laporan penjualan / pembelian
    path("laporan/penjualan", views.penjualan_all, name="penjualan_all"),
    path("laporan/penjualan-nota", views.penjualan_nota, name="penjualan_nota"),
    path("laporan/penjualan-customer", views.penjualan_customer, name="penjualan_customer"),
    path("laporan/penjualan-user", views.penjualan_user, name="penjualan_user"),
    path("laporan/penjualan-periode", views.penjualan_periode, name="penjualan_periode"),
    path("laporan/retur-penjualan", views.retur_penjualan, name="retur_penjualan"),
    path("laporan/pembelian", views.pembelian, name="pembelian"),
    path("laporan/retur-pembelian", views.retur_pembelian, name="retur_pembelian"),
    # Analitik (FMI)
    path("analitik/fmi-penjualan", views.fmi_penjualan, name="fmi_penjualan"),
    path("analitik/fmi-stok", views.fmi_stok, name="fmi_stok"),
    # Promo & Voucher
    path("promo/diskon", views.promo, name="promo"),
    path("promo/voucher", views.voucher, name="voucher"),
    # Kas & Shift
    path("kas/harian", views.kas_harian, name="kas"),
    path("kas/shift", views.shift, name="shift"),
    # Menu management (superadmin) + own profile
    path("menus", views.menus_index, name="menus"),
    path("menus/save", views.menus_save, name="menus_save"),
    path("profile", views.profile_view, name="profile"),
    path("profile/save", views.profile_save, name="profile_save"),
]

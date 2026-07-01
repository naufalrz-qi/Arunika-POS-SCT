"""Admin menu registry (single source of truth for sidebar + RBAC filtering)."""

# Section order + display labels for the collapsible sidebar groups.
SECTIONS = ["ringkasan", "penjualan", "pembelian", "stok", "analitik", "promo", "kas", "master", "admin"]
SECTION_LABELS = {
    "ringkasan": "Ringkasan",
    "penjualan": "Penjualan",
    "pembelian": "Pembelian",
    "stok": "Inventori & Stok",
    "analitik": "Analitik",
    "promo": "Promo & Voucher",
    "kas": "Kas & Shift",
    "master": "Master Data",
    "admin": "Administrasi",
}

ALL_MENUS = [
    {"key": "dashboard", "label": "Dashboard", "icon": "dashboard", "href": "/admin-panel/dashboard", "section": "ringkasan"},
    # Penjualan (laporan)
    {"key": "penjualan_all", "label": "Penjualan (Detail)", "icon": "cart", "href": "/admin-panel/laporan/penjualan", "section": "penjualan"},
    {"key": "penjualan_nota", "label": "Penjualan per Nota", "icon": "list", "href": "/admin-panel/laporan/penjualan-nota", "section": "penjualan"},
    {"key": "penjualan_customer", "label": "Penjualan per Customer", "icon": "user", "href": "/admin-panel/laporan/penjualan-customer", "section": "penjualan"},
    {"key": "penjualan_user", "label": "Penjualan per User", "icon": "users", "href": "/admin-panel/laporan/penjualan-user", "section": "penjualan"},
    {"key": "penjualan_periode", "label": "Penjualan per Periode", "icon": "calendar", "href": "/admin-panel/laporan/penjualan-periode", "section": "penjualan"},
    {"key": "retur_penjualan", "label": "Retur Penjualan", "icon": "refund", "href": "/admin-panel/laporan/retur-penjualan", "section": "penjualan"},
    # Pembelian
    {"key": "pembelian", "label": "Pembelian", "icon": "truck", "href": "/admin-panel/laporan/pembelian", "section": "pembelian"},
    {"key": "retur_pembelian", "label": "Retur Pembelian", "icon": "refund", "href": "/admin-panel/laporan/retur-pembelian", "section": "pembelian"},
    # Inventori & Stok
    {"key": "stock", "label": "Monitoring Stok", "icon": "box", "href": "/admin-panel/inventory/stock", "section": "stok"},
    {"key": "barang_histori", "label": "Barang Histori", "icon": "list", "href": "/admin-panel/inventory/histori", "section": "stok"},
    {"key": "stok_divisi", "label": "Stok per Divisi", "icon": "store", "href": "/admin-panel/inventory/stok-divisi", "section": "stok"},
    {"key": "stok_akhir", "label": "Stok Akhir per Tanggal", "icon": "cash", "href": "/admin-panel/inventory/stok-akhir", "section": "stok"},
    {"key": "opname", "label": "Opname Stok", "icon": "clipboard", "href": "/admin-panel/inventory/opname", "section": "stok"},
    # Analitik (FMI)
    {"key": "fmi_penjualan", "label": "FMI Penjualan", "icon": "trending", "href": "/admin-panel/analitik/fmi-penjualan", "section": "analitik"},
    {"key": "fmi_stok", "label": "FMI Stok", "icon": "chart", "href": "/admin-panel/analitik/fmi-stok", "section": "analitik"},
    # Promo & Voucher
    {"key": "promo", "label": "Promo & Diskon", "icon": "tag", "href": "/admin-panel/promo/diskon", "section": "promo"},
    {"key": "voucher", "label": "Voucher", "icon": "ticket", "href": "/admin-panel/promo/voucher", "section": "promo"},
    # Kas & Shift
    {"key": "kas", "label": "Kas Harian", "icon": "cash", "href": "/admin-panel/kas/harian", "section": "kas"},
    {"key": "shift", "label": "Shift Kasir", "icon": "clock", "href": "/admin-panel/kas/shift", "section": "kas"},
    # Master Data
    {"key": "products", "label": "Master Produk", "icon": "box", "href": "/admin-panel/master/products", "section": "master"},
    {"key": "customers", "label": "Master Pelanggan", "icon": "user", "href": "/admin-panel/master/customers", "section": "master"},
    {"key": "update_barang", "label": "Update Barang", "icon": "pencil", "href": "/admin-panel/master/update-barang", "section": "master"},
    {"key": "sync_harga", "label": "Sinkronisasi Harga", "icon": "refresh", "href": "/admin-panel/master/sync-harga", "section": "master"},
    # Administrasi
    {"key": "users", "label": "Manajemen User", "icon": "users", "href": "/admin-panel/users", "section": "admin"},
    {"key": "connections", "label": "Koneksi Server", "icon": "server", "href": "/admin-panel/connections", "section": "admin"},
    {"key": "logs", "label": "Log Aktivitas", "icon": "list", "href": "/admin-panel/logs", "section": "admin"},
    # Superadmin-only: cannot be granted to a regular admin.
    {"key": "menus", "label": "Kelola Menu", "icon": "key", "href": "/admin-panel/menus", "section": "admin", "superadmin_only": True},
]


def assignable_menus():
    """Menus a superadmin may grant/revoke for other users (excludes superadmin-only)."""
    return [m for m in ALL_MENUS if not m.get("superadmin_only")]


def menus_for(user):
    """Return the menu list visible to `user` (PRD §4.3/§4.4)."""
    from apps.auth_app.models import Role

    if not user or not user.is_authenticated:
        return []
    if user.role == Role.SUPERADMIN:
        return ALL_MENUS  # full access, always
    if user.role == Role.ADMIN:
        # Default to all assignable menus when nothing is configured yet.
        keys = user.allowed_menu_keys or [m["key"] for m in assignable_menus()]
        allowed = set(keys)
        return [m for m in ALL_MENUS if not m.get("superadmin_only") and m["key"] in allowed]
    # Kasir / supervisor don't use the admin panel in this phase.
    return []

"""Admin menu registry (single source of truth for sidebar + RBAC filtering)."""

# Section order + display labels for the collapsible sidebar groups.
SECTIONS = [
    "pos", "ringkasan", "penjualan", "pembelian", "stok", "analitik", "promo", "kas",
    "master", "master_harga", "master_sync", "admin",
]
SECTION_LABELS = {
    # Menu harian kasir & supervisor. Bawaan peran mereka, bukan bawaan admin.
    "pos": "Kasir",
    "ringkasan": "Ringkasan",
    "penjualan": "Penjualan",
    "pembelian": "Pembelian",
    "stok": "Inventori & Stok",
    "analitik": "Analitik",
    "promo": "Promo & Voucher",
    "kas": "Kas & Shift",
    # Master Data dipecah jadi sub-grup bertajuk di sidebar (satu tab yang sama).
    "master": "Master Data",
    "master_harga": "Harga & Update Barang",
    "master_sync": "Sinkronisasi",
    "admin": "Administrasi",
}

ALL_MENUS = [
    # --- Kasir & supervisor ---------------------------------------------------
    # "roles": menu ini BAWAAN peran yang disebut, dan sengaja BUKAN bawaan admin
    # (lihat default_keys_for) — admin tetap bisa diberi lewat Kelola Menu.
    # Rutenya di bawah /kasir, bukan /admin-panel: penjaga Tailscale menutup
    # seluruh /admin-panel, sedangkan kasir di toko tidak ada di rentang CGNAT.
    {"key": "kasir_stok", "label": "Cek Stok", "icon": "box", "href": "/kasir/stok", "section": "pos", "roles": ("kasir", "supervisor")},
    # Kunci menunya tetap `kasir_penjualan` walau labelnya berganti: kunci itu
    # tersimpan di allowed_menu_keys tiap user, jadi mengubahnya mencabut layar
    # ini dari semua orang yang menunya sudah diatur satu per satu.
    {"key": "kasir_penjualan", "label": "Penjualan", "icon": "cart", "href": "/kasir/penjualan", "section": "pos", "roles": ("kasir", "supervisor")},
    {"key": "kasir_penjualan_order", "label": "Penjualan Order", "icon": "list", "href": "/kasir/penjualan-order", "section": "pos", "roles": ("kasir", "supervisor")},
    {"key": "kasir_faktur", "label": "Cetak Faktur", "icon": "clipboard", "href": "/kasir/faktur", "section": "pos", "roles": ("kasir", "supervisor")},
    {"key": "kasir_retur_penjualan", "label": "Retur Penjualan", "icon": "refund", "href": "/kasir/penjualan-retur", "section": "pos", "roles": ("supervisor",)},
    {"key": "kasir_pembelian", "label": "Terima Pembelian", "icon": "truck", "href": "/kasir/pembelian", "section": "pos", "roles": ("supervisor",)},
    {"key": "kasir_retur_pembelian", "label": "Retur Pembelian", "icon": "refund", "href": "/kasir/pembelian-retur", "section": "pos", "roles": ("supervisor",)},
    {"key": "dashboard", "label": "Dashboard", "icon": "dashboard", "href": "/admin-panel/dashboard", "section": "ringkasan"},
    # "always": tak bisa dicabut lewat Kelola Menu. Bantuan yang bisa hilang dari
    # sidebar justru menghilang tepat saat pengguna paling butuh.
    {"key": "bantuan", "label": "Bantuan & Istilah", "icon": "help", "href": "/admin-panel/bantuan", "section": "ringkasan", "always": True},
    # Penjualan (laporan). Sebagian jadi bawaan supervisor: memantau hasil
    # penjualan/pembelian/retur itu pekerjaan hariannya, beda dari mengubah
    # data induk yang tetap wewenang admin.
    {"key": "penjualan_all", "label": "Penjualan (Detail)", "icon": "cart", "href": "/admin-panel/laporan/penjualan", "section": "penjualan", "roles": ("supervisor",)},
    {"key": "penjualan_hpp", "label": "Laba per Barang", "icon": "trending", "href": "/admin-panel/laporan/penjualan-hpp", "section": "penjualan"},
    {"key": "penjualan_nota", "label": "Penjualan per Nota", "icon": "list", "href": "/admin-panel/laporan/penjualan-nota", "section": "penjualan", "roles": ("kasir", "supervisor")},
    {"key": "penjualan_customer", "label": "Penjualan per Customer", "icon": "user", "href": "/admin-panel/laporan/penjualan-customer", "section": "penjualan"},
    {"key": "penjualan_user", "label": "Penjualan per User", "icon": "users", "href": "/admin-panel/laporan/penjualan-user", "section": "penjualan"},
    {"key": "penjualan_periode", "label": "Penjualan per Periode", "icon": "calendar", "href": "/admin-panel/laporan/penjualan-periode", "section": "penjualan"},
    {"key": "retur_penjualan", "label": "Retur Penjualan", "icon": "refund", "href": "/admin-panel/laporan/retur-penjualan", "section": "penjualan", "roles": ("supervisor",)},
    {"key": "piutang", "label": "Piutang Pelanggan", "icon": "cash", "href": "/admin-panel/laporan/piutang", "section": "penjualan"},
    # Pembelian
    {"key": "pembelian", "label": "Pembelian", "icon": "truck", "href": "/admin-panel/laporan/pembelian", "section": "pembelian", "roles": ("supervisor",)},
    {"key": "pembelian_supplier", "label": "Pembelian per Supplier", "icon": "truck", "href": "/admin-panel/laporan/pembelian-supplier", "section": "pembelian"},
    {"key": "pembelian_periode", "label": "Pembelian per Periode", "icon": "calendar", "href": "/admin-panel/laporan/pembelian-periode", "section": "pembelian"},
    {"key": "retur_pembelian", "label": "Retur Pembelian", "icon": "refund", "href": "/admin-panel/laporan/retur-pembelian", "section": "pembelian", "roles": ("supervisor",)},
    # Inventori & Stok
    {"key": "stock", "label": "Stok Akhir", "icon": "box", "href": "/admin-panel/inventory/stock", "section": "stok"},
    {"key": "barang_histori", "label": "Barang Histori", "icon": "list", "href": "/admin-panel/inventory/histori", "section": "stok"},
    {"key": "stok_divisi", "label": "Stok per Divisi", "icon": "store", "href": "/admin-panel/inventory/stok-divisi", "section": "stok"},
    {"key": "stok_akhir", "label": "Mutasi Stok", "icon": "refresh", "href": "/admin-panel/inventory/mutasi-stok", "section": "stok"},
    {"key": "stok_awal", "label": "Stok Awal Barang", "icon": "box", "href": "/admin-panel/inventory/stok-awal", "section": "stok"},
    {"key": "transaksi_barang", "label": "Transaksi Barang", "icon": "list", "href": "/admin-panel/inventory/transaksi", "section": "stok"},
    # "admin_only": kedua layar opname khusus admin/superadmin, dan itu bukan
    # sekadar bawaan yang bisa dilonggarkan lewat Kelola Menu. Halaman Opname
    # Stok kini juga MENULIS koreksi stok: satu baris di t_opname_stok langsung
    # menggeser stok lewat trigger dan terkirim ke pusat, dan tak ada layar mana
    # pun yang bisa menariknya kembali.
    {"key": "opname", "label": "Opname Stok", "icon": "clipboard", "href": "/admin-panel/inventory/opname", "section": "stok", "admin_only": True},
    # Section "stok" sudah cukup: "Operasional" bukan section backend, melainkan
    # tab navbar (useNav.js) yang menggabungkan stok+promo+kas. Rute /export,
    # /detail, dan /save mewarisi menu key ini lewat pencocokan prefix di
    # menu_key_for_path — termasuk penjagaannya.
    {"key": "opname_neraca", "label": "Neraca Opname", "icon": "chart", "href": "/admin-panel/inventory/opname-neraca", "section": "stok", "admin_only": True},
    # Analitik (FMI)
    {"key": "fmi_penjualan", "label": "FMI Penjualan", "icon": "trending", "href": "/admin-panel/analitik/fmi-penjualan", "section": "analitik"},
    {"key": "fmi_stok", "label": "FMI Stok", "icon": "chart", "href": "/admin-panel/analitik/fmi-stok", "section": "analitik"},
    {"key": "klasifikasi_pelanggan", "label": "Klasifikasi Pelanggan", "icon": "user", "href": "/admin-panel/analitik/klasifikasi-pelanggan", "section": "analitik"},
    # Promo & Voucher
    {"key": "promo", "label": "Promo & Diskon", "icon": "tag", "href": "/admin-panel/promo/diskon", "section": "promo"},
    {"key": "voucher", "label": "Voucher", "icon": "ticket", "href": "/admin-panel/promo/voucher", "section": "promo"},
    # Kas & Shift
    {"key": "kas", "label": "Kas Harian", "icon": "cash", "href": "/admin-panel/kas/harian", "section": "kas"},
    {"key": "shift", "label": "Shift Kasir", "icon": "clock", "href": "/admin-panel/kas/shift", "section": "kas"},
    {"key": "biaya_operasional", "label": "Biaya Operasional", "icon": "cash", "href": "/admin-panel/laporan/biaya-operasional", "section": "kas"},
    {"key": "biaya_kategori", "label": "Biaya per Kategori", "icon": "chart", "href": "/admin-panel/laporan/biaya-kategori", "section": "kas"},
    # Master Data — sub-grup 1: data master
    # Master data adalah wewenang admin, bukan pekerjaan harian toko: satu salah
    # ketik di sini ikut terbawa ke SETIAP nota yang menunjuk ke baris itu, dan
    # nota yang sudah tertulis tak bisa ditarik.
    {"key": "products", "label": "Master Produk", "icon": "box", "href": "/admin-panel/master/products", "section": "master"},
    {"key": "customers", "label": "Master Pelanggan", "icon": "user", "href": "/admin-panel/master/customers", "section": "master"},
    {"key": "suppliers", "label": "Master Supplier", "icon": "truck", "href": "/admin-panel/master/suppliers", "section": "master"},
    {"key": "kelola_pelanggan", "label": "Kelola Pelanggan", "icon": "pencil", "href": "/admin-panel/master/kelola-pelanggan", "section": "master"},
    {"key": "kelola_supplier", "label": "Kelola Supplier", "icon": "pencil", "href": "/admin-panel/master/kelola-supplier", "section": "master"},
    # Master Data — sub-grup 2: harga & update barang
    {"key": "update_barang", "label": "Update Barang", "icon": "pencil", "href": "/admin-panel/master/update-barang", "section": "master_harga"},
    {"key": "riwayat_update_barang", "label": "Riwayat Update Barang", "icon": "clock", "href": "/admin-panel/master/riwayat-update-barang", "section": "master_harga"},
    {"key": "pergerakan_harga", "label": "Pergerakan Harga", "icon": "trending", "href": "/admin-panel/master/pergerakan-harga", "section": "master_harga"},
    # Master Data — sub-grup 3: sinkronisasi antar-server
    {"key": "sync_harga", "label": "Sinkronisasi Harga", "icon": "refresh", "href": "/admin-panel/master/sync-harga", "section": "master_sync"},
    {"key": "sync_master", "label": "Sinkronisasi Master Data", "icon": "refresh", "href": "/admin-panel/master/sync-master", "section": "master_sync"},
    {"key": "sync_history", "label": "Riwayat Sinkronisasi", "icon": "list", "href": "/admin-panel/master/sync-history", "section": "master_sync"},
    # Superadmin-only: memperlihatkan kondisi seluruh armada server sekaligus
    # (antrean menumpuk, sync yang mati), bukan data satu koneksi yang sedang
    # dipakai. Itu urusan yang memegang seluruh jaringan toko, bukan per-admin.
    {"key": "sync_health", "label": "Kesehatan Sync", "icon": "power", "href": "/admin-panel/master/sync-health", "section": "master_sync", "superadmin_only": True},
    # Superadmin-only: kepala_nota menentukan awalan SETIAP nomor nota yang
    # dibuat sesudahnya, dan salah isi berarti nota tercatat atas nama cabang
    # lain — sekali tertulis, tak bisa ditarik.
    {"key": "kode_nota", "label": "Kelola Kode Nota", "icon": "key", "href": "/admin-panel/master/kode-nota", "section": "master_sync", "superadmin_only": True},
    # Administrasi
    {"key": "users", "label": "Manajemen User", "icon": "users", "href": "/admin-panel/users", "section": "admin"},
    {"key": "connections", "label": "Koneksi Server", "icon": "server", "href": "/admin-panel/connections", "section": "admin"},
    {"key": "logs", "label": "Log Aktivitas", "icon": "list", "href": "/admin-panel/logs", "section": "admin"},
    # Superadmin-only: cannot be granted to a regular admin.
    {"key": "menus", "label": "Kelola Menu", "icon": "key", "href": "/admin-panel/menus", "section": "admin", "superadmin_only": True},
]


def assignable_menus():
    """Menus a superadmin may grant/revoke for other users.

    Excludes superadmin-only menus and `always` menus (Bantuan) — menampilkan
    yang tak bisa dicabut di layar Kelola Menu cuma menyesatkan."""
    return [m for m in ALL_MENUS if not m.get("superadmin_only") and not m.get("always")]


def landing_for(user) -> str | None:
    """Menu pertama yang boleh dibuka `user`, atau None kalau tak ada satu pun.

    Dipakai saat seseorang membuka menu yang tak diberikan kepadanya: lebih baik
    diantar ke halaman yang memang miliknya daripada dihadang tembok.

    Menu ber-`always` (Bantuan & Istilah) sengaja dilewati DULU. Ia tak pernah
    bisa dicabut, jadi ia selalu ada di daftar — dan karena letaknya di awal
    ALL_MENUS, mengambil elemen pertama begitu saja akan mengantar semua orang
    ke Bantuan walau mereka punya Laporan Penjualan. Ia cadangan terakhir, bukan
    pilihan pertama; itu pula yang membuatnya selalu ada tempat mendarat.
    """
    menus = menus_for(user)
    if not menus:
        return None
    kerja = [m for m in menus if not m.get("always")]
    if not kerja:
        return menus[0]["href"]
    # Utamakan menu BAWAAN perannya. Superadmin melihat seluruh ALL_MENUS, jadi
    # mengambil elemen pertama begitu saja mengantarnya ke menu apa pun yang
    # kebetulan ada di awal daftar — saat menu kasir ditaruh di atas, seluruh
    # superadmin mendarat di layar Cek Stok, bukan Dashboard.
    bawaan = set(default_keys_for(user.role))
    milik = [m for m in kerja if m["key"] in bawaan]
    return (milik or kerja)[0]["href"]


def default_keys_for(role) -> list[str]:
    """Menu bawaan sebuah peran, dipakai saat `allowed_menu_keys` masih kosong.

    Admin dapat semua menu yang bisa diberikan KECUALI yang ber-`roles`. Menu
    ber-`roles` itu milik harian kasir/supervisor; memberikannya ke setiap admin
    secara diam-diam membuat "khusus untuk mereka" tidak berarti apa-apa. Admin
    tetap bisa diberi menu itu lewat Kelola Menu — ia hanya tidak otomatis.

    Kasir/supervisor dapat menu yang menyebut perannya. Perhatikan bahwa untuk
    mereka "kosong" TIDAK boleh berarti akses penuh seperti pada admin: itu
    justru membuka seluruh panel bagi akun yang belum sempat diatur.
    """
    from apps.auth_app.models import Role

    # Yang dikecualikan dari bawaan admin adalah SECTION "pos", bukan setiap
    # menu ber-`roles`. Bedanya penting: menu admin yang juga diberikan ke
    # supervisor (mis. Update Barang) tetap harus jadi bawaan admin — kalau
    # patokannya `roles`, menambahkan supervisor ke satu menu justru
    # MENCABUTNYA dari seluruh admin.
    if role in (Role.ADMIN, Role.SUPERADMIN):
        return [m["key"] for m in assignable_menus() if m["section"] != "pos"]
    return [m["key"] for m in ALL_MENUS if role in m.get("roles", ())]


def menus_for(user):
    """Return the menu list visible to `user` (PRD §4.3/§4.4)."""
    from apps.auth_app.models import Role

    if not user or not user.is_authenticated:
        return []
    if user.role == Role.SUPERADMIN:
        return ALL_MENUS  # full access, always
    # Satu jalur untuk admin, kasir, dan supervisor. Yang membedakan hanya apa
    # arti "belum diatur" bagi tiap peran — itu ada di default_keys_for().
    keys = user.allowed_menu_keys or default_keys_for(user.role)
    allowed = set(keys)
    # Menu ber-`admin_only` tak bisa diberikan ke kasir/supervisor sama sekali —
    # dicentang di Kelola Menu pun tak berlaku. Penjagaannya di SINI dan bukan
    # cuma di sidebar: admin_network_guard._menu_allowed membaca fungsi yang
    # sama, jadi mengetik URL-nya langsung ikut tertutup.
    tier_admin = user.role in (Role.ADMIN, Role.SUPERADMIN)
    return [
        m for m in ALL_MENUS
        if not m.get("superadmin_only")
        and (tier_admin or not m.get("admin_only"))
        and (m.get("always") or m["key"] in allowed)
    ]


# Longest href first so /laporan/penjualan-nota resolves before /laporan/penjualan.
_MENUS_BY_HREF = sorted(ALL_MENUS, key=lambda m: len(m["href"]), reverse=True)


def menu_key_for_path(path: str):
    """Resolve a request path to the menu key that owns it, or None for pages
    outside the menu registry (e.g. /admin-panel/profile). Sub-paths such as
    /export or /save belong to their menu's key."""
    for m in _MENUS_BY_HREF:
        href = m["href"]
        if path == href or path.startswith(href + "/"):
            return m["key"]
    return None

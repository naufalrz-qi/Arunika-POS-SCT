"""Admin menu registry (single source of truth for sidebar + RBAC filtering)."""

# Section order + display labels for the collapsible sidebar groups.
SECTIONS = [
    "pos_jual", "pos_beli", "pos_lain",
    "ringkasan", "penjualan", "pembelian", "akuntansi", "stok", "analitik", "promo", "kas",
    "master", "master_harga", "master_sync", "admin",
]
# Menu kasir dipecah tiga, seperti Master Data — satu tab navbar yang sama,
# tiga sub-grup bertajuk. Sebelumnya ketujuhnya berdesakan di bawah satu judul
# "Kasir", dan "Retur Penjualan" bersebelahan dengan "Retur Pembelian" walau
# keduanya menyentuh pihak, tabel, dan stok yang sama sekali berbeda.
SECTION_LABELS = {
    "pos_jual": "Penjualan (Kasir)",
    "pos_beli": "Pembelian (Kasir)",
    "pos_lain": "Lainnya",
    "ringkasan": "Ringkasan",
    "penjualan": "Penjualan",
    "pembelian": "Pembelian",
    # Nama seksi mengikuti menu legacy ("Akuntansi"), supaya orang yang terbiasa
    # dengan aplikasi lama mencarinya di tempat yang sama.
    "akuntansi": "Akuntansi",
    "stok": "Inventori & Stok",
    "analitik": "Analitik",
    "promo": "Promo & Voucher",
    "kas": "Kas & Shift",
    # Master Data dipecah jadi sub-grup bertajuk di sidebar (satu tab yang sama).
    "master": "Master Data",
    "master_harga": "Harga & Barang",
    "master_sync": "Sinkronisasi",
    "admin": "Administrasi",
}

ALL_MENUS = [
    # --- Kasir & supervisor ---------------------------------------------------
    # "roles": menu ini BAWAAN peran yang disebut, dan sengaja BUKAN bawaan admin
    # (lihat default_keys_for) — admin tetap bisa diberi lewat Kelola Menu.
    # Rutenya di bawah /kasir, bukan /admin-panel: penjaga Tailscale menutup
    # seluruh /admin-panel, sedangkan kasir di toko tidak ada di rentang CGNAT.
    #
    # "butuh_tautan": layar MENULIS ke server legacy dan karena itu memerlukan
    # `kd_user` + `kd_divisi` akun ini UNTUK KONEKSI YANG SEDANG AKTIF (lihat
    # menus_for + apps/auth_app/tautan.py). Tanpa itu `tautan_wajib` menolak
    # simpanannya, jadi membiarkan menunya terlihat cuma memindahkan kegagalan
    # ke saat keranjang sudah terisi. Cek Stok & Cetak Faktur sengaja TIDAK
    # ditandai: keduanya hanya membaca, dan mencabutnya membuat kasir yang belum
    # ditautkan tak punya satu pun halaman kasir — landing-nya lalu jatuh ke
    # Bantuan, yang ada di /admin-panel dan tertutup penjaga Tailscale dari
    # jaringan toko.
    # URUTAN DI BERKAS INI MENENTUKAN HALAMAN PENDARATAN, bukan urutan sidebar.
    # `landing_for()` mengambil menu bawaan peran yang PERTAMA di ALL_MENUS,
    # sedangkan sidebar mengurutkan sub-grupnya dari NAV_GROUPS di useNav.js.
    # Karena itu Cek Stok berdiri di sini, di atas, walau tampil di grup
    # "Lainnya" paling bawah: ia satu-satunya layar kasir yang tak menulis dan
    # tak pernah tertutup gerbang tautan, jadi ia tempat mendarat yang selalu
    # ada. Memindahkannya ke bawah diam-diam mengubah ke mana setiap kasir
    # mendarat setelah login.
    {"key": "kasir_stok", "label": "Cek Stok", "icon": "box", "href": "/kasir/stok", "section": "pos_lain", "roles": ("kasir", "supervisor")},
    {"key": "kasir_faktur", "label": "Cetak Faktur", "icon": "clipboard", "href": "/kasir/faktur", "section": "pos_lain", "roles": ("kasir", "supervisor")},
    # Kunci menunya tetap `kasir_penjualan` walau labelnya berganti: kunci itu
    # tersimpan di allowed_menu_keys tiap user, jadi mengubahnya mencabut layar
    # ini dari semua orang yang menunya sudah diatur satu per satu. Alasan yang
    # sama membuat `kasir_pembelian` bertahan walau labelnya bukan lagi "Terima
    # Pembelian" — sekarang ada Order Pembelian di sebelahnya, dan "Terima"
    # justru mengaburkan mana yang memesan dan mana yang mencatat barang masuk.
    {"key": "kasir_penjualan", "label": "Penjualan", "icon": "cart", "href": "/kasir/penjualan", "section": "pos_jual", "roles": ("kasir", "supervisor"), "butuh_tautan": True},
    {"key": "kasir_penjualan_order", "label": "Penjualan Order", "icon": "list", "href": "/kasir/penjualan-order", "section": "pos_jual", "roles": ("kasir", "supervisor"), "butuh_tautan": True},
    {"key": "kasir_retur_penjualan", "label": "Retur Penjualan", "icon": "refund", "href": "/kasir/penjualan-retur", "section": "pos_jual", "roles": ("supervisor",), "butuh_tautan": True},
    {"key": "kasir_pembelian", "label": "Pembelian", "icon": "truck", "href": "/kasir/pembelian", "section": "pos_beli", "roles": ("supervisor",), "butuh_tautan": True},
    # Menulis ke `t_pembelian_order`, yang PUNYA trigger insert_temp_m_* —
    # order pembelian ikut terkirim ke pusat begitu disimpan, beda dari order
    # penjualan yang tabelnya tanpa trigger sama sekali.
    {"key": "kasir_pembelian_order", "label": "Order Pembelian", "icon": "list", "href": "/kasir/pembelian-order", "section": "pos_beli", "roles": ("supervisor",), "butuh_tautan": True},
    {"key": "kasir_retur_pembelian", "label": "Retur Pembelian", "icon": "refund", "href": "/kasir/pembelian-retur", "section": "pos_beli", "roles": ("supervisor",), "butuh_tautan": True},
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
    # Order penjualan sudah DITULIS sejak lama (layar kasir Penjualan Order),
    # tapi sampai sekarang tak ada layar yang membacanya kembali.
    {"key": "order_penjualan", "label": "Order Penjualan", "icon": "clipboard", "href": "/admin-panel/laporan/order-penjualan", "section": "penjualan"},
    # Pembelian
    {"key": "pembelian", "label": "Pembelian", "icon": "truck", "href": "/admin-panel/laporan/pembelian", "section": "pembelian", "roles": ("supervisor",)},
    {"key": "pembelian_supplier", "label": "Pembelian per Supplier", "icon": "truck", "href": "/admin-panel/laporan/pembelian-supplier", "section": "pembelian"},
    {"key": "pembelian_periode", "label": "Pembelian per Periode", "icon": "calendar", "href": "/admin-panel/laporan/pembelian-periode", "section": "pembelian"},
    {"key": "retur_pembelian", "label": "Retur Pembelian", "icon": "refund", "href": "/admin-panel/laporan/retur-pembelian", "section": "pembelian", "roles": ("supervisor",)},
    {"key": "order_pembelian", "label": "Order Pembelian", "icon": "clipboard", "href": "/admin-panel/laporan/order-pembelian", "section": "pembelian"},
    # Hutang ke supplier: cerminan Piutang Pelanggan di seksi sebelah.
    {"key": "hutang", "label": "Hutang Supplier", "icon": "cash", "href": "/admin-panel/laporan/hutang", "section": "pembelian"},
    # Akuntansi — angkanya SENGAJA tidak sama dengan aplikasi lama (legacy memakai
    # LIFO yang dilarang PSAK 14); layarnya yang menjelaskan. Lihat laba_rugi.py.
    {"key": "laba_rugi", "label": "Laba Rugi", "icon": "chart", "href": "/admin-panel/laporan/laba-rugi", "section": "akuntansi"},
    # Inventori & Stok
    {"key": "stock", "label": "Stok Akhir", "icon": "box", "href": "/admin-panel/inventory/stock", "section": "stok"},
    {"key": "barang_histori", "label": "Barang Histori", "icon": "list", "href": "/admin-panel/inventory/histori", "section": "stok"},
    {"key": "stok_divisi", "label": "Stok per Divisi", "icon": "store", "href": "/admin-panel/inventory/stok-divisi", "section": "stok"},
    {"key": "stok_akhir", "label": "Mutasi Stok", "icon": "refresh", "href": "/admin-panel/inventory/mutasi-stok", "section": "stok"},
    {"key": "stok_awal", "label": "Stok Awal Barang", "icon": "box", "href": "/admin-panel/inventory/stok-awal", "section": "stok"},
    {"key": "transaksi_barang", "label": "Transaksi Barang", "icon": "list", "href": "/admin-panel/inventory/transaksi", "section": "stok"},
    # "admin_only": ketiga layar opname khusus admin/superadmin, dan itu bukan
    # sekadar bawaan yang bisa dilonggarkan lewat Kelola Menu. Koreksi Stok
    # MENULIS: satu baris di t_opname_stok langsung menggeser stok lewat trigger
    # dan terkirim ke pusat, dan tak ada layar mana pun yang bisa menariknya
    # kembali. Kedua layar laporannya ikut dikunci karena mereka memperlihatkan
    # selisih yang jadi dasar koreksi itu.
    {"key": "opname", "label": "Opname Stok", "icon": "clipboard", "href": "/admin-panel/inventory/opname", "section": "stok", "admin_only": True},
    {"key": "koreksi_stok", "label": "Koreksi Stok", "icon": "pencil", "href": "/admin-panel/inventory/koreksi-stok", "section": "stok", "admin_only": True, "butuh_tautan": True},
    # Section "stok" sudah cukup: "Operasional" bukan section backend, melainkan
    # tab navbar (useNav.js) yang menggabungkan stok+promo+kas. Rute /export,
    # /detail, dan /save mewarisi menu key ini lewat pencocokan prefix di
    # menu_key_for_path — termasuk penjagaannya.
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
    # Empat layar TULIS kas. `admin_only` + `butuh_tautan` dengan alasan yang
    # sama persis seperti Koreksi Stok: uang bergerak begitu disimpan,
    # `kd_user` menentukan itu tercatat atas nama siapa, dan tak ada layar mana
    # pun di sini yang bisa menariknya kembali.
    {"key": "kas_biaya_input", "label": "Input Biaya Operasional", "icon": "cash", "href": "/admin-panel/kas/input/biaya", "section": "kas", "admin_only": True, "butuh_tautan": True},
    {"key": "kas_pendapatan", "label": "Pendapatan Lain-Lain", "icon": "cash", "href": "/admin-panel/kas/input/pendapatan", "section": "kas", "admin_only": True, "butuh_tautan": True},
    {"key": "kas_penambahan", "label": "Penambahan Kas", "icon": "cash", "href": "/admin-panel/kas/input/penambahan", "section": "kas", "admin_only": True, "butuh_tautan": True},
    {"key": "kas_mutasi", "label": "Mutasi Kas", "icon": "refresh", "href": "/admin-panel/kas/input/mutasi", "section": "kas", "admin_only": True, "butuh_tautan": True},
    # Master Data — sub-grup 1: data master
    # Master data adalah wewenang admin, bukan pekerjaan harian toko: satu salah
    # ketik di sini ikut terbawa ke SETIAP nota yang menunjuk ke baris itu, dan
    # nota yang sudah tertulis tak bisa ditarik.
    {"key": "products", "label": "Master Produk", "icon": "box", "href": "/admin-panel/master/products", "section": "master"},
    {"key": "customers", "label": "Master Pelanggan", "icon": "user", "href": "/admin-panel/master/customers", "section": "master"},
    {"key": "suppliers", "label": "Master Supplier", "icon": "truck", "href": "/admin-panel/master/suppliers", "section": "master"},
    {"key": "kelola_pelanggan", "label": "Kelola Pelanggan", "icon": "pencil", "href": "/admin-panel/master/kelola-pelanggan", "section": "master"},
    {"key": "kelola_supplier", "label": "Kelola Supplier", "icon": "pencil", "href": "/admin-panel/master/kelola-supplier", "section": "master"},
    # Sebelas tabel referensi (kategori, merk, model, warna, jenis bahan, satuan,
    # bank, kota, jenis biaya, voucher, kas) di balik SATU key. Href-nya sengaja
    # tanpa entitas: menu_key_for_path mencocokkan prefix, jadi seluruh
    # /referensi/<entitas> dan /save ikut terjaga oleh key ini.
    #
    # Kota & Bank di sini bukan pelengkap. Tanpa keduanya, Kelola Pelanggan dan
    # Kelola Supplier buntu untuk kota/bank yang belum terdaftar — kolomnya
    # berkunci-asing dan menolak string kosong.
    {"key": "kelola_referensi", "label": "Kelola Data Referensi", "icon": "pencil", "href": "/admin-panel/master/referensi", "section": "master"},
    # Master Data — sub-grup 2: harga & update barang
    # STRUKTUR barang: membuat barang, menambah satuan, menambah baris divisi.
    # Tanpa `butuh_tautan` (tabelnya tak punya kd_user), tapi service-nya menolak
    # server non-gudang: katalog dipakai bersama dan disebarkan dari gudang, jadi
    # yang dibuat/disunting di toko akan tertimpa sapuan berikutnya.
    {"key": "kelola_barang", "label": "Kelola Barang", "icon": "box", "href": "/admin-panel/master/kelola-barang", "section": "master_harga"},
    # HARGA barang — dulu bernama "Update Barang", padahal ia tak pernah mengubah
    # struktur barangnya. Key-nya ikut berganti, jadi ada migrasi 0008 yang
    # menulis ulang `User.allowed_menu_keys`; tanpa itu menu ini lenyap diam-diam
    # dari setiap akun yang hak aksesnya diatur satu per satu.
    {"key": "update_harga", "label": "Update Harga", "icon": "pencil", "href": "/admin-panel/master/update-harga", "section": "master_harga"},
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
    # Superadmin saja, sama seperti Kelola Menu: tautan ini menentukan transaksi
    # tercatat atas nama siapa di server mana, dan salah isi tak bisa ditarik.
    {"key": "tautan_user", "label": "Kelola Tautan User", "icon": "users", "href": "/admin-panel/tautan-user", "section": "admin", "superadmin_only": True},
]


# Section milik layar kasir. Dulu satu string "pos" yang dibandingkan langsung;
# begitu ia dipecah tiga, pembandingan itu diam-diam jadi selalu benar dan
# SELURUH menu kasir masuk ke bawaan admin. Dijadikan satu himpunan bernama
# supaya pemecahan berikutnya tak mengulang kegagalan yang sama.
SECTIONS_POS = frozenset({"pos_jual", "pos_beli", "pos_lain"})


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

    # Yang dikecualikan dari bawaan admin adalah SECTION kasir, bukan setiap
    # menu ber-`roles`. Bedanya penting: menu admin yang juga diberikan ke
    # supervisor (mis. Update Barang) tetap harus jadi bawaan admin — kalau
    # patokannya `roles`, menambahkan supervisor ke satu menu justru
    # MENCABUTNYA dari seluruh admin.
    if role in (Role.ADMIN, Role.SUPERADMIN):
        return [m["key"] for m in assignable_menus() if m["section"] not in SECTIONS_POS]
    return [m["key"] for m in ALL_MENUS if role in m.get("roles", ())]


KEYS_BUTUH_TAUTAN = {m["key"] for m in ALL_MENUS if m.get("butuh_tautan")}


def tautan_lengkap(user) -> bool:
    """Apakah `user` sudah ditautkan ke user legacy untuk koneksi yang AKTIF.

    Hasilnya di-memo pada instance user, berkunci id profil. `request.user`
    adalah objek yang sama sepanjang satu permintaan, sedangkan `menus_for()`
    dipanggil tiga kali di sana (penjaga menu, prop bersama, landing_for) —
    tanpa memo itu tiga query SQLite yang menjawab pertanyaan yang sama persis.
    Kuncinya id profil, bukan sekadar "sudah dihitung": satu permintaan memang
    hanya punya satu koneksi, tapi memo tanpa kunci akan bertahan salah kalau
    objek user dipakai ulang di luar siklus permintaan (mis. di test).
    """
    from apps.auth_app import tautan as t
    from core import mssql

    profile = mssql.get_active_profile()
    kunci = profile.pk if profile else None
    memo = getattr(user, "_memo_tautan", None)
    if memo is not None and memo[0] == kunci:
        return memo[1]
    hasil = t.lengkap(user, profile)
    user._memo_tautan = (kunci, hasil)
    return hasil


def menus_for(user, abaikan_tautan: bool = False):
    """Return the menu list visible to `user` (PRD §4.3/§4.4).

    `abaikan_tautan` melewati gerbang tautan legacy dan hanya dipakai oleh
    `_pesan_tautan` di middleware, untuk membedakan "menunya memang tak
    diberikan" dari "diberikan, tapi akunnya belum ditautkan". Jangan memakainya
    untuk memutuskan akses: yang menjaga akses adalah pemanggilan tanpa argumen.
    """
    from apps.auth_app.models import Role

    if not user or not user.is_authenticated:
        return []
    if user.role == Role.SUPERADMIN:
        dasar = ALL_MENUS  # full access, always
    else:
        # Satu jalur untuk admin, kasir, dan supervisor. Yang membedakan hanya
        # apa arti "belum diatur" bagi tiap peran — itu ada di default_keys_for().
        keys = user.allowed_menu_keys or default_keys_for(user.role)
        allowed = set(keys)
        # Menu ber-`admin_only` tak bisa diberikan ke kasir/supervisor sama
        # sekali — dicentang di Kelola Menu pun tak berlaku. Penjagaannya di
        # SINI dan bukan cuma di sidebar: admin_network_guard._menu_allowed
        # membaca fungsi yang sama, jadi mengetik URL-nya langsung ikut tertutup.
        tier_admin = user.role in (Role.ADMIN, Role.SUPERADMIN)
        dasar = [
            m for m in ALL_MENUS
            if not m.get("superadmin_only")
            and (tier_admin or not m.get("admin_only"))
            and (m.get("always") or m["key"] in allowed)
        ]
    # Gerbang tautan berlaku SESUDAH cabang peran, jadi superadmin pun ikut
    # digerbangi. Ia juga tak bisa menyimpan tanpa kd_user di koneksi itu;
    # membiarkan menunya terlihat cuma menunda penolakan sampai keranjang
    # terisi. Query-nya cuma dijalankan kalau memang ada menu yang menuntutnya.
    if abaikan_tautan:
        return dasar
    if any(m.get("butuh_tautan") for m in dasar) and not tautan_lengkap(user):
        return [m for m in dasar if not m.get("butuh_tautan")]
    return dasar


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

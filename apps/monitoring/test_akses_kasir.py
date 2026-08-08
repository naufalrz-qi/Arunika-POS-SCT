"""Kasir & supervisor kini boleh masuk — tapi hanya ke menu yang memang mereka punya.

Sebelumnya mereka terhalang TIGA lapis yang berdiri sendiri: login memaksa
logout, middleware menuntut `is_admin_tier`, dan menus_for() mengembalikan [].
Membuka satu lapis saja tidak menghasilkan apa pun, jadi ketiganya diuji di sini.

Yang paling penting: bagi kasir, `allowed_menu_keys` kosong TIDAK boleh berarti
akses penuh. Konvensi itu berlaku untuk admin (lihat menus_for), dan menerapkannya
apa adanya ke kasir akan membuka seluruh panel bagi akun yang belum sempat diatur.
"""
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.core.menus import (
    ALL_MENUS,
    assignable_menus,
    default_keys_for,
    menus_for,
)


def _keys(user):
    return {m["key"] for m in menus_for(user)}


class MenuBawaanPeranTests(TestCase):
    def setUp(self):
        self.kasir = User.objects.create_user("kasir9", password="rahasia-kuat-123", role=Role.KASIR)
        self.spv = User.objects.create_user("spv9", password="rahasia-kuat-123", role=Role.SUPERVISOR)
        self.admin = User.objects.create_user("admin9", password="rahasia-kuat-123", role=Role.ADMIN)

    def test_kasir_tanpa_pengaturan_hanya_dapat_menu_pos(self):
        """Kosong = menu POS saja, BUKAN akses penuh."""
        keys = _keys(self.kasir)
        self.assertIn("kasir_stok", keys)
        self.assertIn("kasir_penjualan", keys)
        for terlarang in ("users", "connections", "logs", "dashboard", "stock"):
            self.assertNotIn(terlarang, keys, f"{terlarang} bocor ke kasir")

    def test_supervisor_juga_dapat_menu_pos(self):
        self.assertIn("kasir_stok", _keys(self.spv))

    def test_bantuan_selalu_ikut(self):
        """Menu `always` tak bisa dicabut — termasuk untuk kasir, yang justru
        paling butuh daftar istilah."""
        self.assertIn("bantuan", _keys(self.kasir))

    def test_admin_tidak_otomatis_dapat_menu_pos(self):
        """'Khusus untuk mereka' jadi tak berarti kalau tiap admin dapat diam-diam."""
        self.assertNotIn("kasir_stok", default_keys_for(Role.ADMIN))
        self.assertNotIn("kasir_stok", _keys(self.admin))

    def test_admin_tetap_dapat_sisanya_seperti_dulu(self):
        keys = _keys(self.admin)
        for tetap in ("dashboard", "users", "connections", "logs", "stock"):
            self.assertIn(tetap, keys, f"{tetap} hilang dari admin")

    def test_superadmin_melihat_semuanya(self):
        boss = User.objects.create_user("boss9", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.assertEqual(_keys(boss), {m["key"] for m in ALL_MENUS})

    def test_pendaratan_ikut_peran_bukan_urutan_daftar(self):
        """Superadmin melihat seluruh ALL_MENUS. Mengambil elemen pertama begitu
        saja mengantarnya ke menu apa pun yang kebetulan ada di awal daftar —
        saat menu kasir ditaruh di atas, semua superadmin mendarat di Cek Stok."""
        from apps.core.menus import landing_for

        boss = User.objects.create_user("boss8", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.assertEqual(landing_for(boss), "/admin-panel/dashboard")
        self.assertEqual(landing_for(self.admin), "/admin-panel/dashboard")
        self.assertEqual(landing_for(self.kasir), "/kasir/stok")
        self.assertEqual(landing_for(self.spv), "/kasir/stok")

    def test_kasir_bisa_diberi_menu_admin(self):
        """Inti permintaannya: akses ke fitur admin tetap dikelola admin/superadmin."""
        self.kasir.allowed_menu_keys = ["kasir_stok", "stock"]
        self.kasir.save(update_fields=["allowed_menu_keys"])
        self.assertEqual(_keys(self.kasir), {"kasir_stok", "stock", "bantuan"})


class GerbangHalamanKasirTests(TestCase):
    def setUp(self):
        self.kasir = User.objects.create_user("kasir8", password="rahasia-kuat-123", role=Role.KASIR)

    def test_login_kasir_tidak_lagi_dikeluarkan(self):
        r = self.client.post(
            "/login",
            {"username": "kasir8", "password": "rahasia-kuat-123"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/kasir/stok")
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_kasir_boleh_membuka_halamannya(self):
        self.client.force_login(self.kasir)
        self.assertEqual(self.client.get("/kasir/stok").status_code, 200)

    def test_kasir_dialihkan_dari_menu_yang_tak_diberikan(self):
        """GET diantar ke halaman miliknya sendiri, bukan ditabrakkan ke 403."""
        self.client.force_login(self.kasir)
        r = self.client.get("/admin-panel/users")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/kasir/stok")

    def test_kasir_menulis_ke_menu_terlarang_tetap_403(self):
        """Pengalihan hanya untuk GET — mengalihkan POST menelan tulisan diam-diam."""
        self.client.force_login(self.kasir)
        self.assertEqual(self.client.post("/admin-panel/users/save", {}).status_code, 403)

    def test_kasir_yang_dicabut_semua_menunya_ditolak(self):
        """Bukan 500 dan bukan pengalihan berputar: ditolak dengan alasan yang jelas."""
        self.kasir.allowed_menu_keys = ["stock"]  # menu POS-nya dicabut
        self.kasir.save(update_fields=["allowed_menu_keys"])
        self.client.force_login(self.kasir)
        r = self.client.get("/kasir/stok")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/admin-panel/inventory/stock")

    def test_tamu_tak_bisa_masuk_halaman_kasir(self):
        r = self.client.get("/kasir/stok")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r["Location"])


class LayarBaruKasirTests(TestCase):
    """Penjualan Order & Cetak Faktur: rutenya hidup, dan izinnya per-layar.

    Yang gampang luput: kedua layar meminjam kotak cari milik layar Penjualan.
    Kalau endpoint itu cuma terpasang di bawah /kasir/penjualan, orang yang
    diberi Penjualan Order saja akan terpental begitu mengetik di kotaknya —
    dan yang terlihat cuma "pencarian tak jalan", bukan pesan izin.
    """

    def setUp(self):
        self.kasir = User.objects.create_user("kasir7", password="rahasia-kuat-123",
                                              role=Role.KASIR)
        self.client.force_login(self.kasir)

    def test_layar_baru_terbuka_untuk_kasir(self):
        for jalur in ("/kasir/penjualan-order", "/kasir/faktur"):
            self.assertEqual(self.client.get(jalur).status_code, 200, jalur)

    def test_kotak_cari_terpasang_di_bawah_tiap_layar(self):
        """Bukan sekali di satu tempat bersama — izin diberikan per-prefix."""
        from apps.core.menus import menu_key_for_path

        self.assertEqual(menu_key_for_path("/kasir/penjualan-order/cari-barang"),
                         "kasir_penjualan_order")
        self.assertEqual(menu_key_for_path("/kasir/penjualan/cari-barang"),
                         "kasir_penjualan")
        self.assertEqual(menu_key_for_path("/kasir/pembelian/cari-barang"),
                         "kasir_pembelian")
        # Dan tak ada satu pun yang jatuh ke "bebas" — path tanpa menu tak dijaga.
        for jalur in ("/kasir/penjualan-retur/cari-barang",
                      "/kasir/pembelian-retur/cari-barang",
                      "/kasir/penjualan-order/cari-customer",
                      "/kasir/penjualan/satuan",
                      "/kasir/penjualan-order/satuan",
                      "/kasir/penjualan-retur/satuan",
                      "/kasir/pembelian/satuan",
                      "/kasir/pembelian-retur/satuan"):
            self.assertIsNotNone(menu_key_for_path(jalur), jalur)

    def test_order_tak_ikut_terbuka_kalau_menunya_dicabut(self):
        self.kasir.allowed_menu_keys = ["kasir_penjualan"]
        self.kasir.save(update_fields=["allowed_menu_keys"])
        r = self.client.get("/kasir/penjualan-order")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/kasir/penjualan")


class LayarKelolaMenuTests(TestCase):
    """Layar Kelola Menu harus JUJUR soal apa yang sedang dipegang seseorang."""

    def setUp(self):
        self.boss = User.objects.create_user(
            "boss5", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        User.objects.create_user("kasir5", password="rahasia-kuat-123", role=Role.KASIR)
        self.client.force_login(self.boss)

    def test_mengirim_menu_bawaan_tiap_peran(self):
        """Tanpa ini layar berbohong: akun yang belum diatur tampil tanpa satu
        centang pun, padahal ia SEDANG memegang menu bawaan perannya."""
        self.assertIn("kasir_stok", default_keys_for(Role.KASIR))
        self.assertIn("kasir_stok", default_keys_for(Role.SUPERVISOR))
        self.assertNotIn("kasir_stok", default_keys_for(Role.ADMIN))
        self.assertIn("users", default_keys_for(Role.ADMIN))
        # Dan benar-benar sampai ke layar, bukan cuma benar di Python.
        isi = self.client.get("/admin-panel/menus").content.decode()
        self.assertIn("role_defaults", isi)

    def test_menu_membawa_penanda_peran(self):
        """Penanda di tiap baris berasal dari `roles` di registry menu."""
        menus = {m["key"]: m for m in assignable_menus()}
        self.assertEqual(list(menus["kasir_stok"]["roles"]), ["kasir", "supervisor"])
        self.assertEqual(list(menus["retur_penjualan"]["roles"]), ["supervisor"])
        self.assertNotIn("roles", menus["users"])

    def test_master_data_tetap_wewenang_admin(self):
        """Mengubah data induk bukan pekerjaan harian toko: satu salah ketik di
        sini ikut terbawa ke SETIAP nota yang menunjuk ke baris itu."""
        menus = {m["key"]: m for m in assignable_menus()}
        for kunci in ("products", "customers", "suppliers", "update_barang",
                      "kelola_pelanggan", "kelola_supplier"):
            self.assertNotIn("roles", menus[kunci], f"{kunci} bocor ke kasir/supervisor")
            self.assertIn(kunci, default_keys_for(Role.ADMIN))

    def test_supervisor_dapat_pemantauan_transaksi(self):
        """Yang jadi jatah mereka: memantau hasil penjualan/pembelian/retur."""
        bawaan = default_keys_for(Role.SUPERVISOR)
        for kunci in ("penjualan_all", "penjualan_nota", "retur_penjualan",
                      "pembelian", "retur_pembelian"):
            self.assertIn(kunci, bawaan)
        for terlarang in ("products", "kelola_pelanggan", "users"):
            self.assertNotIn(terlarang, bawaan)

    def test_menyimpan_kosong_mengembalikan_ke_bawaan_bukan_mencabut_semua(self):
        """Yang tertulis di layar harus benar: `allowed_menu_keys` kosong
        dibaca menus_for sebagai 'pakai bawaan peran', bukan 'tak boleh apa-apa'."""
        kasir = User.objects.get(username="kasir5")
        kasir.allowed_menu_keys = []
        kasir.save(update_fields=["allowed_menu_keys"])
        self.assertEqual(_keys(kasir), set(default_keys_for(Role.KASIR)) | {"bantuan"})


class KoneksiTerkunciTests(TestCase):
    """Kasir/supervisor tak memilih koneksi — koneksi menentukan ke server toko
    MANA notanya tertulis, dan nota yang masuk ke cabang salah tak bisa ditarik:
    trigger legacy langsung mengirimkannya ke pusat."""

    def setUp(self):
        from apps.connections.models import ServerProfile

        self.a = ServerProfile.objects.create(name="TOKO A", db_type="grosir",
                                              host="a", db_name="x", is_default=True)
        self.b = ServerProfile.objects.create(name="TOKO B", db_type="grosir",
                                              host="b", db_name="y")
        self.kasir = User.objects.create_user("kasir4", password="rahasia-kuat-123",
                                              role=Role.KASIR, server_profile=self.b)
        self.admin = User.objects.create_user("admin4", password="rahasia-kuat-123",
                                              role=Role.ADMIN)

    def test_peran_toko_terkunci_peran_kantor_tidak(self):
        self.assertTrue(self.kasir.koneksi_terkunci)
        self.assertFalse(self.admin.koneksi_terkunci)

    def test_kasir_memakai_servernya_sendiri_bukan_default(self):
        from core import mssql

        self.client.force_login(self.kasir)
        s = self.client.session
        s["active_profile_id"] = self.a.pk   # coba paksa lewat sesi
        s.save()
        self.client.get("/kasir/stok")
        # Middleware mengunci ke server akun, bukan pilihan sesi.
        mssql.set_request_profile_id(self.kasir.server_profile_id, strict=True)
        self.assertEqual(mssql.get_active_profile().pk, self.b.pk)

    def test_terkunci_tanpa_server_tidak_jatuh_ke_default(self):
        """Menebak berarti nota tertulis ke server toko yang salah."""
        from core import mssql

        mssql.set_request_profile_id(None, strict=True)
        try:
            self.assertIsNone(mssql.get_active_profile())
        finally:
            mssql.clear_request_profile()

    def test_tanpa_strict_masih_jatuh_ke_default(self):
        """Perilaku lama untuk admin & pekerjaan latar tak boleh berubah."""
        from core import mssql

        mssql.set_request_profile_id(None)
        try:
            self.assertEqual(mssql.get_active_profile().pk, self.a.pk)
        finally:
            mssql.clear_request_profile()

    def test_kasir_tak_bisa_pindah_koneksi(self):
        self.client.force_login(self.kasir)
        r = self.client.post(f"/admin-panel/connections/{self.a.pk}/set-default", {})
        self.assertEqual(r.status_code, 302)
        self.assertIn("terikat", self.client.session.get("flash_error", ""))

    def test_kasir_hanya_melihat_koneksinya_sendiri(self):
        """Pemilih koneksi di navbar jadi tak punya apa pun untuk dipindah."""
        self.client.force_login(self.kasir)
        isi = self.client.get("/kasir/stok").content.decode()
        self.assertIn("TOKO B", isi)
        self.assertNotIn("TOKO A", isi)

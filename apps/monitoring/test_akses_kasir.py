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
        self.assertEqual(list(menus["kasir_pelanggan"]["roles"]), ["supervisor"])
        self.assertNotIn("roles", menus["users"])

    def test_menyimpan_kosong_mengembalikan_ke_bawaan_bukan_mencabut_semua(self):
        """Yang tertulis di layar harus benar: `allowed_menu_keys` kosong
        dibaca menus_for sebagai 'pakai bawaan peran', bukan 'tak boleh apa-apa'."""
        kasir = User.objects.get(username="kasir5")
        kasir.allowed_menu_keys = []
        kasir.save(update_fields=["allowed_menu_keys"])
        self.assertEqual(_keys(kasir), set(default_keys_for(Role.KASIR)) | {"bantuan"})

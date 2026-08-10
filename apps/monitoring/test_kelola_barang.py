"""Kelola Barang & penggantian nama Update Barang → Update Harga.

Dua hal dijaga di sini, dan yang kedua justru yang paling mudah lolos dari
pengujian manual: **key menu yang berganti tanpa migrasi akan mencabut menunya
diam-diam** dari setiap akun yang hak aksesnya diatur satu per satu.
"""
import importlib

from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.menus import ALL_MENUS, assignable_menus, menu_key_for_path, menus_for
from core import mssql

MIGRASI = importlib.import_module(
    "apps.auth_app.migrations.0008_rename_menu_update_harga")


class _Apps:
    """Pengganti `apps` historis milik migrasi — modelnya sama, tak ada
    perubahan skema di migrasi ini (hanya isi JSONField yang ditulis ulang)."""

    def get_model(self, app_label, model_name):
        return User


class PetaMenuTests(TestCase):
    def test_key_lama_sudah_tak_ada(self):
        keys = {m["key"] for m in ALL_MENUS}
        self.assertNotIn("update_barang", keys)
        self.assertNotIn("barang_baru", keys)
        self.assertIn("update_harga", keys)
        self.assertIn("kelola_barang", keys)

    def test_keduanya_bisa_diberikan_lewat_kelola_menu(self):
        keys = {m["key"] for m in assignable_menus()}
        self.assertIn("update_harga", keys)
        self.assertIn("kelola_barang", keys)

    def test_prefix_menutup_seluruh_sub_rute_update_harga(self):
        for sub in ("", "/harga", "/harga-massal", "/status", "/identitas",
                    "/riwayat", "/detail"):
            path = f"/admin-panel/master/update-harga{sub}"
            self.assertEqual(menu_key_for_path(path), "update_harga", path)

    def test_prefix_menutup_seluruh_sub_rute_kelola_barang(self):
        for sub in ("", "/cari", "/muat", "/save"):
            path = f"/admin-panel/master/kelola-barang{sub}"
            self.assertEqual(menu_key_for_path(path), "kelola_barang", path)

    def test_url_lama_tak_lagi_dimiliki_menu_mana_pun(self):
        """Kalau masih ada yang memilikinya, berarti ada href yang belum diganti."""
        self.assertIsNone(menu_key_for_path("/admin-panel/master/update-barang"))
        self.assertIsNone(menu_key_for_path("/admin-panel/master/barang-baru"))


class MigrasiKeyTests(TestCase):
    def setUp(self):
        self.apps = _Apps()

    def _user(self, nama, keys):
        return User.objects.create_user(
            nama, password="rahasia-kuat-123", role=Role.ADMIN,
            allowed_menu_keys=keys)

    def test_key_lama_ditulis_ulang(self):
        u = self._user("m1", ["dashboard", "update_barang", "stock"])
        MIGRASI.maju(self.apps, None)
        u.refresh_from_db()
        self.assertEqual(u.allowed_menu_keys, ["dashboard", "update_harga", "stock"])

    def test_akun_yang_terdampak_tetap_melihat_menunya(self):
        """Inti seluruh migrasi ini."""
        u = self._user("m2", ["dashboard", "update_barang"])
        MIGRASI.maju(self.apps, None)
        u.refresh_from_db()
        self.assertIn("update_harga", {m["key"] for m in menus_for(u)})

    def test_daftar_kosong_tidak_disentuh(self):
        """Kosong = akses penuh (lihat auth_app/models.py). Mengisinya di sini
        justru MENYEMPITKAN hak akses orang yang sebelumnya dapat semuanya."""
        u = self._user("m3", [])
        MIGRASI.maju(self.apps, None)
        u.refresh_from_db()
        self.assertEqual(u.allowed_menu_keys, [])

    def test_akun_tanpa_key_itu_tidak_berubah(self):
        u = self._user("m4", ["dashboard", "stock"])
        MIGRASI.maju(self.apps, None)
        u.refresh_from_db()
        self.assertEqual(u.allowed_menu_keys, ["dashboard", "stock"])

    def test_tidak_menghasilkan_duplikat(self):
        u = self._user("m5", ["update_barang", "update_harga"])
        MIGRASI.maju(self.apps, None)
        u.refresh_from_db()
        self.assertEqual(u.allowed_menu_keys, ["update_harga"])

    def test_bisa_dibalik(self):
        u = self._user("m6", ["dashboard", "update_barang"])
        MIGRASI.maju(self.apps, None)
        MIGRASI.mundur(self.apps, None)
        u.refresh_from_db()
        self.assertEqual(u.allowed_menu_keys, ["dashboard", "update_barang"])


class RuteTests(TestCase):
    def setUp(self):
        self.profil = ServerProfile.objects.create(
            name="TOKO B", host="host-b", db_name="SOLID_SIM",
            username="sa", password_encrypted="x", is_default=True)
        self.boss = User.objects.create_user(
            "boss_b", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.admin = User.objects.create_user(
            "admin_b", password="rahasia-kuat-123", role=Role.ADMIN,
            server_profile=self.profil)
        mssql.set_request_profile_id(self.profil.id)
        self.addCleanup(mssql.clear_request_profile)

    def test_url_lama_dialihkan_beserta_querystring(self):
        """Tab yang sudah terbuka masih memegang alamat lama.

        `?search=` ikut terbawa: mengalihkan tanpa itu membuang apa yang sedang
        dicari orang, dan di layar berisi 53.865 barang itu bukan hal kecil.
        """
        self.client.force_login(self.boss)
        r = self.client.get("/admin-panel/master/update-barang?search=OFOCTB26")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"],
                         "/admin-panel/master/update-harga?search=OFOCTB26")
        r = self.client.get("/admin-panel/master/barang-baru")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/admin-panel/master/kelola-barang")

    def test_save_menolak_GET(self):
        self.client.force_login(self.boss)
        self.assertEqual(
            self.client.get("/admin-panel/master/kelola-barang/save").status_code, 405)

    def test_menu_dicabut_menutup_sub_rutenya(self):
        self.admin.allowed_menu_keys = ["dashboard"]
        self.admin.save(update_fields=["allowed_menu_keys"])
        self.client.force_login(self.admin)
        for path in ("/admin-panel/master/kelola-barang",
                     "/admin-panel/master/kelola-barang/cari",
                     "/admin-panel/master/update-harga"):
            r = self.client.get(path)
            self.assertIn(r.status_code, (302, 403), path)


class TakAdaAlamatBasiTests(TestCase):
    """Tak ada satu pun berkas sumber yang masih menunjuk alamat lama.

    Test ini lahir dari kesalahan nyata: penggantian URL dijalankan dengan
    daftar berkas yang disusun tangan, dan `frontend/pages/` tak ikut masuk.
    Akibatnya `UpdateBarang.vue` memanggil alamatnya sendiri yang sudah tak ada
    — layar Update Harga menabrak 404 begitu kotak carinya dipakai. Seluruh 662
    test lolos saat itu, karena tak satu pun menyentuh berkas .vue.

    Menyisir teks memang kasar, tapi ia menangkap persis yang luput: rujukan
    yang hidup di berkas yang tak pernah dijalankan test mana pun.
    """

    LAMA = ("/admin-panel/master/update-barang", "/admin-panel/master/barang-baru")
    # urls.py memang HARUS menyebutnya — di situlah pengalihannya didefinisikan.
    DIKECUALIKAN = {"urls.py", "test_kelola_barang.py"}
    SUFIKS = (".py", ".vue", ".js")
    LEWATI = {"node_modules", "dist", "__pycache__", ".git", "venv", "staticfiles"}

    def test_tak_ada_rujukan_alamat_lama(self):
        import pathlib

        akar = pathlib.Path(__file__).resolve().parents[2]
        temuan = []
        for folder in ("apps", "frontend", "config", "core"):
            for f in (akar / folder).rglob("*"):
                if (not f.is_file() or f.suffix not in self.SUFIKS
                        or f.name in self.DIKECUALIKAN
                        or self.LEWATI & set(f.parts)):
                    continue
                isi = f.read_text(encoding="utf-8", errors="replace")
                for alamat in self.LAMA:
                    # "riwayat-update-barang" menu yang berbeda dan tetap ada.
                    for baris_no, baris in enumerate(isi.splitlines(), 1):
                        if alamat in baris.replace("riwayat-update-barang", ""):
                            temuan.append(f"{f.relative_to(akar)}:{baris_no}")
        self.assertEqual(temuan, [], "alamat lama masih dirujuk: " + ", ".join(temuan))

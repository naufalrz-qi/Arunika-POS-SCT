"""Pembaruan Database: migrasi dari panel, pengganti `migrate` di rilis rutin.

Yang dijaga di sini hal-hal yang gagal tanpa suara:

1. **DB Arunika hanya menerima `bisnis`.** Tanpa saringan app, `auth`/`core`/dst.
   tampak tertunda selamanya di sana — penanda tak pernah hilang, dan tombolnya
   akan mencoba menjalankan migrasi pangkal ke database yang salah.
2. **DB Arunika yang belum ada bukan galat**, dan layar ini tak boleh
   membuatnya: itu tugas Transfer ke Arunika, yang tahu mode view-nya.
3. **Satu sasaran gagal tak menjatuhkan yang lain.**
4. **Penanda hanya untuk superadmin, dan hanya menghubungi pangkal.**
"""
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.bisnis.siapkan import Ditolak
from apps.connections.models import ServerProfile
from apps.core import migrasi
from apps.core.middleware import _migrasi_tertunda
from apps.core.menus import ALL_MENUS


def _mig(app, nama):
    m = MagicMock()
    m.app_label, m.name = app, nama
    return m


class Tertunda(TestCase):
    def test_test_db_mutakhir(self):
        """Test DB dibangun dari seluruh migrasi, jadi tak ada yang tertunda —
        yang dibuktikan di sini jalurnya sampai ke MigrationExecutor sungguhan."""
        self.assertEqual(migrasi.tertunda(), [])

    def test_saringan_app_membuang_app_lain(self):
        rencana = [(_mig("core", "0019_x"), False), (_mig("bisnis", "0022_y"), False),
                   (_mig("auth_app", "0009_z"), False)]
        with patch.object(migrasi, "MigrationExecutor") as ex:
            ex.return_value.migration_plan.return_value = rencana
            # Aliasnya tak penting di sini — executor-nya palsu; yang diuji saringannya.
            self.assertEqual(migrasi.tertunda("default", app="bisnis"), ["bisnis.0022_y"])
            self.assertEqual(migrasi.tertunda(),
                             ["core.0019_x", "bisnis.0022_y", "auth_app.0009_z"])

    def test_langkah_mundur_tak_dihitung(self):
        with patch.object(migrasi, "MigrationExecutor") as ex:
            ex.return_value.migration_plan.return_value = [(_mig("core", "0019_x"), True)]
            self.assertEqual(migrasi.tertunda(), [])


class Jalankan(TestCase):
    def setUp(self):
        self.ar = ServerProfile.objects.create(
            name="TOKO A", host="h", db_name="SOLID_SIM", username="sa",
            password_encrypted="x", db_arunika="arunika_a")
        # Profil tanpa DB Arunika tak boleh jadi sasaran sama sekali.
        ServerProfile.objects.create(
            name="TOKO B", host="h", db_name="SOLID_SIM", username="sa",
            password_encrypted="x")

    def test_sasaran_pangkal_dulu_lalu_hanya_profil_ber_db_arunika(self):
        self.assertEqual(migrasi.sasaran(), [None, self.ar])

    def _jalan(self, tertunda, ada=True, migrate=None):
        with patch.object(migrasi, "tertunda", side_effect=tertunda) as t, \
             patch.object(migrasi, "database_ada", return_value=ada), \
             patch.object(migrasi.db_alias, "daftarkan", return_value="cabang_a"), \
             patch.object(migrasi, "connections", MagicMock()), \
             patch.object(migrasi, "call_command", side_effect=migrate) as cc:
            return migrasi.jalankan(), cc, t

    def test_pangkal_penuh_arunika_hanya_bisnis(self):
        antrean = {"default": [["core.0019_x"], []],
                   "cabang_a": [["bisnis.0022_y"], []]}
        hasil, cc, _ = self._jalan(lambda alias="default", app=None: antrean[alias].pop(0))
        panggilan = [(c.args, c.kwargs["database"]) for c in cc.call_args_list]
        self.assertEqual(panggilan, [(("migrate",), "default"),
                                     (("migrate", "bisnis"), "cabang_a")])
        self.assertEqual(hasil[0]["diterapkan"], ["core.0019_x"])
        self.assertEqual(hasil[1]["diterapkan"], ["bisnis.0022_y"])

    def test_db_arunika_belum_ada_dilewati_bukan_dibuat(self):
        hasil, cc, _ = self._jalan(lambda alias="default", app=None: [], ada=False)
        self.assertEqual(hasil[1]["keadaan"], "belum_ada")
        # Tak ada `migrate` ke database yang tak ada — dan tak ada CREATE apa pun.
        self.assertEqual([c.kwargs["database"] for c in cc.call_args_list], [])

    def test_mutakhir_tak_memanggil_migrate(self):
        _, cc, _ = self._jalan(lambda alias="default", app=None: [])
        cc.assert_not_called()

    def test_satu_sasaran_gagal_yang_lain_tetap_jalan(self):
        antrean = {"default": [["core.0019_x"], ["core.0019_x"]],
                   "cabang_a": [["bisnis.0022_y"], []]}

        def migrate(*args, database, **kw):
            if database == "default":
                raise RuntimeError("kolom sudah ada")

        hasil, cc, _ = self._jalan(
            lambda alias="default", app=None: antrean[alias].pop(0), migrate=migrate)
        self.assertEqual(hasil[0]["keadaan"], "galat")
        self.assertIn("kolom sudah ada", hasil[0]["pesan"])
        # Dihitung ulang sesudah gagal: yang belum jadi tetap terpampang.
        self.assertEqual(hasil[0]["tertunda"], ["core.0019_x"])
        self.assertEqual(hasil[0]["diterapkan"], [])
        self.assertEqual(hasil[1]["diterapkan"], ["bisnis.0022_y"])

    def test_dua_klik_bersamaan_ditolak(self):
        migrasi._kunci.acquire()
        try:
            with self.assertRaises(Ditolak):
                migrasi.jalankan()
        finally:
            migrasi._kunci.release()


class HalamanDanPenanda(TestCase):
    def setUp(self):
        self.sa = User.objects.create_user(
            "sa_m", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.admin = User.objects.create_user(
            "admin_m", password="rahasia-kuat-123", role=Role.ADMIN)

    def test_menu_superadmin_saja(self):
        m = next(m for m in ALL_MENUS if m["key"] == "migrasi")
        self.assertTrue(m.get("superadmin_only"))
        self.assertEqual(m["href"], "/admin-panel/pengaturan/migrasi")

    def test_admin_tak_bisa_menjalankan(self):
        """POST ditolak di DUA lapis: penjaga menu dan view itu sendiri."""
        self.client.force_login(self.admin)
        with patch.object(migrasi, "jalankan") as j:
            r = self.client.post("/admin-panel/pengaturan/migrasi/jalankan")
        j.assert_not_called()
        self.assertIn(r.status_code, (302, 403))

    def test_superadmin_menjalankan_dan_hasilnya_tampil_sekali(self):
        self.client.force_login(self.sa)
        hasil = [{"sasaran": "Pangkal", "db": "(basis data aplikasi)", "keadaan": "ok",
                  "pesan": "", "tertunda": [], "diterapkan": ["core.0019_x"]}]
        with patch.object(migrasi, "jalankan", return_value=hasil):
            r = self.client.post("/admin-panel/pengaturan/migrasi/jalankan",
                                 data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 302)

        def hasil_di_halaman():
            # Header partial-reload yang sama dengan test_uang_e2e.
            r = self.client.get(
                "/admin-panel/pengaturan/migrasi", HTTP_X_INERTIA="true",
                HTTP_X_INERTIA_VERSION="1.0", HTTP_X_INERTIA_PARTIAL_DATA="hasil",
                HTTP_X_INERTIA_PARTIAL_COMPONENT="Admin/Pengaturan/Migrasi")
            return json.loads(r.content)["props"]["hasil"]

        self.assertEqual(hasil_di_halaman(), hasil)
        self.assertIsNone(hasil_di_halaman())   # sekali tampil, lalu hilang

    def test_penanda_nol_bagi_non_superadmin_tanpa_menyentuh_db(self):
        with patch.object(migrasi, "tertunda") as t:
            self.assertEqual(_migrasi_tertunda(self.admin), 0)
            t.assert_not_called()

    def test_penanda_menghitung_hanya_pangkal(self):
        with patch.object(migrasi, "tertunda", return_value=["core.0019_x", "bisnis.0022_y"]) as t:
            self.assertEqual(_migrasi_tertunda(self.sa), 2)
        # Tanpa alias: pangkal saja. Menghubungi DB Arunika di sini berarti
        # satu server jauh yang mati menahan SETIAP render lima detik.
        t.assert_called_once_with()

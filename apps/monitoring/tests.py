"""Security regression tests: user management hardening + per-menu RBAC."""
import io

import pyodbc
from django.test import SimpleTestCase, TestCase

from apps.auth_app.models import Role, User
from apps.core import reporting
from apps.core.menus import menu_key_for_path
from apps.core.middleware import _menu_allowed
from core import mssql
from core.encryption import PasswordDecryptError


class ProfileAuthErrorTests(SimpleTestCase):
    """Regresi: POS_FERNET_KEY rusak/dirotasi melempar PasswordDecryptError
    (RuntimeError), yang lolos SEMUA `except pyodbc.Error` di views -> 500 di
    hampir tiap halaman data. mssql.cursor() harus membungkusnya."""

    class _Profile:
        host, port, db_name, username = "h", 1433, "db", "u"
        password_encrypted = "gibberish"

    def test_key_rusak_jadi_pyodbc_error_berpesan_indonesia(self):
        def boom(_):
            raise PasswordDecryptError(
                "Password tersimpan tidak bisa dibaca — kemungkinan POS_FERNET_KEY di .env berubah."
            )

        with self.settings():
            orig = mssql.decrypt_checked
            mssql.decrypt_checked = boom
            try:
                with self.assertRaises(pyodbc.Error) as ctx:
                    with mssql.cursor(self._Profile()):
                        pass
            finally:
                mssql.decrypt_checked = orig
        self.assertIn("POS_FERNET_KEY", str(ctx.exception.args[-1]))


class FriendlyErrorTests(SimpleTestCase):
    """Teks driver ODBC (Inggris, ber-SQLSTATE) tak boleh bocor ke banner Indonesia."""

    def test_prefiks_driver_dibuang(self):
        exc = pyodbc.Error("42S22", "[Microsoft][ODBC Driver 17 for SQL Server]Kolom tak dikenal")
        msg = mssql.friendly_error(exc, "Gagal membaca stok")
        self.assertNotIn("[Microsoft]", msg)
        self.assertTrue(msg.startswith("Gagal membaca stok: "))

    def test_sqlstate_koneksi_jadi_kalimat_indonesia(self):
        exc = pyodbc.Error("08001", "[Microsoft][ODBC Driver 17 for SQL Server]Login timeout expired")
        msg = mssql.friendly_error(exc, "Gagal membaca stok")
        self.assertEqual(msg, "Gagal membaca stok: server tidak dapat dihubungi. Periksa jaringan/koneksi.")

    def test_profile_auth_error_diteruskan_apa_adanya(self):
        exc = mssql.ProfileAuthError("HY000", "POS_FERNET_KEY di .env berubah.")
        self.assertEqual(mssql.friendly_error(exc, "Gagal"), "POS_FERNET_KEY di .env berubah.")


class XlsxIllegalCharTests(TestCase):
    """Regresi: teks legacy MS SQL berkarakter kontrol bikin openpyxl melempar
    IllegalCharacterError (lolos `except pyodbc.Error` -> 500 saat export)."""

    def test_clean_buang_karakter_kontrol_dan_trim(self):
        self.assertEqual(reporting._clean("bad\x00te\x1fxt "), "badtext")
        self.assertEqual(reporting._clean("\tok\n"), "\tok\n".strip())  # tab/LF sah

    def test_xlsx_response_tak_error_untuk_teks_kotor(self):
        cols = [{"key": "nama", "label": "Nama"}]
        resp = reporting.xlsx_response("t", cols, [{"nama": "PT ABC\x00 \x07Jaya"}])
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        self.assertEqual(wb["Data"].cell(row=2, column=1).value, "PT ABC Jaya")


class UsersSaveHardeningTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            "boss", password="rahasia-kuat-123", role=Role.SUPERADMIN
        )
        self.kasir = User.objects.create_user(
            "kasir1", password="rahasia-kuat-123", role=Role.KASIR
        )
        self.client.force_login(self.superadmin)

    def test_admin_tak_bisa_bikin_superadmin(self):
        """Superadmin BOLEH membuat superadmin (_managed_roles memuat semua role
        untuknya). Yang harus ditolak: seorang admin menaikkan hak ke superadmin."""
        admin = User.objects.create_user("adm", password="rahasia-kuat-123", role=Role.ADMIN)
        self.client.force_login(admin)
        self.client.post(
            "/admin-panel/users/save",
            {"username": "jahat", "name": "X", "role": "superadmin", "password": "rahasia-kuat-123"},
        )
        self.assertFalse(User.objects.filter(username="jahat").exists())

    def test_role_tak_dikenal_ditolak(self):
        self.client.post(
            "/admin-panel/users/save",
            {"username": "aneh", "name": "X", "role": "hacker", "password": "rahasia-kuat-123"},
        )
        self.assertFalse(User.objects.filter(username="aneh").exists())

    def test_superadmin_terakhir_tak_bisa_diturunkan(self):
        """Superadmin kini boleh mengelola sesama superadmin, jadi bukan lagi 404 —
        yang menahan adalah _last_superadmin_guard (redirect + flash)."""
        resp = self.client.post(
            "/admin-panel/users/save",
            {"id": self.superadmin.pk, "name": "Pwned", "role": "kasir", "password": "rahasia-kuat-123"},
        )
        self.assertEqual(resp.status_code, 302)
        self.superadmin.refresh_from_db()
        self.assertEqual(self.superadmin.role, Role.SUPERADMIN)

    def test_admin_tak_bisa_edit_superadmin(self):
        admin = User.objects.create_user("adm2", password="rahasia-kuat-123", role=Role.ADMIN)
        self.client.force_login(admin)
        resp = self.client.post(
            "/admin-panel/users/save",
            {"id": self.superadmin.pk, "name": "Pwned", "role": "kasir", "password": "rahasia-kuat-123"},
        )
        self.assertEqual(resp.status_code, 404)
        self.superadmin.refresh_from_db()
        self.assertEqual(self.superadmin.role, Role.SUPERADMIN)

    def test_superadmin_terakhir_tak_bisa_dihapus(self):
        """/delete kini hard delete; penjaganya redirect, bukan 404."""
        resp = self.client.post(f"/admin-panel/users/{self.superadmin.pk}/delete")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.superadmin.pk).exists())

    def test_user_baru_wajib_password(self):
        self.client.post(
            "/admin-panel/users/save", {"username": "baru", "name": "B", "role": "kasir"}
        )
        self.assertFalse(User.objects.filter(username="baru").exists())

    def test_password_lemah_ditolak(self):
        self.client.post(
            "/admin-panel/users/save",
            {"username": "baru", "name": "B", "role": "kasir", "password": "123"},
        )
        self.assertFalse(User.objects.filter(username="baru").exists())

    def test_user_valid_tersimpan(self):
        self.client.post(
            "/admin-panel/users/save",
            {"username": "baru", "name": "Budi Santoso", "role": "kasir", "password": "rahasia-kuat-123"},
        )
        user = User.objects.get(username="baru")
        self.assertEqual(user.role, Role.KASIR)
        self.assertTrue(user.check_password("rahasia-kuat-123"))


class MenuRbacEnforcementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "admin1",
            password="rahasia-kuat-123",
            role=Role.ADMIN,
            allowed_menu_keys=["dashboard"],
        )
        self.superadmin = User.objects.create_user(
            "boss", password="rahasia-kuat-123", role=Role.SUPERADMIN
        )

    def test_admin_terbatas_diblokir_dari_menu_lain(self):
        self.client.force_login(self.admin)
        for path in ("/admin-panel/users", "/admin-panel/connections", "/admin-panel/logs"):
            self.assertEqual(self.client.get(path).status_code, 403, path)

    def test_admin_terbatas_boleh_menu_miliknya(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/admin-panel/dashboard").status_code, 200)

    def test_admin_diblokir_dari_menu_superadmin(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/admin-panel/menus").status_code, 403)

    def test_bantuan_selalu_boleh_walau_tak_diberikan(self):
        """Menu ber-`always` tak bisa dicabut: bantuan yang hilang dari sidebar
        justru menghilang tepat saat pengguna paling butuh."""
        self.client.force_login(self.admin)  # allowed_menu_keys = ["dashboard"] saja
        self.assertEqual(self.client.get("/admin-panel/bantuan").status_code, 200)

    def test_bantuan_tak_muncul_di_daftar_yang_bisa_dicabut(self):
        from apps.core.menus import assignable_menus
        self.assertNotIn("bantuan", {m["key"] for m in assignable_menus()})

    def test_superadmin_bebas(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get("/admin-panel/users").status_code, 200)
        self.assertEqual(self.client.get("/admin-panel/menus").status_code, 200)

    def test_path_export_ikut_menu_induknya(self):
        self.assertEqual(menu_key_for_path("/admin-panel/laporan/penjualan/export"), "penjualan_all")
        self.assertEqual(menu_key_for_path("/admin-panel/laporan/penjualan-nota"), "penjualan_nota")
        self.assertIsNone(menu_key_for_path("/admin-panel/profile"))

    def test_switcher_koneksi_dikecualikan(self):
        self.assertTrue(_menu_allowed(self.admin, "/admin-panel/connections/3/set-default"))
        self.assertFalse(_menu_allowed(self.admin, "/admin-panel/connections"))


class DashboardAktivitasScopeTests(TestCase):
    """Kartu Aktivitas Terbaru di dashboard hanya menampilkan jejak pemakainya.

    Halaman Log Aktivitas (/admin-panel/logs) sengaja TIDAK ikut disaring — itu
    layar audit, dan aksesnya sudah dijaga lewat menu. Kalau suatu saat ada yang
    "merapikan" keduanya jadi satu jalur, tes ini yang menahannya.
    """

    def setUp(self):
        from apps.core.models import ActivityLog

        self.staf = User.objects.create_user(
            "staf", password="rahasia-kuat-123", role=Role.ADMIN)
        self.boss = User.objects.create_user(
            "boss", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        ActivityLog.objects.create(username="staf", action="login", detail="Login berhasil")
        ActivityLog.objects.create(username="orang_lain", action="konfigurasi", detail="Ganti koneksi")

    def _dashboard_users(self, user):
        import json

        self.client.force_login(user)
        r = self.client.get(
            "/admin-panel/dashboard",
            HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0",
            HTTP_X_INERTIA_PARTIAL_DATA="dashboard",
            HTTP_X_INERTIA_PARTIAL_COMPONENT="Admin/Dashboard",
        )
        rows = json.loads(r.content)["props"]["dashboard"]["recent_activity"]
        return {a["user"] for a in rows}

    def test_admin_hanya_melihat_jejaknya_sendiri(self):
        self.assertEqual(self._dashboard_users(self.staf), {"staf"})

    def test_superadmin_melihat_semua(self):
        self.assertIn("orang_lain", self._dashboard_users(self.boss))

    def test_halaman_log_tidak_ikut_disaring(self):
        import json

        self.client.force_login(self.staf)
        r = self.client.get("/admin-panel/logs", HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0")
        users = {a["user"] for a in json.loads(r.content)["props"]["logs"]}
        self.assertIn("orang_lain", users)


class DashboardStatusServerTests(TestCase):
    """Status server khusus superadmin.

    Daftarnya membuka nama host dan port tiap server MS SQL — peta
    infrastruktur yang tak dibutuhkan siapa pun untuk memakai aplikasi. Yang
    diuji isi RESPONS, bukan layarnya: `v-if` di Vue tak menahan apa pun.
    """

    def setUp(self):
        self.staf = User.objects.create_user(
            "staf", password="rahasia-kuat-123", role=Role.ADMIN)
        self.boss = User.objects.create_user(
            "boss", password="rahasia-kuat-123", role=Role.SUPERADMIN)

    def _dashboard(self, user):
        import json

        self.client.force_login(user)
        r = self.client.get(
            "/admin-panel/dashboard",
            HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0",
            HTTP_X_INERTIA_PARTIAL_DATA="dashboard",
            HTTP_X_INERTIA_PARTIAL_COMPONENT="Admin/Dashboard",
        )
        return json.loads(r.content)["props"]["dashboard"]

    def test_admin_tak_menerima_daftar_server(self):
        self.assertEqual(self._dashboard(self.staf)["servers"], [])

    def test_admin_tak_menerima_hitungan_server(self):
        # Kalau kuncinya tetap dikirim bernilai 0, layar membaca "0 / 0" —
        # terbaca seperti semua server mati, bukan seperti tak berhak melihat.
        stats = self._dashboard(self.staf)["stats"]
        self.assertNotIn("servers_online", stats)
        self.assertNotIn("servers_total", stats)

    def test_superadmin_menerima_keduanya(self):
        d = self._dashboard(self.boss)
        self.assertIn("servers_total", d["stats"])

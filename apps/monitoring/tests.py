"""Security regression tests: user management hardening + per-menu RBAC."""
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.core.menus import menu_key_for_path
from apps.core.middleware import _menu_allowed


class UsersSaveHardeningTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            "boss", password="rahasia-kuat-123", role=Role.SUPERADMIN
        )
        self.kasir = User.objects.create_user(
            "kasir1", password="rahasia-kuat-123", role=Role.KASIR
        )
        self.client.force_login(self.superadmin)

    def test_role_admin_tier_ditolak(self):
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

    def test_akun_admin_tier_tak_bisa_diedit(self):
        resp = self.client.post(
            "/admin-panel/users/save",
            {"id": self.superadmin.pk, "name": "Pwned", "role": "kasir", "password": "rahasia-kuat-123"},
        )
        self.assertEqual(resp.status_code, 404)
        self.superadmin.refresh_from_db()
        self.assertEqual(self.superadmin.role, Role.SUPERADMIN)

    def test_akun_admin_tier_tak_bisa_dinonaktifkan(self):
        resp = self.client.post(f"/admin-panel/users/{self.superadmin.pk}/delete")
        self.assertEqual(resp.status_code, 404)

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

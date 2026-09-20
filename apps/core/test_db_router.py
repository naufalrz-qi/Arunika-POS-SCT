"""Router: tabel `bisnis` tak dibuat di pangkal, tabel Django tak dibuat di cabang.

Dua arahnya sama pentingnya. Yang kedua yang lebih berbahaya: `migrate` tanpa nama app
terhadap alias `cabang_*` akan menumpahkan auth, sesi, dan log ke database Arunika milik
sebuah cabang — dan itu perintah yang wajar diketik orang.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.core.db_alias import PREFIX
from apps.core.db_router import PangkalRouter


class AllowMigrate(SimpleTestCase):
    def setUp(self):
        self.router = PangkalRouter()

    def test_terpasang_di_settings(self):
        """Router yang tak terdaftar tak menjalankan apa pun."""
        self.assertIn("apps.core.db_router.PangkalRouter", settings.DATABASE_ROUTERS)

    @override_settings(TESTING=False)
    def test_bisnis_tidak_ke_pangkal(self):
        self.assertFalse(self.router.allow_migrate("default", "bisnis"))

    def test_bisnis_ke_alias_cabang(self):
        self.assertTrue(self.router.allow_migrate(f"{PREFIX}gudang", "bisnis"))

    @override_settings(TESTING=True)
    def test_bisnis_ke_database_test(self):
        """Dikecualikan dengan sengaja: apps/bisnis/test_pergerakan.py memakai ORM
        di koneksi default."""
        self.assertTrue(self.router.allow_migrate("default", "bisnis"))

    def test_app_django_tak_tumpah_ke_cabang(self):
        for app in ("auth_app", "sessions", "core", "contenttypes"):
            with self.subTest(app=app):
                self.assertFalse(self.router.allow_migrate(f"{PREFIX}gudang", app))

    def test_app_django_tetap_ke_pangkal(self):
        for app in ("auth_app", "sessions", "core"):
            with self.subTest(app=app):
                self.assertTrue(self.router.allow_migrate("default", app))

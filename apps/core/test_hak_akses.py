"""Hak akses bertingkat — spec docs/superpowers/specs/2026-09-22-hak-akses-bertingkat-design.md."""
from django.test import TestCase

from apps.auth_app.models import Role, User, bisa_kelola, peran_terkelola

PW = "rahasia-kuat-123"


def _u(nama, role, **kw):
    return User.objects.create_user(nama, password=PW, role=role, **kw)


class UrutanPeranTests(TestCase):
    """§3.4 — satu urutan untuk Kelola Menu dan Manajemen User."""

    def setUp(self):
        self.boss = _u("boss", Role.SUPERADMIN)
        self.adm = _u("adm", Role.ADMIN)
        self.adm2 = _u("adm2", Role.ADMIN)
        self.spv = _u("spv", Role.SUPERVISOR)
        self.kasir = _u("kasir", Role.KASIR)

    def test_peran_terkelola_setara_atau_di_bawah(self):
        self.assertEqual(peran_terkelola(self.boss),
                         [Role.KASIR, Role.SUPERVISOR, Role.ADMIN, Role.SUPERADMIN])
        self.assertEqual(peran_terkelola(self.adm), [Role.KASIR, Role.SUPERVISOR, Role.ADMIN])
        self.assertEqual(peran_terkelola(self.spv), [Role.KASIR, Role.SUPERVISOR])

    def test_bisa_kelola(self):
        self.assertTrue(bisa_kelola(self.adm, self.adm2))
        self.assertTrue(bisa_kelola(self.adm, self.kasir))
        self.assertFalse(bisa_kelola(self.adm, self.adm), "diri sendiri")
        self.assertFalse(bisa_kelola(self.adm, self.boss))
        self.assertFalse(bisa_kelola(self.spv, self.adm))
        self.assertTrue(bisa_kelola(self.boss, self.boss))

    def test_supervisor_dengan_manajemen_user_tak_bisa_membuat_admin(self):
        """Celah lama: _managed_roles() memberi setiap non-superadmin wewenang atas admin."""
        self.spv.allowed_menu_keys = ["users"]
        self.spv.save(update_fields=["allowed_menu_keys"])
        self.client.force_login(self.spv)
        self.client.post("/admin-panel/users/save",
                         {"username": "naik", "name": "N", "role": "admin", "password": PW})
        self.assertFalse(User.objects.filter(username="naik").exists())

    def test_admin_tak_bisa_menyunting_dirinya_lewat_manajemen_user(self):
        self.adm.allowed_menu_keys = ["users"]
        self.adm.save(update_fields=["allowed_menu_keys"])
        self.client.force_login(self.adm)
        r = self.client.post("/admin-panel/users/save",
                             {"id": self.adm.pk, "username": "adm", "name": "Ganti", "role": "admin"})
        self.assertEqual(r.status_code, 404)

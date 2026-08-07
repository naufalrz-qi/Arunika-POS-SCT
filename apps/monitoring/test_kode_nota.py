"""Kelola Kode Nota — setelan yang menentukan awalan SETIAP nomor nota berikutnya.

Salah isi berarti nota tercatat atas nama cabang lain, dan nota yang sudah
tertulis tak bisa ditarik lagi. Karena itu layarnya superadmin-only, tulisnya
POST-only, dan nilai lamanya ikut dicatat ke log.
"""
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.auth_app.models import Role, User
from apps.master_data import services as master


class ValidasiKodeNotaTests(SimpleTestCase):
    def _update(self, kepala):
        # Ditolak sebelum menyentuh MS SQL, jadi profilnya tak perlu nyata.
        return master.update_kepala_nota(object(), "DAA000", kepala)

    def test_kode_dengan_spasi_ditolak(self):
        """Spasi di awalan membuat nomor nota tak bisa dicocokkan dengan LIKE —
        jalan yang dipakai penomoran maupun laporan."""
        with self.assertRaises(ValueError):
            self._update("S C")

    def test_kode_kosong_ditolak(self):
        with self.assertRaises(ValueError):
            self._update("")

    def test_kode_kepanjangan_ditolak(self):
        """varchar(5) di m_divisi."""
        with self.assertRaises(ValueError):
            self._update("ABCDEF")

    def test_tanda_baca_ditolak(self):
        with self.assertRaises(ValueError):
            self._update("SC-")

    def test_divisi_kosong_ditolak(self):
        with self.assertRaises(ValueError):
            master.update_kepala_nota(object(), "", "SC")


class GerbangKodeNotaTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            "boss6", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.admin = User.objects.create_user(
            "admin6", password="rahasia-kuat-123", role=Role.ADMIN)

    def test_admin_biasa_tidak_boleh_membuka(self):
        """Dihadang middleware sebelum view-nya jalan: menu superadmin-only tak
        pernah masuk daftar menu admin. Yang MEMBACA diantar ke halamannya
        sendiri, bukan ditabrakkan ke tembok — itu perilaku yang sudah ada."""
        self.client.force_login(self.admin)
        r = self.client.get("/admin-panel/master/kode-nota")
        self.assertEqual(r.status_code, 302)
        self.assertNotEqual(r["Location"], "/admin-panel/master/kode-nota")

    def test_admin_biasa_tidak_boleh_menyimpan(self):
        self.client.force_login(self.admin)
        r = self.client.post("/admin-panel/master/kode-nota/save",
                             {"kd_divisi": "DAA000", "kepala_nota": "XX"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_superadmin_boleh_membuka(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get("/admin-panel/master/kode-nota").status_code, 200)

    def test_menyimpan_lewat_get_ditolak(self):
        """Tanpa @require_POST, setelan ini bisa diubah cuma dengan membuka URL."""
        self.client.force_login(self.boss)
        self.assertEqual(
            self.client.get("/admin-panel/master/kode-nota/save").status_code, 405)

    def test_perubahan_dicatat_dengan_nilai_lamanya(self):
        """Kalau muncul nota berawalan aneh, yang dicari pertama adalah kapan
        setelan ini berubah — dan dari apa."""
        from apps.core.models import ActivityLog

        self.client.force_login(self.boss)
        with patch.object(master, "update_kepala_nota",
                          return_value={"kd_divisi": "DAA000", "lama": "SC", "baru": "XX"}), \
             patch("apps.monitoring.views._active", return_value=object()):
            self.client.post("/admin-panel/master/kode-nota/save",
                             {"kd_divisi": "DAA000", "kepala_nota": "XX"},
                             content_type="application/json")
        log = ActivityLog.objects.filter(action="kode_nota").first()
        self.assertIsNotNone(log)
        self.assertIn("SC", log.detail)
        self.assertIn("XX", log.detail)

"""Akun Arunika ditautkan ke user legacy, bukan disalin darinya.

Transaksi legacy menyimpan `kd_user` (m_userx), bukan id user Arunika. Tanpa
tautan itu nota yang ditulis Arunika tak bisa dikenali laporan "Penjualan per
User" — di Arunika maupun di aplikasi POS lama.

Yang dijaga di sini: tautannya tersimpan, dan kolom sandi legacy tidak pernah
ikut terbawa. m_userx.passwd menyimpan sandi apa adanya (terukur 4-9 karakter),
dan passweb adalah peninggalan pengembang sebelumnya yang sudah diketahui
mengganggu aplikasi legacy. Keduanya haram disentuh.
"""
import inspect

from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.master_data import services as master


class TautanUserLegacyTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            "boss7", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.client.force_login(self.boss)

    def _simpan(self, **extra):
        payload = {"username": "kasir7", "name": "Budi", "role": Role.KASIR,
                   "password": "rahasia-kuat-123"}
        payload.update(extra)
        return self.client.post("/admin-panel/users/save", payload,
                                content_type="application/json")

    def test_tautan_tersimpan(self):
        self._simpan(kd_user="UAA002", kd_divisi="DAA000")
        u = User.objects.get(username="kasir7")
        self.assertEqual(u.kd_user, "UAA002")
        self.assertEqual(u.kd_divisi, "DAA000")

    def test_tanpa_tautan_tetap_boleh_disimpan(self):
        """Akun admin tak butuh kd_user; memaksakannya akan menghalangi
        pembuatan akun yang memang tak pernah membuat transaksi."""
        self._simpan()
        self.assertEqual(User.objects.get(username="kasir7").kd_user, "")

    def test_kode_kepanjangan_dipangkas_bukan_meledak(self):
        """kd_user char(6) di legacy. Yang kepanjangan ditolak di sini, bukan
        jadi galat SQLite yang tak berarti apa pun bagi yang mengisinya."""
        self._simpan(kd_user="UAA002XXXXX")
        self.assertEqual(User.objects.get(username="kasir7").kd_user, "UAA002")

    def test_tautan_bisa_diubah_dan_dikosongkan(self):
        self._simpan(kd_user="UAA002")
        u = User.objects.get(username="kasir7")
        self.client.post("/admin-panel/users/save",
                         {"id": u.id, "username": "kasir7", "name": "Budi",
                          "role": Role.KASIR, "kd_user": ""},
                         content_type="application/json")
        u.refresh_from_db()
        self.assertEqual(u.kd_user, "")


class SandiLegacyTakPernahDisentuhTests(TestCase):
    def test_list_userx_tidak_membaca_kolom_sandi(self):
        """Membacanya ke dalam proses saja sudah membuatnya bisa bocor lewat log
        atau pesan galat — jadi kolomnya tidak ikut di-SELECT sama sekali."""
        src = inspect.getsource(master.list_userx)
        self.assertIn("m_userx", src)
        self.assertNotIn("passwd", src.split('"""')[-1])
        self.assertNotIn("passweb", src.split('"""')[-1])

    def test_arunika_tak_pernah_menulis_m_userx(self):
        """Satu arah. Menulis m_userx berarti menulis sandi terbuka, dan
        aplikasi POS lama tetap pemilik akunnya."""
        src = inspect.getsource(master)
        for tulis in ("INSERT INTO m_userx", "UPDATE m_userx", "DELETE FROM m_userx"):
            self.assertNotIn(tulis, src)

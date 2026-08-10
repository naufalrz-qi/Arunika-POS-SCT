"""Akun Arunika ditautkan ke user legacy PER KONEKSI, bukan sekali untuk semua.

`kd_user` dibuat berurutan (`UAA000`, `UAA001`, …) oleh tiap server SENDIRI-
SENDIRI, jadi kode yang sama menunjuk orang yang berbeda di server yang berbeda.
Terukur antara dua server nyata: dari 11 kode yang ada di keduanya, 10 milik
orang lain — `UAA002` adalah KASIR01 di satu server dan YIQ di server lain.

Yang paling penting dijaga di sini: **tidak ada fallback**. Tautan koneksi A
tidak boleh dipinjam saat menulis ke koneksi B. Peminjaman itu tak menimbulkan
galat apa pun — kodenya valid di server tujuan, lolos foreign key, dan langsung
terkirim ke pusat oleh trigger — cuma atas nama orang yang tak menyentuhnya.

Dijaga juga: kolom sandi legacy tak pernah ikut terbawa. m_userx.passwd
menyimpan sandi apa adanya (terukur 4-9 karakter), dan passweb adalah
peninggalan pengembang sebelumnya yang sudah diketahui mengganggu aplikasi
legacy. Keduanya haram disentuh.
"""
import inspect

from django.test import TestCase

from apps.auth_app.models import Role, TautanUser, User
from apps.auth_app.tautan import tautan_untuk, tautan_wajib
from apps.connections.models import ServerProfile
from apps.master_data import services as master


def _profil(nama, **kw):
    return ServerProfile.objects.create(
        name=nama, host=f"host-{nama}", db_name="SOLID_SIM",
        username="sa", password_encrypted="x", **kw)


class TautanPerKoneksiTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            "boss7", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.client.force_login(self.boss)
        self.kasir = User.objects.create_user(
            "kasir7", password="rahasia-kuat-123", role=Role.KASIR)
        self.a = _profil("TOKO A", is_default=True)
        self.b = _profil("TOKO B")

    def _simpan(self, profile, **nilai):
        payload = {"user_id": self.kasir.id, "profile_id": profile.id}
        payload.update(nilai)
        return self.client.post("/admin-panel/tautan-user/save", payload,
                                content_type="application/json")

    def test_tautan_tersimpan_untuk_koneksi_yang_dipilih(self):
        self._simpan(self.a, kd_user="UAA002", kd_divisi="DAA000")
        t = TautanUser.objects.get(user=self.kasir, profile=self.a)
        self.assertEqual((t.kd_user, t.kd_divisi), ("UAA002", "DAA000"))
        self.assertFalse(TautanUser.objects.filter(profile=self.b).exists())

    def test_kode_sama_di_dua_koneksi_jadi_dua_baris(self):
        """Kode yang sama BOLEH ada di dua server — ia memang menunjuk orang
        berbeda di sana, jadi tak ada yang boleh saling menimpa."""
        self._simpan(self.a, kd_user="UAA002", kd_divisi="DAA000")
        self._simpan(self.b, kd_user="UAA002", kd_divisi="DAA000")
        self.assertEqual(TautanUser.objects.filter(user=self.kasir).count(), 2)

    def test_kode_kepanjangan_dipangkas_bukan_meledak(self):
        """kd_user char(6) di legacy. Yang kepanjangan ditolak di sini, bukan
        jadi galat SQLite yang tak berarti apa pun bagi yang mengisinya."""
        self._simpan(self.a, kd_user="UAA002XXXXX", kd_divisi="DAA000")
        self.assertEqual(
            TautanUser.objects.get(user=self.kasir, profile=self.a).kd_user, "UAA002")

    def test_dikosongkan_berarti_dicabut_bukan_baris_kosong(self):
        """Baris kosong akan membuat layar tampak 'sudah ditautkan' padahal
        jalur tulis tetap menolak."""
        self._simpan(self.a, kd_user="UAA002", kd_divisi="DAA000")
        self._simpan(self.a, kd_user="", kd_divisi="", kd_pegawai="")
        self.assertFalse(TautanUser.objects.filter(user=self.kasir).exists())

    def test_hanya_superadmin_yang_boleh_mengubah(self):
        """Tautan menentukan transaksi tercatat atas nama siapa di server mana."""
        admin = User.objects.create_user(
            "admin7", password="rahasia-kuat-123", role=Role.ADMIN)
        self.client.force_login(admin)
        r = self._simpan(self.a, kd_user="UAA002", kd_divisi="DAA000")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TautanUser.objects.exists())


class TanpaFallbackTests(TestCase):
    """Inti keamanannya: koneksi yang tak punya tautan menolak, tidak meminjam."""

    def setUp(self):
        self.u = User.objects.create_user(
            "admin8", password="rahasia-kuat-123", role=Role.ADMIN)
        self.a = _profil("TOKO A", is_default=True)
        self.b = _profil("TOKO B")
        TautanUser.objects.create(
            user=self.u, profile=self.a, kd_user="UAA002", kd_divisi="DAA000")

    def test_koneksi_lain_tidak_meminjam_tautan(self):
        with self.assertRaises(ValueError) as ctx:
            tautan_wajib(self.u, self.b)
        pesan = str(ctx.exception)
        self.assertIn("TOKO B", pesan)
        self.assertNotIn("UAA002", pesan)

    def test_koneksi_bawaan_pun_tidak_dipinjam(self):
        """TOKO A kebetulan is_default. Itu tak boleh membuatnya jadi jawaban
        untuk pertanyaan tentang TOKO B."""
        self.assertEqual(tautan_untuk(self.u, self.b).kd_user, "")

    def test_tanpa_koneksi_aktif_juga_ditolak(self):
        with self.assertRaises(ValueError):
            tautan_wajib(self.u, None)

    def test_divisi_kosong_sama_wajibnya_dengan_kd_user(self):
        """kd_divisi menentukan awalan nomor dan divisi mana yang bergeser."""
        TautanUser.objects.create(user=self.u, profile=self.b, kd_user="UAA009")
        with self.assertRaises(ValueError) as ctx:
            tautan_wajib(self.u, self.b)
        self.assertIn("divisi", str(ctx.exception))

    def test_koneksi_yang_ditautkan_lolos(self):
        self.assertEqual(tautan_wajib(self.u, self.a).kd_user, "UAA002")

    def test_tautan_ikut_terhapus_bersama_koneksinya(self):
        """Tautan ke server yang sudah tak ada cuma jadi baris hantu di layar."""
        self.a.delete()
        self.assertFalse(TautanUser.objects.filter(user=self.u).exists())


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

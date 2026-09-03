"""Identitas perusahaan disimpan di tabel Arunika, bukan di tabel legacy.

`g_info_profile` bukan tabel master yang rapi. Terukur 2026-09-03: 16.581 baris
di grosirPusat, 18.927 di SERVER-TOYS, 14.867 di testGudang — dan
`COUNT(DISTINCT)` = 1 pada SETIAP kolom, seluruhnya duplikat identik.
`sys.indexes` cuma memulangkan satu baris HEAP: tanpa primary key, tanpa kolom
identity, tanpa index. Tak ada `WHERE` yang bisa menunjuk satu baris di sana.

Versi pertama layar ini menulis ke sana dengan `UPDATE ... SET` TANPA `WHERE`,
jadi satu klik Simpan menulis ulang belasan ribu baris milik aplikasi lama.
Sekarang identitasnya milik Arunika sendiri (`core.InfoPerusahaan`, SQLite):
punya kunci, satu baris per koneksi, dan tak menyentuh satu pun tabel legacy.
Yang dijaga di sini persis itu.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import TestCase

from apps.connections.models import ServerProfile
from apps.core.models import InfoPerusahaan
from apps.master_data import services as master


@contextmanager
def _ctx(cur):
    yield cur


class KursorPalsu:
    """Menjawab satu SELECT `g_info_profile` dan merekam SQL yang lewat."""

    def __init__(self, row=None):
        self.sql = []
        self._row = row
        self.connection = self

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))

    def fetchone(self):
        return self._row

    def commit(self):
        self.sql.append("COMMIT")


def _profil(nama="Testing"):
    return ServerProfile.objects.create(
        name=nama, host=f"host-{nama}", db_name="SOLID_SIM",
        username="sa", password_encrypted="x")


DATA = {
    "perusahaan": "SUKSES CROWN TOYS PRAYA",
    "alamat": "Jln. Jendral Sudirman PERTOKOAN DISPENDA NO. 14 PRAYA",
    "kota": "PRAYA", "telp": "0819 9821 5758", "hp": "08123456789",
    "email": "sct@example.com", "website": "www.sct.co.id", "nama_kontak": "BUDI",
}


class SimpanInfoPerusahaanTest(TestCase):
    def setUp(self):
        self.p = _profil()

    def test_tidak_menyentuh_mssql_sama_sekali(self):
        """Ini inti perubahannya: menyimpan identitas perusahaan tak lagi
        mengirim satu perintah pun ke server legacy."""
        cur = KursorPalsu()
        with patch.object(master.mssql, "cursor", lambda *a, **k: _ctx(cur)):
            master.simpan_info_perusahaan(self.p, DATA)
        self.assertEqual(cur.sql, [], f"MS SQL tersentuh: {cur.sql}")

    def test_tersimpan_satu_baris_per_koneksi(self):
        master.simpan_info_perusahaan(self.p, DATA)
        master.simpan_info_perusahaan(self.p, {**DATA, "perusahaan": "GANTI"})
        self.assertEqual(InfoPerusahaan.objects.filter(profile=self.p).count(), 1)
        self.assertEqual(InfoPerusahaan.objects.get(profile=self.p).perusahaan, "GANTI")

    def test_tiap_koneksi_punya_identitasnya_sendiri(self):
        """Satu Arunika melayani gudang dan delapan grosir; alamat dan telepon
        tiap server berbeda. Alasan yang sama seperti TautanUser."""
        lain = _profil("GUDANG")
        master.simpan_info_perusahaan(self.p, DATA)
        master.simpan_info_perusahaan(lain, {**DATA, "perusahaan": "GUDANG SCT"})
        self.assertEqual(master.baca_info_perusahaan(self.p)["perusahaan"],
                         "SUKSES CROWN TOYS PRAYA")
        self.assertEqual(master.baca_info_perusahaan(lain)["perusahaan"], "GUDANG SCT")

    def test_nama_kontak_ikut_tersimpan(self):
        """Sebelumnya ia dibaca di layar tapi jalur tulisnya mengisi "-", jadi
        mengetiknya tak pernah berefek."""
        master.simpan_info_perusahaan(self.p, DATA)
        self.assertEqual(master.baca_info_perusahaan(self.p)["nama_kontak"], "BUDI")

    def test_nama_perusahaan_kosong_ditolak(self):
        with self.assertRaises(ValueError):
            master.simpan_info_perusahaan(self.p, {**DATA, "perusahaan": "  "})
        self.assertFalse(InfoPerusahaan.objects.exists())


class BacaInfoPerusahaanTest(TestCase):
    def setUp(self):
        self.p = _profil()

    def _baca_dengan_legacy(self, row):
        cur = KursorPalsu(row)
        with patch.object(master.mssql, "cursor", lambda *a, **k: _ctx(cur)):
            return master.baca_info_perusahaan(self.p), cur

    def test_jatuh_ke_legacy_saat_tabel_arunika_kosong(self):
        """Server yang identitasnya terlanjur terisi di g_info_profile (Testing,
        RTL PUSAT) tak boleh mendadak kehilangan kopnya."""
        info, _ = self._baca_dengan_legacy(
            ("CROWN TOYS", "JL. SELAPARANG", "MATARAM", "0370-1", "", "", "", ""))
        self.assertEqual(info["perusahaan"], "CROWN TOYS")

    def test_legacy_dibaca_berurutan(self):
        """Tanpa ORDER BY, TOP 1 atas sebuah heap tak menjanjikan baris yang
        sama dua kali — kop struk bisa berganti sendiri."""
        _, cur = self._baca_dengan_legacy(("X", "", "", "", "", "", "", ""))
        self.assertIn("ORDER BY", cur.sql[0])

    def test_tabel_arunika_menang_atas_legacy(self):
        master.simpan_info_perusahaan(self.p, DATA)
        info, cur = self._baca_dengan_legacy(("LEGACY LAMA", "", "", "", "", "", "", ""))
        self.assertEqual(info["perusahaan"], "SUKSES CROWN TOYS PRAYA")
        self.assertEqual(cur.sql, [], "legacy tak perlu dibaca kalau sudah ada isinya")

    def test_memulangkan_seluruh_kunci_layar(self):
        info, _ = self._baca_dengan_legacy(None)
        for k in master._INFO_KOLOM:
            self.assertIn(k, info)

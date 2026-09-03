"""Informasi Perusahaan menulis ke tabel yang tak bisa menunjuk barisnya sendiri.

`g_info_profile` bukan tabel master yang rapi. Terukur di server Testing
(grosirPusat, 2026-09-03): 16.581 baris, tapi `COUNT(DISTINCT)` = 1 pada SETIAP
kolom — seluruhnya duplikat identik — dan `sys.indexes` cuma memulangkan satu
baris HEAP: tanpa primary key, tanpa kolom identity, tanpa index. testGudang:
14.867 baris. Tak ada `WHERE` yang bisa menunjuk satu baris di sana.

Versi pertama layar ini memakai `UPDATE ... SET` TANPA `WHERE`, jadi satu klik
Simpan menulis ulang 16.581 baris; dan tesnya menembak koneksi sungguhan lewat
`core.mssql.get_profile` — fungsi yang tidak pernah ada di `core/mssql.py`,
sehingga berkas ini gagal saat import dan mematahkan `manage.py test` untuk
SELURUH proyek. Keduanya dijaga di sini, tanpa menyentuh MS SQL.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.master_data import services as master


@contextmanager
def _ctx(cur):
    yield cur


class KursorPalsu:
    def __init__(self, modal_awal=None):
        self.sql = []
        self.params = []
        self.commits = 0
        self.autocommit = None
        self._modal = modal_awal
        self.connection = self

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self.params.append(list(params or []))

    def fetchone(self):
        if "modal_awal" in self.sql[-1]:
            return (self._modal,) if self._modal is not None else None
        return ("SUKSES CROWN TOYS", "Jl. Selaparang 166", "MATARAM",
                "0370-123", "0812", "a@b.c", "www", "-")

    def commit(self):
        self.commits += 1


def _jalankan(fn, *a, modal_awal=None, **kw):
    cur = KursorPalsu(modal_awal)

    def palsu(profile, autocommit=True, query_timeout=None):
        cur.autocommit = autocommit
        return _ctx(cur)

    with patch.object(master.mssql, "cursor", palsu):
        hasil = fn(object(), *a, **kw)
    return hasil, cur


DATA = {
    "perusahaan": "SUKSES CROWN TOYS", "alamat": "Jl. Selaparang 166/36",
    "kota": "MATARAM", "telp": "0370-123456", "hp": "08123456789",
    "email": "sct@example.com", "website": "www.sct.co.id", "nama_kontak": "BUDI",
}


class SimpanInfoPerusahaanTest(SimpleTestCase):
    def test_tidak_pernah_update_tanpa_where(self):
        """Ini cacat yang paling mahal di layar ini: satu klik Simpan menulis
        ulang 16.581 baris, dan tak ada satu pun gejala di layar."""
        _, cur = _jalankan(master.simpan_info_perusahaan, DATA)
        for sql in cur.sql:
            if sql.upper().startswith("UPDATE"):
                self.fail(f"UPDATE tanpa WHERE masih ada: {sql}")

    def test_ganti_seluruh_isi_dengan_satu_baris(self):
        _, cur = _jalankan(master.simpan_info_perusahaan, DATA)
        tulis = [s for s in cur.sql if s.upper().startswith(("DELETE", "INSERT"))]
        self.assertEqual(len(tulis), 2)
        self.assertTrue(tulis[0].startswith("DELETE FROM g_info_profile"))
        self.assertTrue(tulis[1].startswith("INSERT INTO g_info_profile"))

    def test_delete_dan_insert_satu_transaksi(self):
        """DELETE yang berhasil lalu INSERT yang gagal akan mengosongkan
        identitas perusahaan di seluruh struk, diam-diam."""
        _, cur = _jalankan(master.simpan_info_perusahaan, DATA)
        self.assertIs(cur.autocommit, False)
        self.assertEqual(cur.commits, 1)

    def test_nama_kontak_ikut_tersimpan(self):
        """Sebelumnya ia dibaca di layar tapi jalur tulisnya mengisi "-", jadi
        mengetiknya tak pernah berefek."""
        _, cur = _jalankan(master.simpan_info_perusahaan, DATA)
        self.assertIn("BUDI", cur.params[-1])

    def test_modal_awal_tidak_hilang_karena_delete(self):
        """Kolom akuntansi milik aplikasi lama; ia tak ada di layar ini, jadi
        DELETE polos akan membuangnya tanpa ada yang tahu."""
        _, cur = _jalankan(master.simpan_info_perusahaan, DATA, modal_awal=1500.0)
        self.assertEqual(cur.params[-1][-1], 1500.0)

    def test_nama_perusahaan_kosong_ditolak_sebelum_menghapus(self):
        cur_dipakai = []

        def palsu(profile, autocommit=True, query_timeout=None):
            cur = KursorPalsu()
            cur_dipakai.append(cur)
            return _ctx(cur)

        with patch.object(master.mssql, "cursor", palsu):
            with self.assertRaises(ValueError):
                master.simpan_info_perusahaan(object(), {**DATA, "perusahaan": "  "})
        self.assertEqual(cur_dipakai, [], "DELETE tak boleh sempat berjalan")

    def test_nilai_dipangkas_ke_lebar_kolom(self):
        """varchar(1000) NOT NULL. Nilai yang lebih panjang ditolak database
        sebagai galat ODBC mentah, bukan pesan yang bisa dibaca operator."""
        _, cur = _jalankan(master.simpan_info_perusahaan, {**DATA, "alamat": "x" * 2000})
        self.assertEqual(len(cur.params[-1][1]), 1000)


class BacaInfoPerusahaanTest(SimpleTestCase):
    def test_top_1_selalu_berurutan(self):
        """Tanpa ORDER BY, TOP 1 atas sebuah heap tak menjanjikan baris yang
        sama dua kali — kop struk bisa berganti sendiri."""
        _, cur = _jalankan(master.baca_info_perusahaan)
        self.assertIn("ORDER BY", cur.sql[0])

    def test_memulangkan_seluruh_kunci_layar(self):
        info, _ = _jalankan(master.baca_info_perusahaan)
        for k in ("perusahaan", "alamat", "kota", "telp", "hp", "email",
                  "website", "nama_kontak"):
            self.assertIn(k, info)

"""Master Produk wajib menampilkan NAMA lookup, bukan kode.

Dulu empat kolom di layar (Jenis Bahan / Model / Merk / Warna) berlabel manusiawi
tapi terikat ke kunci `kd_*`, jadi operator melihat MAA003 alih-alih namanya.
Hanya kategori yang benar-benar di-join.

Yang diuji di sini bukan SQL-nya, melainkan penjodohan kuncinya. Collation MS SQL
tak peduli besar-kecil huruf dan mengabaikan spasi ekor; dict Python peduli
keduanya. Kalau `_k()` hilang dari salah satu sisi, nama jadi kosong TANPA satu
pun galat — persis kerusakan yang tak terlihat di layar sampai ada yang mengeluh.

MS SQL tidak disentuh — cursor di-fake.
"""
from django.test import SimpleTestCase

from apps.master_data import services


class FakeCursor:
    """Mengembalikan satu baris lookup dengan kunci yang 'kotor' seperti di legacy."""

    def __init__(self, rows, cols):
        self._rows = rows
        self.description = [(c,) for c in cols]

    def execute(self, sql, params=None):
        return None

    def fetchall(self):
        return list(self._rows)


class NormalisasiKunciLookupTests(SimpleTestCase):
    def test_key_map_k_menormalkan_kunci(self):
        cur = FakeCursor([("maa003  ", "TOP")], ["kd_merk", "nama"])
        peta = services._key_map_k(cur, "SELECT kd_merk, nama FROM m_merk", "kd_merk", "nama")
        self.assertEqual(peta, {"MAA003": "TOP"})

    def test_kode_kotor_tetap_ketemu(self):
        """Kunci dari m_barang dan dari m_merk sering beda spasi/huruf besar."""
        cur = FakeCursor([("maa003  ", "TOP")], ["kd_merk", "nama"])
        peta = services._key_map_k(cur, "x", "kd_merk", "nama")
        for kode in ("MAA003", "maa003", " MAA003 ", "MaA003  "):
            self.assertEqual(peta.get(services._k(kode)), "TOP", f"gagal untuk {kode!r}")

    def test_kode_kosong_tidak_meledak(self):
        self.assertEqual(services._k(None), "")
        cur = FakeCursor([("MAA003", "TOP")], ["kd_merk", "nama"])
        peta = services._key_map_k(cur, "x", "kd_merk", "nama")
        self.assertEqual(services._st(peta.get(services._k(None))), "")


class IstilahKolomTests(SimpleTestCase):
    def test_label_memakai_sebutan_toko(self):
        """Nama kolom legacy != sebutan di toko. Yang dilihat operator sebutannya."""
        self.assertEqual(services.COL_LABELS["kd_model"], "Departemen")
        self.assertEqual(services.COL_LABELS["kd_merk"], "Divisi Barang")
        self.assertEqual(services.COL_LABELS["kd_warna"], "Sub Kategori")
        self.assertEqual(services.COL_LABELS["kd_kategori"], "Kategori")

    def test_kunci_nama_punya_label_juga(self):
        """Kolom nama hasil resolusi ikut diekspor, jadi labelnya harus ada."""
        for k in ("departemen", "divisi_barang", "sub_kategori", "jenis_bahan", "kategori"):
            self.assertIn(k, services.COL_LABELS, f"{k} belum punya label ekspor")

"""Kunci urut Stok Akhir harus tahan kolom yang campur teks dan angka.

Barisnya datang dari mesin pergerakan (dict Python), bukan dari SELECT, jadi
ORDER BY dikerjakan `list.sort` di server. Pola yang dipakai FMI Stok —
`key=lambda r: (r.get(k) is None, r.get(k) or 0)` — hanya benar bila seluruh
kolom yang bisa diurut numerik: di kolom teks, sel kosong jadi 0 lalu
dibandingkan dengan str dan sort meledak TypeError. Stok Akhir bisa diurut per
`barang`/`kategori` (teks) DAN `stok_akhir`/`nominal` (angka), jadi jebakan itu
nyata di sini.
"""
from django.test import SimpleTestCase

from apps.monitoring.views import _stok_sort_key
from apps.transactions.reports import SORTS_STOK

ROWS = [
    {"barang": "Zebra", "kategori": "", "stok_akhir": 3.0, "nominal": 300.0},
    {"barang": "apel", "kategori": "BUAH", "stok_akhir": -1.0, "nominal": -100.0},
    {"barang": "Mangga", "kategori": None, "stok_akhir": 0.0, "nominal": 0.0},
    {"barang": "", "kategori": "SAYUR", "stok_akhir": 12.0, "nominal": 1200.0},
]


def _sorted(key, reverse=False):
    return sorted(ROWS, key=lambda r: _stok_sort_key(r, key), reverse=reverse)


class StokSortKey(SimpleTestCase):
    def test_every_whitelisted_column_sorts_without_typeerror(self):
        # Ini inti tesnya: kolom teks berisi "" dan None di sebelah kolom angka.
        for key in SORTS_STOK:
            with self.subTest(kolom=key):
                _sorted(key)
                _sorted(key, reverse=True)

    def test_text_sorts_case_insensitively(self):
        self.assertEqual(
            [r["barang"] for r in _sorted("barang")],
            ["", "apel", "Mangga", "Zebra"],
        )

    def test_numbers_sort_numerically_not_lexically(self):
        self.assertEqual(
            [r["stok_akhir"] for r in _sorted("stok_akhir")],
            [-1.0, 0.0, 3.0, 12.0],
        )

    def test_none_sorts_last_ascending(self):
        self.assertIsNone(_sorted("kategori")[-1]["kategori"])

    def test_missing_column_is_not_fatal(self):
        # `sort` sudah disaring whitelist sebelum sampai sini, tapi baris yang
        # kehilangan satu kunci tak boleh menjatuhkan seluruh halaman.
        _sorted("kolom_yang_tak_ada")

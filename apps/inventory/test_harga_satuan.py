"""Satuan harga di Stok Akhir: `harga_average` HARUS per satuan terkecil.

Kenapa bentuk SQL-nya yang diperiksa dan bukan angkanya: rumusnya hidup di SQL
Server (`CONVERT(DATE, ...)`, window function), jadi tak bisa dijalankan di
SQLite tes. Angkanya dijaga di `manage.py check_stock_agg` terhadap server nyata
lewat invarian "rata-rata tak melampaui harga tertinggi penyusunnya".

Yang dijaga DI SINI adalah kesalahan yang benar-benar terjadi, dan bentuknya
memang terlihat di teks SQL: pembilang dan penyebut sama-sama DIBAGI
`bs.jumlah`, sehingga faktornya saling menghilangkan dan hasilnya harga per
satuan BELI. `stok_akhir` yang mengalikannya dalam satuan TERKECIL, jadi kolom
`nominal` menggelembung sebesar faktor kemasan — terukur 2,25x sampai 3,89x atas
seluruh katalog, dan tepat 10,00x pada `AMP013` (dibeli per satuan berisi 10).
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.inventory import services as inv


class FakeCursor:
    """Merekam SQL. `description` + baris dibuat agar `_dictify` bisa jalan."""

    def __init__(self):
        self.sql = []
        self.description = [("kd_barang",), ("x",)]
        self._rows = []

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self._rows = []

    def fetchall(self):
        return self._rows


def _jalankan():
    cur = FakeCursor()
    inv._purchase_prices(cur, "2026-08-11")
    return cur.sql


class BentukRumus(SimpleTestCase):
    def setUp(self):
        self.sql = _jalankan()
        self.avg = self.sql[0]

    def test_penyebut_mengalikan_jumlah_bukan_membagi(self):
        """Inti bugnya. `SUM(qty / jumlah)` di penyebut membuat faktornya hilang
        terhadap pembilang, dan yang keluar harga per satuan BELI."""
        self.assertIn("SUM(pd.qty * COALESCE(bs.jumlah, 1))", self.avg)
        self.assertNotIn("pd.qty / NULLIF(bs.jumlah", self.avg)

    def test_pembilang_tidak_membagi_jumlah(self):
        self.assertIn("SUM(pd.qty * pd.harga_beli)", self.avg)
        self.assertNotIn("pd.harga_beli / NULLIF(bs.jumlah", self.avg)

    def test_harga_beli_akhir_tetap_per_satuan_terkecil(self):
        """Kolom tetangganya sudah benar sejak awal, dan justru itu yang membuat
        bugnya lolos lama — dua kolom bersebelahan memakai satuan berbeda."""
        akhir = self.sql[1]
        self.assertIn("pd.harga_beli / NULLIF(COALESCE(bs.jumlah, 1), 0)", akhir)

    def test_jumlah_diambil_lewat_subquery_ber_max(self):
        """(kd_barang, kd_satuan) bisa ganda di m_barang_satuan; join langsung
        menggandakan baris pembelian dan ikut menggandakan bobot rata-ratanya."""
        for q in self.sql[:2]:
            self.assertIn("MAX(jumlah) AS jumlah", q)
            self.assertIn("GROUP BY kd_barang, kd_satuan", q)

    def test_baris_tanpa_satuan_terdaftar_tetap_ikut(self):
        """LEFT JOIN, bukan INNER: sisi KUANTITAS sudah menghitung baris itu, jadi
        menjatuhkannya di sisi harga membuat keduanya bicara tentang barang
        yang berbeda."""
        for q in self.sql[:2]:
            self.assertIn("LEFT JOIN (SELECT kd_barang, kd_satuan", q)
            self.assertNotIn("INNER JOIN m_barang_satuan", q)


class NominalMemakaiSatuanYangSama(SimpleTestCase):
    """`nominal = stok_akhir * harga_average`, jadi keduanya wajib satu satuan.

    Dijalankan lewat `stok_akhir_per_tanggal` dengan seluruh pembacaan MS SQL
    dipalsukan — yang diuji perkalian dan rantai fallback-nya, bukan SQL-nya.
    """

    STOK = 120.0        # satuan terkecil (mis. 12 lusin @10)
    HARGA_BASE = 1_160.13   # per satuan terkecil
    HARGA_BELI_UNIT = 11_601.35  # per satuan beli — angka yang DULU keluar

    def _rows(self, avg_map, init_map=None):
        sums = [{"kd_divisi": "DAA000", "kd_barang": "AMP013",
                 "stok_awal": 0.0, "masuk": self.STOK, "keluar": 0.0}]
        with patch.object(inv.mssql, "report_cursor", _cursor_kosong()), \
             patch.object(inv, "_movement_sums", lambda *a, **k: sums), \
             patch.object(inv, "_universe_for", lambda *a, **k: [("DAA000", "AMP013")]), \
             patch.object(inv, "_cached", lambda profile, name, build, **k: build()), \
             patch.object(inv, "_div_rows_full", lambda cur: [{"kd_divisi": "DAA000", "nama": "UMUM"}]), \
             patch.object(inv, "_barang_meta", lambda cur: {"AMP013": {"nama": "AMPLOP"}}), \
             patch.object(inv, "_harga_jual_map", lambda cur: {"AMP013": 2000.0}), \
             patch.object(inv, "_purchase_prices",
                          lambda cur, tgl: (avg_map, {}, init_map or {})):
            import datetime as dt
            return inv.stok_akhir_per_tanggal(object(), dt.datetime(2026, 8, 11, 23, 59, 59))

    def test_nominal_memakai_harga_per_satuan_terkecil(self):
        r = self._rows({"AMP013": self.HARGA_BASE})[0]
        self.assertEqual(r["stok_akhir"], self.STOK)
        self.assertEqual(r["harga_average"], round(self.HARGA_BASE, 2))
        self.assertEqual(r["nominal"], round(self.STOK * self.HARGA_BASE, 2))

    def test_harga_per_satuan_beli_akan_menggelembung_sepuluh_kali(self):
        """Bukan menguji kode — menahan angkanya supaya kalau suatu hari nominal
        naik 10x lagi, tes ini menyebut sebabnya, bukan cuma 'angka berubah'."""
        salah = self._rows({"AMP013": self.HARGA_BELI_UNIT})[0]
        benar = self._rows({"AMP013": self.HARGA_BASE})[0]
        self.assertAlmostEqual(salah["nominal"] / benar["nominal"], 10.0, places=3)

    def test_fallback_ke_harga_beli_awal_saat_belum_pernah_dibeli(self):
        r = self._rows({}, init_map={"AMP013": 900.0})[0]
        self.assertEqual(r["harga_average"], 900.0)
        self.assertEqual(r["nominal"], round(self.STOK * 900.0, 2))


def _cursor_kosong():
    from contextlib import contextmanager

    @contextmanager
    def c(profile, query_timeout=None):
        yield None
    return c

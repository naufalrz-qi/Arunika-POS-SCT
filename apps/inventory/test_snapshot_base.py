"""Regresi batas tutup buku pada snapshot stok.

Bug asli: `_base_date()` (~13 bln lalu) jatuh SEBELUM tanggal tutup buku, jadi
jendela transaksi (closing, base_dt] kosong dan base beku hanya berisi stok_awal
mentah — tapi bertanggal base_dt. Lapisan live lalu menambah ulang pergerakan
(base_dt, closing] yang sudah terkandung di stok_awal. KWT001 di grosirPusat:
snapshot 2634, seharusnya 6801.
"""
import datetime as dt

from django.test import SimpleTestCase

from apps.inventory import services


CLOSING = dt.datetime(2025, 12, 31, 23, 59, 59)


class SnapshotBaseClampTest(SimpleTestCase):
    """snapshot_stok_base tak boleh membeku pada tanggal sebelum tutup buku."""

    def _run(self, base_date):
        """Jalankan snapshot_stok_base dengan semua sentuhan MS SQL di-stub."""
        seen = {}

        class _Cur:
            def __enter__(self_inner):
                return object()

            def __exit__(self_inner, *exc):
                return False

        orig = (services._base_date, services._closing_date, services._movement_sums,
                services.mssql.report_cursor, services._write_snapshot)
        services._base_date = lambda *a, **k: base_date
        services._closing_date = lambda cur: CLOSING
        services._movement_sums = lambda cur, **kw: seen.update(kw) or []
        services.mssql.report_cursor = lambda profile: _Cur()
        services._write_snapshot = lambda profile, table, rows: None
        try:
            res = services.snapshot_stok_base(profile=None)
        finally:
            (services._base_date, services._closing_date, services._movement_sums,
             services.mssql.report_cursor, services._write_snapshot) = orig
        return res, seen

    def test_base_sebelum_closing_dijepit_ke_closing(self):
        # Kondisi bug: base 2025-06-01 mendahului tutup buku 2025-12-31.
        res, seen = self._run(dt.datetime(2025, 6, 1))
        self.assertEqual(res["base_date"], CLOSING)
        # Jendela yang discan juga ikut, bukan cuma angka yang dilaporkan.
        self.assertEqual(seen["date_to"], CLOSING)

    def test_base_setelah_closing_dibiarkan(self):
        # Perilaku normal saat tutup buku sudah lama lewat: base tetap bergulir.
        base = dt.datetime(2026, 3, 1)
        res, seen = self._run(base)
        self.assertEqual(res["base_date"], base)
        self.assertEqual(seen["date_to"], base)


class BarangHistoriSaldoTest(SimpleTestCase):
    """Kolom saldo berjalan: per (divisi, barang), tanpa dobel hitung Stok Awal."""

    # Dua barang berselang-seling supaya deret saldo wajib terpisah per SKU.
    MOVES = [
        {"kd_divisi": "D1", "kd_barang": "A", "tanggal": dt.datetime(2025, 12, 31), "jenis": 0,
         "transaksi": "Stok Awal", "no_transaksi": "0", "debet": 100, "kredit": 0, "kd_satuan": "PCS", "harga": 0},
        {"kd_divisi": "D1", "kd_barang": "B", "tanggal": dt.datetime(2025, 12, 31), "jenis": 0,
         "transaksi": "Stok Awal", "no_transaksi": "0", "debet": 7, "kredit": 0, "kd_satuan": "PCS", "harga": 0},
        {"kd_divisi": "D1", "kd_barang": "A", "tanggal": dt.datetime(2026, 2, 1), "jenis": 5,
         "transaksi": "Pembelian", "no_transaksi": "P1", "debet": 2, "kredit": 0, "kd_satuan": "BOX", "harga": 0},
        {"kd_divisi": "D1", "kd_barang": "B", "tanggal": dt.datetime(2026, 2, 2), "jenis": 7,
         "transaksi": "Penjualan", "no_transaksi": "S1", "debet": 0, "kredit": 3, "kd_satuan": "PCS", "harga": 0},
        {"kd_divisi": "D1", "kd_barang": "A", "tanggal": dt.datetime(2026, 2, 3), "jenis": 7,
         "transaksi": "Penjualan", "no_transaksi": "S2", "debet": 0, "kredit": 5, "kd_satuan": "PCS", "harga": 0},
    ]
    FACTORS = {("A", "PCS"): 1.0, ("A", "BOX"): 12.0, ("B", "PCS"): 1.0}

    def _histori(self, date_from=None, opening=None):
        class _Cur:
            def __enter__(self_inner):
                return object()

            def __exit__(self_inner, *exc):
                return False

        orig = (services.mssql.report_cursor, services._fetch_movements, services._movement_sums,
                services._cached, services._div_rows_full, services._satuan_rows)
        services.mssql.report_cursor = lambda profile: _Cur()
        services._fetch_movements = lambda cur, **kw: list(self.MOVES)
        services._movement_sums = lambda cur, **kw: opening or []
        services._cached = lambda profile, key, build: (
            self.FACTORS if key == "factors" else {"A": "Barang A", "B": "Barang B"}
        )
        services._div_rows_full = lambda cur: []
        services._satuan_rows = lambda cur: []
        try:
            return services.barang_histori(None, kd_divisi="D1", date_from=date_from)
        finally:
            (services.mssql.report_cursor, services._fetch_movements, services._movement_sums,
             services._cached, services._div_rows_full, services._satuan_rows) = orig

    def test_saldo_terpisah_per_barang(self):
        saldo = {(r["kd_barang"], r["no_transaksi"]): r["saldo"] for r in self._histori()}
        # A: 100 -> +2 BOX (faktor 12) = 124 -> -5 = 119
        self.assertEqual(saldo[("A", "0")], 100)
        self.assertEqual(saldo[("A", "P1")], 124)
        self.assertEqual(saldo[("A", "S2")], 119)
        # B jalan sendiri, tidak terseret angka A.
        self.assertEqual(saldo[("B", "0")], 7)
        self.assertEqual(saldo[("B", "S1")], 4)

    def test_stok_awal_tak_dihitung_dua_kali_saat_date_from(self):
        # Agregat stok_awal SUDAH memuat blok [0]; blok itu juga muncul di listing.
        opening = [{"kd_divisi": "D1", "kd_barang": "A", "stok_awal": 100.0, "masuk": 0.0, "keluar": 0.0}]
        rows = self._histori(date_from=dt.datetime(2026, 1, 1), opening=opening)
        saldo = {(r["kd_barang"], r["no_transaksi"]): r["saldo"] for r in rows}
        self.assertEqual(saldo[("A", "0")], 100)   # bukan 200
        self.assertEqual(saldo[("A", "S2")], 119)  # bukan 219

    def test_sku_di_luar_agregat_tidak_meledak(self):
        # HAVING di _movement_sums membuang grup bersaldo nol -> key tak ada.
        rows = self._histori(date_from=dt.datetime(2026, 1, 1), opening=[])
        self.assertEqual({(r["kd_barang"], r["no_transaksi"]): r["saldo"] for r in rows}[("B", "S1")], -3)


class MovementSqlReverseTest(SimpleTestCase):
    """date_to sebelum closing: saldo dihitung mundur dari jangkar stok_awal."""

    def test_tanpa_reverse_jendela_kosong(self):
        # Dokumentasi bug: batas maju menghasilkan (closing, date_to] yang mustahil.
        sql, params = services._movement_sql(
            CLOSING, kd_barang="KWT001", date_to=dt.datetime(2025, 6, 1),
        )
        self.assertNotIn("kredit AS debet", sql)
        # Blok penjualan terikat > closing DAN <= date_to sekaligus.
        self.assertIn(CLOSING, params)
        self.assertIn(dt.datetime(2025, 6, 1), params)

    def test_reverse_membalik_debet_kredit(self):
        sql, _ = services._movement_sql(
            CLOSING, kd_barang="KWT001", date_to=dt.datetime(2025, 6, 1), reverse=True,
        )
        # Blok [0] stok_awal tetap maju, blok transaksi dibungkus wrapper pembalik.
        self.assertIn("bd.stok_awal AS debet", sql)
        self.assertIn("kredit AS debet, debet AS kredit", sql)
        # Derived table wajib punya daftar kolom eksplisit — blok UNION tak beralias.
        self.assertIn(") rev (kd_divisi, tanggal", sql)

    def test_satuan_dasar_dideduplikasi(self):
        # PENAL02 punya SAA000 dan SAA006 sama-sama jumlah=1; join langsung
        # menggandakan baris stok_awal (139 terhitung 255 di snapshot).
        sql, _ = services._movement_sql(CLOSING, kd_barang="PENAL02")
        self.assertNotIn("bs.jumlah = 1 ", sql)
        self.assertIn("MIN(kd_satuan) AS kd_satuan FROM m_barang_satuan", sql)

    def test_reverse_menggeser_jendela_ke_date_to_closing(self):
        date_to = dt.datetime(2025, 6, 1)
        _, params = services._movement_sql(
            CLOSING, kd_barang="KWT001", date_to=date_to, reverse=True,
        )
        # 7 blok transaksi (opname masuk/keluar digabung satu blok), masing-masing
        # dengan batas bawah date_to.
        self.assertEqual(params.count(date_to), 7)
        # closing muncul sebagai tag tanggal blok [0] + batas atas 7 blok transaksi.
        self.assertEqual(params.count(CLOSING), 8)

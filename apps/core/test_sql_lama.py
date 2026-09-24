"""Server SQL Server 2008 R2 (DRAGON, versi 10.50).

Yang dijaga di sini tak akan terlihat di server lain — sepuluh dari dua belas
server sudah 2022 dan RUMAK 2012, jadi semua pengujian lokal dan produksi di
luar DRAGON tetap hijau walau DRAGON rusak total. Itu yang terjadi: 26 dari 26
laporan server-side gagal di sana dengan "Incorrect syntax near 'OFFSET'",
dan Penjualan/Pembelian per Periode dengan "'FORMAT' is not a recognized
built-in function".
"""
import datetime as dt
import json
from contextlib import contextmanager
from unittest.mock import patch

import pyodbc
from django.db import connection
from django.test import SimpleTestCase, TestCase

from apps.auth_app.models import Role, User
from apps.core import reporting
from apps.monitoring import views as v
from apps.transactions import reports as rpt
from core import mssql


class _Koneksi:
    def __init__(self, versi):
        self.versi = versi

    def getinfo(self, jenis):
        if isinstance(self.versi, Exception):
            raise self.versi
        assert jenis == pyodbc.SQL_DBMS_VER
        return self.versi


class CursorPalsu:
    """Mencatat SQL + parameter; menjawab COUNT dan satu halaman baris."""

    def __init__(self, versi="16.00.1000", baris=()):
        self.connection = _Koneksi(versi)
        self.dieksekusi = []
        self._baris, self.description, self._hasil = list(baris), (), []

    def setinputsizes(self, _):
        pass

    def execute(self, sql, params=()):
        self.dieksekusi.append((sql, list(params)))
        if sql.startswith("SELECT COUNT(*)"):
            self.description, self._hasil = (("n",),), [(len(self._baris),)]
        elif self._baris:
            kolom = list(self._baris[0])
            self.description = tuple((k,) for k in kolom)
            self._hasil = [tuple(r[k] for k in kolom) for r in self._baris]
        else:
            self.description, self._hasil = (), []

    def fetchone(self):
        return self._hasil[0] if self._hasil else None

    def fetchall(self):
        return self._hasil


class VersiServer(SimpleTestCase):
    def test_versi_dari_info_driver(self):
        self.assertEqual(mssql.versi_server(CursorPalsu("10.50.1600")), 10)
        self.assertEqual(mssql.versi_server(CursorPalsu("11.00.3128")), 11)
        self.assertEqual(mssql.versi_server(CursorPalsu("16.00.1000")), 16)

    def test_tak_terbaca_dianggap_modern(self):
        """Jalur yang sudah berjalan di sebelas server, bukan jalur cadangan."""
        self.assertEqual(mssql.versi_server(CursorPalsu("")), 99)
        self.assertEqual(mssql.versi_server(CursorPalsu(pyodbc.Error("x"))), 99)
        self.assertEqual(mssql.versi_server(object()), 99)


class BentukHalaman(SimpleTestCase):
    INNER = "SELECT a, b FROM t WHERE c = ?"

    def test_2012_ke_atas_tetap_offset_fetch(self):
        for versi in (11, 16):
            sql, batas = reporting.sql_halaman(self.INNER, "q.a DESC", 40, 20, versi)
            self.assertEqual(sql, f"SELECT * FROM ({self.INNER}) AS q ORDER BY q.a DESC "
                                  "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY")
            self.assertEqual(batas, [40, 20])

    def test_2008_pakai_row_number(self):
        sql, batas = reporting.sql_halaman(self.INNER, "q.a DESC, q.b", 40, 20, 10)
        self.assertNotIn("OFFSET", sql)
        self.assertNotIn("FETCH", sql)
        self.assertIn("ROW_NUMBER() OVER (ORDER BY q.a DESC, q.b) AS _rn", sql)
        self.assertTrue(sql.endswith("WHERE h._rn BETWEEN ? AND ? ORDER BY h._rn"))
        # Halaman 3 ukuran 20 = baris 41..60 (ROW_NUMBER mulai dari 1).
        self.assertEqual(batas, [41, 60])

    def test_parameter_batas_di_ujung(self):
        """`?` milik inner lebih dulu di teks, jadi parameternya juga harus."""
        for versi in (10, 16):
            sql, batas = reporting.sql_halaman(self.INNER, "q.a", 0, 10, versi)
            self.assertLess(sql.index("c = ?"), sql.rindex("?") - 1)
            self.assertEqual(sql.count("?"), 1 + len(batas))


class RunPaged(SimpleTestCase):
    F = {"page": 2, "per_page": 3, "order_by": "q.a DESC"}

    def _jalan(self, versi, baris):
        cur = CursorPalsu(versi, baris)
        rows, total = reporting.run_paged(cur, "SELECT a FROM t WHERE c = ?", ["X"], self.F)
        return cur, rows, total

    def test_2008_membuang_kolom_nomor_urut(self):
        cur, rows, _ = self._jalan("10.50.1600", [{"a": 9, "_rn": 4}, {"a": 8, "_rn": 5}])
        self.assertEqual(rows, [{"a": 9, "_rid": 4}, {"a": 8, "_rid": 5}])
        sql, params = cur.dieksekusi[-1]
        self.assertIn("ROW_NUMBER()", sql)
        self.assertEqual(params, ["X", 4, 6])

    def test_2022_tak_berubah(self):
        cur, rows, _ = self._jalan("16.00.1000", [{"a": 9}])
        sql, params = cur.dieksekusi[-1]
        self.assertIn("OFFSET ? ROWS FETCH NEXT ? ROWS ONLY", sql)
        self.assertEqual(params, ["X", 3, 3])
        self.assertEqual(rows, [{"a": 9, "_rid": 4}])


class KeduaBentukDiSqlServerSungguhan(TestCase):
    """Dijalankan di SQL Server pangkal uji (2022), yang memahami KEDUA bentuk:
    halaman yang sama harus berisi baris yang sama, dalam urutan yang sama."""

    INNER = "SELECT v, w FROM (VALUES (3, 'c'), (1, 'a'), (5, 'e'), (2, 'b'), (4, 'd'), (6, 'f')) t(v, w)"

    def _halaman(self, versi, halaman, per):
        sql, batas = reporting.sql_halaman(self.INNER, "q.v DESC", (halaman - 1) * per, per, versi)
        with connection.cursor() as cur:
            cur.execute(sql.replace("?", "%s"), batas)
            return [(r[0], r[1]) for r in cur.fetchall()]

    def test_halaman_identik(self):
        for halaman in (1, 2, 3):
            self.assertEqual(self._halaman(10, halaman, 2), self._halaman(16, halaman, 2), halaman)
        self.assertEqual(self._halaman(10, 2, 2), [(4, "d"), (3, "c")])

    def test_periode_sama_dengan_format(self):
        """CONVERT gaya 120 menghasilkan string yang sama persis dengan FORMAT
        lama — label periode di layar dan Excel tak berubah."""
        with connection.cursor() as cur:
            for g, fmt in (("harian", "yyyy-MM-dd"), ("bulanan", "yyyy-MM")):
                ekspresi = rpt._periode("p.t", g)
                cur.execute(f"SELECT {ekspresi}, FORMAT(p.t, '{fmt}') FROM (SELECT %s AS t) p",
                            [dt.datetime(2026, 9, 4, 13, 5, 9)])
                a, b = cur.fetchone()
                self.assertEqual(a, b)


class TanpaFungsi2012(SimpleTestCase):
    """Laporan legacy tak boleh memakai fungsi yang tak ada di 2008 R2."""

    F = {"date_from": dt.datetime(2026, 1, 1), "date_to": dt.datetime(2026, 1, 31, 23, 59, 59), "search": ""}

    def test_laporan_periode_tanpa_format(self):
        for fungsi in (rpt.penjualan_periode, rpt.pembelian_periode):
            for g in ("harian", "bulanan"):
                sql, _ = fungsi({**self.F, "granularitas": g})
                self.assertNotIn("FORMAT(", sql, f"{fungsi.__name__} {g}")
                self.assertIn("CONVERT(char(", sql)


def _cursor_versi(versi):
    @contextmanager
    def c(profile, autocommit=True, query_timeout=None):
        yield CursorPalsu(versi)
    return c


class LaporanBerurutanMenolakDiServerLama(TestCase):
    """Kas Harian (saldo berjalan) dan FMI Penjualan (akumulasi) memakai
    `SUM() OVER (… ORDER BY …)`, yang baru ada sejak 2012. Di server lama
    mereka harus MENOLAK dengan pesan yang bisa dibaca orang — diuji lewat
    respons HTTP, bukan dengan memanggil helper-nya."""

    def setUp(self):
        u = User.objects.create_user("lama", password="rahasia-kuat-123", role=Role.ADMIN,
                                     allowed_menu_keys=["fmi_penjualan", "kas"])
        self.client.force_login(u)

    def _props(self, url, komponen, versi):
        profil = type("Profil", (), {"pk": 1, "name": "DRAGON"})()
        with patch.object(v, "_active", lambda: profil), \
             patch.object(v, "_arunika_siap", lambda p: False), \
             patch.object(v, "_opt_divisi", lambda p: []), \
             patch.object(v.mssql, "report_read_profiles", lambda p: [p]), \
             patch.object(v.mssql, "report_cursor", _cursor_versi(versi)), \
             patch.object(v.mssql, "cursor", _cursor_versi(versi)), \
             patch.object(v, "_opt_kas", lambda p, arunika=False: []):
            r = self.client.get(url, HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0",
                                HTTP_X_INERTIA_PARTIAL_DATA="report", HTTP_X_INERTIA_PARTIAL_COMPONENT=komponen)
        self.assertEqual(r.status_code, 200, url)
        return json.loads(r.content)["props"]["report"]

    def test_fmi_penjualan(self):
        lama = self._props("/admin-panel/analitik/fmi-penjualan", "Admin/Analytics/FmiPenjualan", "10.50.1600")
        self.assertEqual(lama["conn_error"], v._PESAN_SQL_LAMA)
        baru = self._props("/admin-panel/analitik/fmi-penjualan", "Admin/Analytics/FmiPenjualan", "16.00.1000")
        self.assertIsNone(baru["conn_error"])

    def test_kas_harian(self):
        lama = self._props("/admin-panel/kas/harian", "Admin/Cash/Kas", "10.50.1600")
        self.assertEqual(lama["conn_error"], v._PESAN_SQL_LAMA)
        baru = self._props("/admin-panel/kas/harian", "Admin/Cash/Kas", "16.00.1000")
        self.assertIsNone(baru["conn_error"])

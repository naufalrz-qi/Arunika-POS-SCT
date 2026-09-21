"""Kontrak `mssql.execute_varchar`: ikat HANYA posisi string.

Helper ini lahir dari penyelidikan yang membatalkan asumsi awal. Rencananya
semula memakai `hub_sync.bind_varchar` apa adanya, tapi helper itu menyetel
SELURUH posisi jadi VARCHAR -- benar untuk daftar `IN (...)` yang seragam, salah
untuk daftar campuran seperti kueri pergerakan stok (38 parameter, 22 di
antaranya `datetime`).

Memaksa datetime jadi VARCHAR menyerahkan penafsiran tanggalnya ke setelan
bahasa server. Terukur di SQL Server 2022:

    SET LANGUAGE us_english  -> lolos
    SET LANGUAGE british     -> DataError 22007
    SET LANGUAGE deutsch     -> DataError 22007

Yang berbahaya bukan galatnya, melainkan bahwa ia LOLOS di mesin pengembang.
Test di bawah menjaga sifat yang membuatnya aman: posisi non-string tak pernah
disentuh.

Tanpa server: yang diuji keputusan pengikatannya, bukan hasil kuerinya.
Pembuktian bahwa hasilnya identik dan 21,3x lebih cepat dilakukan terhadap
server sungguhan (lihat docstring `core/mssql.execute_varchar`).
"""
import datetime as dt

import pyodbc
from django.test import SimpleTestCase

from core import mssql


class CursorPalsu:
    """Merekam setiap panggilan setinputsizes dan execute, tanpa database."""

    def __init__(self, meledak=False):
        self.sizes = []
        self.executed = []
        self.meledak = meledak

    def setinputsizes(self, v):
        self.sizes.append(v)

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.meledak:
            raise pyodbc.Error("HY000", "pura-pura gagal")


class HanyaPosisiString(SimpleTestCase):
    PARAMS = [dt.datetime(2026, 1, 1), "ABC123", dt.datetime(2026, 2, 2), "DAA000"]

    def test_posisi_non_string_dibiarkan_none(self):
        """None = 'biarkan pyodbc memutuskan'. Inilah yang mencegah datetime
        dikirim sebagai teks dan ditafsirkan menurut bahasa server."""
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", self.PARAMS)
        pasang = cur.sizes[0]
        self.assertIsNone(pasang[0])
        self.assertIsNone(pasang[2])
        self.assertEqual(pasang[1][0], pyodbc.SQL_VARCHAR)
        self.assertEqual(pasang[3][0], pyodbc.SQL_VARCHAR)

    def test_panjang_dari_nilai_terpanjang(self):
        """Deklarasi yang lebih PENDEK dari nilainya memotongnya diam-diam, dan
        baris yang hilang karena kunci terpotong tidak memunculkan galat."""
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", ["pendek", "j" * 42], panjang_min=10)
        self.assertEqual(cur.sizes[0][0][1], 42)

    def test_panjang_minimum_dihormati(self):
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", ["ab"], panjang_min=10)
        self.assertEqual(cur.sizes[0][0][1], 10)

    def test_selalu_direset(self):
        """Ikatan menempel di cursor; execute berikutnya dengan jumlah parameter
        berbeda akan salah kalau tidak direset."""
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", self.PARAMS)
        self.assertIsNone(cur.sizes[-1])

    def test_direset_walau_execute_gagal(self):
        cur = CursorPalsu(meledak=True)
        with self.assertRaises(pyodbc.Error):
            mssql.execute_varchar(cur, "SELECT 1", self.PARAMS)
        self.assertIsNone(cur.sizes[-1])

    def test_tanpa_string_tak_menyentuh_setinputsizes(self):
        """Tanpa parameter string tak ada yang perlu diperbaiki; menyentuh
        cursor tanpa alasan hanya menambah cara untuk salah."""
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", [dt.datetime(2026, 1, 1), 5])
        self.assertEqual(cur.sizes, [])
        self.assertEqual(len(cur.executed), 1)

    def test_parameter_tetap_dikirim_apa_adanya(self):
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", self.PARAMS)
        self.assertEqual(cur.executed[0][1], self.PARAMS)


class StringNonAscii(SimpleTestCase):
    """Kata kunci pencarian diketik pengguna dan bisa memuat apa saja.

    Memaksanya lewat VARCHAR menyerahkan konversinya ke codepage server, yang
    bisa memetakan dua karakter berbeda ke byte yang sama -- kecocokan yang
    salah, tanpa galat. Dibiarkan NVARCHAR ia sekadar tidak cocok dengan apa
    pun, dan itu memang jawaban yang benar untuk kolom `varchar`.
    """

    def test_non_ascii_dibiarkan_nvarchar(self):
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", ["biasa", "日本語"])
        pasang = cur.sizes[0]
        self.assertEqual(pasang[0][0], pyodbc.SQL_VARCHAR)
        self.assertIsNone(pasang[1])

    def test_semua_non_ascii_tak_menyentuh_setinputsizes(self):
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", ["日本語"])
        self.assertEqual(cur.sizes, [])
        self.assertEqual(len(cur.executed), 1)

    def test_panjang_dihitung_dari_yang_diikat_saja(self):
        """Nilai non-ASCII yang panjang tak boleh melebarkan deklarasi untuk
        nilai lain -- ia toh tidak ikut diikat."""
        cur = CursorPalsu()
        mssql.execute_varchar(cur, "SELECT 1", ["abc", "é" * 99], panjang_min=1)
        self.assertEqual(cur.sizes[0][0][1], 3)

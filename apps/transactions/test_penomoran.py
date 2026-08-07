"""Penomoran nota harus aman berdampingan dengan aplikasi POS lama.

MS SQL tidak disentuh — cursor di-fake dan SQL yang dieksekusi direkam.
"""
import datetime as dt

import pyodbc
from django.test import SimpleTestCase

from apps.transactions import penomoran as pn


class FakeCursor:
    def __init__(self, maks=None, kepala="SC"):
        self.maks = maks
        self.kepala = kepala
        self.sql = []
        self.params = []
        self._row = None
        self.inputsizes = []

    def setinputsizes(self, v):
        self.inputsizes.append(v)

    def execute(self, sql, params=None):
        rapi = " ".join(sql.split())
        self.sql.append(rapi)
        self.params.append(list(params or []))
        if "kepala_nota" in rapi:
            self._row = (self.kepala,)
        else:
            self._row = (self.maks,)

    def fetchone(self):
        return self._row


TGL = dt.datetime(2026, 8, 7, 10, 0)


class AwalanTests(SimpleTestCase):
    def test_diambil_dari_kepala_nota(self):
        cur = FakeCursor(kepala="SC")
        self.assertEqual(pn.awalan_untuk(cur), "SC")

    def test_kepala_nota_kosong_ditolak_dengan_jelas(self):
        """Lebih baik berhenti daripada menulis nota tanpa awalan."""
        cur = FakeCursor(kepala="   ")
        with self.assertRaises(ValueError) as ctx:
            pn.awalan_untuk(cur)
        self.assertIn("Kelola Kode Nota", str(ctx.exception))


class NoBerikutnyaTests(SimpleTestCase):
    def test_hari_kosong_mulai_dari_satu(self):
        cur = FakeCursor(maks=None)
        self.assertEqual(pn.no_berikutnya(cur, "penjualan", "SC", TGL), "SC2608070001")

    def test_melanjutkan_urutan_terakhir(self):
        cur = FakeCursor(maks="SC2608070033")
        self.assertEqual(pn.no_berikutnya(cur, "penjualan", "SC", TGL), "SC2608070034")

    def test_max_disaring_dengan_awalan_sendiri(self):
        """Tanpa saringan ini, baris kiriman sync (CT/GP) ikut menggeser urutan."""
        cur = FakeCursor(maks=None)
        pn.no_berikutnya(cur, "penjualan", "SC", TGL)
        self.assertEqual(cur.params[-1], ["SC260807%"])

    def test_memakai_kunci_rentang(self):
        """UPDLOCK saja mengunci baris yang ADA; nomor baru justru baris yang
        belum ada, jadi HOLDLOCK-lah yang menahan dua kasir menyimpulkan nomor
        yang sama."""
        cur = FakeCursor(maks=None)
        pn.no_berikutnya(cur, "penjualan", "SC", TGL)
        self.assertIn("WITH (UPDLOCK, HOLDLOCK)", cur.sql[-1])

    def test_mengikat_varchar_lalu_meresetnya(self):
        """Ikatan menempel di cursor; tanpa reset, execute berikutnya salah."""
        cur = FakeCursor(maks=None)
        pn.no_berikutnya(cur, "penjualan", "SC", TGL)
        self.assertEqual(cur.inputsizes[-1], None)
        self.assertIsNotNone(cur.inputsizes[0])

    def test_nomor_lama_berbentuk_aneh_tidak_menghentikan_kasir(self):
        cur = FakeCursor(maks="SC260807XXXX")
        self.assertEqual(pn.no_berikutnya(cur, "penjualan", "SC", TGL), "SC2608070001")

    def test_kuota_harian_habis_ditolak(self):
        cur = FakeCursor(maks="SC2608079999")
        with self.assertRaises(ValueError):
            pn.no_berikutnya(cur, "penjualan", "SC", TGL)

    def test_jenis_di_luar_whitelist_ditolak(self):
        """Nama tabel masuk ke SQL sebagai teks — ia tak boleh dari input."""
        cur = FakeCursor(maks=None)
        with self.assertRaises(KeyError):
            pn.no_berikutnya(cur, "t_penjualan; DROP TABLE m_barang--", "SC", TGL)

    def test_tiap_jenis_menunjuk_tabel_dan_kolom_yang_benar(self):
        for jenis, (tabel, kolom) in pn.JENIS.items():
            cur = FakeCursor(maks=None)
            pn.no_berikutnya(cur, jenis, "SC", TGL)
            self.assertIn(f"FROM {tabel}", cur.sql[-1], jenis)
            self.assertIn(f"MAX({kolom})", cur.sql[-1], jenis)


def _galat_duplikat():
    return pyodbc.IntegrityError(
        "23000", "[23000] [SQL Server]Violation of PRIMARY KEY constraint (2627)")


class SimpanDenganNomorTests(SimpleTestCase):
    def test_nomor_bentrok_diulang_dengan_nomor_baru(self):
        """POS lama bisa memakai nomor itu di sela kita membaca dan menulis."""
        cur = FakeCursor(maks="SC2608070001")
        dicoba = []

        def tulis(nomor):
            dicoba.append(nomor)
            if len(dicoba) == 1:
                cur.maks = "SC2608070002"
                raise _galat_duplikat()

        hasil = pn.simpan_dengan_nomor(cur, "penjualan", "SC", tulis, TGL)
        self.assertEqual(dicoba, ["SC2608070002", "SC2608070003"])
        self.assertEqual(hasil, "SC2608070003")

    def test_galat_lain_tidak_diulang(self):
        """Mengulang galat yang bukan bentrok cuma menunda kabar buruknya."""
        cur = FakeCursor(maks=None)
        panggil = []

        def tulis(nomor):
            panggil.append(nomor)
            raise pyodbc.Error("42S22", "[42S22] Invalid column name")

        with self.assertRaises(pyodbc.Error):
            pn.simpan_dengan_nomor(cur, "penjualan", "SC", tulis, TGL)
        self.assertEqual(len(panggil), 1)

    def test_menyerah_dengan_jujur_bukan_menyimpan_nomor_salah(self):
        cur = FakeCursor(maks=None)

        def tulis(nomor):
            raise _galat_duplikat()

        with self.assertRaises(RuntimeError) as ctx:
            pn.simpan_dengan_nomor(cur, "penjualan", "SC", tulis, TGL, percobaan=3)
        self.assertIn("Coba lagi", str(ctx.exception))

    def test_berhasil_sekali_jalan_mengembalikan_nomornya(self):
        cur = FakeCursor(maks=None)
        self.assertEqual(
            pn.simpan_dengan_nomor(cur, "penjualan", "SC", lambda n: None, TGL),
            "SC2608070001")

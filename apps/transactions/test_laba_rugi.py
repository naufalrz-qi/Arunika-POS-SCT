"""Laba Rugi — yang dijaga di sini ARITMETIKANYA, bukan SQL-nya.

MS SQL tak disentuh: `nilai_persediaan` dan cursor dipalsukan, lalu baris hasilnya
diperiksa apakah benar-benar MENJUMLAH. Laporan laba rugi yang baris-barisnya tak
foot tidak ada gunanya, dan itulah satu-satunya hal yang tak bisa ketahuan dari
melihat layarnya sekilas.

Harga pokok rata-rata (`_harga_pokok_rata`) tidak diuji di sini — ia murni SQL,
dan sudah diadu dengan server nyata: 30-06-2026 di GUDANG cocok sampai sen
(Rp 7.610.410.176,11), dan jumlah kelima divisi = total server dalam Rp 0,02.
"""
import datetime as dt
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import laba_rugi as lr


class FakeCursor:
    """Cursor palsu: tiap `execute` mengambil jawaban berikutnya dari antrean."""

    def __init__(self, jawaban):
        self.jawaban = list(jawaban)
        self.sql = []
        self._row = None
        self.description = [("x",)]

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        j = self.jawaban.pop(0) if self.jawaban else 0
        if isinstance(j, dict):
            self.description = [(k,) for k in j]
            self._rows = [tuple(j.values())]
            self._row = self._rows[0]
        else:
            self.description = [("nilai",)]
            self._rows = [(j,)]
            self._row = (j,)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


# Angka bulat supaya identitasnya bisa dicek dengan mata:
#   tersedia = 1000 + 600 - 100 = 1500 ; hpp = 1500 - 900 = 600
#   bersih   = 2000 - 0 + 0 - 200 = 1800 ; laba kotor = 1800 - 600 = 1200
#   laba bersih = 1200 - 150 + 50 = 1100
JAWABAN = [
    {"bruto": 2000.0, "pajak": 0.0, "netto": 2000.0, "tunai": 1500.0, "kredit": 500.0},
    600.0,   # pembelian
    100.0,   # retur pembelian
    200.0,   # retur penjualan
    {"kategori": "Operasional (Penjualan)", "total": 150.0},  # biaya
    50.0,    # pendapatan
    25.0,    # tagihan piutang
]
PERSEDIAAN = [
    {"nilai": 1000.0, "unit": 10, "barang": 5, "tanpa_harga": 1, "stok_negatif": 0},
    {"nilai": 900.0, "unit": 9, "barang": 5, "tanpa_harga": 2, "stok_negatif": 3},
]


@contextmanager
def _fake(cur, tutup_buku=dt.datetime(2017, 12, 31), persediaan=None):
    @contextmanager
    def ganti(profile, autocommit=True, query_timeout=None):
        yield cur

    nilai = list(persediaan if persediaan is not None else PERSEDIAAN)
    with patch.object(lr.mssql, "cursor", ganti), \
         patch.object(lr.inv, "_closing_date", lambda c: tutup_buku), \
         patch.object(lr.inv, "nilai_persediaan", lambda *a, **k: nilai.pop(0)):
        yield


def _hitung(**kw):
    cur = FakeCursor(JAWABAN)
    with _fake(cur, **kw):
        return lr.hitung(object(), dt.datetime(2026, 7, 1), dt.datetime(2026, 7, 31, 23, 59, 59))


def _nilai(hasil, label):
    return next(b["nilai"] for b in hasil["baris"] if b["label"] == label)


class IdentitasTests(SimpleTestCase):
    """Tiap subtotal harus sama dengan jumlah baris di atasnya. Kalau salah satu
    lepas, laporannya berhenti jadi laporan keuangan."""

    def setUp(self):
        self.h = _hitung()

    def test_barang_tersedia_dijual(self):
        self.assertEqual(
            _nilai(self.h, "Barang Tersedia Dijual"),
            _nilai(self.h, "Persediaan Awal") + _nilai(self.h, "Pembelian")
            + _nilai(self.h, "Retur Pembelian"))

    def test_penjualan_bersih(self):
        self.assertEqual(
            _nilai(self.h, "Penjualan Bersih"),
            _nilai(self.h, "Penjualan Bruto") + _nilai(self.h, "Potongan Penjualan")
            + _nilai(self.h, "Pajak Penjualan") + _nilai(self.h, "Retur Penjualan"))

    def test_hpp(self):
        self.assertEqual(
            _nilai(self.h, "Harga Pokok Penjualan"),
            _nilai(self.h, "Barang Tersedia Dijual") + _nilai(self.h, "Persediaan Akhir"))

    def test_laba_kotor(self):
        self.assertEqual(
            _nilai(self.h, "Laba Kotor"),
            _nilai(self.h, "Penjualan Bersih") - _nilai(self.h, "Harga Pokok Penjualan"))

    def test_laba_bersih(self):
        self.assertEqual(
            _nilai(self.h, "Laba Bersih"),
            _nilai(self.h, "Laba Kotor") + _nilai(self.h, "Operasional (Penjualan)")
            + _nilai(self.h, "Pendapatan Lain-Lain"))

    def test_angka_yang_diharapkan(self):
        self.assertEqual(_nilai(self.h, "Harga Pokok Penjualan"), 600.0)
        self.assertEqual(_nilai(self.h, "Laba Kotor"), 1200.0)
        self.assertEqual(_nilai(self.h, "Laba Bersih"), 1100.0)

    def test_pengurang_dikirim_negatif(self):
        """Kolomnya harus bisa dijumlah apa adanya oleh layar dan oleh export."""
        for label in ("Retur Pembelian", "Retur Penjualan", "Persediaan Akhir",
                      "Operasional (Penjualan)"):
            self.assertLess(_nilai(self.h, label), 0, label)


class MarginTests(SimpleTestCase):
    def test_margin_terhadap_penjualan_bersih(self):
        """Bukan terhadap HPP: legacy menyebut laba/HPP sebagai "Rasio Kontribusi",
        itu markup atas modal dan labelnya menyesatkan pembaca laporan keuangan."""
        h = _hitung()
        # 1200 / 1800 = 66,67% (thd penjualan bersih), BUKAN 1200 / 600 = 200% (thd HPP).
        self.assertEqual(_nilai(h, "Margin Kotor (% penjualan bersih)"), 66.67)

    def test_penjualan_nol_tidak_meledak(self):
        self.assertEqual(lr._persen(100, 0), 0.0)


class TutupBukuTests(SimpleTestCase):
    def test_tanggal_mulai_digeser_dan_dikatakan(self):
        """Legacy menggeser diam-diam. Di PUSAT tutup bukunya 2025-12-31, jadi tiap
        permintaan periode 2025 di sana berubah jadi 2026 tanpa sepatah kata pun."""
        h = _hitung(tutup_buku=dt.datetime(2026, 7, 15, 23, 59, 59))
        self.assertIsNotNone(h["notice"])
        self.assertIn("16-07-2026", h["notice"])
        self.assertEqual(h["periode"]["dari"].date(), dt.date(2026, 7, 16))

    def test_tanpa_geseran_tak_ada_notice(self):
        self.assertIsNone(_hitung()["notice"])

    def test_periode_yang_seluruhnya_tertutup_ditolak(self):
        """Menggeser tanggal mulai di sini akan menghasilkan periode satu hari
        sesudah tutup buku yang dibaca orang sebagai bulan yang ia minta — persis
        penggantian diam-diam yang jadi alasan laporan ini ditulis ulang."""
        with self.assertRaises(lr.PeriodeTertutup) as ctx:
            _hitung(tutup_buku=dt.datetime(2026, 12, 31, 23, 59, 59))
        self.assertIn("31-12-2026", str(ctx.exception))


class BentukTests(SimpleTestCase):
    def test_info_membawa_pengungkapan(self):
        info = _hitung()["info"]
        self.assertEqual(info["tanpa_harga"], 2)
        self.assertEqual(info["stok_negatif"], 3)

    def test_memo_tak_ikut_baris_utama(self):
        h = _hitung()
        label = {b["label"] for b in h["baris"]}
        self.assertNotIn("Penjualan Tunai", label)
        self.assertEqual({b["label"] for b in h["memo"]} & label, set())

    def test_nol_tidak_jadi_minus_nol(self):
        """"-0,00" di kolom rupiah terbaca sebagai angka negatif yang dibulatkan."""
        for b in _hitung()["baris"]:
            self.assertFalse(str(b["nilai"]).startswith("-0.0"), b["label"])

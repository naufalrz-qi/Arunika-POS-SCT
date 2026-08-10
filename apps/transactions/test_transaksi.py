"""Retur penjualan, pembelian, retur pembelian — satu mesin, tiga bentuk.

Bentuknya mirip tapi TIDAK sama, dan justru kemiripan itu yang berbahaya:
menyalin bentuk penjualan apa adanya akan menyebut kolom yang tak ada
(diskon_uang, kd_voucher, status di retur) atau kolom terhitung
(t_pembelian_detail.total) — keduanya membuat INSERT ditolak seluruhnya.

MS SQL tidak disentuh — cursor di-fake dan SQL yang dieksekusi direkam.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import transaksi as tx

ITEM = [{"kd_barang": "000-06", "kd_satuan": "SAA000", "qty": 2, "harga": 146000.0}]


class FakeCursor:
    def __init__(self):
        self.sql = []
        self.params = []
        self.connection = self

    def setinputsizes(self, v):
        pass

    def commit(self):
        pass

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self.params.append(list(params or []))

    def fetchone(self):
        akhir = self.sql[-1]
        if "kepala_nota" in akhir:
            return ("SC",)
        return (None,)


@contextmanager
def _fake(cur):
    with patch.object(tx.mssql, "cursor", lambda *a, **k: _ctx(cur)):
        yield


@contextmanager
def _ctx(cur):
    yield cur


def _buat(jenis, cur, **kw):
    dasar = dict(kd_user="UAA002", kd_divisi="DAA000", kd_pihak="X",
                 kd_jenis="JAA000", kd_kas="KAA000", kd_pegawai="PAA000", items=ITEM)
    dasar.update(kw)
    with _fake(cur):
        return tx.buat(object(), jenis, **dasar)


class BentukInsertTests(SimpleTestCase):
    def test_kolom_terhitung_pembelian_tidak_ditulis(self):
        """t_pembelian_detail.total kolom terhitung — menyebutnya membuat SQL
        Server menolak seluruh statement."""
        self.assertNotIn("total", tx.spec("pembelian")["detail"])

    def test_retur_tidak_menyebut_kolom_yang_tak_ada(self):
        """Kolom ini ada di t_penjualan tapi TIDAK di tabel retur."""
        for jenis in ("penjualan_retur", "pembelian_retur"):
            kolom = tx.spec(jenis)["header"]
            for hilang in ("status", "diskon_uang", "kd_voucher", "tanggal_jatuh_tempo"):
                self.assertNotIn(hilang, kolom, f"{hilang} tak ada di {jenis}")

    def test_tiap_jenis_memakai_nama_kolom_harganya_sendiri(self):
        self.assertEqual(tx.spec("penjualan_retur")["harga"], "harga_jual")
        self.assertEqual(tx.spec("pembelian")["harga"], "harga_beli")
        self.assertEqual(tx.spec("pembelian_retur")["harga"], "harga")

    def test_jenis_tak_dikenal_ditolak(self):
        """Nama tabel masuk ke SQL sebagai teks — ia tak boleh dari input."""
        with self.assertRaises(KeyError):
            tx.spec("t_pembelian; DROP TABLE m_barang--")

    def test_insert_menyebut_persis_kolom_spec(self):
        for jenis in tx.SPEC:
            cur = FakeCursor()
            _buat(jenis, cur)
            s = tx.spec(jenis)
            ins_h = next(q for q in cur.sql if q.startswith(f"INSERT INTO {s['tabel']} "))
            ins_d = next(q for q in cur.sql if q.startswith(f"INSERT INTO {s['tabel_detail']}"))
            for k in s["header"]:
                self.assertIn(k, ins_h, f"{jenis}: {k} hilang dari kepala")
            for k in s["detail"]:
                self.assertIn(k, ins_d, f"{jenis}: {k} hilang dari baris")

    def test_harga_generik_masuk_ke_kolom_yang_benar(self):
        for jenis in tx.SPEC:
            cur = FakeCursor()
            _buat(jenis, cur)
            s = tx.spec(jenis)
            i = next(n for n, q in enumerate(cur.sql)
                     if q.startswith(f"INSERT INTO {s['tabel_detail']}"))
            self.assertIn(146000.0, cur.params[i], jenis)


class TotalTests(SimpleTestCase):
    def test_semantik_ghb_sama_dengan_nota_penjualan(self):
        self.assertAlmostEqual(tx.total(ITEM), 292000.0)

    def test_pajak_dan_ppnbm_fraksi_berlipat(self):
        self.assertAlmostEqual(tx.total(ITEM, pajak=0.05, ppnbm=0.1), 292000 * 1.05 * 1.1)

    def test_diskon_baris_pecahan_dibaca_persen(self):
        self.assertAlmostEqual(
            tx.total([{**ITEM[0], "diskon1": 0.5}]), 146000.0)


class ValidasiTests(SimpleTestCase):
    def test_tanpa_tautan_akun_ditolak_dengan_arahan(self):
        with self.assertRaises(ValueError) as ctx:
            tx._periksa(ITEM, "", "DAA000")
        self.assertIn("Kelola Tautan User", str(ctx.exception))

    def test_divisi_kosong_juga_ditolak(self):
        """kd_divisi menentukan awalan nomor — tanpanya nomor bisa salah cabang."""
        with self.assertRaises(ValueError):
            tx._periksa(ITEM, "UAA002", "")

    def test_tanpa_baris_ditolak(self):
        with self.assertRaises(ValueError):
            tx._periksa([], "UAA002", "DAA000")

    def test_qty_nol_ditolak(self):
        with self.assertRaises(ValueError):
            tx._periksa([{"kd_barang": "X", "qty": 0}], "UAA002", "DAA000")

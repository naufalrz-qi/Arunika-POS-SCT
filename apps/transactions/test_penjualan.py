"""Uang di nota penjualan harus persis sama dengan hitungan aplikasi legacy.

Angka yang meleset di sini tidak menimbulkan galat apa pun — ia cuma jadi omzet
yang salah di laporan, dan baru ketahuan saat tutup buku.

Semantik yang ditiru ada di tiga UDF legacy, dan kembaran SQL-nya di
`_ghb`/`_nota_net` (apps/transactions/reports.py). Diperiksa terhadap 300 nota
SC nyata di server testing: 300 cocok, 0 beda.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import penjualan as pj


@contextmanager
def _ctx(cur):
    yield cur


class GhbTests(SimpleTestCase):
    def test_diskon_pecahan_dibaca_sebagai_persen(self):
        """Nilai di (-1, 1) berarti PERSEN. 82 dari 2.990.262 baris memakai mode
        ini; memperlakukannya sebagai rupiah berarti memotong Rp0,2."""
        self.assertAlmostEqual(pj.ghb(58400, [0.2]), 46720.0)

    def test_diskon_besar_dibaca_sebagai_rupiah(self):
        self.assertAlmostEqual(pj.ghb(58400, [400]), 58000.0)

    def test_diskon_berlapis_berurutan(self):
        self.assertAlmostEqual(pj.ghb(100000, [0.1, 0.5]), 45000.0)

    def test_harga_nol_atau_minus_dikembalikan_apa_adanya(self):
        """Guard UDF. Tanpanya baris berharga nol jadi subtotal negatif palsu."""
        self.assertEqual(pj.ghb(0, [0.5]), 0)
        self.assertEqual(pj.ghb(-500, [0.5]), -500)

    def test_diskon_kosong_tidak_mengubah_harga(self):
        self.assertAlmostEqual(pj.ghb(146000, [None, 0, None, 0]), 146000.0)


class TotalNotaTests(SimpleTestCase):
    def _item(self, **kw):
        dasar = {"kd_barang": "X", "kd_satuan": "S", "qty": 2, "harga_jual": 146000}
        dasar.update(kw)
        return dasar

    def test_kasus_yang_diverifikasi_ke_server(self):
        """Nota SC2608070001 yang benar-benar ditulis: 2 x 146.000 = 292.000,
        dan kolom terhitung di database mengembalikan angka yang sama."""
        self.assertAlmostEqual(pj.total_nota([self._item()]), 292000.0)

    def test_pajak_adalah_fraksi_bukan_angka_persen(self):
        """pajak 0,05 = 5%. Membaginya /100 membuat pajak jadi 0,05%."""
        self.assertAlmostEqual(pj.total_nota([self._item()], pajak=0.05), 306600.0)

    def test_diskon_uang_dikurangi_paling_akhir(self):
        """Setelah pajak, bukan sebelum — urutannya mengubah hasilnya."""
        self.assertAlmostEqual(
            pj.total_nota([self._item()], diskon_uang=2000, pajak=0.05), 304600.0)

    def test_diskon_header_berlaku_atas_harga_yang_sudah_didiskon_baris(self):
        hasil = pj.total_nota([self._item(diskon1=0.1)], diskon_header=[0.5, 0, 0, 0])
        self.assertAlmostEqual(hasil, 131400.0)


class ValidasiTests(SimpleTestCase):
    def test_tanpa_tautan_user_legacy_ditolak_dengan_arahan(self):
        """t_penjualan.kd_user NOT NULL. Ditahan di sini supaya kasir dapat
        kalimat yang bisa ditindaklanjuti, bukan galat ODBC."""
        with self.assertRaises(ValueError) as ctx:
            pj._periksa([{"kd_barang": "X", "qty": 1}], "")
        self.assertIn("Manajemen User", str(ctx.exception))

    def test_nota_kosong_ditolak(self):
        with self.assertRaises(ValueError):
            pj._periksa([], "UAA002")

    def test_qty_nol_ditolak(self):
        with self.assertRaises(ValueError):
            pj._periksa([{"kd_barang": "X", "qty": 0}], "UAA002")

    def test_baris_tanpa_barang_ditolak(self):
        with self.assertRaises(ValueError):
            pj._periksa([{"kd_barang": "  ", "qty": 1}], "UAA002")


class FakeCursor:
    """Cursor palsu yang merekam SQL — MS SQL tak disentuh (lihat test_transaksi)."""

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
        return (None,)   # belum ada nomor untuk awalan ini


class OrderTests(SimpleTestCase):
    """Order yang salah tanda tak bisa diambil jadi nota — dan tak ada galat
    apa pun yang memberi tahu; ia cuma hilang dari daftar order terbuka."""

    ITEM = [{"kd_barang": "000-06", "kd_satuan": "SAA000", "qty": 2,
             "harga_jual": 146000.0}]

    def _buat(self, **kw):
        cur = FakeCursor()
        dasar = dict(kd_user="UAA002", kd_divisi="DAA000", kd_customer="CAA000",
                     kd_jenis="JAA000", kd_kas="KAA001", kd_voucher="VAA000",
                     kd_pegawai="PAA000", items=self.ITEM)
        dasar.update(kw)
        with patch.object(pj.mssql, "cursor", lambda *a, **k: _ctx(cur)):
            return cur, pj.buat_order(object(), **dasar)

    def test_nomor_memakai_awalan_order_bukan_kepala_nota(self):
        """kepala_nota divisi ini `SC`, tapi seluruh 7.209 order legacy `OJ`."""
        cur, hasil = self._buat()
        self.assertTrue(hasil["no_order"].startswith("OJ"), hasil["no_order"])
        # kepala_nota tak dibaca sama sekali: layar order tetap jalan walau
        # kolomnya belum diisi.
        self.assertFalse(any("kepala_nota" in s for s in cur.sql))

    def test_ditandai_belum_diambil(self):
        """no_transaksi = no_order DAN status 0 — `daftar_order` menyaring pada
        yang pertama, jadi mengosongkannya membuat order langsung dianggap
        sudah jadi nota."""
        cur, hasil = self._buat()
        i = next(k for k, s in enumerate(cur.sql) if "INSERT INTO t_penjualan_order (" in s)
        nilai = dict(zip(pj._ORDER_HEADER, cur.params[i]))
        self.assertEqual(nilai["no_transaksi"], hasil["no_order"])
        self.assertEqual(nilai["status"], 0)

    def test_tanggal_server_diisi_jam_server(self):
        """Kolomnya NOT-NULL-able tanpa DEFAULT, beda dari t_penjualan; kalau
        tak disebut ia jadi NULL padahal 7.209 baris legacy semuanya terisi."""
        cur, _ = self._buat()
        insert = next(s for s in cur.sql if "INSERT INTO t_penjualan_order (" in s)
        self.assertIn("tanggal_server", insert)
        self.assertIn("GETDATE()", insert)

    def test_baris_ditulis_dengan_jenis_satu(self):
        cur, _ = self._buat()
        i = next(k for k, s in enumerate(cur.sql) if "t_penjualan_order_detail" in s)
        nilai = dict(zip(pj._ORDER_DETAIL, cur.params[i]))
        self.assertEqual(nilai["jenis"], pj.JENIS_BARIS)

    def test_order_kosong_ditolak_sebelum_menyentuh_database(self):
        with self.assertRaises(ValueError):
            self._buat(items=[])


class SatuanBarangTests(SimpleTestCase):
    """Ganti satuan harus ikut mengganti harga: 541 barang punya >1 satuan dan
    harganya beda per satuan (1001: PCS 4.800, LUSIN 57.600)."""

    class _Cur(FakeCursor):
        def fetchall(self):
            return [("SAA000", "PCS", 1.0, 4800.0, 1),
                    ("SAA001  ", " LUSIN ", 12.0, 57600.0, 1)]

    def _panggil(self, kode="1001"):
        cur = self._Cur()
        with patch.object(pj.mssql, "cursor", lambda *a, **k: _ctx(cur)):
            return cur, pj.satuan_barang(object(), kode)

    def test_mengembalikan_harga_per_satuan(self):
        _, rows = self._panggil()
        self.assertEqual(
            rows,
            [{"kd_satuan": "SAA000", "satuan": "PCS", "jumlah": 1.0,
              "harga_jual": 4800.0, "status": 1},
             {"kd_satuan": "SAA001", "satuan": "LUSIN", "jumlah": 12.0,
              "harga_jual": 57600.0, "status": 1}])

    def test_kode_kosong_tidak_menyentuh_database(self):
        cur, rows = self._panggil("   ")
        self.assertEqual(rows, [])
        self.assertEqual(cur.sql, [])


class BentukInsertTests(SimpleTestCase):
    def test_jenis_baris_mengikuti_data_legacy(self):
        """Legacy menulis 1 di SELURUH 2.990.259 baris t_penjualan_detail; 68
        baris ber-jenis 0 semuanya tulisan Arunika sendiri saat pengujian."""
        self.assertEqual(pj.JENIS_BARIS, 1)

    def test_kolom_order_menyebut_semua_kolom_wajib(self):
        """Seluruh kolom t_penjualan_order NOT NULL kecuali tanggal_server &
        no_transaksi — yang tak disebut membuat INSERT ditolak."""
        for k in ("no_order", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas",
                  "kd_voucher", "no_bukti", "tanggal", "tanggal_terima", "status",
                  "diskon_uang", "pajak", "keterangan", "jaminan", "kd_user"):
            self.assertIn(k, pj._ORDER_HEADER, f"{k} hilang — kolomnya NOT NULL")

    def test_kolom_terhitung_tidak_ikut_ditulis(self):
        """t_penjualan_detail.total kolom terhitung — menyebutnya membuat INSERT
        ditolak SQL Server, dan itu baru ketahuan saat menulis nota sungguhan."""
        self.assertNotIn("total", pj._DETAIL)

    def test_header_menyebut_semua_kolom_wajib(self):
        for k in ("no_transaksi", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas",
                  "kd_voucher", "no_bukti", "tanggal", "tanggal_jatuh_tempo",
                  "status", "diskon_uang", "pajak", "keterangan", "kd_user"):
            self.assertIn(k, pj._HEADER, f"{k} hilang — kolomnya NOT NULL")

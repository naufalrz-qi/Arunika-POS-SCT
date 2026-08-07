"""Uang di nota penjualan harus persis sama dengan hitungan aplikasi legacy.

Angka yang meleset di sini tidak menimbulkan galat apa pun — ia cuma jadi omzet
yang salah di laporan, dan baru ketahuan saat tutup buku.

Semantik yang ditiru ada di tiga UDF legacy, dan kembaran SQL-nya di
`_ghb`/`_nota_net` (apps/transactions/reports.py). Diperiksa terhadap 300 nota
SC nyata di server testing: 300 cocok, 0 beda.
"""
from django.test import SimpleTestCase

from apps.transactions import penjualan as pj


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


class BentukInsertTests(SimpleTestCase):
    def test_kolom_terhitung_tidak_ikut_ditulis(self):
        """t_penjualan_detail.total kolom terhitung — menyebutnya membuat INSERT
        ditolak SQL Server, dan itu baru ketahuan saat menulis nota sungguhan."""
        self.assertNotIn("total", pj._DETAIL)

    def test_header_menyebut_semua_kolom_wajib(self):
        for k in ("no_transaksi", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas",
                  "kd_voucher", "no_bukti", "tanggal", "tanggal_jatuh_tempo",
                  "status", "diskon_uang", "pajak", "keterangan", "kd_user"):
            self.assertIn(k, pj._HEADER, f"{k} hilang — kolomnya NOT NULL")

"""Salinan legacy untuk uji: penggolongan tabel dan bentuk kolom, tanpa server."""
from django.test import SimpleTestCase

from apps.bisnis import salin_legacy as sl


class TabelDirujuk(SimpleTestCase):
    def test_diturunkan_dari_adapter_tanpa_nama_palsu(self):
        """Badan adapter yang digabung tanpa pemisah pernah melahirkan
        `m_barang_satuanCREATE` -- tabel yang tak ada di mana pun."""
        t = sl.tabel_dirujuk()
        self.assertIn("t_penjualan_detail", t)
        self.assertIn("m_barang_satuan", t)
        self.assertFalse([x for x in t if not x.islower() or "create" in x])

    def test_tabel_layar_stok_ikut(self):
        """Tanpa `g_tutup_buku` profil salinan bisa dipilih dari navbar tapi
        seluruh layar stok gagal -- adapter tak membacanya, mesin stok membaca."""
        self.assertIn("g_tutup_buku", sl.tabel_dirujuk())
        self.assertIn("m_barang_supplier", sl.tabel_dirujuk())

    def test_cache_snapshot_tidak_disalin(self):
        """Snapshot stok server sumber memuat pergerakan di luar jendela salinan;
        menyalinnya membuat stok salah tanpa galat."""
        t = sl.tabel_dirujuk()
        self.assertNotIn("pos_stok_snapshot", t)
        self.assertNotIn("pos_stok_snapshot_base", t)

    def test_tutup_buku_disalin_utuh(self):
        """Ia bertanggal, tapi bukan `t_*`: memotongnya ke jendela akan membuang
        tanggal tutup buku yang justru jadi jangkar hitungan stok."""
        kelas = sl.kelas_tabel("g_tutup_buku", {"g_tutup_buku": ["periode", "tanggal"]})
        self.assertEqual(kelas[0], "utuh")


class KelasTabel(SimpleTestCase):
    KOLOM = {
        "m_barang": ["kd_barang", "nama"],
        "t_penjualan": ["no_transaksi", "tanggal"],
        "t_penjualan_detail": ["no_transaksi", "kd_barang"],
        "t_penjualan_order": ["no_order", "no_transaksi", "tanggal"],
        "t_penjualan_order_detail": ["no_order", "kd_barang"],
        "t_aneh": ["kd_barang", "qty"],
        "t_yatim_detail": ["no_transaksi"],
    }

    def test_master_utuh(self):
        self.assertEqual(sl.kelas_tabel("m_barang", self.KOLOM)[0], "utuh")

    def test_kepala_bertanggal_dipotong(self):
        self.assertEqual(sl.kelas_tabel("t_penjualan", self.KOLOM)[0], "kepala")

    def test_detail_ikut_kunci_miliknya_sendiri(self):
        """Kepala order punya `no_order` DAN `no_transaksi`; detailnya cuma
        `no_order`. Memakai `no_transaksi` akan memotong detail ke nota, bukan
        ke order."""
        self.assertEqual(sl.kelas_tabel("t_penjualan_detail", self.KOLOM),
                         ("detail", "t_penjualan", "no_transaksi"))
        self.assertEqual(sl.kelas_tabel("t_penjualan_order_detail", self.KOLOM),
                         ("detail", "t_penjualan_order", "no_order"))

    def test_transaksi_tak_terpotong_ditolak(self):
        """Menyalin utuh sebuah tabel `t_*` berarti membawa seluruh riwayat
        produksi tanpa ada yang memintanya."""
        for nama in ("t_aneh", "t_yatim_detail"):
            with self.assertRaises(ValueError, msg=nama):
                sl.kelas_tabel(nama, self.KOLOM)


class TipeKolom(SimpleTestCase):
    def _c(self, **kw):
        base = {"COLUMN_NAME": "k", "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": None,
                "NUMERIC_SCALE": None, "DATETIME_PRECISION": None, "COLLATION_NAME": None}
        return base | kw

    def test_bentuk(self):
        c = self._c
        self.assertEqual(sl.tipe_kolom(c(DATA_TYPE="char", CHARACTER_MAXIMUM_LENGTH=6,
                                         COLLATION_NAME="SQL_Latin1_General_CP1_CI_AS")),
                         "[k] char(6) COLLATE SQL_Latin1_General_CP1_CI_AS NULL")
        self.assertEqual(sl.tipe_kolom(c(DATA_TYPE="varchar", CHARACTER_MAXIMUM_LENGTH=-1)),
                         "[k] varchar(max) NULL")
        self.assertEqual(sl.tipe_kolom(c(DATA_TYPE="decimal", NUMERIC_PRECISION=18, NUMERIC_SCALE=4)),
                         "[k] decimal(18,4) NULL")
        self.assertEqual(sl.tipe_kolom(c(DATA_TYPE="money")), "[k] money NULL")

    def test_rowversion_bisa_diisi(self):
        self.assertEqual(sl.tipe_kolom(self._c(DATA_TYPE="timestamp")), "[k] varbinary(8) NULL")

    def test_lob_mematikan_fast_executemany(self):
        self.assertTrue(sl.punya_lob([self._c(DATA_TYPE="image")]))
        self.assertTrue(sl.punya_lob([self._c(DATA_TYPE="varchar", CHARACTER_MAXIMUM_LENGTH=-1)]))
        self.assertFalse(sl.punya_lob([self._c(DATA_TYPE="varchar", CHARACTER_MAXIMUM_LENGTH=50)]))

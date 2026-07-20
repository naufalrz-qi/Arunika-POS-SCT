from django.test import SimpleTestCase

from apps.master_data.services import HargaTidakBulat, _cek_harga_bulat


class CekHargaBulatTest(SimpleTestCase):
    def test_bilangan_bulat_lolos_dan_dinormalkan(self):
        self.assertEqual(_cek_harga_bulat({"PCS": 3000, "BOX": "45000", "LSN": 12000.0}),
                         {"PCS": 3000.0, "BOX": 45000.0, "LSN": 12000.0})

    def test_nol_lolos(self):
        self.assertEqual(_cek_harga_bulat({"PCS": 0}), {"PCS": 0.0})

    def test_pecahan_ditolak(self):
        # Kasus yang dilaporkan: Rp3.000,001
        with self.assertRaises(HargaTidakBulat) as ctx:
            _cek_harga_bulat({"PCS": 3000.001})
        self.assertIn("PCS", str(ctx.exception))

    def test_negatif_ditolak(self):
        with self.assertRaises(HargaTidakBulat):
            _cek_harga_bulat({"PCS": -1})

    def test_bukan_angka_ditolak(self):
        with self.assertRaises(HargaTidakBulat):
            _cek_harga_bulat({"PCS": "tiga ribu"})

    def test_none_ditolak_bukan_dianggap_nol(self):
        # Regresi: _f(None) -> 0.0, jadi field `harga` yang hilang dari payload
        # JSON pernah lolos sebagai harga 0 dan menghapus harga barang.
        with self.assertRaises(HargaTidakBulat):
            _cek_harga_bulat({"PCS": None})

    def test_bool_ditolak(self):
        with self.assertRaises(HargaTidakBulat):
            _cek_harga_bulat({"PCS": True})

    def test_nan_dan_infinity_ditolak(self):
        for nilai in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(HargaTidakBulat):
                _cek_harga_bulat({"PCS": nilai})

    def test_string_kosong_ditolak(self):
        with self.assertRaises(HargaTidakBulat):
            _cek_harga_bulat({"PCS": ""})

    def test_semua_satuan_salah_dilaporkan_sekaligus(self):
        with self.assertRaises(HargaTidakBulat) as ctx:
            _cek_harga_bulat({"PCS": 3000.001, "BOX": 45000.5, "LSN": 12000})
        pesan = str(ctx.exception)
        self.assertIn("PCS", pesan)
        self.assertIn("BOX", pesan)
        self.assertNotIn("LSN", pesan)

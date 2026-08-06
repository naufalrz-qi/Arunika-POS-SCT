"""Sebar harga GUDANG -> toko: invarian yang kalau rusak tidak memunculkan error.

Semua kegagalan di sini berbentuk sama: tidak ada exception, harga di toko saja
yang salah — atau delapan toko dibanjiri tulisan yang tidak perlu, dan tiap
tulisan itu menyalakan trigger legacy di sana.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import harga_sync


class ProfilPalsu:
    def __init__(self, pk, name):
        self.pk = pk
        self.name = name


GUDANG = ProfilPalsu(1, "GUDANG")
TOKO_A = ProfilPalsu(2, "TOKO_A")
TOKO_B = ProfilPalsu(3, "TOKO_B")


def _peta(**kv):
    """{'A1|PCS': 1000} -> {('A1','PCS'): 1000}"""
    return {tuple(k.split("|")): v for k, v in kv.items()}


class SapuTests(SimpleTestCase):
    def setUp(self):
        harga_sync._terakhir.clear()

    def _sapu(self, sumber, toko, **kw):
        """Jalankan sapu dengan pembacaan harga dipalsukan per profil."""
        def baca(p):
            return sumber if p.name == "GUDANG" else toko[p.name]

        with patch.object(harga_sync, "baca_harga", side_effect=baca), \
             patch.object(harga_sync, "dorong", return_value={"sku": 0, "per_toko": {}, "gagal": {}}) as d:
            hasil = harga_sync.sapu(GUDANG, [TOKO_A, TOKO_B], **kw)
        return hasil, d

    def test_sapuan_pertama_dipaksa_penuh(self):
        """Salinan memori masih kosong sesudah restart. Kalau mode cepat tetap
        dipakai, 55.365 harga terbaca 'baru saja berubah' dan didorong ke delapan
        toko sekaligus — banjir tulisan yang menyalakan trigger legacy di semua
        toko, untuk nol perubahan nyata."""
        sumber = _peta(**{"A1|PCS": 1000, "B1|PCS": 2000})
        toko = {"TOKO_A": dict(sumber), "TOKO_B": dict(sumber)}
        hasil, dorong = self._sapu(sumber, toko)  # penuh=False, tapi salinan kosong
        self.assertEqual(hasil["mode"], "penuh")
        self.assertEqual(hasil["sku"], 0)
        dorong.assert_not_called()

    def test_mode_penuh_menemukan_toko_yang_tertinggal(self):
        sumber = _peta(**{"A1|PCS": 1500, "B1|PCS": 2000})
        toko = {"TOKO_A": _peta(**{"A1|PCS": 1000, "B1|PCS": 2000}),   # A1 basi
                "TOKO_B": _peta(**{"A1|PCS": 1500, "B1|PCS": 2000})}
        hasil, dorong = self._sapu(sumber, toko, penuh=True)
        self.assertEqual(hasil["sku"], 1)
        self.assertEqual(dorong.call_args[0][2], {("A1", "PCS")})

    def test_mode_cepat_hanya_melihat_perubahan_sumber(self):
        sumber = _peta(**{"A1|PCS": 1000})
        toko = {"TOKO_A": dict(sumber), "TOKO_B": dict(sumber)}
        self._sapu(sumber, toko, penuh=True)          # isi salinan
        sumber2 = _peta(**{"A1|PCS": 1750})
        hasil, dorong = self._sapu(sumber2, toko)     # cepat
        self.assertEqual(hasil["mode"], "cepat")
        self.assertEqual(dorong.call_args[0][2], {("A1", "PCS")})

    def test_tanpa_perubahan_tidak_menulis_apa_pun(self):
        """Sapuan tiap 60 detik yang tetap menulis walau tak ada perubahan akan
        membanjiri antrean legacy tiap toko sepanjang hari."""
        sumber = _peta(**{"A1|PCS": 1000})
        toko = {"TOKO_A": dict(sumber), "TOKO_B": dict(sumber)}
        self._sapu(sumber, toko, penuh=True)
        _, dorong = self._sapu(sumber, toko)
        dorong.assert_not_called()

    def test_dry_run_tidak_menyegarkan_salinan(self):
        """Pratinjau yang diam-diam menandai perubahan sebagai beres membuat
        sapuan sungguhan berikutnya melewatinya."""
        sumber = _peta(**{"A1|PCS": 1000})
        toko = {"TOKO_A": _peta(**{"A1|PCS": 900}), "TOKO_B": dict(sumber)}
        hasil, dorong = self._sapu(sumber, toko, penuh=True, dry_run=True)
        self.assertEqual(hasil["sku"], 1)
        dorong.assert_not_called()
        self.assertNotIn(GUDANG.pk, harga_sync._terakhir)

    def test_toko_mati_tidak_menghentikan_toko_lain(self):
        import pyodbc

        sumber = _peta(**{"A1|PCS": 1500})

        def baca(p):
            if p.name == "TOKO_A":
                raise pyodbc.Error("08001", "mati")
            return sumber if p.name == "GUDANG" else _peta(**{"A1|PCS": 1000})

        with patch.object(harga_sync, "baca_harga", side_effect=baca), \
             patch.object(harga_sync, "dorong", return_value={"sku": 1, "per_toko": {}, "gagal": {}}):
            hasil = harga_sync.sapu(GUDANG, [TOKO_A, TOKO_B], penuh=True)
        self.assertIn("TOKO_A", hasil["gagal"])
        self.assertEqual(hasil["sku"], 1)  # TOKO_B tetap diperiksa dan ketahuan basi


class NormalisasiTests(SimpleTestCase):
    def test_spasi_ekor_dan_huruf_besar_bukan_sku_berbeda(self):
        """Collation SQL Server mengabaikan keduanya, dict Python tidak. Tanpa
        normalisasi, SKU yang sama terbaca 'berubah' tiap sapuan dan harganya
        didorong ulang ke delapan toko setiap 60 detik, selamanya."""
        self.assertEqual(harga_sync._norm("lyg005 "), harga_sync._norm("LYG005"))

    def test_angka_tidak_disentuh(self):
        self.assertEqual(harga_sync._norm(1500), 1500)
        self.assertIsNone(harga_sync._norm(None))


class DorongPerubahanTests(SimpleTestCase):
    def setUp(self):
        harga_sync._terakhir.clear()

    def test_menyegarkan_salinan_supaya_tidak_terdorong_dua_kali(self):
        """Tanpa ini, sapuan cepat berikutnya melihat harga baru sebagai
        perubahan dan mendorongnya untuk kedua kalinya — tulisan sia-sia ke
        delapan toko, dan delapan trigger legacy ikut menyala."""
        harga_sync._terakhir[GUDANG.pk] = _peta(**{"A1|PCS": 1000})
        changes = [{"kd_barang": "A1", "kd_satuan": "PCS", "harga_lama": 1000, "harga_baru": 1750}]
        with patch.object(harga_sync, "dorong", return_value={"sku": 1, "per_toko": {}, "gagal": {}}):
            harga_sync.dorong_perubahan(GUDANG, [TOKO_A], changes)
        self.assertEqual(harga_sync._terakhir[GUDANG.pk][("A1", "PCS")], 1750)

    def test_baris_tanpa_kunci_lengkap_dilewati(self):
        with patch.object(harga_sync, "dorong", return_value={"sku": 0, "per_toko": {}, "gagal": {}}) as d:
            harga_sync.dorong_perubahan(GUDANG, [TOKO_A], [{"kd_satuan": "PCS", "harga_baru": 1}])
        self.assertEqual(d.call_args[0][2], set())


class IkatanVarcharTests(SimpleTestCase):
    def test_ambil_baris_mengikat_varchar(self):
        """Kolom kunci `m_barang_satuan` bertipe varchar/char. Tanpa ikatan ini
        daftar `IN` berubah jadi satu scan tabel per nilai — terukur 6,23 dtk
        untuk 50 nilai, 0,01 dtk sesudahnya."""
        class Kursor:
            def __init__(self):
                self.inputsizes = "belum"
            def setinputsizes(self, u):
                self.inputsizes = u
            def execute(self, *a):
                pass
            def fetchall(self):
                return []

        cur = Kursor()
        harga_sync._ambil_baris(cur, [("A1", "PCS")], ["kd_barang", "kd_satuan", "harga_jual"])
        # Direset sesudah dipakai; ikatan menempel di cursor dan execute
        # berikutnya dengan jumlah parameter berbeda akan salah.
        self.assertIsNone(cur.inputsizes)

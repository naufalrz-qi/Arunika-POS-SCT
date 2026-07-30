"""Penentuan server gudang acuan + pemilihan mekanisme saran harga.

Diuji tanpa MS SQL: yang dijaga di sini penelusuran rantai dan PEMILIHAN
mekanismenya, bukan angka hasil query. Salah pilih mekanisme tidak menimbulkan
error — layar tetap rapi sambil menyarankan harga ecer orang lain ke server
grosir.
"""
from unittest import mock

from django.test import TestCase

from apps.connections.models import DbType, ServerProfile
from apps.master_data import services as master
from core import mssql


def _profil(nama, tipe, cost_source=None):
    return ServerProfile.objects.create(
        name=nama, db_type=tipe, host="localhost", port=1433,
        db_name="db", username="sa", cost_source=cost_source,
    )


class SumberGudang(TestCase):
    def test_gudang_menunjuk_dirinya_sendiri(self):
        g = _profil("G", DbType.GUDANG)
        self.assertEqual(mssql.get_gudang_source(g), g)

    def test_satu_langkah(self):
        g = _profil("G", DbType.GUDANG)
        gr = _profil("GR", DbType.GROSIR, cost_source=g)
        self.assertEqual(mssql.get_gudang_source(gr), g)

    def test_dua_langkah_lewat_grosir(self):
        # Bentuk yang benar-benar ada di lapangan: RTL PUSAT -> PUSAT -> GUDANG.
        # cost_source milik retail adalah GROSIR, jadi satu langkah saja tak akan
        # pernah menemukan gudang — inilah kenapa penelusurannya berulang.
        g = _profil("G", DbType.GUDANG)
        gr = _profil("GR", DbType.GROSIR, cost_source=g)
        rtl = _profil("RTL", DbType.RETAIL, cost_source=gr)
        self.assertEqual(mssql.get_gudang_source(rtl), g)

    def test_rantai_buntu_mengembalikan_none(self):
        # RTL RUMAK -> RUMAK -> (kosong): ada di data nyata, jadi None harus
        # ditangani, bukan dianggap mustahil.
        gr = _profil("GR", DbType.GROSIR)
        rtl = _profil("RTL", DbType.RETAIL, cost_source=gr)
        self.assertIsNone(mssql.get_gudang_source(rtl))

    def test_tanpa_cost_source(self):
        self.assertIsNone(mssql.get_gudang_source(_profil("GR", DbType.GROSIR)))

    def test_siklus_tidak_menggantung(self):
        # cost_source FK ke tabel yang sama, jadi A->B->A bisa dibuat dari layar
        # Koneksi tanpa ada yang melarang. Tanpa penjaga siklus, satu profil
        # salah-konfigurasi menggantung request selamanya.
        a = _profil("A", DbType.GROSIR)
        b = _profil("B", DbType.GROSIR, cost_source=a)
        a.cost_source = b
        a.save()
        self.assertIsNone(mssql.get_gudang_source(a))

    def test_gudang_di_dalam_siklus_tetap_ditemukan(self):
        # Karena cost_source bernilai tunggal, rantainya selalu linear: ia
        # berakhir, menemukan gudang, atau berputar — tak ada gudang "di balik"
        # sebuah siklus. Yang mungkin adalah gudang ADA DI DALAM siklusnya, dan
        # itu harus ditemukan lebih dulu daripada penjaga siklus menghentikan
        # penelusuran.
        g = _profil("G", DbType.GUDANG)
        a = _profil("A", DbType.GROSIR, cost_source=g)
        g.cost_source = a
        g.save()
        self.assertEqual(mssql.get_gudang_source(a), g)


class PilihMekanisme(TestCase):
    """`saran_harga` memilih jalur mana; query-nya di-mock."""

    def test_retail_pakai_keterangan(self):
        rtl = _profil("RTL", DbType.RETAIL)
        with mock.patch.object(master, "list_saran_harga", return_value=[{"x": 1}]) as m:
            hasil = master.saran_harga(rtl)
        m.assert_called_once_with(rtl)
        self.assertEqual(hasil["sumber"], "keterangan")
        self.assertIsNone(hasil["gudang"])
        self.assertIsNone(hasil["pesan"])

    def test_retail_tak_pernah_pakai_jalur_gudang(self):
        # Nominal keterangan ("ECER 3.450.000") adalah harga ecer yang ditulis
        # manual; hanya benar untuk retail. Kalau retail ikut jalur gudang, ia
        # kehilangan satu-satunya mekanisme yang memang miliknya.
        g = _profil("G", DbType.GUDANG)
        rtl = _profil("RTL", DbType.RETAIL, cost_source=g)
        with mock.patch.object(master, "list_saran_harga", return_value=[]), \
             mock.patch.object(master, "list_saran_harga_gudang") as m_gudang:
            self.assertEqual(master.saran_harga(rtl)["sumber"], "keterangan")
        m_gudang.assert_not_called()

    def test_grosir_pakai_harga_gudang(self):
        g = _profil("G", DbType.GUDANG)
        gr = _profil("GR", DbType.GROSIR, cost_source=g)
        with mock.patch.object(master, "list_saran_harga_gudang", return_value=[{"x": 1}]) as m:
            hasil = master.saran_harga(gr)
        m.assert_called_once_with(gr, g)
        self.assertEqual(hasil["sumber"], "gudang")
        self.assertEqual(hasil["gudang"], "G")

    def test_grosir_tak_pakai_keterangan(self):
        g = _profil("G", DbType.GUDANG)
        gr = _profil("GR", DbType.GROSIR, cost_source=g)
        with mock.patch.object(master, "list_saran_harga_gudang", return_value=[]), \
             mock.patch.object(master, "list_saran_harga") as m_ket:
            master.saran_harga(gr)
        m_ket.assert_not_called()

    def test_gudang_sendiri_tak_punya_acuan(self):
        g = _profil("G", DbType.GUDANG)
        with mock.patch.object(master, "list_saran_harga_gudang") as m:
            hasil = master.saran_harga(g)
        m.assert_not_called()
        self.assertEqual(hasil["sumber"], "gudang_sendiri")
        self.assertEqual(hasil["rows"], [])
        self.assertIn("acuan", hasil["pesan"])

    def test_rantai_buntu_menjelaskan_yang_harus_diisi(self):
        # Daftar kosong tanpa penjelasan dan daftar kosong karena harga sudah
        # sama adalah dua keadaan berbeda yang butuh dua tindakan berbeda.
        gr = _profil("GR", DbType.GROSIR)
        hasil = master.saran_harga(gr)
        self.assertEqual(hasil["sumber"], "tanpa_acuan")
        self.assertEqual(hasil["rows"], [])
        self.assertIn("Sumber Modal", hasil["pesan"])

    def test_setiap_jalur_mengembalikan_kunci_yang_sama(self):
        # Layar membaca keempat kunci ini tanpa memeriksa jalurnya; satu jalur
        # yang lupa mengirim salah satunya jadi `undefined` di Vue.
        g = _profil("G", DbType.GUDANG)
        gr = _profil("GR", DbType.GROSIR, cost_source=g)
        rtl = _profil("RTL", DbType.RETAIL)
        buntu = _profil("BUNTU", DbType.GROSIR)
        with mock.patch.object(master, "list_saran_harga", return_value=[]), \
             mock.patch.object(master, "list_saran_harga_gudang", return_value=[]):
            for p in (rtl, gr, g, buntu):
                with self.subTest(profil=p.name):
                    self.assertEqual(
                        set(master.saran_harga(p)), {"rows", "sumber", "gudang", "pesan"})

"""Penjaga untuk audit harga beli.

Dua hal yang wajib tak boleh bergeser diam-diam:

1. PENJAGA TULIS. Modul ini menulis ke tabel transaksi legacy yang juga dibaca
   aplikasi POS lama, dan pembatalannya cuma lewat ActivityLog. Daftar-putihnya
   harus menolak apa pun selain database uji — termasuk profil produksi yang
   namanya mirip.
2. PEMILIHAN HARGA. Aturan "pembelian gudang terakhir bertanggal <= tanggal nota"
   menang telak atas "terakhir kapan pun" (87,5% vs 60,5%) saat diadu lawan
   koreksi manual admin. Kalau bisect-nya bergeser satu langkah, angka usulannya
   salah tanpa ada yang gagal.
"""
import datetime as dt

from django.test import SimpleTestCase

from apps.master_data import harga_beli as hb


class _Profile:
    def __init__(self, host, db_name, name="uji"):
        self.host = host
        self.db_name = db_name
        self.name = name


class PenjagaTulisTest(SimpleTestCase):
    def test_database_uji_diizinkan(self):
        self.assertTrue(hb.boleh_tulis(_Profile("localhost", "grosirPusat")))
        # Collation MS SQL abai huruf besar/kecil; perbandingannya harus ikut.
        self.assertTrue(hb.boleh_tulis(_Profile("LOCALHOST", "GROSIRPUSAT")))
        self.assertTrue(hb.boleh_tulis(_Profile(" localhost ", " grosirpusat ")))

    def test_produksi_ditolak(self):
        for host, db in (
            ("SERVER-LOTIM", "SOLID_SIM"),      # ANDARIA
            ("SERVER-TOYS", "SOLID_SIM"),       # PUSAT
            ("localhost", "SOLID_SIM"),         # db produksi di host lokal
            ("SERVER-LOTIM", "grosirPusat"),    # nama db uji di host produksi
        ):
            with self.subTest(host=host, db=db):
                self.assertFalse(hb.boleh_tulis(_Profile(host, db)))

    def test_terapkan_menolak_profil_produksi(self):
        """Penjaga harus di jalur tulis, bukan cuma di tombol UI — endpoint bisa
        dipanggil langsung tanpa lewat halaman."""
        andaria = _Profile("SERVER-LOTIM", "SOLID_SIM", name="ANDARIA")
        items = [{"no_transaksi": "GP01", "kd_barang": "X", "kd_satuan": "S",
                  "jenis": "1", "harga_usulan": 1000}]
        with self.assertRaises(PermissionError):
            hb.terapkan_koreksi(andaria, items)

    def test_terapkan_tanpa_item_tidak_menyentuh_koneksi(self):
        # Daftar kosong harus keluar lebih dulu, bukan membuka koneksi ke server.
        self.assertEqual(hb.terapkan_koreksi(_Profile("localhost", "grosirPusat"), []), (0, []))


class UsulanHargaTest(SimpleTestCase):
    """Riwayat pembelian gudang: tiga pembelian, harga naik tiap kali."""

    def setUp(self):
        self.riwayat = {
            ("BRG1", "PCS"): (
                [dt.datetime(2024, 1, 10), dt.datetime(2025, 6, 1), dt.datetime(2026, 3, 5)],
                [1000.0, 1500.0, 2000.0],
                ["GD-A", "GD-B", "GD-C"],
            )
        }

    def test_memakai_harga_yang_berlaku_saat_itu(self):
        # Nota 2025-12: harga saat itu 1500, BUKAN 2000 (pembelian 2026 belum ada).
        # Inilah selisih 87,5% vs 60,5% terhadap aturan "terakhir kapan pun".
        harga, nota, _tgl = hb._usulan(self.riwayat, ("BRG1", "PCS"), dt.datetime(2025, 12, 1))
        self.assertEqual((harga, nota), (1500.0, "GD-B"))

    def test_tepat_di_tanggal_pembelian_memakai_pembelian_itu(self):
        harga, nota, _ = hb._usulan(self.riwayat, ("BRG1", "PCS"), dt.datetime(2025, 6, 1))
        self.assertEqual((harga, nota), (1500.0, "GD-B"))

    def test_nota_mendahului_semua_pembelian_mundur_ke_yang_pertama(self):
        # Riwayat gudang lebih pendek dari riwayat toko — pakai pembelian paling
        # awal daripada tak mengusulkan apa pun.
        harga, nota, _ = hb._usulan(self.riwayat, ("BRG1", "PCS"), dt.datetime(2020, 1, 1))
        self.assertEqual((harga, nota), (1000.0, "GD-A"))

    def test_barang_tanpa_riwayat_tidak_mengarang_angka(self):
        self.assertEqual(hb._usulan(self.riwayat, ("TIDAK-ADA", "PCS"), dt.datetime(2025, 1, 1)),
                         (None, "", None))


class NormalisasiKeyTest(SimpleTestCase):
    def test_key_join_abai_spasi_dan_huruf(self):
        # Tanpa ini baris hilang diam-diam saat join lintas server.
        self.assertEqual(hb._k(" brg1 "), hb._k("BRG1"))
        self.assertEqual(hb._k(None), "")

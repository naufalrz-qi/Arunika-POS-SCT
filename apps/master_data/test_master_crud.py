"""CRUD master pelanggan & supplier.

MS SQL tidak disentuh — cursor di-fake dan SQL yang dieksekusi direkam.
"""
from django.test import SimpleTestCase

from apps.master_data import master_crud as mc


class FakeCursor:
    def __init__(self, ada=True, maks=None):
        self.ada = ada
        self.maks = maks
        self.sql = []
        self.params = []
        self._row = None
        self.connection = self

    def setinputsizes(self, v):
        pass

    def commit(self):
        self.sql.append("COMMIT")

    def execute(self, sql, params=None):
        rapi = " ".join(sql.split())
        self.sql.append(rapi)
        self.params.append(list(params or []))
        if rapi.startswith("SELECT MAX"):
            self._row = (self.maks,)
        elif rapi.startswith("SELECT 1"):
            self._row = (1,) if self.ada else None
        else:
            self._row = None

    def fetchone(self):
        return self._row


class BersihkanTests(SimpleTestCase):
    def test_nama_wajib(self):
        with self.assertRaises(ValueError):
            mc._bersihkan("pelanggan", {"nama": "   ", "kd_kota": "KAA000"})

    def test_kolom_berkunci_asing_wajib_diisi(self):
        """kd_kota punya FOREIGN KEY ke m_kota; string kosong ditolak database.
        Ditahan di sini supaya operator dapat kalimat, bukan galat FK."""
        with self.assertRaises(ValueError) as ctx:
            mc._bersihkan("pelanggan", {"nama": "Budi"})
        self.assertIn("Kota", str(ctx.exception))

    def test_pesan_wajib_memakai_nama_manusia(self):
        """"Kd_kota wajib diisi" tak memberi tahu kotak mana yang harus diisi."""
        with self.assertRaises(ValueError) as ctx:
            mc._bersihkan("supplier", {"nama": "x", "kd_kota": "KAA000"})
        self.assertIn("Bank", str(ctx.exception))

    def test_teks_dipangkas_ke_panjang_kolom(self):
        """Legacy varchar(35) untuk nama. Dipangkas di sini supaya isian panjang
        jadi data yang benar, bukan galat ODBC yang tak menyebut kolom mana."""
        hasil = mc._bersihkan("pelanggan", {"nama": "A" * 80, "kd_kota": "KAA000"})
        self.assertEqual(len(hasil["nama"]), 35)

    def test_keterangan_beda_panjang_per_entitas(self):
        self.assertEqual(len(mc._bersihkan("pelanggan", {"nama": "x", "kd_kota": "KAA000", "kd_bank": "BAA000", "keterangan": "k" * 300})["keterangan"]), 200)
        self.assertEqual(len(mc._bersihkan("supplier", {"nama": "x", "kd_kota": "KAA000", "kd_bank": "BAA000", "keterangan": "k" * 300})["keterangan"]), 50)

    def test_kolom_tak_dikenal_diabaikan(self):
        """Kolom hanya boleh dari _MASTER — kalau tidak, kiriman apa pun bisa
        ikut masuk ke UPDATE."""
        hasil = mc._bersihkan("pelanggan", {"nama": "Budi", "kd_kota": "KAA000", "status_pinjam": "9", "drop": "x"})
        self.assertNotIn("status_pinjam", hasil)
        self.assertNotIn("drop", hasil)

    def test_angka_tak_masuk_akal_jadi_nol_bukan_meledak(self):
        self.assertEqual(mc._bersihkan("pelanggan", {"nama": "x", "kd_kota": "KAA000", "disc": "abc"})["disc"], 0)
        self.assertEqual(mc._bersihkan("pelanggan", {"nama": "x", "kd_kota": "KAA000", "disc": ""})["disc"], 0)

    def test_entitas_tak_dikenal_ditolak(self):
        """Nama tabel masuk ke SQL sebagai teks — ia tak boleh dari input."""
        with self.assertRaises(KeyError):
            mc.spec("m_customer; DROP TABLE m_barang--")


class SimpanTests(SimpleTestCase):
    def _profile(self, cur):
        from contextlib import contextmanager
        from unittest.mock import patch

        @contextmanager
        def fake(profile, autocommit=True, query_timeout=None):
            yield cur

        return patch.object(mc.mssql, "cursor", fake)

    def test_baris_baru_dapat_kode_berformat(self):
        cur = FakeCursor(maks=None)
        with self._profile(cur):
            hasil = mc.simpan_master(object(), "supplier", {"nama": "PT Maju", "kd_kota": "KAA000", "kd_bank": "BAA000"})
        self.assertEqual(hasil["kode"], "SAA001")
        self.assertTrue(hasil["baru"])
        self.assertTrue(any(s.startswith("INSERT INTO m_supplier") for s in cur.sql))

    def test_kode_melanjutkan_yang_sudah_ada(self):
        cur = FakeCursor(maks="SAA003")
        with self._profile(cur):
            self.assertEqual(
                mc.simpan_master(object(), "supplier", {"nama": "PT Baru", "kd_kota": "KAA000", "kd_bank": "BAA000"})["kode"], "SAA004")

    def test_insert_menyebut_semua_kolom(self):
        """SELURUH kolom m_supplier NOT NULL — yang tak disebut akan ditolak."""
        cur = FakeCursor(maks=None)
        with self._profile(cur):
            mc.simpan_master(object(), "supplier", {"nama": "PT Maju", "kd_kota": "KAA000", "kd_bank": "BAA000"})
        ins = next(s for s in cur.sql if s.startswith("INSERT"))
        s = mc.spec("supplier")
        for k in [s["kunci"], *s["teks"], *s["angka"]]:
            self.assertIn(k, ins)

    def test_ubah_tidak_menyentuh_kolom_kunci(self):
        """Mengubah kode memutus setiap nota yang menunjuk ke baris ini."""
        cur = FakeCursor(ada=True)
        with self._profile(cur):
            hasil = mc.simpan_master(
                object(), "supplier", {"kd_supplier": "SAA002", "nama": "PT Ubah", "kd_kota": "KAA000", "kd_bank": "BAA000"})
        self.assertFalse(hasil["baru"])
        upd = next(s for s in cur.sql if s.startswith("UPDATE"))
        self.assertNotIn("kd_supplier = ?,", upd)
        self.assertTrue(upd.endswith("WHERE kd_supplier = ?"))

    def test_ubah_baris_yang_tak_ada_ditolak(self):
        """SELECT eksplisit, bukan rowcount: trigger legacy membuat rowcount
        tak bisa dipercaya untuk menyimpulkan sebuah baris ada."""
        cur = FakeCursor(ada=False)
        with self._profile(cur):
            with self.assertRaises(ValueError):
                mc.simpan_master(object(), "supplier", {"kd_supplier": "ZZZ999", "nama": "x", "kd_kota": "KAA000", "kd_bank": "BAA000"})


class SupplierTidakDisinkronTests(SimpleTestCase):
    """Supplier boleh DIEDIT per server, tidak boleh MENYEBERANG antar server.

    Gudang yang membeli, jadi gudang yang menyimpan daftar supplier lengkap;
    server toko cuma memakai segelintir supplier miliknya sendiri (PAGESANGAN:
    3 baris). Menyalin daftar gudang ke toko sudah pernah terjadi lewat halaman
    Sinkronisasi Master Data dan harus dipulihkan manual.
    """

    def test_supplier_bukan_entitas_sinkronisasi(self):
        from apps.master_data import services as master

        self.assertNotIn("m_supplier", master._SYNC_ENTITIES)
        self.assertIn("m_barang", master._SYNC_ENTITIES)

    def test_supplier_tetap_bisa_diedit(self):
        """Larangannya soal menyeberang, bukan soal mengelola."""
        self.assertIn("supplier", mc._MASTER)

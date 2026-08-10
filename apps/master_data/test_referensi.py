"""CRUD sebelas tabel referensi (kategori, merk, …, kas).

MS SQL tidak disentuh — cursor di-fake dan SQL yang dieksekusi direkam. Bentuknya
mengikuti test_master_crud.py; yang diuji di sini justru yang MEMBEDAKAN tabel
referensi dari pelanggan/supplier: kode berblok yang bergulir, status sebagai
satu-satunya pembatalan, dan tabel yang kolomnya tidak seragam.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.master_data import master_crud as mc
from apps.transactions import penomoran


class FakeCursor:
    """Cursor palsu. `maks` = jawaban untuk setiap `SELECT MAX`."""

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


@contextmanager
def _fake(cur):
    @contextmanager
    def ganti(profile, autocommit=True, query_timeout=None):
        yield cur

    with patch.object(mc.mssql, "cursor", ganti):
        yield


class BlokKodeTests(SimpleTestCase):
    """Kode master `{huruf}{blok}{NNN}` dan pergulirannya."""

    def _kode(self, maks, huruf="M"):
        cur = FakeCursor(maks=maks)
        return penomoran.kode_master_berikutnya(cur, "m_merk", "kd_merk", huruf)

    def test_lanjut_di_blok_yang_sama(self):
        self.assertEqual(self._kode("MAA482"), "MAA483")

    def test_tabel_kosong_mulai_dari_nol(self):
        self.assertEqual(self._kode(None), "MAA000")

    def test_digit_habis_menaikkan_blok(self):
        """Inti perubahan ini: MAA999 -> MAB000, bukan "nomor sudah habis".

        m_merk sungguh sudah di MAB483 dan m_model di MAB296 — awalan tetap
        seperti ("SAA", None, 3) akan menolak menyimpan di server itu.
        """
        self.assertEqual(self._kode("MAA999"), "MAB000")

    def test_blok_kanan_habis_menggeser_huruf_kiri(self):
        self.assertEqual(self._kode("MAZ999"), "MBA000")

    def test_blok_benar_benar_habis_ditolak_dengan_jelas(self):
        with self.assertRaises(ValueError) as ctx:
            self._kode("MZZ999")
        self.assertIn("habis", str(ctx.exception).lower())

    def test_pola_menyaring_kode_tak_berbentuk(self):
        """`KAATES` di m_kategori dan `1` di m_voucher tak boleh ikut MAX().

        Tanpa saringan bentuk, MAX() mengembalikan KAATES (huruf > angka secara
        leksikal), ekornya bukan angka, dan penomorannya mengulang dari 001 —
        kode yang sudah dipakai bertahun-tahun.
        """
        cur = FakeCursor(maks="KAA861")
        penomoran.kode_master_berikutnya(cur, "m_kategori", "kd_kategori", "K")
        sql = cur.sql[0]
        self.assertIn("LIKE 'K[A-Z][A-Z][0-9][0-9][0-9]'", sql)
        self.assertIn("UPDLOCK, HOLDLOCK", sql)


class SpecTests(SimpleTestCase):
    def test_semua_entitas_referensi_terdaftar(self):
        for e in mc.REFERENSI:
            s = mc.spec(e)
            self.assertIn("huruf", s, f"{e} tak punya skema kode")
            self.assertEqual(len(s["huruf"]), 1)
            self.assertTrue(s["label"])

    def test_kunci_utama_tak_pernah_jadi_kolom_isian(self):
        """Mengubah kd_* merambat ke belasan tabel lewat ON UPDATE CASCADE."""
        for e in mc.REFERENSI:
            s = mc.spec(e)
            self.assertNotIn(s["kunci"], mc._kolom_isi(s))

    def test_kolom_nama_ada_di_kolom_isian(self):
        """ORDER BY / kotak cari memakai kolom ini; m_kas memakai `cabang`."""
        for e in mc.REFERENSI:
            s = mc.spec(e)
            self.assertIn(s.get("kolom_nama", "nama"), mc._kolom_isi(s))

    def test_kas_tidak_memakai_kolom_nama(self):
        self.assertEqual(mc.spec("kas")["kolom_nama"], "cabang")
        self.assertNotIn("nama", mc._kolom_isi(mc.spec("kas")))


class StatusTests(SimpleTestCase):
    def test_baris_baru_aktif_bukan_nonaktif(self):
        """Isian kosong jatuh ke opsi PERTAMA (Aktif), bukan ke 0."""
        nilai = mc._bersihkan("merk", {"nama": "PENDEKAR"})
        self.assertEqual(nilai["status"], 1)

    def test_biaya_aktif_bernilai_dua(self):
        """Seluruh 38 baris m_biaya bernilai 2. Menulis 1 membuat baris asing."""
        self.assertEqual(mc._bersihkan("biaya", {"nama": "LISTRIK"})["status"], 2)

    def test_nonaktif_bisa_disimpan(self):
        self.assertEqual(mc._bersihkan("merk", {"nama": "X", "status": 0})["status"], 0)

    def test_pelanggan_baru_juga_aktif(self):
        """Sebelumnya pelanggan baru lahir status=0 — ikut bucket 286 baris mati."""
        nilai = mc._bersihkan("pelanggan", {"nama": "Budi", "kd_kota": "KAA000"})
        self.assertEqual(nilai["status"], 1)


class TulisTests(SimpleTestCase):
    def test_tak_ada_delete_di_jalur_mana_pun(self):
        """Satu-satunya jaminan yang benar-benar penting di berkas ini.

        DELETE di m_merk merambat ON DELETE CASCADE ke m_barang, lalu tertahan
        NO_ACTION di m_barang_satuan — menghapus separuh katalog lalu gagal.
        """
        for e in mc.REFERENSI:
            s = mc.spec(e)
            isian = {k: "x" for k in s["teks"]}
            isian.update({k: "KAA000" for k in s["lookup"]})
            cur = FakeCursor(maks=None)
            with _fake(cur):
                mc.simpan_master(object(), e, isian)
            gabung = " ".join(cur.sql).upper()
            self.assertNotIn("DELETE", gabung, f"{e} mengeksekusi DELETE")
            self.assertNotIn("DROP", gabung)

    def test_insert_menyebut_seluruh_kolom_isian(self):
        s = mc.spec("kategori")
        cur = FakeCursor(maks="KAA861")
        with _fake(cur):
            hasil = mc.simpan_master(object(), "kategori", {"nama": "SEPEDA"})
        self.assertEqual(hasil["kode"], "KAA862")
        ins = next(x for x in cur.sql if x.startswith("INSERT"))
        for k in [s["kunci"], *mc._kolom_isi(s)]:
            self.assertIn(k, ins)

    def test_ubah_tak_menyentuh_kolom_kunci(self):
        cur = FakeCursor(ada=True)
        with _fake(cur):
            mc.simpan_master(object(), "merk", {"kd_merk": "MAA797", "nama": "PENDEKAR",
                                                "status": 0})
        upd = next(x for x in cur.sql if x.startswith("UPDATE"))
        self.assertNotIn("kd_merk = ?,", upd)
        self.assertTrue(upd.endswith("WHERE kd_merk = ?"))

    def test_ubah_baris_yang_tak_ada_ditolak(self):
        cur = FakeCursor(ada=False)
        with _fake(cur):
            with self.assertRaises(ValueError):
                mc.simpan_master(object(), "merk", {"kd_merk": "MZZ999", "nama": "X"})


class LookupTests(SimpleTestCase):
    def test_lookup_membuang_yang_nonaktif(self):
        """Kalau tidak, tombol "Nonaktifkan" tak berpengaruh apa pun."""
        catat = []

        class Cur(FakeCursor):
            def execute(self, sql, params=None):
                catat.append(" ".join(sql.split()))

            def fetchall(self):
                return []

        cur = Cur()
        with _fake(cur):
            mc.list_lookups(object(), "kota")
        self.assertTrue(catat)
        self.assertIn("WHERE status <> 0", catat[0])


class PotongTests(SimpleTestCase):
    def test_nama_dipotong_ke_panjang_kolom(self):
        """varchar(35). Lebih panjang = galat ODBC yang tak menyebut kolomnya."""
        nilai = mc._bersihkan("merk", {"nama": "A" * 80})
        self.assertEqual(len(nilai["nama"]), 35)

    def test_keterangan_referensi_lima_puluh(self):
        nilai = mc._bersihkan("merk", {"nama": "X", "keterangan": "B" * 200})
        self.assertEqual(len(nilai["keterangan"]), 50)

    def test_keterangan_pelanggan_tetap_dua_ratus(self):
        nilai = mc._bersihkan("pelanggan",
                              {"nama": "X", "kd_kota": "KAA000", "keterangan": "B" * 400})
        self.assertEqual(len(nilai["keterangan"]), 200)

    def test_nama_wajib_di_semua_entitas(self):
        for e in mc.REFERENSI:
            s = mc.spec(e)
            isian = {k: "KAA000" for k in s["lookup"]}
            with self.assertRaises(ValueError, msg=f"{e} menerima nama kosong"):
                mc._bersihkan(e, isian)

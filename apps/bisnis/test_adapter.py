"""Kontrak generator adapter: ia harus BERHENTI, bukan menebak.

`apps/bisnis/adapter.py` membangkitkan badan iTVF dengan memanggil
`_movement_sql` memakai nilai penanda, lalu menukar tiap `?` dengan nama
parameter T-SQL. Itu membuat `_movement_sql` tetap satu-satunya sumber logika
stok -- tapi juga berarti generator ini **terikat pada bentuk keluarannya**.

Kalau suatu hari `_movement_sql` menambah parameter, kegagalannya tidak akan
terlihat: fungsi yang terpasang tetap valid secara SQL, hanya saja salah satu
filternya jadi konstanta tahun 1901, dan stoknya salah tanpa satu pun galat.
Test ini memastikan hal itu meledak di CI, bukan di layar orang.

Tidak butuh SQL Server: yang diuji pembangkitan teksnya, bukan eksekusinya.
Pembuktian bahwa hasilnya identik dengan jalur legacy dilakukan terhadap server
sungguhan (lihat catatan hasil di docstring `adapter.py`).
"""
from unittest import mock

from django.test import SimpleTestCase

from apps.bisnis import adapter


class BadanFungsi(SimpleTestCase):
    def test_semua_placeholder_tergantikan(self):
        """Satu '?' yang tersisa = SQL yang tak bisa di-CREATE FUNCTION."""
        badan, _ = adapter.badan_fungsi()
        self.assertNotIn("?", badan)

    def test_tak_ada_penanda_yang_bocor_ke_sql(self):
        """Penanda yang lolos berarti filternya jadi konstanta, diam-diam."""
        badan, _ = adapter.badan_fungsi()
        for nilai in adapter._PENANDA.values():
            self.assertNotIn(str(nilai), badan, f"penanda {nilai!r} bocor ke badan fungsi")

    def test_memakai_kelima_parameter(self):
        badan, nama = adapter.badan_fungsi()
        self.assertEqual(set(nama), {f"@{n}" for n in adapter.URUT_PARAMETER})
        for n in adapter.URUT_PARAMETER:
            self.assertIn(f"@{n}", badan)


class PetaParameter(SimpleTestCase):
    def test_nilai_asing_ditolak(self):
        """Menebak di sini berarti memasang fungsi yang memfilter salah."""
        with self.assertRaises(RuntimeError) as ctx:
            adapter._peta_parameter([adapter._PENANDA["closing"], "nilai-yang-tak-dikenal"])
        self.assertIn("bukan penanda", str(ctx.exception))

    def test_urutan_dipertahankan(self):
        p = adapter._PENANDA
        self.assertEqual(
            adapter._peta_parameter([p["kd_barang"], p["closing"], p["kd_divisi"]]),
            ["@kd_barang", "@closing", "@kd_divisi"],
        )


class Ddl(SimpleTestCase):
    def test_inline_bukan_multi_statement(self):
        """`RETURNS TABLE AS RETURN (...)` adalah bentuk yang di-inline SQL Server.

        Bentuk multi-statement (`RETURNS @t TABLE (...) BEGIN ... END`) TIDAK
        di-inline, dan seluruh keunggulan kecepatan yang diukur akan hilang.
        """
        ddl = adapter.ddl_pergerakan_stok("LEGACYDB")
        self.assertIn("RETURNS TABLE AS RETURN", ddl)
        self.assertNotIn("BEGIN", ddl.upper().replace("BEGINNING", ""))

    def test_parameter_varchar_bukan_nvarchar(self):
        """Justru tipe di tanda tangan inilah yang membuat predikatnya tetap seek.

        pyodbc mengikat `str` sebagai NVARCHAR sementara kolom kunci legacy
        `varchar`; konversi implisit di sisi kolom membatalkan index seek.
        Parameter fungsi yang bertipe `varchar` mengonversi sekali di batas
        fungsi, bukan meracuni predikat tiap cabang. Terukur 6,5x.
        """
        ddl = adapter.ddl_pergerakan_stok("LEGACYDB")
        self.assertIn("@kd_barang varchar(30)", ddl)
        self.assertIn("@kd_divisi varchar(30)", ddl)
        self.assertNotIn("nvarchar", ddl.lower())

    def test_selalu_di_schema_sendiri(self):
        """Tak pernah dbo. Sejak Fase 4 ia hidup di database ARUNIKA, bukan di
        database legacy -- yang terakhir tidak menerima objek apa pun."""
        self.assertIn("[arunika_src].[pergerakan_stok]", adapter.ddl_pergerakan_stok("LEGACYDB"))

    def test_jumlah_placeholder_pemanggilan_cocok(self):
        self.assertEqual(adapter.panggil().count("?"), len(adapter.URUT_PARAMETER))


class KualifikasiLintasDatabase(SimpleTestCase):
    """Fungsi ini hidup di database Arunika, jadi tiap nama tabel legacy harus
    berkualifikasi database.

    Lupa mengualifikasi tidak ketahuan saat `CREATE FUNCTION` -- SQL Server
    menunda resolusi nama sampai fungsinya DIPANGGIL. Jadi pemasangannya sukses,
    dan kegagalannya muncul dari dalam sebuah laporan, entah kapan.
    """

    def test_setiap_tabel_legacy_dikualifikasi(self):
        ddl = adapter.ddl_pergerakan_stok("SOLID_SIM")
        for potongan in ("FROM t_", "JOIN t_", "FROM m_", "JOIN m_"):
            self.assertNotIn(potongan, ddl, f"masih ada rujukan tak berkualifikasi: {potongan}")
        self.assertIn("[SOLID_SIM].dbo.t_penjualan_detail", ddl)

    def test_derived_table_tidak_ikut_disentuh(self):
        """`FROM (SELECT ...` bukan nama tabel; mengualifikasinya merusak SQL."""
        sql, n = adapter._kualifikasi("SELECT * FROM (SELECT 1) q JOIN m_barang b ON 1=1", "DB")
        self.assertIn("FROM (SELECT 1) q", sql)
        self.assertEqual(n, 1)

    def test_nama_database_nakal_ditolak(self):
        with self.assertRaises(ValueError):
            adapter._kualifikasi("FROM m_barang", "X]; DROP DATABASE y --")

    def test_berhenti_kalau_tak_mengenali_apa_pun(self):
        """Nol rujukan dikenali = `_movement_sql` berubah bentuk. Berhenti,
        jangan pasang fungsi yang akan gagal saat dipanggil."""
        with mock.patch.object(adapter, "badan_fungsi", return_value=("SELECT 1", [])):
            with self.assertRaises(RuntimeError):
                adapter.ddl_pergerakan_stok("DB")


class GayaPlaceholder(SimpleTestCase):
    """Dua jalur akses data, dua konvensi. Salah pilih gagal jauh dari sebabnya:
    galatnya muncul di pemformat SQL debug Django sebagai `TypeError: not all
    arguments converted during string formatting`, tanpa menyebut placeholder."""

    def test_pyodbc_memakai_tanda_tanya(self):
        self.assertEqual(adapter.panggil(adapter.GAYA_PYODBC).count("?"), len(adapter.URUT_PARAMETER))

    def test_django_memakai_persen_s(self):
        q = adapter.panggil(adapter.GAYA_DJANGO)
        self.assertEqual(q.count("%s"), len(adapter.URUT_PARAMETER))
        self.assertNotIn("?", q)

    def test_gaya_asing_ditolak(self):
        with self.assertRaises(ValueError):
            adapter.panggil(":1")

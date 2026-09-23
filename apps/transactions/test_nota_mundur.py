"""Laporan Nota Tanggal Mundur.

Dua hal yang dijaga di sini tidak akan terlihat sampai produksi:

1. **Bentuk predikatnya.** `tanggal_server` tak punya satu pun indeks. Yang
   membuat laporan ini terjangkau adalah urutan predikatnya — `tanggal` yang
   terindeks dulu, perbandingan CAST menyusul sebagai residual. Menukarnya
   mengubah tiap arm jadi table scan di tabel 445.873 baris, dan tak satu pun
   test lain akan merah karenanya.

2. **Tanda `selisih_hari`.** Membungkusnya dengan ABS() menghapus seluruh
   kategori "bertanggal maju" (49 baris di testGudang) tanpa gejala apa pun:
   jumlah barisnya tetap masuk akal, hanya satu jenis anomali yang lenyap.
"""
import datetime as dt

from django.db import connection
from django.test import SimpleTestCase, TestCase

from apps.transactions import reports as rpt


def _f(**kw):
    dasar = {
        "date_from": dt.datetime(2025, 1, 1),
        "date_to": dt.datetime(2025, 12, 31, 23, 59, 59),
        "search": "",
    }
    dasar.update(kw)
    return dasar


class BentukSql(SimpleTestCase):
    def test_predikat_tanggal_mendahului_perbandingan(self):
        """`tanggal >= ?` harus muncul SEBELUM perbandingan CAST di tiap arm.

        Ini yang mengerjakan index seek; perbandingannya hanya disaring di atas
        hasilnya. Kalau urutannya terbalik, laporan ini men-scan seluruh tabel.
        """
        sql, _ = rpt.nota_mundur(_f())
        for arm in sql.split("UNION ALL"):
            if "WHERE" not in arm:
                continue
            i_tgl = arm.index("tanggal >= ?")
            i_cast = arm.index("CAST(tanggal AS DATE) <> CAST(tanggal_server AS DATE)")
            self.assertLess(i_tgl, i_cast, "predikat terindeks harus lebih dulu")

    def test_tidak_ada_or_di_predikat(self):
        """`OR` pada kolom tak berindeks membuang seluruh seek."""
        sql, _ = rpt.nota_mundur(_f())
        for arm in sql.split("UNION ALL"):
            if "WHERE" in arm:
                self.assertNotIn(" OR ", arm.split("WHERE", 1)[1])

    def test_selisih_hari_bertanda_bukan_mutlak(self):
        """Yang dipajang WAJIB bertanda; hanya kolom pengurutan yang mutlak."""
        sql, _ = rpt.nota_mundur(_f())
        self.assertIn(f"{rpt._SELISIH} AS selisih_hari", sql)
        self.assertIn(f"ABS({rpt._SELISIH}) AS jarak_hari", sql)
        # Kalau seseorang membungkus yang dipajang dengan ABS, ini yang merah.
        self.assertNotIn(f"ABS({rpt._SELISIH}) AS selisih_hari", sql)

    def test_arah_membedakan_maju_dari_mundur(self):
        sql, _ = rpt.nota_mundur(_f())
        self.assertIn("WHEN x.selisih_hari > 0 THEN 'Mundur'", sql)
        self.assertIn("'Maju'", sql)

    def test_penambahan_kas_tidak_ikut(self):
        """Ia satu-satunya dokumen kas tanpa `tanggal_server`.

        Memasukkannya dengan NULL akan membuatnya terbaca "tak pernah
        bermasalah", padahal yang benar adalah "tak bisa dijawab".
        """
        sql, _ = rpt.nota_mundur(_f())
        self.assertNotIn("t_penambahan_kas", sql)

    def test_delapan_arm_saat_tanpa_filter_jenis(self):
        sql, params = rpt.nota_mundur(_f())
        self.assertEqual(sql.count("UNION ALL"), len(rpt._DOK_MUNDUR) - 1)
        # 3 param per arm: date_from, date_to, min_selisih.
        self.assertEqual(len(params), len(rpt._DOK_MUNDUR) * 3)


class FilterJenis(SimpleTestCase):
    def test_memilih_jenis_membuang_arm_lain(self):
        """Bukan menyaring hasil UNION — tujuh tabel lain tak disentuh."""
        sql, params = rpt.nota_mundur(_f(jenis="Penjualan"))
        self.assertNotIn("UNION ALL", sql)
        self.assertIn("FROM t_penjualan WHERE", sql)
        self.assertNotIn("t_pembelian", sql)
        self.assertEqual(len(params), 3)

    def test_jenis_tak_dikenal_tidak_mengosongkan_laporan(self):
        """Nilai nakal dari query string harus jatuh ke 'semua', bukan nol arm —
        laporan kosong tanpa sebab lebih menyesatkan daripada laporan penuh."""
        sql, _ = rpt.nota_mundur(_f(jenis="Bukan Jenis Apa Pun"))
        self.assertEqual(sql.count("UNION ALL"), len(rpt._DOK_MUNDUR) - 1)

    def test_jenis_yang_ditawarkan_sama_dengan_yang_diterima(self):
        """`JENIS_MUNDUR` mengisi dropdown; kalau ia menyimpang dari
        `_DOK_MUNDUR`, pengguna memilih nilai yang membuang semua arm."""
        self.assertEqual(rpt.JENIS_MUNDUR, [d[0] for d in rpt._DOK_MUNDUR])
        for j in rpt.JENIS_MUNDUR:
            sql, _ = rpt.nota_mundur(_f(jenis=j))
            self.assertNotIn("UNION ALL", sql, f"{j} tak menyisakan tepat satu arm")


class AmbangSelisih(SimpleTestCase):
    def test_bawaan_satu_hari(self):
        _, params = rpt.nota_mundur(_f(jenis="Penjualan"))
        self.assertEqual(params[2], 1)

    def test_ambang_dipakai_per_arm(self):
        _, params = rpt.nota_mundur(_f(min_selisih=30))
        self.assertEqual(params[2::3], [30] * len(rpt._DOK_MUNDUR))

    def test_ambang_nakal_jatuh_ke_bawaan(self):
        for nakal in ("", None, "abc", 0, -5):
            _, params = rpt.nota_mundur(_f(min_selisih=nakal, jenis="Penjualan"))
            self.assertGreaterEqual(params[2], 1, f"{nakal!r} lolos jadi ambang tak sah")

    def test_ambang_dinilai_mutlak(self):
        """Ambang memakai ABS supaya dokumen bertanggal MAJU ikut lolos
        saringan; hanya nilai yang DIPAJANG yang bertanda."""
        sql, _ = rpt.nota_mundur(_f(min_selisih=7))
        self.assertIn(f"ABS({rpt._SELISIH}) >= ?", sql)


class JejakLog(SimpleTestCase):
    """Penyebab (diedit / diinput mundur) dibaca dari tbl_log_transaksi.

    Yang dijaga di sini semuanya soal ONGKOS, dan tak satu pun akan merah di
    tes lain: tabel log berisi jutaan baris tanpa index selain `id`, jadi satu
    bentuk yang salah berarti scan jutaan baris PER BARIS laporan.
    """

    def test_tanpa_index_log_tidak_disentuh(self):
        """Tanpa `log_siap`, tabel log tak boleh muncul sama sekali — dan
        pembuat TIDAK ditebak dari kd_user, yang justru sudah ditimpa pengedit."""
        sql, params = rpt.nota_mundur(_f())
        self.assertNotIn("tbl_log_transaksi", sql)
        self.assertIn("'Belum dicek' AS penyebab", sql)
        self.assertIn("CAST(NULL AS varchar(50)) AS dibuat_oleh", sql)
        self.assertEqual(len(params), len(rpt._DOK_MUNDUR) * 3)

    def test_tiap_pencarian_seek_pada_aksi_dan_waktu(self):
        """Kunci index adalah (table_aksi, waktu). Pencarian yang tak menyaring
        keduanya dengan = / rentang tak bisa seek."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        pencarian = sql.split("OUTER APPLY (SELECT TOP 1")[1:]
        self.assertEqual(len(pencarian), 4)
        for p in pencarian:
            self.assertRegex(p, r"l\.table_aksi = x\.aksi_(ins|upd) AND l\.waktu >= .+ AND l\.waktu < ")
            self.assertIn("ORDER BY l.waktu", p)
            # LIKE dengan nomor dokumen butuh escape `_`; LEFT(...) = tidak.
            self.assertNotIn("LIKE", p)

    def test_pencarian_mahal_hanya_untuk_yang_membutuhkan(self):
        """Predikat yang hanya merujuk kolom luar jadi predikat startup: insert
        dicari hanya kalau tak ada update, pembuat asli hanya untuk yang diedit,
        jendela lebar hanya kalau jendela sempit kosong."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertIn("WHERE su.id IS NULL AND l.table_aksi = x.aksi_ins", sql)
        self.assertIn("WHERE su.id IS NOT NULL AND l.table_aksi = x.aksi_ins", sql)
        self.assertIn("WHERE su.id IS NOT NULL AND a1.fd IS NULL AND l.table_aksi = x.aksi_ins", sql)

    def test_tiap_arm_membawa_alamat_jejaknya(self):
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        for _label, tabel, nokol in rpt._DOK_MUNDUR:
            self.assertIn(f"'{tabel}__insert' AS aksi_ins, '{tabel}__update' AS aksi_upd", sql)
            self.assertIn(f"'val__{nokol}__' + RTRIM({nokol}) + ';' AS kunci_ins", sql)
            self.assertIn(f"'key__{nokol}__' + RTRIM({nokol}) + ';' AS kunci_upd", sql)

    def test_jejak_tidak_menambah_parameter(self):
        """Semua nilai pencarian log berasal dari kolom baris, bukan `?` — kalau
        ada yang lolos jadi parameter, urutan `?` bergeser dan pyodbc diam saja."""
        _, tanpa = rpt.nota_mundur(_f())
        _, dengan = rpt.nota_mundur(_f(log_siap=True))
        self.assertEqual(tanpa, dengan)


class KolomLog(TestCase):
    """`kolom_log` dijalankan di SQL Server sungguhan (pangkal uji), bukan
    dibaca teksnya: CHARINDEX/SUBSTRING yang meleset satu karakter tetap
    menghasilkan string yang tampak masuk akal."""

    def _ambil(self, payload, kolom):
        with connection.cursor() as cur:
            cur.execute(f"SELECT {rpt.kolom_log('p.fd', kolom)} FROM (SELECT %s AS fd) p", [payload])
            return cur.fetchone()[0]

    def test_nilai_di_tengah_dan_di_ujung(self):
        fd = "val__no_transaksi__SC1;val__kd_user__UAA009;val__divisi_id__DAA004"
        self.assertEqual(self._ambil(fd, "kd_user"), "UAA009")
        self.assertEqual(self._ambil(fd, "divisi_id"), "DAA004")

    def test_kolom_tak_ada_jadi_null(self):
        self.assertIsNone(self._ambil("val__no_transaksi__SC1;val__keterangan__-", "kd_user"))

    def test_tak_tertukar_dengan_kolom_berakhiran_sama(self):
        """`;val__` di depan mencegah `x_kd_user` terbaca sebagai `kd_user`."""
        fd = "val__no_transaksi__SC1;val__x_kd_user__SALAH;val__kd_user__BENAR"
        self.assertEqual(self._ambil(fd, "kd_user"), "BENAR")


class FilterPenyebab(SimpleTestCase):
    def test_penyebab_disaring_di_luar_dengan_parameter_terakhir(self):
        sql, params = rpt.nota_mundur(_f(log_siap=True, penyebab="Diedit", kd_divisi="DAA001"))
        self.assertTrue(sql.endswith("WHERE p.penyebab = ?"))
        self.assertEqual(params[-2:], ["DAA001", "Diedit"])

    def test_penyebab_tak_dikenal_diabaikan(self):
        sql, params = rpt.nota_mundur(_f(log_siap=True, penyebab="'; DROP TABLE x --"))
        self.assertNotIn("p.penyebab", sql)
        self.assertEqual(len(params), len(rpt._DOK_MUNDUR) * 3)

    def test_pilihan_penyebab_sama_dengan_yang_dihasilkan_sql(self):
        """Dropdown diisi PENYEBAB_MUNDUR; nilai yang tak pernah dihasilkan SQL
        berarti pilihan yang selalu kosong."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        for p in rpt.PENYEBAB_MUNDUR:
            self.assertIn(f"'{p}'", sql)


class UrutanParameter(SimpleTestCase):
    def test_param_arm_mendahului_param_luar(self):
        """Parameter harus urut sama dengan urutan `?` di teks SQL.

        Arm dulu (di dalam kurung), baru WHERE luar. Tertukar = pencarian
        dibandingkan dengan tanggal, dan pyodbc tidak akan mengeluh.
        """
        sql, params = rpt.nota_mundur(_f(jenis="Penjualan", search="AB1", kd_divisi="DAA001"))
        self.assertEqual(params[:3], [_f()["date_from"], _f()["date_to"], 1])
        self.assertEqual(params[-1], "DAA001")
        self.assertIn("%AB1%", params)
        self.assertLess(sql.index("FROM t_penjualan WHERE"), sql.index("x.kd_divisi = ?"))

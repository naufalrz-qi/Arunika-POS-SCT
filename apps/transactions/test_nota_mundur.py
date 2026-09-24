"""Laporan Nota Tanggal Mundur.

Yang dijaga di sini tidak akan terlihat sampai produksi:

1. **Bentuk predikatnya.** `tanggal_server` tak punya satu pun indeks. Yang
   membuat laporan ini terjangkau adalah urutan predikatnya — `tanggal` yang
   terindeks dulu, perbandingan CAST menyusul sebagai residual. Menukarnya
   mengubah tiap arm jadi table scan di tabel 445.873 baris, dan tak satu pun
   test lain akan merah karenanya.

2. **Tanda `selisih_hari`.** Membungkusnya dengan ABS() menghapus seluruh
   kategori "bertanggal maju" (49 baris di testGudang) tanpa gejala apa pun:
   jumlah barisnya tetap masuk akal, hanya satu jenis anomali yang lenyap.

3. **Tabel log berisi jutaan baris.** Setiap pencarian ke sana harus seek
   `(table_aksi, waktu)`; satu bentuk yang salah = scan jutaan baris per baris
   laporan.

4. **Urutan `?`.** Tiga macam arm × delapan tabel + tiga lapis. Parameter yang
   tergeser membandingkan tanggal dengan kata kunci, dan pyodbc diam saja.
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


# Parameter per tabel: arm A (dari, sampai, min) + arm C (dari, sampai), dan
# bila log siap arm B (waktu, 2×asal, 2×kini, 3×syarat A).
PARAM_A, PARAM_C, PARAM_B = 3, 2, 8


class ArmTabel(SimpleTestCase):
    """Arm A (selisih) dan C (tidak wajar) membaca tabel dokumen langsung."""

    def test_predikat_tanggal_mendahului_perbandingan(self):
        """`tanggal >= ?` harus muncul SEBELUM perbandingan CAST.

        Ini yang mengerjakan index seek; perbandingannya hanya disaring di atas
        hasilnya. Kalau urutannya terbalik, laporan ini men-scan seluruh tabel.
        """
        for label, tabel, nokol in rpt._DOK_MUNDUR:
            arm = rpt._arm_selisih(label, tabel, nokol)
            where = arm.split(" WHERE ", 1)[1]
            self.assertLess(where.index("tanggal >= ?"),
                            where.index("CAST(tanggal AS DATE) <> CAST(tanggal_server AS DATE)"), tabel)

    def test_tidak_ada_or_di_predikat(self):
        """`OR` pada kolom tak berindeks membuang seluruh seek."""
        for label, tabel, nokol in rpt._DOK_MUNDUR:
            for arm in (rpt._arm_selisih(label, tabel, nokol), rpt._arm_tidak_wajar(label, tabel, nokol)):
                self.assertNotIn(" OR ", arm.split(" WHERE ", 1)[1], tabel)

    def test_jumlah_parameter_arm(self):
        for label, tabel, nokol in rpt._DOK_MUNDUR:
            self.assertEqual(rpt._arm_selisih(label, tabel, nokol).count("?"), PARAM_A)
            self.assertEqual(rpt._arm_tidak_wajar(label, tabel, nokol).count("?"), PARAM_C)
            self.assertEqual(rpt._arm_pindah(label, tabel, nokol).count("?"), PARAM_B)

    def test_selisih_hari_bertanda_bukan_mutlak(self):
        """Yang dipajang WAJIB bertanda; hanya kolom pengurutan yang mutlak."""
        arm = rpt._arm_selisih("Penjualan", "t_penjualan", "no_transaksi")
        self.assertIn(f"{rpt._SELISIH} AS selisih_hari", arm)
        self.assertIn(f"ABS({rpt._SELISIH}) AS jarak_hari", arm)
        self.assertNotIn(f"ABS({rpt._SELISIH}) AS selisih_hari", arm)

    def test_tidak_wajar_tak_bergantung_rentang(self):
        """Tahun 7252 tak pernah masuk rentang mana pun — arm C harus menangkapnya
        tanpa rentang, dan hanya membuang yang sudah tertangkap arm A."""
        arm = rpt._arm_tidak_wajar("Penjualan", "t_penjualan", "no_transaksi")
        self.assertIn(rpt._tidak_wajar("tanggal"), arm)
        self.assertIn("NOT (tanggal >= ? AND tanggal <= ?)", arm)
        self.assertNotIn(" OR ", rpt._tidak_wajar("tanggal"))

    def test_tiap_arm_membawa_alamat_jejaknya(self):
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        for _label, tabel, nokol in rpt._DOK_MUNDUR:
            self.assertIn(f"'{tabel}__insert' AS aksi_ins, '{tabel}__update' AS aksi_upd", sql)
            self.assertIn(f"'val__{nokol}__' AS awal_ins, 'key__{nokol}__' AS awal_upd", sql)
            self.assertIn(f"';val__{nokol}__' + RTRIM({nokol}) + ';' AS kunci_val", sql)

    def test_penambahan_kas_tidak_ikut(self):
        """Ia satu-satunya dokumen kas tanpa `tanggal_server`.

        Memasukkannya dengan NULL akan membuatnya terbaca "tak pernah
        bermasalah", padahal yang benar adalah "tak bisa dijawab".
        """
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertNotIn("t_penambahan_kas", sql)


class ArmPindah(SimpleTestCase):
    """Arm B: dokumen yang nomornya diganti lewat edit (tanggal dipindah)."""

    ARM = rpt._arm_pindah("Penjualan", "t_penjualan", "no_transaksi")

    def test_seek_log_pada_aksi_dan_waktu(self):
        self.assertIn("WHERE l.table_aksi = 't_penjualan__update' AND l.waktu >= ?", self.ARM)
        self.assertNotIn("LIKE", self.ARM)

    def test_hanya_update_yang_mengganti_nomor(self):
        self.assertIn("INNER JOIN t_penjualan d ON d.no_transaksi = m.nomor_baru", self.ARM)
        self.assertIn("g.nomor_asal <> g.nomor_baru", self.ARM)

    def test_satu_baris_per_dokumen_dan_nomor_pakai_ulang(self):
        """Hanya pemindahan TERAKHIR ke sebuah nomor, dan hanya bila nomor itu
        tak dipindah pergi lagi sesudahnya (lalu dipakai dokumen lain)."""
        self.assertIn("ROW_NUMBER() OVER (PARTITION BY g.nomor_baru ORDER BY g.id DESC) AS urut", self.ARM)
        self.assertIn("WHERE m.urut = 1", self.ARM)
        self.assertIn("AND NOT EXISTS (SELECT 1 FROM tbl_log_transaksi l2 WHERE l2.table_aksi = 't_penjualan__update' "
                      "AND l2.waktu >= g.waktu AND l2.id > g.id", self.ARM)

    def test_tak_dobel_dengan_arm_lain(self):
        """Yang sudah tertangkap arm A (atau C) dibuang di sini."""
        self.assertIn("AND NOT (d.tanggal >= ? AND d.tanggal <= ? AND d.tanggal_server IS NOT NULL", self.ARM)
        self.assertIn(f"AND NOT ({rpt._tidak_wajar('d.tanggal')})", self.ARM)

    def test_selisih_diukur_dari_tanggal_asal(self):
        self.assertIn("DATEDIFF(day, CAST(d.tanggal AS DATE), t.tanggal_asal) AS selisih_hari", self.ARM)

    def test_hanya_ada_kalau_log_siap(self):
        tanpa, _ = rpt.nota_mundur(_f())
        dengan, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertNotIn("m.nomor_baru", tanpa)
        self.assertIn("m.nomor_baru", dengan)


class JumlahArm(SimpleTestCase):
    def test_tanpa_log(self):
        sql, params = rpt.nota_mundur(_f())
        self.assertEqual(sql.count("UNION ALL"), 2 * len(rpt._DOK_MUNDUR) - 1)
        self.assertEqual(len(params), len(rpt._DOK_MUNDUR) * (PARAM_A + PARAM_C))

    def test_dengan_log(self):
        sql, params = rpt.nota_mundur(_f(log_siap=True))
        self.assertEqual(sql.count("UNION ALL"), 3 * len(rpt._DOK_MUNDUR) - 1)
        self.assertEqual(len(params), len(rpt._DOK_MUNDUR) * (PARAM_A + PARAM_C + PARAM_B))

    def test_tanda_tanya_sama_dengan_parameter(self):
        """Invarian paling murah yang menangkap parameter tergeser."""
        for kw in ({}, {"log_siap": True}, {"log_siap": True, "gudang": True},
                   {"log_siap": True, "search": "AB1", "kd_divisi": "DAA001", "penyebab": "Diedit"},
                   {"jenis": "Penjualan", "search": "X"}):
            sql, params = rpt.nota_mundur(_f(**kw))
            self.assertEqual(sql.count("?"), len(params), kw)


class JejakLog(SimpleTestCase):
    """Penyebab dibaca dari tbl_log_transaksi — semuanya soal ONGKOS."""

    def test_tanpa_index_log_tidak_disentuh(self):
        """Tanpa `log_siap`, tabel log tak boleh muncul sama sekali — dan
        pembuat TIDAK ditebak dari kd_user, yang justru sudah ditimpa pengedit.
        Tanggal tak wajar tetap terdeteksi: ia tak butuh log."""
        sql, _ = rpt.nota_mundur(_f())
        self.assertNotIn("tbl_log_transaksi", sql)
        self.assertIn("'Belum dicek'", sql)
        self.assertIn("'Tanggal tidak wajar'", sql)
        self.assertIn("CAST(NULL AS varchar(50)) AS dibuat_oleh", sql)

    def test_tiap_pencarian_seek_pada_aksi_dan_waktu(self):
        """Kunci index adalah (table_aksi, waktu)."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        pencarian = sql.split("OUTER APPLY (SELECT TOP 1")[1:]
        self.assertEqual(len(pencarian), 6)  # su, si, sp, a1, a2, a3
        for p in pencarian:
            self.assertRegex(p, r"l\.table_aksi = x\.aksi_(ins|upd) AND l\.waktu >= .+ AND l\.waktu < ")
            self.assertIn("ORDER BY l.waktu", p)
            # LIKE dengan nomor dokumen butuh escape `_`; LEFT/CHARINDEX tidak.
            self.assertNotIn("LIKE", p)

    def test_update_dicocokkan_lewat_nomor_sesudah_edit(self):
        """Edit yang mengganti nomor tercatat `key__<LAMA>; val__<BARU>`.
        Mencari `key__<nomor sekarang>` tak akan pernah menemukannya."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertIn("l.table_aksi = x.aksi_upd", sql)
        self.assertIn("CHARINDEX(x.kunci_val, l.formatted_data) > 0", sql)

    def test_pemindahan_dicari_walau_diedit_lagi_sesudahnya(self):
        """Nota yang dipindah lalu diedit biasa di hari lain: `su` = edit biasa
        itu. Pencarian `sp` mencari update yang MENGGANTI nomor — yang nomor
        sebelum-editnya bukan nomor sekarang — hanya untuk baris yang diedit."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertIn("WHERE su.id IS NOT NULL AND x.nomor_asal IS NULL AND l.table_aksi = x.aksi_upd", sql)
        self.assertIn("AND NOT (LEFT(l.formatted_data, LEN(x.awal_upd + x.no_dokumen + ';')) "
                      "= x.awal_upd + x.no_dokumen + ';')", sql)
        self.assertIn("ORDER BY l.waktu DESC) sp", sql)

    def test_pencarian_mahal_hanya_untuk_yang_membutuhkan(self):
        """Predikat yang hanya merujuk kolom luar jadi predikat startup: insert
        dicari hanya kalau tak ada update, pembuat asli hanya untuk yang diedit
        atau dipindah, jendela lebar hanya kalau jendela sempit kosong."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertIn("WHERE su.id IS NULL AND l.table_aksi = x.aksi_ins", sql)
        self.assertIn("WHERE ja.perlu = 1 AND l.table_aksi = x.aksi_ins", sql)
        self.assertIn("WHERE ja.perlu = 1 AND a1.fd IS NULL AND l.table_aksi = x.aksi_ins", sql)

    def test_pembuat_asli_dicari_dengan_nomor_asal(self):
        """Insert nota yang dipindah tercatat dengan nomor LAMA, dekat tanggal
        yang tersimpan di nomor lama itu."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertIn("x.awal_ins + COALESCE(na.nomor_asal, x.no_dokumen) + ';' AS kunci", sql)
        self.assertIn(f"CAST(COALESCE({rpt._tanggal_nomor('na.nomor_asal')}, x.tanggal) AS datetime) AS jangkar", sql)


class Lapis(SimpleTestCase):
    def test_pencarian_sesudah_rombongan_dihitung(self):
        """Mencari satu nomor tak boleh membuat rombongannya tinggal satu."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True, search="SC26", kd_divisi="DAA001"))
        self.assertLess(sql.index("OVER (PARTITION BY"), sql.index("b.no_dokumen LIKE ?"))
        self.assertLess(sql.index("OVER (PARTITION BY"), sql.index("b.kd_divisi = ?"))

    def test_jam_komputer_tak_dipakai_di_gudang(self):
        toko, _ = rpt.nota_mundur(_f(log_siap=True))
        gudang, _ = rpt.nota_mundur(_f(log_siap=True, gudang=True))
        self.assertIn("'Jam komputer salah'", toko)
        self.assertNotIn("'Jam komputer salah'", gudang)
        self.assertNotIn("AS n_serupa", gudang)

    def test_jam_komputer_hanya_penjualan_dan_ambangnya(self):
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertIn(f"WHEN x.jenis = 'Penjualan' AND x.n_serupa >= {rpt.JAM_KOMPUTER_MIN_NOTA} "
                      f"AND x.rentang_serupa >= {rpt.JAM_KOMPUTER_MIN_MENIT} THEN 'Jam komputer salah'", sql)
        # Label hanya di cabang "diinput" (si ditemukan), bukan untuk nota diedit.
        self.assertLess(sql.index("WHEN si.id IS NOT NULL THEN CASE"), sql.index("'Jam komputer salah'"))

    def test_rombongan_dihitung_di_bawah_pencarian_log(self):
        """Window di ATAS pencarian log membuat halaman `ORDER BY … FETCH 100`
        melonjak dari 0,17 dtk ke 51–116 dtk di grosirPusat. Ia harus duduk
        langsung di atas gabungan arm, sebelum OUTER APPLY pertama."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertLess(sql.index("COUNT(*) OVER (PARTITION BY x0."), sql.index("OUTER APPLY"))
        self.assertEqual(sql.count(" OVER (PARTITION BY x0."), 3)

    def test_geseran_menit_hanya_untuk_baris_wajar(self):
        """Tahun 7252 vs 2022 dalam menit melampaui int (galat 535)."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        self.assertIn("CASE WHEN x0.jenis = 'Penjualan' AND x0.nomor_asal IS NULL AND x0.tidak_wajar = 0 "
                      "THEN ROUND(DATEDIFF(minute, x0.tanggal, x0.tanggal_server) / 60.0, 0) END", sql)

    def test_arah_membedakan_maju_dari_mundur(self):
        sql, _ = rpt.nota_mundur(_f())
        self.assertIn("WHEN x.selisih_hari > 0 THEN 'Mundur'", sql)
        self.assertIn("WHEN x.selisih_hari < 0 THEN 'Maju'", sql)


class FilterJenis(SimpleTestCase):
    def test_memilih_jenis_membuang_arm_lain(self):
        """Bukan menyaring hasil UNION — tujuh tabel lain tak disentuh."""
        sql, params = rpt.nota_mundur(_f(jenis="Penjualan", log_siap=True))
        self.assertIn("FROM t_penjualan WHERE", sql)
        self.assertNotIn("t_pembelian", sql)
        self.assertEqual(sql.count("UNION ALL"), 2)
        self.assertEqual(len(params), PARAM_A + PARAM_C + PARAM_B)

    def test_jenis_tak_dikenal_tidak_mengosongkan_laporan(self):
        """Nilai nakal dari query string harus jatuh ke 'semua', bukan nol arm —
        laporan kosong tanpa sebab lebih menyesatkan daripada laporan penuh."""
        sql, _ = rpt.nota_mundur(_f(jenis="Bukan Jenis Apa Pun"))
        self.assertEqual(sql.count("UNION ALL"), 2 * len(rpt._DOK_MUNDUR) - 1)

    def test_jenis_yang_ditawarkan_sama_dengan_yang_diterima(self):
        """`JENIS_MUNDUR` mengisi dropdown; kalau ia menyimpang dari
        `_DOK_MUNDUR`, pengguna memilih nilai yang membuang semua arm."""
        self.assertEqual(rpt.JENIS_MUNDUR, [d[0] for d in rpt._DOK_MUNDUR])
        for j in rpt.JENIS_MUNDUR:
            sql, _ = rpt.nota_mundur(_f(jenis=j))
            self.assertEqual(sql.count("UNION ALL"), 1, f"{j} tak menyisakan tepat satu tabel")


class AmbangSelisih(SimpleTestCase):
    def test_bawaan_satu_hari(self):
        _, params = rpt.nota_mundur(_f(jenis="Penjualan"))
        self.assertEqual(params[2], 1)

    def test_ambang_dipakai_per_tabel(self):
        _, params = rpt.nota_mundur(_f(min_selisih=30))
        self.assertEqual(params[2::PARAM_A + PARAM_C], [30] * len(rpt._DOK_MUNDUR))

    def test_ambang_nakal_jatuh_ke_bawaan(self):
        for nakal in ("", None, "abc", 0, -5):
            _, params = rpt.nota_mundur(_f(min_selisih=nakal, jenis="Penjualan"))
            self.assertGreaterEqual(params[2], 1, f"{nakal!r} lolos jadi ambang tak sah")

    def test_ambang_dinilai_mutlak(self):
        """Ambang memakai ABS supaya dokumen bertanggal MAJU ikut lolos
        saringan; hanya nilai yang DIPAJANG yang bertanda."""
        sql, _ = rpt.nota_mundur(_f(min_selisih=7))
        self.assertIn(f"ABS({rpt._SELISIH}) >= ?", sql)


class UrutanParameter(SimpleTestCase):
    def test_param_arm_mendahului_param_luar(self):
        """Parameter harus urut sama dengan urutan `?` di teks SQL.

        Arm dulu (di dalam kurung), baru WHERE luar, baru penyebab. Tertukar =
        pencarian dibandingkan dengan tanggal, dan pyodbc tidak akan mengeluh.
        """
        sql, params = rpt.nota_mundur(_f(jenis="Penjualan", search="AB1", kd_divisi="DAA001",
                                         penyebab="Diedit", log_siap=True))
        self.assertEqual(params[:3], [_f()["date_from"], _f()["date_to"], 1])
        self.assertEqual(params[-2:], ["DAA001", "Diedit"])
        self.assertIn("%AB1%", params)
        self.assertLess(sql.index("FROM t_penjualan WHERE"), sql.index("b.kd_divisi = ?"))


class FilterPenyebab(SimpleTestCase):
    def test_penyebab_disaring_di_luar_dengan_parameter_terakhir(self):
        sql, params = rpt.nota_mundur(_f(log_siap=True, penyebab="Jam komputer salah", kd_divisi="DAA001"))
        self.assertTrue(sql.endswith("WHERE p.penyebab = ?"))
        self.assertEqual(params[-2:], ["DAA001", "Jam komputer salah"])

    def test_penyebab_tak_dikenal_diabaikan(self):
        sql, params = rpt.nota_mundur(_f(log_siap=True, penyebab="'; DROP TABLE x --"))
        self.assertNotIn("p.penyebab", sql)

    def test_pilihan_penyebab_sama_dengan_yang_dihasilkan_sql(self):
        """Dropdown diisi PENYEBAB_MUNDUR; nilai yang tak pernah dihasilkan SQL
        berarti pilihan yang selalu kosong."""
        sql, _ = rpt.nota_mundur(_f(log_siap=True))
        for p in rpt.PENYEBAB_MUNDUR:
            self.assertIn(f"'{p}'", sql)


class Tetangga(SimpleTestCase):
    def test_pola_dari_awalan_dan_tanggal(self):
        (sql, params), (sql_n, prm_n) = rpt.nota_mundur_tetangga("Penjualan", "SC2609170043")
        self.assertEqual(params, ["SC260917%", "SC2609170043", "SC2609170043", "SC260917%", "SC2609170043"])
        self.assertEqual(prm_n, ["SC260917%"])
        self.assertIn("GROUP BY no_transaksi", sql)

    def test_awalan_di_escape(self):
        (_, params), _ = rpt.nota_mundur_tetangga("Penjualan", "S_2609170043")
        self.assertEqual(params[0], "S[_]260917%")

    def test_nomor_tak_berbentuk_tanggal(self):
        self.assertIsNone(rpt.nota_mundur_tetangga("Penjualan", "ABC"))
        self.assertIsNone(rpt.nota_mundur_tetangga("Penjualan", "SC26091X0043"))


class EkspresiSql(TestCase):
    """Dijalankan di SQL Server sungguhan (pangkal uji), bukan dibaca teksnya:
    CHARINDEX/SUBSTRING yang meleset satu karakter tetap menghasilkan string
    yang tampak masuk akal."""

    def _nilai(self, ekspresi, nilai):
        with connection.cursor() as cur:
            cur.execute(f"SELECT {ekspresi} FROM (SELECT %s AS fd) p", [nilai])
            return cur.fetchone()[0]

    def test_kolom_log_nilai_di_tengah_dan_di_ujung(self):
        fd = "val__no_transaksi__SC1;val__kd_user__UAA009;val__divisi_id__DAA004"
        self.assertEqual(self._nilai(rpt.kolom_log("p.fd", "kd_user"), fd), "UAA009")
        self.assertEqual(self._nilai(rpt.kolom_log("p.fd", "divisi_id"), fd), "DAA004")

    def test_kolom_log_tak_ada_jadi_null(self):
        self.assertIsNone(self._nilai(rpt.kolom_log("p.fd", "kd_user"), "val__no_transaksi__SC1;val__keterangan__-"))

    def test_kolom_log_tak_tertukar_dengan_kolom_berakhiran_sama(self):
        """`;val__` di depan mencegah `x_kd_user` terbaca sebagai `kd_user`."""
        fd = "val__no_transaksi__SC1;val__x_kd_user__SALAH;val__kd_user__BENAR"
        self.assertEqual(self._nilai(rpt.kolom_log("p.fd", "kd_user"), fd), "BENAR")

    def test_tanggal_nomor(self):
        e = rpt._tanggal_nomor("p.fd")
        self.assertEqual(self._nilai(e, "ST2602080069"), dt.date(2026, 2, 8))
        # Nomor dari jam komputer rusak: tahun 7252 tersimpan sebagai "52".
        self.assertEqual(self._nilai(e, "AT5201090001"), dt.date(2052, 1, 9))
        self.assertIsNone(self._nilai(e, "SC2602300001"))  # 30 Februari
        self.assertIsNone(self._nilai(e, "X"))

    def test_nomor_lama_dari_payload_update(self):
        e = rpt._nomor_lama("p.fd", "'key__no_transaksi__'")
        fd = "key__no_transaksi__ST2602080069;val__no_transaksi__ST2609150023;val__kd_user__UAA001"
        self.assertEqual(self._nilai(e, fd), "ST2602080069")
        self.assertIsNone(self._nilai(e, "val__no_transaksi__ST2602080069;"))
        self.assertIsNone(self._nilai(e, "key__no_transaksi__"))  # tanpa ';': bukan galat 537

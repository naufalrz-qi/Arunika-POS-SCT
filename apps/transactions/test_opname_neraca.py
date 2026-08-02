"""Pembangun SQL Neraca Opname.

Diuji sebagai fungsi murni, tanpa MS SQL: yang bisa salah di sini bukan hasil
query-nya, melainkan bentuk SQL yang dihasilkan — dan tiga di antaranya pernah
benar-benar menggigit di laporan lain:

1. `grup` diinterpolasi ke SQL (GROUP BY tak bisa di-parameterize) sementara
   nilainya datang mentah dari query string. Whitelist-nya adalah batas injeksi.
2. Urutan params harus mengikuti urutan `?` di teks SQL; subquery bersarang
   membuat ini gampang tertukar dan gagalnya senyap (baris salah, bukan error).
3. Alias yang bisa di-sort harus benar-benar ada sebagai kolom keluaran, kalau
   tidak header-nya bisa diklik tapi diam-diam jatuh ke sort bawaan.
"""
from django.test import SimpleTestCase

from apps.transactions import reports as rpt


def buat_f(**ubah):
    """`f` minimal seperti yang dihasilkan reporting.parse_report_params."""
    f = {
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "search": "",
        "kd_divisi": "",
        "grup": "",
    }
    f.update(ubah)
    return f


class GrupWhitelistTests(SimpleTestCase):
    def test_nilai_dikenal_dipakai(self):
        for kunci, ekspresi in rpt.GRUP_NERACA.items():
            self.assertEqual(rpt._grup_neraca(buat_f(grup=kunci)), ekspresi)

    def test_kosong_jatuh_ke_bawaan(self):
        bawaan = rpt.GRUP_NERACA[rpt.GRUP_NERACA_DEFAULT]
        for nilai in ("", "   ", None):
            self.assertEqual(rpt._grup_neraca(buat_f(grup=nilai)), bawaan)

    def test_nilai_asing_tidak_pernah_masuk_sql(self):
        """Ini uji injeksi, bukan uji kerapian: f['grup'] disalin apa adanya dari
        query string oleh _spec_params, lalu diinterpolasi ke GROUP BY."""
        jahat = "b.nama FROM m_barang; DROP TABLE t_opname_stok --"
        self.assertEqual(
            rpt._grup_neraca(buat_f(grup=jahat)),
            rpt.GRUP_NERACA[rpt.GRUP_NERACA_DEFAULT],
        )
        inner, _ = rpt.opname_neraca(buat_f(grup=jahat))
        self.assertNotIn("DROP TABLE", inner)
        self.assertNotIn("--", inner)

    def test_bawaan_adalah_nama(self):
        """Dipilih atas dasar presisi, bukan recall. `kkm` menemukan pasangan di
        27-50% keluarga tapi satu keluarganya bisa berisi 139 barang — tak bisa
        ditindaklanjuti. `nama` menemukan jauh lebih sedikit, tapi yang ketemu
        langsung bisa dikerjakan (GSG102 +299 vs GSG042 -221, nama identik,
        diposting pada detik yang sama). Jangan balik tanpa mengukur ulang."""
        self.assertEqual(rpt.GRUP_NERACA_DEFAULT, "nama")


class ParamsTests(SimpleTestCase):
    def test_jumlah_placeholder_sama_dengan_params(self):
        for f in (
            buat_f(),
            buat_f(search="sisir"),
            buat_f(kd_divisi="DAA000"),
            buat_f(search="sisir", kd_divisi="DAA000", grup="nama"),
        ):
            inner, params = rpt.opname_neraca(f)
            self.assertEqual(inner.count("?"), len(params), msg=f"f={f}")

    def test_params_pencarian_di_akhir(self):
        """Teks subquery muncul sebelum WHERE terluar, jadi params periode harus
        mendahului params pencarian. Tertukar = baris salah tanpa error."""
        _, params = rpt.opname_neraca(buat_f(search="sisir"))
        self.assertEqual(params[0], "2025-01-01")
        self.assertEqual(params[1], "2025-12-31")
        self.assertTrue(all(p == "%sisir%" for p in params[2:]))

    def test_detail_menambah_nilai_grup_di_akhir(self):
        for fungsi in (rpt.opname_neraca_anggota, rpt.opname_neraca_kejadian):
            sql, params = fungsi(buat_f(), "KAA022|MAA705|MAA003")
            self.assertEqual(sql.count("?"), len(params), msg=fungsi.__name__)
            self.assertEqual(params[-1], "KAA022|MAA705|MAA003", msg=fungsi.__name__)


class KontrakInnerTests(SimpleTestCase):
    def test_tanpa_order_by_top_offset(self):
        """spec['inner'] harus polos; paging dan sorting ditambahkan reporting."""
        inner, _ = rpt.opname_neraca(buat_f())
        atas = inner.upper()
        for terlarang in ("ORDER BY", "OFFSET", "SELECT TOP"):
            self.assertNotIn(terlarang, atas)

    def test_semua_alias_sort_ada_di_keluaran(self):
        inner, _ = rpt.opname_neraca(buat_f())
        for param, alias in rpt.SORTS_OPNAME_NERACA.items():
            self.assertIn(
                f"AS {alias}",
                inner,
                msg=f"alias sort {param!r} -> {alias!r} tak ada di keluaran",
            )

    def test_kolom_export_ada_di_keluaran(self):
        """Export mengalirkan tuple, jadi kunci nyasar jadi kolom kosong senyap."""
        from apps.monitoring import views

        inner, _ = rpt.opname_neraca(buat_f())
        for kolom in views._OPNAME_NERACA["columns"]:
            self.assertIn(f"AS {kolom['key']}", inner, msg=f"kolom {kolom['key']!r}")

    def test_selisih_nol_dibuang(self):
        """Barang yang koreksinya sudah saling meniadakan bukan temuan."""
        inner, _ = rpt.opname_neraca(buat_f())
        self.assertIn("HAVING", inner.upper())
        self.assertIn("<> 0", inner)

    def test_arah_sama_dengan_mesin_pergerakan(self):
        """status=2 masuk, selain itu keluar — konvensi yang sama dengan
        _movement_sql dan laporan opname. Kalau menyimpang, total halaman ini
        tak bisa lagi dicocokkan dengan Opname Stok."""
        inner, _ = rpt.opname_neraca(buat_f())
        self.assertIn("h.status = 2 THEN h.qty ELSE -h.qty", inner)


class SummaryTests(SimpleTestCase):
    def test_bruto_dan_neto_keduanya_ada(self):
        """Alasan laporan ini ada: SUM bertanda menyembunyikan sesi yang plus dan
        minusnya saling meniadakan."""
        for kunci in ("total_lebih", "total_kurang", "total_terpasang", "total_neto"):
            self.assertIn(kunci, rpt.SUMMARY_OPNAME_NERACA)

    def test_summary_opname_lama_juga_membawa_bruto(self):
        for kunci in ("total_masuk", "total_keluar", "total_diferensi"):
            self.assertIn(kunci, rpt.SUMMARY_OPNAME)

    def test_alias_summary_cocok_dengan_keluaran_inner(self):
        """SUMMARY dijalankan sebagai SELECT ... FROM (inner) AS q, jadi setiap
        q.<kolom> yang dirujuknya harus benar-benar ada di inner."""
        import re

        inner, _ = rpt.opname_neraca(buat_f())
        for kolom in set(re.findall(r"\bq\.(\w+)", rpt.SUMMARY_OPNAME_NERACA)):
            self.assertIn(f"AS {kolom}", inner, msg=f"summary merujuk q.{kolom}")


class SatuanDanUangTests(SimpleTestCase):
    def test_qty_dinormalkan_ke_satuan_dasar(self):
        """t_opname_stok mencatat qty dalam kd_satuan-nya sendiri, dan opname
        nyata memakai beberapa satuan. Tanpa konversi, `terpasang` bisa mengklaim
        3 lusin menutup 3 pcs."""
        inner, _ = rpt.opname_neraca(buat_f())
        self.assertIn("COALESCE(sat.isi, 1)", inner)
        self.assertIn("m_barang_satuan", inner)

    def test_join_harga_tak_bisa_menggandakan_baris(self):
        """Join harga harus lewat subquery ber-GROUP BY. Penggandaan diam-diam
        di sini melipatkan setiap selisih, dan tak ada yang error."""
        inner, _ = rpt.opname_neraca(buat_f())
        self.assertIn("GROUP BY kd_barang) hj", inner)
        self.assertIn("GROUP BY kd_barang, kd_satuan) sat", inner)

    def test_setiap_field_uang_terdaftar_di_peta_izin(self):
        """money_fields hanya berefek lewat IRISAN dengan _hidden_fields(). Field
        yang tak terdaftar di peta membuat irisannya kosong — pembatasannya jadi
        hiasan, dan halaman tetap memamerkan rupiah."""
        from apps.monitoring import views

        peta = set()
        for nama_field in views._FIELDS_BY_DATA_KEY.values():
            peta |= nama_field
        for field in rpt.UANG_OPNAME_NERACA:
            self.assertIn(field, peta, msg=f"{field!r} tak terdaftar di _FIELDS_BY_DATA_KEY")

    def test_spec_mendaftarkan_money_fields(self):
        from apps.monitoring import views

        self.assertEqual(
            views._OPNAME_NERACA.get("money_fields"), rpt.UANG_OPNAME_NERACA
        )

    def test_field_uang_rute_detail_juga_terdaftar(self):
        """Rute ketiga (detail JSON) menyajikan rupiah yang sama; namanya sengaja
        dipilih agar tercakup peta yang sudah ada."""
        from apps.monitoring import views

        sql, _ = rpt.opname_neraca_anggota(buat_f(), "X")
        peta = views._FIELDS_BY_DATA_KEY["nominal"] | views._FIELDS_BY_DATA_KEY["harga_jual"]
        for field in ("harga_jual", "nilai"):
            self.assertIn(f"AS {field}", sql)
            self.assertIn(field, peta)


class OpnameLamaTests(SimpleTestCase):
    def test_alias_menyesatkan_sudah_hilang(self):
        """qty_sistem/qty_fisik: salah satunya selalu 0, tak satu pun saldo stok."""
        inner, _ = rpt.opname(buat_f())
        self.assertNotIn("qty_sistem", inner)
        self.assertNotIn("qty_fisik", inner)
        self.assertIn("AS koreksi_masuk", inner)
        self.assertIn("AS koreksi_keluar", inner)

    def test_pencarian_mencakup_no_transaksi(self):
        """Placeholder-nya menjanjikan 'no opname'; sebelumnya tak dicari."""
        inner, params = rpt.opname(buat_f(search="ST26"))
        self.assertIn("h.no_transaksi LIKE ?", inner)
        self.assertEqual(inner.count("?"), len(params))

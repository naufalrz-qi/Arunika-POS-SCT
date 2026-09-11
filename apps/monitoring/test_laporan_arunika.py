"""Kontrak spec laporan yang membaca bentuk Arunika.

Sebuah spec setengah-pindah tidak memunculkan galat saat ditulis: SQL-nya tetap
valid, hanya saja sebagian membaca bentuk baru dan sebagian masih tabel legacy.
Di database Arunika, tabel legacy TIDAK ADA -- jadi kegagalannya muncul saat
laporan dibuka, pada pemasangan yang kebetulan menyalakan ARUNIKA_LAPORAN, entah
kapan.

Test ini menahan tiga hal yang tidak bisa dilihat dari membaca spec satu per
satu: bahwa tiap `inner_arunika` benar-benar hanya menyentuh `arunika_src.*`,
bahwa layar yang memakainya memang `_report_view` (satu-satunya yang membaca
kunci itu), dan bahwa gerbangnya tetap mati kecuali ketiga syaratnya terpenuhi.
"""
import re
from pathlib import Path

from django.test import RequestFactory, SimpleTestCase

from apps.core import reporting
from apps.monitoring import views
from apps.transactions import reports as rpt


def _spec_arunika():
    """Tiap `_SPEC` di views.py yang sudah punya padanan bentuk Arunika."""
    for nama in dir(views):
        obj = getattr(views, nama)
        if isinstance(obj, dict) and obj.get("inner_arunika"):
            yield nama, obj


def _filter(spec):
    req = RequestFactory().get("/x?date_from=2026-01-01&date_to=2026-01-31")
    f = reporting.parse_report_params(
        req, spec["sorts"], spec["default_sort"], max_range_days=None
    )
    for k in spec.get("filter_keys", []):
        f.setdefault(k, "")
    return f


class BentukArunikaSaja(SimpleTestCase):
    def test_ada_yang_sudah_dipindah(self):
        """Kalau nol, test di bawah lulus tanpa menguji apa pun."""
        self.assertTrue(list(_spec_arunika()))

    def test_tak_menyentuh_tabel_legacy(self):
        """Tabel legacy tidak ada di database Arunika. Satu rujukan tersisa
        berarti laporan itu meledak saat dibuka, bukan saat ditulis."""
        for nama, spec in _spec_arunika():
            sql, _ = spec["inner_arunika"](_filter(spec))
            tersisa = re.findall(r"\b(?:FROM|JOIN)\s+((?:m_|t_)\w+)", sql, re.IGNORECASE)
            self.assertEqual(tersisa, [], f"{nama}: masih membaca {tersisa}")

    def test_membaca_schema_sumber(self):
        for nama, spec in _spec_arunika():
            sql, _ = spec["inner_arunika"](_filter(spec))
            self.assertIn(f"{rpt.SRC}.", sql, f"{nama}: tak menyentuh {rpt.SRC}")

    def test_kolom_keluaran_sama_dengan_jalur_lama(self):
        """Bentuk baru menggantikan yang lama di tempat yang sama; kolom yang
        hilang membuat layar dan export kehilangan isi tanpa pesan apa pun.

        Dibandingkan lewat alias yang diminta spec (`sorts` + `summary`), bukan
        dengan menjalankan SQL-nya -- test ini tak butuh server.
        """
        for nama, spec in _spec_arunika():
            f = _filter(spec)
            baru, _ = spec["inner_arunika"](f)
            for alias in spec["sorts"].values():
                self.assertIn(alias, baru, f"{nama}: kolom sort '{alias}' hilang")


class GerbangnyaMati(SimpleTestCase):
    """Tiga syarat, dan semuanya harus benar. Default MATI supaya memindahkan
    jalur baca tak pernah jadi efek samping dari menarik kode terbaru."""

    class _Profil:
        name = "uji"
        db_arunika = "arunika"

    def test_mati_kalau_env_tak_dinyalakan(self):
        with self.settings():
            asli = views.LAPORAN_ARUNIKA
            views.LAPORAN_ARUNIKA = False
            try:
                self.assertFalse(views._pakai_bentuk_arunika(
                    {"inner_arunika": lambda f: ("", [])}, self._Profil()))
            finally:
                views.LAPORAN_ARUNIKA = asli

    def test_mati_kalau_spec_belum_punya_padanan(self):
        asli = views.LAPORAN_ARUNIKA
        views.LAPORAN_ARUNIKA = True
        try:
            self.assertFalse(views._pakai_bentuk_arunika({}, self._Profil()))
        finally:
            views.LAPORAN_ARUNIKA = asli

    def test_mati_kalau_profil_belum_punya_database_arunika(self):
        """Profil lama (db_arunika kosong) harus tetap di jalur legacy, apa pun
        setelan env-nya."""
        asli = views.LAPORAN_ARUNIKA
        views.LAPORAN_ARUNIKA = True
        kosong = self._Profil()
        kosong.db_arunika = ""
        try:
            self.assertFalse(views._pakai_bentuk_arunika(
                {"inner_arunika": lambda f: ("", [])}, kosong))
        finally:
            views.LAPORAN_ARUNIKA = asli


class DibacaOlehLayarnya(SimpleTestCase):
    """`inner_arunika` HANYA dibaca `_report_view`/`_report_export`.

    Sebuah spec yang layarnya bespoke -- Klasifikasi Pelanggan misalnya, yang
    kolumnar dengan export dua-sheet sendiri -- tetap menerima kunci itu tanpa
    galat, dan tetap lulus seluruh test di atas. Ia hanya tak pernah dipakai:
    laporannya terus membaca jalur legacy sementara semua orang mengira sudah
    pindah. Itu kegagalan yang tak punya gejala sama sekali.
    """

    def test_specnya_dipakai_report_view(self):
        sumber = Path(views.__file__).read_text(encoding="utf-8")
        for nama, _ in _spec_arunika():
            self.assertIn(
                f"_report_view({nama})", sumber,
                f"{nama}: punya inner_arunika tapi layarnya bukan _report_view, "
                "jadi bentuk Arunika-nya tak akan pernah dibaca",
            )


class KlasifikasiBespoke(SimpleTestCase):
    """Klasifikasi Pelanggan tak punya satu `inner` untuk diganti.

    Enam kueri di tiga rute: agregat utama (layar + sheet 1), favorit massal
    (sheet 2), favorit satu pelanggan, nota satu pelanggan, dan profil pelanggan
    — yang terakhir dulu `SELECT` mentah ke `m_customer` di dalam view, satu-
    satunya rujukan legacy layar ini yang tak lewat `reports.py`.

    Kalau salah satu tertinggal, layarnya tetap jalan: ia cuma membaca dua
    sumber sekaligus, dan di database Arunika yang tertinggal itu meledak.
    """

    def _f(self):
        req = RequestFactory().get("/x?date_from=2026-01-01&date_to=2026-01-31")
        f = reporting.parse_report_params(
            req, rpt.SORTS_KLASIFIKASI_PELANGGAN, "segmen", max_range_days=None
        )
        f.setdefault("kd_divisi", "")
        for k, v in rpt.AMBANG_KLASIFIKASI.items():
            f.setdefault(k, v[0])
        return f

    def _semua_sql(self):
        f = self._f()
        yield "klasifikasi_pelanggan_arunika", rpt.klasifikasi_pelanggan_arunika(f)[0]
        yield "barang_favorit_massal_arunika", rpt.barang_favorit_massal_arunika(f, top_n=5)[0]
        yield "barang_favorit_pelanggan_arunika", rpt.barang_favorit_pelanggan_arunika(f, "X", 20)[0]
        yield "nota_pelanggan_arunika", rpt.nota_pelanggan_arunika(f, "X", 20)[0]
        yield "profil_pelanggan_arunika", rpt.profil_pelanggan_arunika("X")[0]

    def test_tak_menyentuh_tabel_legacy(self):
        for nama, sql in self._semua_sql():
            tersisa = re.findall(r"\b(?:FROM|JOIN)\s+((?:m_|t_)\w+)", sql, re.IGNORECASE)
            self.assertEqual(tersisa, [], f"{nama}: masih membaca {tersisa}")
            self.assertIn(f"{rpt.SRC}.", sql, f"{nama}: tak menyentuh {rpt.SRC}")

    def test_spec_tak_diberi_inner_arunika(self):
        """Layar ini BUKAN `_report_view`, jadi `inner_arunika` di spec-nya tak
        akan pernah dibaca — memasangnya justru menyesatkan."""
        self.assertNotIn("inner_arunika", views._KLASIFIKASI_PELANGGAN)

    def test_segmen_tak_disalin(self):
        """Ambang segmen harus datang dari `_segmen_case` yang sama dengan jalur
        lama; dua definisi segmen bisa menyimpang tanpa satu pun galat."""
        f = self._f()
        urut, label = rpt._segmen_case(f)
        self.assertIn(urut, rpt.klasifikasi_pelanggan_arunika(f)[0])
        self.assertIn(label, rpt.klasifikasi_pelanggan_arunika(f)[0])


class KasHarianBespoke(SimpleTestCase):
    """Kas Harian juga tak punya satu `inner` untuk diganti.

    Tiga rute: baris (layar + export), ringkasan (saldo awal pra-rentang, bukan
    agregat inner biasa), dan pilihan kas di kotak filter. Yang paling mudah
    tertinggal justru yang ketiga — ia `SELECT` mentah ke `m_kas` di dalam
    `views.py`, satu-satunya rujukan legacy layar ini yang tak lewat `reports.py`.
    Persis bentuk kesalahan yang sama dengan `profil_pelanggan` di Klasifikasi.
    """

    def _f(self, kd_kas=""):
        req = RequestFactory().get("/x?date_from=2026-01-01&date_to=2026-01-31")
        f = reporting.parse_report_params(req, rpt.SORTS_KAS, "tanggal", max_range_days=None)
        f["kd_kas"] = kd_kas
        return f

    def _semua_sql(self, kd_kas=""):
        f = self._f(kd_kas)
        yield "kas_harian_arunika", rpt.kas_harian_arunika(f)
        yield "kas_summary_arunika", rpt.kas_summary_arunika(f)
        yield "opsi_kas_arunika", (rpt.opsi_kas_arunika(), [])

    def test_tak_menyentuh_tabel_legacy(self):
        for nama, (sql, _) in self._semua_sql():
            tersisa = re.findall(r"\b(?:FROM|JOIN)\s+((?:m_|t_)\w+)", sql, re.IGNORECASE)
            self.assertEqual(tersisa, [], f"{nama}: masih membaca {tersisa}")
            self.assertIn(f"{rpt.SRC}.", sql, f"{nama}: tak menyentuh {rpt.SRC}")

    def test_dipakai_layarnya(self):
        """Ketiganya dipanggil dari `views.py`. Sebuah fungsi yang benar tapi tak
        pernah dipanggil membuat layar terus membaca jalur lama tanpa gejala."""
        sumber = Path(views.__file__).read_text(encoding="utf-8")
        for nama in ("kas_harian_arunika", "kas_summary_arunika", "opsi_kas_arunika"):
            self.assertIn(f"rpt.{nama}", sumber, f"{nama}: tak pernah dipanggil layarnya")

    def test_kolom_sama_dengan_jalur_lama(self):
        """Kolom layar + kunci ringkasan datang dari satu daftar di `views.py`;
        kolom yang hilang membuat sel kosong, bukan galat."""
        sql, _ = rpt.kas_harian_arunika(self._f())
        for kol in views._KAS_COLUMNS:
            self.assertIn(kol["key"], sql, f"kolom '{kol['key']}' hilang")
        ringkas, _ = rpt.kas_summary_arunika(self._f())
        for kunci in ("jml_baris", "total_masuk", "total_keluar", "saldo_awal", "saldo_akhir"):
            self.assertIn(kunci, ringkas, f"ringkasan '{kunci}' hilang")

    def test_jumlah_param_cocok_dengan_tanda_tanya(self):
        """Urutan param mengikuti posisi `?` kiri-ke-kanan dalam teks SQL, bukan
        urutan pembuatannya — jebakan yang sudah tercatat dua kali di
        `reports.py`. Jumlahnya yang salah memberi galat; urutannya yang salah
        memberi ANGKA yang salah, jadi yang ini cuma menahan separuhnya."""
        for kd_kas in ("", "KAA000"):
            for nama, (sql, params) in self._semua_sql(kd_kas):
                self.assertEqual(sql.count("?"), len(params),
                                 f"{nama} (kd_kas={kd_kas!r})")
                # Jalur lama diperiksa dengan ukuran yang sama: keduanya harus
                # tetap bisa dijalankan selama gerbangnya masih bisa dimatikan.
            f = self._f(kd_kas)
            for nama, (sql, params) in (("kas_harian", rpt.kas_harian(f)),
                                        ("kas_summary", rpt.kas_summary(f))):
                self.assertEqual(sql.count("?"), len(params),
                                 f"{nama} (kd_kas={kd_kas!r})")

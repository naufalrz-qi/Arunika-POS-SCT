"""Kontrak spec laporan yang membaca bentuk Arunika.

Sebuah spec setengah-pindah tidak memunculkan galat saat ditulis: SQL-nya tetap
valid, hanya saja sebagian membaca bentuk baru dan sebagian masih tabel legacy.
Di database Arunika, tabel legacy TIDAK ADA -- jadi kegagalannya muncul saat
laporan dibuka, pada pemasangan yang kebetulan menyalakan ARUNIKA_LAPORAN, entah
kapan.

Test ini menahan dua hal yang tidak bisa dilihat dari membaca spec satu per
satu: bahwa tiap `inner_arunika` benar-benar hanya menyentuh `arunika_src.*`,
dan bahwa gerbangnya tetap mati kecuali ketiga syaratnya terpenuhi.
"""
import re

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

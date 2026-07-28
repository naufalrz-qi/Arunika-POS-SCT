"""Kontrak sort: whitelist ORDER BY server = daftar kolom yang bisa diklik di layar.

Sebelum ini tiap halaman Vue menandai sendiri kolom mana yang `sortable`, dan
daftarnya menyimpang dari `SORTS_*` di backend: header yang bisa diklik tapi
tak mengubah apa pun (sort tak dikenal diam-diam jatuh ke default), dan kolom
yang sebenarnya bisa diurut tapi tak pernah ditawarkan. Sekarang layar memakai
`filters.sort_keys` dari server, jadi yang perlu dijaga cuma: whitelist itu
benar-benar sampai ke props.
"""
from django.test import RequestFactory, SimpleTestCase

from apps.core import reporting
from apps.monitoring import views


class ParseReportParamsSortKeys(SimpleTestCase):
    SORTS = {"tanggal": "tanggal", "nominal": "nominal"}

    def _f(self, query=""):
        return reporting.parse_report_params(
            RequestFactory().get(f"/x?{query}"), self.SORTS, "tanggal",
        )

    def test_sort_keys_is_the_whitelist(self):
        self.assertEqual(sorted(self._f()["sort_keys"]), ["nominal", "tanggal"])

    def test_unknown_sort_falls_back_to_default(self):
        f = self._f("sort=drop_table&sort_dir=asc")
        self.assertEqual(f["sort"], "tanggal")
        self.assertEqual(f["order_by"], "q.tanggal ASC")

    def test_known_sort_is_honoured(self):
        self.assertEqual(self._f("sort=nominal")["order_by"], "q.nominal DESC")


class SpecFiltersCarrySortKeys(SimpleTestCase):
    """Tiap spec _report_view harus mengirim sort_keys ke frontend — kalau tidak,
    seluruh header tabel halaman itu berhenti bisa diurut tanpa suara."""

    def test_every_report_spec(self):
        specs = [
            (name, s) for name, s in vars(views).items()
            if isinstance(s, dict) and "sorts" in s and "component" in s
        ]
        self.assertGreater(len(specs), 10, "spec laporan tak terdeteksi — cek introspeksi")
        for name, spec in specs:
            with self.subTest(spec=name):
                f = views._spec_params(RequestFactory().get(spec["url"]), spec)
                filters = views._spec_filters(f, spec)
                self.assertEqual(sorted(filters["sort_keys"]), sorted(spec["sorts"]))
                # default_sort harus ada di whitelist, atau setiap permintaan
                # jatuh ke ORDER BY yang tak pernah diminta siapa pun.
                self.assertIn(spec["default_sort"], spec["sorts"])

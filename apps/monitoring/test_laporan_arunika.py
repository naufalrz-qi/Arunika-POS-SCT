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

from pathlib import Path

from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.core import reporting
from apps.monitoring import views
from apps.transactions import reports as rpt


def _spec_arunika():
    """Tiap `_SPEC` di views.py yang sudah punya padanan bentuk Arunika."""
    for nama in dir(views):
        obj = getattr(views, nama)
        if isinstance(obj, dict) and obj.get("inner_arunika"):
            yield nama, obj


def _select_terluar(sql: str) -> str:
    """Potong daftar SELECT terluar: dari `SELECT` pertama sampai `FROM` yang
    sepadan dengannya (kedalaman kurung nol).

    Yang menentukan nama kolom keluaran hanya bagian ini. Sisa SQL-nya penuh
    kecocokan palsu -- nama tabel, alias join, kolom di WHERE -- dan itu bukan
    kekhawatiran teoretis: versi pertama test pemanggilnya mencari di seluruh
    teks dan lolos saat alias `kota` sengaja dirusak, karena `arunika_src.kota`
    masih tertulis di klausa JOIN.
    """
    m = re.search(r"\bSELECT\b", sql, re.IGNORECASE)
    if not m:
        return ""
    i, dalam = m.end(), 0
    while i < len(sql):
        c = sql[i]
        if c == "(":
            dalam += 1
        elif c == ")":
            dalam -= 1
        elif dalam == 0 and sql.startswith("FROM", i) and re.match(r"FROM\b", sql[i:], re.I):
            return sql[m.end():i]
        i += 1
    return sql[m.end():]


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

    def test_kolom_pajangan_dan_penyaring_ikut_ada(self):
        """`sorts` saja tidak cukup, dan celahnya beda gejala untuk masing-masing.

        Kolom yang cuma ada di `columns` hilang tanpa suara: selnya kosong, dan
        tak satu pun test lama merah. Kolom yang cuma ada di `filters` lebih
        buruk -- `_report_view` menyusun `WHERE <alias> ...` dari nilainya, jadi
        aliasnya yang absen membuat laporan MELEDAK, tapi hanya ketika seseorang
        benar-benar mengetik di kotak filter itu.

        ## Kenapa hanya daftar SELECT terluar yang diperiksa

        Versi pertama test ini mencari nama kolom di SELURUH teks SQL dan karena
        itu **tidak menggigit sama sekali**: diuji dengan sengaja mengganti alias
        `kota` jadi `kotaXX` di Penjualan per Nota, dan ia tetap hijau -- sebab
        kata `kota` masih muncul sebagai NAMA TABEL di
        `JOIN arunika_src.kota kt`. Nama tabel, alias join, dan predikat WHERE
        semuanya memberi kecocokan palsu.

        Yang menentukan keluaran hanyalah daftar SELECT terluar, jadi itu yang
        dipotong (`_select_terluar`) sebelum dicocokkan.
        """
        for nama, spec in _spec_arunika():
            sql, _ = spec["inner_arunika"](_filter(spec))
            keluaran = _select_terluar(sql)
            # `SELECT g.*` (FMI Penjualan) menurunkan kolomnya dari subquery,
            # jadi daftar terluar tak bisa menjawab apa-apa. Turun ke pencarian
            # seluruh teks di kasus itu -- lebih lemah, dan memang begitu:
            # tanpa menjalankan SQL-nya, bintang tak bisa dipecahkan.
            berbintang = "*" in keluaran
            ruang = sql if berbintang else keluaran

            def ada(kol):
                if berbintang:
                    return re.search(r"\b" + re.escape(kol) + r"\b", ruang) is not None
                # `]?` wajib: alias yang bertabrakan dengan kata terpesan ditulis
                # berkurung siku -- `AS [user]` di Penjualan per User.
                pola = r"\b" + re.escape(kol) + r"\]?\s*(?:,|$)"
                return re.search(pola, ruang) is not None

            for kol in spec.get("columns", []):
                self.assertTrue(ada(kol["key"]),
                                f"{nama}: kolom layar '{kol['key']}' tak ada di SELECT terluar")
            for nilai in (spec.get("filters") or {}).values():
                alias = nilai[0] if isinstance(nilai, (tuple, list)) else nilai
                self.assertTrue(ada(alias),
                                f"{nama}: kolom penyaring '{alias}' tak ada di SELECT terluar")


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

    def test_specnya_dipakai_report_view_dan_report_export(self):
        """DUA-duanya, bukan cuma layarnya.

        Versi pertama test ini hanya memeriksa `_report_view`, dan justru itu
        yang membuat bug-nya hidup: `_report_export` memakai `spec["inner"]`
        tanpa syarat selama berbulan-bulan, sehingga dengan ARUNIKA_LAPORAN=1
        layar membaca Arunika dan tombol Excel di layar yang sama membaca
        legacy. Pemeriksaan struktural ini membuktikan spec-nya TERPASANG di
        kedua jalur; `SumberLayarDanExportSama` di bawah membuktikan keduanya
        benar-benar membuka cursor yang sama.
        """
        sumber = Path(views.__file__).read_text(encoding="utf-8")
        for nama, _ in _spec_arunika():
            self.assertIn(
                f"_report_view({nama})", sumber,
                f"{nama}: punya inner_arunika tapi layarnya bukan _report_view, "
                "jadi bentuk Arunika-nya tak akan pernah dibaca",
            )
            self.assertIn(
                f"_report_export({nama})", sumber,
                f"{nama}: layarnya pindah ke Arunika tapi export-nya tidak, "
                "jadi Excel dan layar akan menyajikan angka dari sumber berbeda",
            )

    def test_report_export_memilih_bentuknya_seperti_report_view(self):
        """Jaring kedua yang murah, untuk saat monkeypatch di bawah rusak sendiri."""
        import inspect

        src = inspect.getsource(views._report_export)
        self.assertIn("_pakai_bentuk_arunika", src)
        self.assertIn("inner_arunika", src)
        self.assertIn("arunika_cursor", src)


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


class SumberLayarDanExportSama(TestCase):
    """Layar dan Excel WAJIB membaca sumber yang sama.

    Ini test yang seharusnya ada sejak awal. Yang lama mengikis TEKS `views.py`
    dan hijau selama berbulan-bulan sementara `_report_export` membaca legacy
    dan layarnya membaca Arunika — dua angka berbeda untuk satu pertanyaan,
    tanpa galat, tanpa tanda apa pun. Yang diperiksa di sini bukan teksnya,
    melainkan CURSOR MANA yang benar-benar dibuka, lewat HTTP sungguhan.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model

        from apps.connections.models import ServerProfile

        self.profil = ServerProfile.objects.create(
            name="UJI", host="h", db_name="SOLID_SIM", username="u",
            db_arunika="arunika_uji", is_default=True,
        )
        U = get_user_model()
        self.sa = U.objects.create_user(username="sa", password="x", role="superadmin")
        self.client.force_login(self.sa)

    class _Kursor:
        """Cukup untuk run_paged/one_row/xlsx_stream_response, tak lebih."""

        description = []

        def execute(self, sql, params=None):
            return self

        def fetchall(self):
            return []

        def fetchone(self):
            return None

        def fetchmany(self, size=None):
            # Dipakai jalur streaming XLSX (`reporting.xlsx_stream_response`).
            # Kosong = habis, jadi loopnya berhenti di iterasi pertama.
            return []

        def __iter__(self):
            return iter(())

    def _jalankan(self, nyalakan: bool):
        """Kembalikan (dipakai_layar, dipakai_export) sebagai himpunan nama cursor."""
        import contextlib
        from unittest.mock import patch

        dipakai = {"layar": set(), "export": set()}
        fase = {"kini": "layar"}

        def perekam(nama):
            @contextlib.contextmanager
            def buka(profile, *a, **kw):
                dipakai[fase["kini"]].add(nama)
                yield SumberLayarDanExportSama._Kursor()
            return buka

        asli = views.LAPORAN_ARUNIKA
        views.LAPORAN_ARUNIKA = nyalakan
        try:
            # Pilihan dropdown divisi (`inv.list_divisi`) membaca master legacy
            # lewat `report_cursor`, DENGAN SENGAJA: master divisi tak punya
            # kembaran Arunika. Hasilnya dicache per profil, jadi laporan mana
            # yang kebetulan mengisi cache duluan berpindah-pindah mengikuti
            # urutan test — dan laporan itu lalu terlihat "membaca legacy".
            # Yang dijaga test ini BADAN laporannya, jadi pemuat pilihan
            # dimatikan alih-alih ikut terekam.
            with patch.object(views, "_opt_divisi", lambda p: []), \
                 patch.object(views.mssql, "arunika_cursor", perekam("arunika")), \
                 patch.object(views.mssql, "report_cursor", perekam("legacy")):
                for nama, spec in _spec_arunika():
                    fase["kini"] = "layar"
                    self.client.get(
                        spec["url"],
                        HTTP_X_INERTIA="true",
                        HTTP_X_INERTIA_PARTIAL_DATA="report",
                        HTTP_X_INERTIA_PARTIAL_COMPONENT=spec["component"],
                    )
                    fase["kini"] = "export"
                    self.client.get(spec["url"] + "/export")
        finally:
            views.LAPORAN_ARUNIKA = asli
        return dipakai["layar"], dipakai["export"]

    def test_gerbang_menyala_keduanya_baca_arunika(self):
        layar, export = self._jalankan(True)
        self.assertEqual(layar, {"arunika"}, "layar tidak membaca Arunika")
        self.assertEqual(
            export, {"arunika"},
            "export membaca sumber lain dari layarnya — ini bug yang sama persis "
            "seperti yang pernah lolos berbulan-bulan",
        )

    def test_gerbang_mati_keduanya_baca_legacy(self):
        layar, export = self._jalankan(False)
        self.assertEqual(layar, {"legacy"})
        self.assertEqual(export, {"legacy"})


class PetaKembaranTerdaftar(SimpleTestCase):
    """Peta "laporan mana yang sudah pindah" di KESIAPAN-FITUR.md harus benar.

    Daftar semacam itu sudah pernah basi sekali: §7.13 rancangan masih
    mendaftar Master Produk sebagai sisa berbulan-bulan sesudah kembarannya
    terpasang, dan tak ada yang tahu sampai seseorang bertanya. Daftar yang
    tidak diperiksa apa pun akan selalu berakhir begitu — jadi yang ini
    dihitung ulang dari `views.py` setiap kali test jalan.
    """

    # Layar yang pindah lewat `_arunika_siap`, bukan `inner_arunika`: keduanya
    # tak punya satu `inner` untuk ditukar (export dua sheet + panel detail),
    # jadi spec-nya sengaja tanpa kunci itu — lihat KlasifikasiBespoke di atas.
    LEWAT_BESPOKE = {"Klasifikasi Pelanggan"}

    def _bagian_peta(self) -> str:
        from django.conf import settings

        teks = (Path(settings.BASE_DIR) / "KESIAPAN-FITUR.md").read_text(encoding="utf-8")
        awal = teks.index("## Kembaran Arunika per laporan")
        return teks[awal : teks.index("\n## ", awal + 10)]

    def _label_per_spec(self) -> list[tuple[str, bool]]:
        from apps.core.menus import ALL_MENUS

        label = {m["href"]: m["label"] for m in ALL_MENUS}
        keluar = []
        for nama in dir(views):
            o = getattr(views, nama)
            if isinstance(o, dict) and o.get("inner") and o.get("url") in label:
                keluar.append((label[o["url"]], bool(o.get("inner_arunika"))))
        return keluar

    def test_setiap_laporan_ada_di_peta_dan_di_sisi_yang_benar(self):
        bagian = self._bagian_peta()
        # Tabel "belum" dimulai di baris header-nya; apa pun sesudah itu = belum.
        potong = bagian.index("| Laporan | Hambatan |")
        sudah, belum = bagian[:potong], bagian[potong:]

        spec = self._label_per_spec()
        self.assertGreaterEqual(len(spec), 20, "penghitung spec nyaris tak menemukan apa pun")

        salah = []
        for nama, punya_kembaran in spec:
            pindah = punya_kembaran or nama in self.LEWAT_BESPOKE
            tujuan, lawan = (sudah, belum) if pindah else (belum, sudah)
            if nama not in tujuan:
                salah.append(
                    f"{nama}: {'sudah' if pindah else 'belum'} punya kembaran, "
                    + ("tercatat di sisi sebaliknya" if nama in lawan else "tak ada di peta"))
        self.assertEqual(salah, [], "KESIAPAN-FITUR.md § Kembaran Arunika tidak sesuai kode")

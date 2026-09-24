"""Regresi konkret: layar yang dulu membocorkan rupiah kini tidak lagi.

Melengkapi `test_hidden_data.KolomRupiahTerdaftar`, yang menjaga kebijakannya
secara umum (setiap kolom berformat rupiah harus punya nama terdaftar). Yang
dijaga DI SINI adalah kasus yang benar-benar pernah bocor, disebut per layar per
kolom — supaya kalau suatu hari penyaringnya dicabut, kegagalannya menyebut
layar mana yang jebol, bukan sekadar "ada nama yang hilang".

Piutang Pelanggan adalah alasan berkas ini ada: ia mengirim `total_penjualan`,
`total_cicilan`, dan `sisa_piutang` ke akun yang izin nominalnya sudah dicabut,
dan baru ketahuan ketika Hutang Supplier — cerminannya, persis di bawahnya di
`views.py` — ternyata sudah menutupnya.
"""
import datetime as dt
import json
import pathlib
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.monitoring import views as v

# url laporan spec-driven -> kolom yang WAJIB hilang bagi akun tanpa izin uang.
BOCOR_DULU = {
    "/admin-panel/laporan/piutang": ("total_penjualan", "total_cicilan", "sisa_piutang"),
    "/admin-panel/laporan/pembelian": ("harga", "subtotal"),
    "/admin-panel/laporan/penjualan": ("harga", "harga_bersih", "subtotal"),
    "/admin-panel/laporan/penjualan-hpp": ("harga_pokok", "total_harga_pokok", "laba", "margin"),
    "/admin-panel/laporan/penjualan-nota": ("total_kotor", "potongan", "total_bersih"),
    "/admin-panel/laporan/penjualan-customer": ("total",),
    "/admin-panel/laporan/penjualan-user": ("nominal",),
    "/admin-panel/laporan/rekap-kasir": ("total_kotor", "total", "total_tunai",
                                         "total_kredit", "rata_nota"),
    "/admin-panel/laporan/penjualan-periode": ("total_kotor", "total"),
    "/admin-panel/laporan/pembelian-supplier": ("total",),
    "/admin-panel/laporan/pembelian-periode": ("total_kotor", "total"),
    "/admin-panel/laporan/retur-penjualan": ("harga_jual", "nilai"),
    "/admin-panel/laporan/retur-pembelian": ("harga", "nilai"),
    "/admin-panel/laporan/biaya-operasional": ("nominal",),
    "/admin-panel/laporan/biaya-kategori": ("total",),
    "/admin-panel/promo/voucher": ("nominal", "nilai_dipakai"),
    "/admin-panel/promo/diskon": ("harga_promo",),
}


class _Req:
    def __init__(self, user):
        self.user = user


def _spec(url):
    for nama, s in vars(v).items():
        if isinstance(s, dict) and s.get("url") == url and "columns" in s:
            return nama, s
    raise AssertionError(f"spec untuk {url} tak ketemu")


def _cursor():
    """Cursor palsu yang cukup untuk view yang memanggil `cur.execute(...)`."""
    @contextmanager
    def c(profile, autocommit=True, query_timeout=None):
        class C:
            description = ()

            def execute(self, *a, **k):
                pass

            def fetchall(self):
                return []

            def fetchmany(self, n=1):
                return []

            def fetchone(self):
                return None

        yield C()
    return c


class UangTakIkutTerkirim(TestCase):
    """Laporan spec-driven: satu kebijakan (`_hidden_fields`) untuk dua jalur."""

    def setUp(self):
        self.req = _Req(User.objects.create_user(
            "batas", role=Role.ADMIN,
            hidden_data_keys=["nominal", "harga_beli", "harga_jual"]))

    def test_kolom_uang_hilang_dari_daftar_kolom(self):
        """Jalur export menyaring DAFTAR KOLOM (barisnya datang sebagai tuple),
        jadi inilah yang menahan rupiah sampai ke sel XLSX."""
        for url, kolom in BOCOR_DULU.items():
            nama, spec = _spec(url)
            punya = {c["key"] for c in spec["columns"]}
            sisa = {c["key"] for c in v._kolom_tanpa_uang(self.req, spec)}
            for k in kolom:
                self.assertIn(k, punya, f"{nama}: kolom {k} sudah tak ada di spec")
                self.assertNotIn(k, sisa, f"{nama} ({url}): {k} masih ikut ke export")

    def test_kolom_uang_masuk_daftar_yang_disaring(self):
        hidden = v._hidden_fields(self.req)
        for url, kolom in BOCOR_DULU.items():
            nama, _ = _spec(url)
            for k in kolom:
                self.assertIn(k, hidden, f"{nama} ({url}): {k} tak pernah disaring")

    def test_kolom_bukan_uang_tetap_utuh(self):
        """Pembatasan yang menelan kolom non-uang membuat laporannya tak
        terpakai, dan orang akan mencabut pembatasannya — bukan memperbaikinya."""
        _, spec = _spec("/admin-panel/laporan/piutang")
        sisa = {c["key"] for c in v._kolom_tanpa_uang(self.req, spec)}
        self.assertEqual(
            sisa, {"no_transaksi", "tanggal", "tanggal_server", "customer",
                   "jatuh_tempo", "hari_terlambat"})

    def test_opname_tak_kehilangan_kuantitasnya(self):
        """`total_masuk`/`koreksi_masuk` di Opname Stok adalah JUMLAH BARANG.
        Menutupnya karena namanya berbunyi seperti uang akan mengosongkan
        laporan yang sama sekali tak menyebut rupiah."""
        sisa = {c["key"] for c in v._kolom_tanpa_uang(self.req, v._OPNAME)}
        self.assertEqual(sisa, {c["key"] for c in v._OPNAME["columns"]})

    def test_tanpa_pencabutan_tak_ada_yang_hilang(self):
        bebas = _Req(User.objects.create_user("bebas", role=Role.ADMIN))
        for url in BOCOR_DULU:
            _, spec = _spec(url)
            self.assertEqual(v._kolom_tanpa_uang(bebas, spec), spec["columns"], url)


class UangBespoke(TestCase):
    """Empat layar yang TAK lewat `_report_view`, diuji lewat RESPONS HTTP.

    Sengaja lewat `self.client.get(...)` dengan header partial-reload Inertia dan
    bukan dengan memanggil `_uang_bespoke()` langsung: versi pertama tes ini
    memanggil helpernya, lalu terbukti tetap hijau ketika penyaringnya DICABUT
    dari view — ia membuktikan alatnya bekerja, bukan bahwa alatnya dipakai.

    Keempatnya menyaring lewat KUNCI IZIN, bukan nama kolom, karena nama
    kolomnya bentrok lintas layar: `masuk`/`keluar`/`total_masuk`/`total_keluar`
    rupiah di Kas Harian tapi KUANTITAS di Mutasi Stok, Opname Stok, dan
    Transaksi Barang.
    """

    KAS_BARIS = {"tanggal": "2026-08-01", "kas": "KAS", "keterangan": "y",
                 "masuk": 1000.0, "keluar": 0.0, "saldo": 5000.0}
    KAS_RINGKAS = {"jml_baris": 1, "total_masuk": 1000.0, "total_keluar": 0.0,
                   "saldo_awal": 4000.0, "saldo_akhir": 5000.0}
    FMI_BARIS = {"kd_barang": "A", "barang": "B", "kategori": "C", "qty_stok": 5.0,
                 "nilai_stok": 999.0, "terjual": 1.0, "rasio": 0.2, "status": "OK"}
    TX_BARIS = {"tanggal": "2026-08-01", "transaksi": "Pembelian", "no_transaksi": "X",
                "kd_barang": "A", "barang": "B", "masuk": 5.0, "keluar": 0.0,
                "satuan": "PCS", "harga": 12_000.0}
    # `stok` sengaja tak ada lagi: kolom itu dibaca dari m_barang_stok_akhir,
    # cache legacy yang terlantar (22.592 dari 22.703 baris negatif).
    PRODUK = {"kd_barang": "A", "nama": "B", "harga_jual": 9_000.0, "satuan": "PCS"}

    MENU = ["kas", "fmi_stok", "transaksi_barang", "products"]

    def _login(self, **kw):
        u = User.objects.create_user(
            f"bsp{User.objects.count()}", password="rahasia-kuat-123",
            role=kw.pop("role", Role.ADMIN), allowed_menu_keys=self.MENU, **kw)
        self.client.force_login(u)
        return u

    def _props(self, url, komponen, prop, patches):
        with ExitStack() as st:
            for target, name, val in patches:
                st.enter_context(patch.object(target, name, val))
            r = self.client.get(
                url, HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0",
                HTTP_X_INERTIA_PARTIAL_DATA=prop,
                HTTP_X_INERTIA_PARTIAL_COMPONENT=komponen)
        self.assertEqual(r.status_code, 200, url)
        return json.loads(r.content)["props"][prop]

    def _kas(self):
        return self._props(
            "/admin-panel/kas/harian", "Admin/Cash/Kas", "report",
            [(v, "_active", lambda: object()),
             (v.mssql, "cursor", _cursor()),
             (v.reporting, "run_paged", lambda *a, **k: ([dict(self.KAS_BARIS)], 1)),
             (v.reporting, "one_row", lambda cur: dict(self.KAS_RINGKAS)),
             (v, "_opt_kas", lambda p, arunika=False: [])])

    def _fmi(self):
        return self._props(
            "/admin-panel/analitik/fmi-stok", "Admin/Analytics/FmiStok", "report",
            [(v, "_active", lambda: object()),
             (v, "_fmi_stok_rows", lambda profile, f: [dict(self.FMI_BARIS)]),
             (v, "_opt_divisi", lambda p: [])])

    def _tx(self):
        return self._props(
            "/admin-panel/inventory/transaksi", "Admin/Inventory/TransaksiBarang", "report",
            [(v, "_active", lambda: object()),
             (v.mssql, "report_read_profiles", lambda p: [p]),
             (v.mssql, "report_cursor", _cursor()),
             (v.reporting, "run_paged", lambda *a, **k: ([dict(self.TX_BARIS)], 1)),
             # Muatan pertama halaman ini memakai mode "100 terbaru", jadi
             # run_recent yang dipanggil — bukan run_paged.
             (v.reporting, "run_recent", lambda *a, **k: ([dict(self.TX_BARIS)], 1, "x")),
             (v.reporting, "one_row",
              lambda cur: {"jml_baris": 1, "total_masuk": 5.0, "total_keluar": 0.0}),
             (v, "_opt_divisi", lambda p: [])])

    def _produk(self):
        # Master Produk kini laporan spec-driven (prop `report`), bukan view
        # bespoke ber-prop `products`: izin uangnya diturunkan otomatis dari
        # `_FIELDS_BY_DATA_KEY`, tanpa panggilan `_uang_bespoke` sendiri.
        return self._props(
            "/admin-panel/master/products", "Admin/MasterData/Products", "report",
            [(v, "_active", lambda: object()),
             (v.mssql, "report_read_profiles", lambda p: [p]),
             (v.mssql, "report_cursor", _cursor()),
             (v.reporting, "run_paged", lambda *a, **k: ([dict(self.PRODUK)], 1)),
             (v.reporting, "one_row",
              lambda cur: {"jml_baris": 1, "jml_aktif": 1, "jml_nonaktif": 0}),
             (v, "_opt_master_produk", lambda p: {})])

    # --- akun yang izin uangnya dicabut -----------------------------------
    def test_kas_harian_rupiah_tak_ikut_di_respons(self):
        self._login(hidden_data_keys=["nominal"])
        d = self._kas()
        self.assertEqual(d["rows"][0],
                         {"tanggal": "2026-08-01", "kas": "KAS", "keterangan": "y"})
        self.assertEqual(d["summary"], {"jml_baris": 1})

    def test_fmi_stok_nilai_tak_ikut_walau_vue_tak_merendernya(self):
        """FmiStok.vue tak punya kolom Nilai Stok, tapi payloadnya membawanya —
        dan payload yang sampai ke peramban terbaca di tab Network."""
        self._login(hidden_data_keys=["nominal"])
        d = self._fmi()
        self.assertNotIn("nilai_stok", d["rows"][0])
        self.assertIn("qty_stok", d["rows"][0])
        self.assertNotIn("total_nilai", d["summary"])
        self.assertIn("total_qty", d["summary"])

    def test_transaksi_barang_hanya_harga_yang_hilang(self):
        """`masuk`/`keluar` di layar ini KUANTITAS — wajib bertahan, kalau tidak
        laporan pergerakan barang kosong tanpa satu pun rupiah terlindungi."""
        self._login(hidden_data_keys=["nominal"])
        d = self._tx()
        self.assertNotIn("harga", d["rows"][0])
        self.assertEqual(d["rows"][0]["masuk"], 5.0)
        self.assertEqual(d["summary"]["total_masuk"], 5.0)

    def test_master_produk_memakai_kunci_harga_jual(self):
        """Kolomnya persis harga jual, jadi kunci izinnya yang tepat — bukan
        `nominal`. Ketiga kunci itu dipisah supaya bisa dicabut satu per satu."""
        self._login(hidden_data_keys=["harga_jual"])
        self.assertNotIn("harga_jual", self._produk()["rows"][0])

    def test_master_produk_tak_ikut_tercabut_oleh_nominal(self):
        self._login(hidden_data_keys=["nominal"])
        self.assertIn("harga_jual", self._produk()["rows"][0])

    # --- akun tanpa pencabutan --------------------------------------------
    def test_akun_biasa_tak_kehilangan_apa_pun(self):
        self._login()
        self.assertEqual(self._kas()["rows"][0], self.KAS_BARIS)
        self.assertEqual(self._kas()["summary"], self.KAS_RINGKAS)
        self.assertIn("nilai_stok", self._fmi()["rows"][0])
        self.assertIn("harga", self._tx()["rows"][0])
        self.assertIn("harga_jual", self._produk()["rows"][0])

    def test_superadmin_tak_pernah_dibatasi(self):
        self._login(role=Role.SUPERADMIN, hidden_data_keys=["nominal"])
        self.assertEqual(self._kas()["rows"][0], self.KAS_BARIS)

    # --- export ------------------------------------------------------------
    def test_daftar_kolom_export_ikut_menyusut(self):
        """Jalur export streaming memetakan kolom lewat NAMA dari cur.description,
        jadi mencabut kolom di daftar aman — tak ada pergeseran indeks."""
        req = _Req(self._login(hidden_data_keys=["nominal"]))
        self.assertEqual(
            [c["key"] for c in v._KAS_COLUMNS
             if c["key"] not in v._uang_bespoke(req, v._KAS_UANG)],
            ["tanggal", "kas", "keterangan"])
        sisa_fmi = {c["key"] for c in v._FMI_STOK_COLUMNS
                    if c["key"] not in v._uang_bespoke(req, v._FMI_STOK_UANG)}
        self.assertNotIn("nilai_stok", sisa_fmi)
        self.assertIn("qty_stok", sisa_fmi)
        sisa_tx = {c["key"] for c in v._TRANSAKSI_COLUMNS
                   if c["key"] not in v._uang_bespoke(req, v._TRANSAKSI_UANG)}
        self.assertNotIn("harga", sisa_tx)
        self.assertIn("masuk", sisa_tx)

    def test_mutasi_stok_tak_punya_kolom_uang(self):
        """Dicatat di CLAUDE.md sebagai belum tertutup, tapi kolomnya
        kd_barang/barang/kategori/divisi/masuk/keluar/stok — tak satu pun rupiah.
        Tak ada yang perlu ditutup, dan itu temuan, bukan kelalaian."""
        teks = (pathlib.Path(settings.BASE_DIR) / "frontend" / "pages" / "Admin"
                / "Inventory" / "MutasiStok.vue").read_text(encoding="utf-8")
        self.assertNotIn('format: "rupiah"', teks)


class NotaMundurDetail(TestCase):
    """Panel detail Nota Tanggal Mundur: rute JSON ketiga di layar itu, dan
    satu-satunya yang memajang harga barang, total nota, dan perubahan diskon
    dari log. Diuji lewat HTTP sungguhan — tes yang memanggil penyaringnya
    langsung akan tetap hijau kalau view berhenti memakainya."""

    HEADER = {"no_transaksi": "SC2609200054", "tanggal": dt.datetime(2026, 9, 20, 12, 0),
              "tanggal_server": dt.datetime(2026, 9, 21, 9, 0), "kd_divisi": "DAA000",
              "kd_customer": "CAA000", "keterangan": "-", "kd_user": "UAA032"}
    BARANG = {"kd_barang": "A", "kd_satuan": "SAA000", "kd_pegawai": "PAA000", "jenis": 1,
              "barang": "Mainan", "satuan": "PCS", "qty": 2, "harga_jual": 5000.0, "subtotal": 10000.0}
    RIWAYAT = {"peristiwa": [
        {"waktu": dt.datetime(2026, 9, 20, 12, 0), "aksi": "Dibuat", "kd_user": "UAA009",
         "tanggal": "2026-9-20 12:00:00", "perubahan": [],
         "barang": {"isi": [{"kd_barang": "A", "kd_satuan": "SAA000", "qty": 1.0, "harga_jual": 5000.0}]}},
        {"waktu": dt.datetime(2026, 9, 21, 9, 0), "aksi": "Diedit", "kd_user": "UAA032",
         "tanggal": "2026-9-20 12:00:00",
         "perubahan": [{"kolom": "diskon_uang", "dari": "0", "ke": "2000"},
                       {"kolom": "keterangan", "dari": "-", "ke": "TF BCA"}],
         "barang": {"ditambah": [], "dihapus": [], "diubah": [
             {"kd_barang": "A", "kd_satuan": "SAA000", "qty": 2.0, "harga_jual": 5000.0,
              "qty_dari": 1.0, "harga_jual_dari": 4000.0}]}},
    ], "barang_akhir": {}}

    def _cursor(self):
        uji = self

        @contextmanager
        def c(profile, autocommit=True, query_timeout=None):
            class C:
                description, _baris, _satu = (), [], None

                def setinputsizes(self, _):
                    pass

                def execute(self, sql, params=()):
                    self.description, self._baris, self._satu = (), [], None
                    if sql.startswith("SELECT TOP 1 * FROM t_penjualan"):
                        isi = [uji.HEADER]
                    elif "FROM t_penjualan_detail d" in sql:
                        isi = [uji.BARANG]
                    elif sql.startswith("SELECT total_bersih"):
                        self._satu = (8000.0,)
                        return
                    elif sql.startswith("SELECT COUNT(DISTINCT"):
                        self._satu = (2, "SC2609200055")
                        return
                    elif "UNION ALL SELECT" in sql:
                        # Urutan sengaja terbalik — view harus mengurutkan.
                        isi = [{"no": "SC2609200055", "tanggal": uji.HEADER["tanggal"],
                                "tanggal_server": uji.HEADER["tanggal"], "kd_user": "UAA009"},
                               {"no": "SC2609200054", "tanggal": uji.HEADER["tanggal"],
                                "tanggal_server": uji.HEADER["tanggal_server"], "kd_user": "UAA032"}]
                    else:
                        isi = []
                    if isi:
                        self.description = [(k,) for k in isi[0]]
                        self._baris = [tuple(r.values()) for r in isi]

                def fetchall(self):
                    return self._baris

                def fetchone(self):
                    return self._satu

            yield C()
        return c

    def _detail(self, **kw):
        u = User.objects.create_user(
            f"nm{User.objects.count()}", password="rahasia-kuat-123",
            role=Role.ADMIN, allowed_menu_keys=["nota_mundur"], **kw)
        self.client.force_login(u)
        with patch.object(v, "_active", lambda: object()), \
             patch.object(v, "_log_siap", lambda p, cur=None: True), \
             patch.object(v.mssql, "report_cursor", self._cursor()), \
             patch.object(v.riwayat_log, "riwayat", lambda *a: self.RIWAYAT), \
             patch.object(v.riwayat_log, "cocok_dengan_sekarang", lambda *a: True):
            r = self.client.get("/admin-panel/analitik/nota-mundur/detail", {"jenis": "Penjualan", "no": "SC2609200054"})
        self.assertEqual(r.status_code, 200)
        return json.loads(r.content)

    def test_tanpa_izin_uang_tak_ada_rupiah_di_respons(self):
        d = self._detail(hidden_data_keys=["nominal", "harga_jual"])
        teks = json.dumps(d)
        for bocor in ("harga_jual", "harga_jual_dari", "subtotal", "5000", "4000", "8000", "Diskon"):
            self.assertNotIn(bocor, teks, bocor)
        self.assertIsNone(d["total_bersih"])
        # Yang bukan uang tetap utuh: qty, dan perubahan keterangan.
        self.assertEqual(d["barang"][0]["qty"], 2)
        self.assertEqual([c["label"] for c in d["riwayat"][1]["perubahan"]], ["Keterangan"])

    def test_dengan_izin_semua_tampil(self):
        d = self._detail()
        self.assertEqual(d["total_bersih"], 8000.0)
        self.assertEqual(d["barang"][0]["subtotal"], 10000.0)
        self.assertEqual(d["riwayat"][1]["barang"]["diubah"][0]["harga_jual_dari"], 4000.0)
        self.assertEqual([c["label"] for c in d["riwayat"][1]["perubahan"]], ["Diskon (Rp)", "Keterangan"])

    def test_urutan_nota_tanpa_uang(self):
        d = self._detail(hidden_data_keys=["nominal", "harga_jual"])
        self.assertEqual([t["no"] for t in d["tetangga"]], ["SC2609200054", "SC2609200055"])
        self.assertEqual([t["ini"] for t in d["tetangga"]], [True, False])
        self.assertEqual(set(d["tetangga"][0]), {"no", "tanggal", "tanggal_server", "kasir", "ini"})
        self.assertEqual(d["jumlah_hari_itu"], 2)
        self.assertFalse(d["terakhir_hari_itu"])

    def test_pembuat_dan_kasir_nota_dipisah(self):
        d = self._detail()
        self.assertEqual([p["aksi"] for p in d["riwayat"]], ["Dibuat", "Diedit"])
        self.assertEqual(d["riwayat"][1]["tanggal_nota"], "2026-09-20 12:00")

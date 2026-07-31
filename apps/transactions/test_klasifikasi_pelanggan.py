"""Aturan klasifikasi pelanggan — diuji tanpa MS SQL.

Yang dijaga di sini bukan angka hasil query (itu butuh server), tapi ATURAN-nya:
urutan pemeriksaan segmen, perilaku ambang saat diisi ngawur, dan daftar
pengecualian. Ketiganya bisa berubah tanpa gejala apa pun di layar — laporan
tetap tampil rapi sambil menamai orang dengan salah.
"""
import datetime as dt
import os
import re
from unittest import mock

from django.test import SimpleTestCase

from apps.transactions import reports as rpt


def _f(**kw):
    """Dict `f` minimal seperti keluaran parse_report_params."""
    base = {
        "date_from": dt.datetime(2024, 7, 30),
        "date_to": dt.datetime(2026, 7, 30, 23, 59, 59),
        "search": "",
        "kd_divisi": "",
        "filters": {},
    }
    base.update(kw)
    return base


class Ambang(SimpleTestCase):
    def test_kosong_pakai_bawaan(self):
        for key, (bawaan, _lo, _hi) in rpt.AMBANG_KLASIFIKASI.items():
            self.assertEqual(rpt._amb(_f(**{key: ""}), key), bawaan)

    def test_teks_ngawur_jatuh_ke_bawaan_bukan_meledak(self):
        # Laporan yang membalas 500 karena seseorang mengetik "abc" di kotak
        # angka lebih buruk daripada laporan yang memakai nilai bawaan.
        self.assertEqual(rpt._amb(_f(hilang_hari="abc"), "hilang_hari"), 180)
        self.assertEqual(rpt._amb(_f(hilang_hari=None), "hilang_hari"), 180)

    def test_di_luar_rentang_di_clamp_ke_batas(self):
        self.assertEqual(rpt._amb(_f(hilang_hari="-99"), "hilang_hari"), 7)
        self.assertEqual(rpt._amb(_f(hilang_hari="99999"), "hilang_hari"), 1095)

    def test_desimal_dibulatkan_ke_int(self):
        # Nilai wajib int: ia ditanam langsung ke SQL, bukan lewat placeholder.
        self.assertIsInstance(rpt._amb(_f(hilang_hari="90.7"), "hilang_hari"), int)
        self.assertEqual(rpt._amb(_f(hilang_hari="90.7"), "hilang_hari"), 90)


def _segmen_dari_sql(label_sql: str, jeda: int, umur: int, nota: int) -> str:
    """Jalankan CASE label buatan _segmen_case dgn Python — cabang pertama yang
    cocok, semantik yang sama dengan SQL Server."""
    for kondisi, hasil in re.findall(r"WHEN (.+?) THEN '(.+?)'", label_sql):
        ekspresi = (kondisi
                    .replace("g.jeda_hari", str(jeda))
                    .replace("g.umur_hari", str(umur))
                    .replace("g.jml_nota", str(nota)))
        if eval(ekspresi):  # noqa: S307 - ekspresi dibangun kode ini sendiri
            return hasil
    return re.search(r"ELSE '(.+?)' END", label_sql).group(1)


class Segmen(SimpleTestCase):
    def setUp(self):
        _urut, self.label = rpt._segmen_case(_f())

    def segmen(self, jeda, umur, nota=1):
        return _segmen_dari_sql(self.label, jeda, umur, nota)

    def test_batas_hilang_persis(self):
        # Ambang bawaan 180: "lebih dari 180" berarti 180 belum hilang, 181 sudah.
        self.assertNotEqual(self.segmen(jeda=180, umur=500), "Hilang")
        self.assertEqual(self.segmen(jeda=181, umur=500), "Hilang")

    def test_batas_baru_persis(self):
        # Ambang bawaan 90: "dalam 90 hari" inklusif, jadi 90 masih baru.
        self.assertEqual(self.segmen(jeda=0, umur=90), "Baru")
        self.assertNotEqual(self.segmen(jeda=0, umur=91), "Baru")

    def test_recency_menang_atas_baru(self):
        # Inti aturan: pelanggan pertama-kali yang datang 200 hari lalu BUKAN
        # pendatang baru yang perlu disambut — ia sudah hilang, dan itu
        # follow-up yang berbeda. Kalau urutan cabang tertukar, tes ini merah.
        self.assertEqual(self.segmen(jeda=200, umur=200), "Hilang")

    def test_setia_butuh_jeda_pendek_dan_banyak_nota(self):
        self.assertEqual(self.segmen(jeda=10, umur=800, nota=5), "Setia")
        self.assertEqual(self.segmen(jeda=10, umur=800, nota=4), "Aktif")

    def test_pelanggan_lama_yang_masih_datang_bukan_baru(self):
        self.assertEqual(self.segmen(jeda=5, umur=900, nota=1), "Aktif")

    def test_mulai_jarang_adalah_pita_antara_dua_ambang(self):
        _urut, label = rpt._segmen_case(_f(jarang_hari="90", hilang_hari="180"))
        self.assertEqual(_segmen_dari_sql(label, jeda=181, umur=300, nota=1), "Hilang")
        self.assertEqual(_segmen_dari_sql(label, jeda=91, umur=300, nota=1), "Mulai Jarang")
        self.assertEqual(_segmen_dari_sql(label, jeda=90, umur=300, nota=1), "Aktif")

    def test_jarang_melebihi_hilang_mengosongkan_mulai_jarang(self):
        # Ambang yang saling bertentangan (jarang 400 > hilang 180) TIDAK ditukar
        # diam-diam: 'Hilang' tetap 180 seperti yang diketik, dan 'Mulai Jarang'
        # jadi kosong — jawaban yang benar, karena semua yang tadinya mulai
        # jarang sudah masuk hilang. Angkanya terlihat di panel filter, jadi
        # pengguna bisa menalar sendiri; ambang yang diganti di belakang punggung
        # tidak bisa.
        _urut, label = rpt._segmen_case(_f(jarang_hari="400", hilang_hari="180"))
        self.assertEqual(_segmen_dari_sql(label, jeda=200, umur=300, nota=1), "Hilang")
        self.assertEqual(_segmen_dari_sql(label, jeda=181, umur=300, nota=1), "Hilang")
        self.assertNotEqual(_segmen_dari_sql(label, jeda=100, umur=300, nota=1), "Mulai Jarang")

    def test_semua_label_terpakai(self):
        _urut, label = rpt._segmen_case(_f())
        for nama in rpt.SEGMEN_LABEL.values():
            self.assertIn(f"'{nama}'", label)

    def test_case_tidak_menanam_ulang_case_angka(self):
        # Label dibangun dari daftar cabang yang sama, BUKAN dengan membandingkan
        # hasil CASE angka — bentuk itu menanam seluruh CASE lima kali dalam satu
        # statement, kelas ledakan ekspresi yang pernah memicu error 8632.
        urut, label = rpt._segmen_case(_f())
        self.assertEqual(label.count("CASE"), 1)
        self.assertEqual(urut.count("CASE"), 1)


class Pengecualian(SimpleTestCase):
    def test_bawaan_memuat_umum_eceran_obral(self):
        # Ketiga kode diverifikasi ada di kelima profil koneksi.
        self.assertEqual(rpt.pseudo_customer_codes(), ("CAA000", "CAA025", "CAA027"))

    @mock.patch.dict(os.environ, {"POS_PSEUDO_CUSTOMERS": "caa000, XX9 "})
    def test_env_menimpa_dan_dinormalkan_huruf_besar(self):
        self.assertEqual(rpt.pseudo_customer_codes(), ("CAA000", "XX9"))

    @mock.patch.dict(os.environ, {"POS_PSEUDO_CUSTOMERS": ""})
    def test_env_kosong_berarti_tanpa_pengecualian(self):
        # Beda dari "tidak diset": string kosong adalah pilihan eksplisit untuk
        # menampilkan semuanya, bukan alasan untuk kembali ke bawaan.
        self.assertEqual(rpt.pseudo_customer_codes(), ())

    @mock.patch.dict(os.environ, {"POS_PSEUDO_CUSTOMER_NAMES": "SHOPEE"})
    def test_nama_disaring_selain_kode(self):
        where, params = [], []
        rpt._pseudo_where(where, params, "n.kd_customer", "c.nama")
        self.assertIn("%SHOPEE%", params)
        self.assertTrue(any("NOT LIKE" in w for w in where))

    def test_kode_dibandingkan_tanpa_spasi_ekor_dan_case_insensitive(self):
        # kd_customer adalah varchar dgn kemungkinan spasi ekor; collation MS SQL
        # memang case-insensitive, tapi perbandingannya dibuat eksplisit di sini
        # supaya tak bergantung pada setelan server.
        where, _params = [], []
        rpt._pseudo_where(where, _params, "n.kd_customer", "c.nama")
        self.assertIn("UPPER(RTRIM(n.kd_customer))", where[0])


class BentukQuery(SimpleTestCase):
    """Jumlah placeholder harus cocok dengan jumlah parameter.

    Urutan `?` di query berlapis ini tidak intuitif — DATEDIFF di daftar SELECT
    muncul sebelum subquery nota di FROM, jadi tanggal acuan MENDAHULUI parameter
    _nota_net. Salah urut tidak menghasilkan error, hanya angka yang salah.
    """

    def test_laporan_utama(self):
        sql, params = rpt.klasifikasi_pelanggan(_f())
        self.assertEqual(sql.count("?"), len(params))

    def test_dengan_search_dan_divisi(self):
        sql, params = rpt.klasifikasi_pelanggan(_f(search="ani", kd_divisi="D01"))
        self.assertEqual(sql.count("?"), len(params))

    def test_dua_tanggal_acuan_di_depan(self):
        _sql, params = rpt.klasifikasi_pelanggan(_f())
        acuan = dt.datetime(2026, 7, 30, 23, 59, 59)
        self.assertEqual(params[:2], [acuan, acuan])

    def test_barang_favorit_massal(self):
        sql, params = rpt.barang_favorit_massal(_f(search="ani"), top_n=5)
        self.assertEqual(sql.count("?"), len(params))
        # ROW_NUMBER per pelanggan, bukan TOP global: tanpa PARTITION BY beberapa
        # pelanggan besar memakan seluruh kuota dan sisanya tak kebagian barang.
        self.assertIn("PARTITION BY x.kd_customer", sql)

    def test_barang_favorit_satu_pelanggan(self):
        sql, params = rpt.barang_favorit_pelanggan(_f(), "CAA999", top_n=20)
        self.assertEqual(sql.count("?"), len(params))
        self.assertIn("CAA999", params)

    def test_nota_pelanggan(self):
        sql, params = rpt.nota_pelanggan(_f(), "CAA999", top_n=20)
        self.assertEqual(sql.count("?"), len(params))
        self.assertIn("CAA999", params)

    def test_favorit_membuang_baris_bernilai_nol(self):
        # Diurut qty apa adanya, tiga teratas hampir tiap pelanggan adalah bonus
        # bernilai nol (BATERAI FREE, KERTAS KADO FREE) — bukan pembelian.
        sql, _params = rpt.barang_favorit_massal(_f())
        self.assertIn("HAVING", sql)
        self.assertIn("> 0", sql)

    def test_top_n_menolak_teks_bukan_menanamnya(self):
        # top_n ditanam langsung ke SQL (TOP N / rn <= N), bukan lewat placeholder,
        # jadi int() di sana adalah penjaganya. Ia MENOLAK (ValueError) alih-alih
        # meloloskan teks — dan itu memang aman: nilainya selalu konstanta dari
        # sisi view, tak pernah dari request.
        with self.assertRaises(ValueError):
            rpt.barang_favorit_pelanggan(_f(), "X", top_n="5; DROP TABLE m_barang")
        with self.assertRaises(ValueError):
            rpt.barang_favorit_massal(_f(), top_n="1 OR 1=1")


class Whitelist(SimpleTestCase):
    def test_setiap_sort_key_menunjuk_kolom_yang_ada_di_keluaran(self):
        sql, _params = rpt.klasifikasi_pelanggan(_f())
        for key, alias in rpt.SORTS_KLASIFIKASI_PELANGGAN.items():
            with self.subTest(sort=key):
                self.assertIn(alias, sql)

    def test_segmen_diurut_lewat_peringkat_bukan_abjad(self):
        # Abjad menaruh 'Aktif' sebelum 'Hilang', jadi mengurut kolom Segmen
        # akan membuang yang paling perlu dihubungi ke halaman terakhir.
        self.assertEqual(rpt.SORTS_KLASIFIKASI_PELANGGAN["segmen"], "segmen_urut")

    def test_setiap_filter_kolom_menunjuk_alias_yang_ada(self):
        sql, _params = rpt.klasifikasi_pelanggan(_f())
        for name, (alias, _kind) in rpt.FILTERS_KLASIFIKASI_PELANGGAN.items():
            with self.subTest(filter=name):
                self.assertIn(alias, sql)


    def test_kolom_kolumnar_semuanya_ada_di_keluaran_sql(self):
        # Payload kolumnar menyebut kolomnya secara eksplisit (KLASIFIKASI_COLS).
        # Kalau satu alias SQL berganti nama, kolom itu jadi None untuk seluruh
        # baris dan layar mencetak deretan "-" — tanpa error di mana pun.
        from apps.transactions.services import KLASIFIKASI_COLS

        sql, _params = rpt.klasifikasi_pelanggan(_f())
        for kolom in KLASIFIKASI_COLS:
            with self.subTest(kolom=kolom):
                self.assertIn(kolom, sql)

    def test_saringan_klien_punya_padanan_filter_server(self):
        # Saringan di peramban (segmen/kelas nilai/kota/cari) diterjemahkan ke
        # parameter server saat Export, supaya file Excel-nya cocok dengan yang
        # terlihat. Hilang satu padanan = export diam-diam mengirim semua baris.
        for name in ("segmen", "tier_nilai", "kota"):
            with self.subTest(saringan=name):
                self.assertIn(name, rpt.FILTERS_KLASIFIKASI_PELANGGAN)

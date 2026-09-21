"""Panel info di layar kasir: member, piutang aktif, dan nota terakhir.

Ketiganya sudah lama ada di /admin-panel — dan /admin-panel tertutup penjaga
Tailscale, jadi dari jaringan toko kasir memang tak pernah bisa melihatnya. Yang
dijaga di sini bukan angkanya (itu perlu MS SQL sungguhan), melainkan tiga hal
yang gagal tanpa suara:

1. **Endpoint-nya harus berada DI BAWAH prefix layarnya.** `menu_key_for_path`
   memberi izin per-prefix, dan path yang tak cocok menu mana pun dianggap
   BEBAS. Endpoint ini membawa piutang, batas kredit, dan nota terakhir
   seseorang — bocor di sini jauh lebih mahal daripada kotak cari barang.
2. **Kolom uang harus dicabut di SERVER.** Penyaringan di Vue cuma kosmetik;
   payload-nya tetap sampai ke peramban. Jebakan ini sudah dua kali terjadi di
   proyek ini (export Stok Akhir, sheet Barang Favorit) dan tak pernah
   menimbulkan gejala apa pun di layar.
3. **`kd_user` tak boleh datang dari layar.** Kalau boleh, siapa pun membaca
   nota orang lain dengan mengganti satu parameter di URL.
"""
import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.auth_app.models import Role, TautanUser, User
from apps.connections.models import ServerProfile
from apps.core.menus import menu_key_for_path
from apps.core.models import BayarNota
from apps.monitoring import views_kasir as vk
from apps.transactions import penjualan as pj

PROFIL = {"kd_customer": "CAA111", "nama": "TOKO MAJU", "alamat": "Jl. Mawar",
          "hp": "0812", "telepon": "", "point": 12.0, "limit_kredit": 5_000_000.0,
          "disc": 2.5, "status": 1}
PIUTANG = [{"no_transaksi": "SC0001", "tanggal": "2026-01-02", "jatuh_tempo": "2026-02-01",
            "total_penjualan": 900_000.0, "total_cicilan": 100_000.0,
            "sisa_piutang": 800_000.0, "hari_terlambat": 12}]
HISTORI = [{"no_transaksi": "SC0009", "tanggal": "2026-08-01 10:00", "status": "Tunai",
            "nominal": 250_000.0, "customer": "TOKO MAJU"}]
REKAP = {"jml_nota": 7, "total": 3_500_000.0,
         "total_tunai": 3_000_000.0, "total_kredit": 500_000.0}


def _profil_server():
    return ServerProfile.objects.create(
        name="TOKO A", host="h", db_name="SOLID_SIM", username="sa",
        password_encrypted="x", is_default=True)


class Penghitung:
    """Pengganti `mssql.cursor` yang menghitung berapa kali ia dimasuki.

    MS SQL tak disentuh: yang diuji berapa banyak sambungan dibuka, bukan apa
    yang dibacanya. Kursornya sendiri tak pernah dipakai karena ketiga fungsi
    layanan di-patch.
    """

    def __init__(self):
        self.dibuka = 0

    def __call__(self, *a, **k):
        self.dibuka += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class InfoCustomerTests(TestCase):
    def setUp(self):
        self.server = _profil_server()
        self.spv = User.objects.create_user(
            "spv_i", password="rahasia-kuat-123", role=Role.SUPERVISOR,
            server_profile=self.server)
        TautanUser.objects.create(user=self.spv, profile=self.server,
                                  kd_user="UAA002", kd_divisi="DAA000")
        self.client.force_login(self.spv)

    def _get(self, url, **params):
        d, _ = self._get_hitung(url, **params)
        return d

    def _get_hitung(self, url, **params):
        """Seperti `_get`, tapi ikut memulangkan berapa kali kursor dibuka."""
        hitung = Penghitung()
        with patch("apps.monitoring.views_kasir.mssql.cursor", hitung), \
             patch("apps.transactions.penjualan.info_customer", return_value=dict(PROFIL)), \
             patch("apps.transactions.penjualan.piutang_customer",
                   return_value=[dict(r) for r in PIUTANG]), \
             patch("apps.transactions.penjualan.histori_nota",
                   return_value=[dict(r) for r in HISTORI]):
            return json.loads(self.client.get(url, params).content), hitung

    def test_satu_round_trip_membawa_ketiganya(self):
        """Tiga endpoint terpisah = tiga perjalanan WAN untuk satu klik."""
        d = self._get("/kasir/penjualan/info-customer", kd_customer="CAA111")
        self.assertEqual(d["profil"]["nama"], "TOKO MAJU")
        self.assertEqual(len(d["piutang"]), 1)
        self.assertEqual(len(d["histori"]), 1)

    def test_satu_koneksi_untuk_ketiganya(self):
        """Satu HTTP tak ada gunanya kalau di dalamnya tetap tiga handshake ODBC.

        Dulu `info_customer`, `piutang_customer`, dan `histori_nota`
        masing-masing membuka `mssql.cursor` sendiri, jadi satu klik pelanggan
        = tiga sambungan. Di profil jauh sambungannya yang mahal, bukan
        querynya.
        """
        _, hitung = self._get_hitung(
            "/kasir/penjualan/info-customer", kd_customer="CAA111")
        self.assertEqual(hitung.dibuka, 1,
                         f"kursor dibuka {hitung.dibuka}x, seharusnya sekali")

    def test_pelanggan_umum_tidak_dijemput(self):
        """CAA000 bawaan hampir tiap nota tunai; menjemputnya = perjalanan
        sia-sia di awal hampir setiap nota."""
        with patch("apps.transactions.penjualan.info_customer") as m:
            d = json.loads(self.client.get(
                "/kasir/penjualan/info-customer", {"kd_customer": "CAA000"}).content)
        m.assert_not_called()
        self.assertIsNone(d["profil"])

    def test_kolom_uang_dicabut_di_server(self):
        self.spv.hidden_data_keys = ["nominal"]
        self.spv.save()
        d = self._get("/kasir/penjualan/info-customer", kd_customer="CAA111")
        for k in ("sisa_piutang", "total_cicilan", "total_penjualan"):
            self.assertNotIn(k, d["piutang"][0], f"{k} lolos ke peramban")
        self.assertNotIn("nominal", d["histori"][0])
        # Satu-satunya rupiah di blok profil, dan ia dict tunggal — bukan baris
        # tabel — jadi ia gampang terlewat dari penyaringan.
        self.assertNotIn("limit_kredit", d["profil"])
        # Yang bukan uang tetap ada; mencabut semuanya bukan tujuannya.
        self.assertIn("no_transaksi", d["piutang"][0])
        self.assertIn("point", d["profil"])

    def test_tanpa_pencabutan_uang_tetap_terkirim(self):
        d = self._get("/kasir/penjualan/info-customer", kd_customer="CAA111")
        self.assertEqual(d["piutang"][0]["sisa_piutang"], 800_000.0)
        self.assertEqual(d["profil"]["limit_kredit"], 5_000_000.0)


class HistoriUserTests(TestCase):
    def setUp(self):
        self.server = _profil_server()
        self.spv = User.objects.create_user(
            "spv_h", password="rahasia-kuat-123", role=Role.SUPERVISOR,
            server_profile=self.server)
        self.tautan = TautanUser.objects.create(
            user=self.spv, profile=self.server, kd_user="UAA002", kd_divisi="DAA000")
        self.client.force_login(self.spv)

    def _get(self, **params):
        with patch("apps.monitoring.views_kasir.mssql.cursor", Penghitung()), \
             patch("apps.transactions.penjualan.histori_nota",
                   return_value=[dict(r) for r in HISTORI]) as m, \
             patch("apps.transactions.penjualan.rekap_hari_ini",
                   return_value=dict(REKAP)) as r:
            resp = self.client.get("/kasir/penjualan/histori-user", params)
        return json.loads(resp.content), m, r

    def test_kd_user_diambil_dari_tautan_bukan_dari_url(self):
        _, m, r = self._get(kd_user="UAA999")
        self.assertEqual(m.call_args.kwargs["kd_user"], "UAA002")
        # Rekapnya UANG, jadi aturan yang sama berlaku — bahkan lebih keras.
        self.assertEqual(r.call_args.args[1], "UAA002")

    def test_kolom_uang_dicabut_di_server(self):
        self.spv.hidden_data_keys = ["nominal"]
        self.spv.save()
        d, _, _ = self._get()
        self.assertNotIn("nominal", d["rows"][0])
        self.assertIn("no_transaksi", d["rows"][0])

    def test_rekap_hari_ini_ikut_terkirim(self):
        """Ia menumpang endpoint ini, bukan rute sendiri: rute baru harus
        didaftarkan ulang di bawah tiap prefix layar, dan path yang tak cocok
        menu mana pun dianggap BEBAS oleh middleware."""
        d, _, _ = self._get()
        self.assertEqual(d["rekap"]["jml_nota"], 7)
        self.assertEqual(d["rekap"]["total"], 3_500_000.0)

    def test_rekap_uangnya_dicabut_tapi_jumlah_notanya_tidak(self):
        """`rekap` dict tunggal — bukan baris tabel — jadi ia gampang terlewat
        dari penyaringan, persis seperti `limit_kredit` di panel member.
        Hitungan nota bukan uang dan tetap tinggal."""
        self.spv.hidden_data_keys = ["nominal"]
        self.spv.save()
        d, _, _ = self._get()
        for k in ("total", "total_tunai", "total_kredit"):
            self.assertNotIn(k, d["rekap"], f"{k} lolos ke peramban")
        self.assertEqual(d["rekap"]["jml_nota"], 7)


class SqlBentukTests(TestCase):
    """Jumlah `?` harus sama dengan jumlah parameter, dan urutannya benar.

    Ini kelas galat yang sudah pernah menggigit di `reports.piutang`: dua `?`
    DATEDIFF berada di SELECT terluar yang dirender SEBELUM klausa FROM yang
    memuat parameter lain, jadi urutan bind-nya bukan urutan penyusunannya.
    Di sini kedua DATEDIFF memakai GETDATE() justru supaya jebakan itu tak bisa
    terulang — tesnya tetap ada karena WHERE-nya masih dibangun.
    """

    def _tangkap(self, fn, **kw):
        """Jalankan pembangun query dengan cursor palsu, ambil (sql, params)."""
        from unittest.mock import MagicMock

        cur = MagicMock()
        cur.fetchall.return_value = []
        # None, bukan MagicMock: pembangun yang memakai fetchone() memeriksa
        # baris kosong, dan MagicMock selalu truthy sehingga ia akan mencoba
        # meng-int-kan mock alih-alih memulangkan nilai nolnya.
        cur.fetchone.return_value = None
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        with patch("core.mssql.cursor", return_value=ctx):
            fn(object(), **kw)
        return cur.execute.call_args[0]

    def test_piutang_customer_seimbang(self):
        from apps.transactions.penjualan import piutang_customer

        sql, params = self._tangkap(piutang_customer, kd_customer="CAA111")
        self.assertEqual(sql.count("?"), len(params))
        self.assertEqual(params, ["CAA111"])
        # Tanpa penyaring tanggal: piutang yang jatuh tempo delapan bulan lalu
        # justru yang paling perlu terlihat, dan ia hilang dari rentang bawaan.
        self.assertNotIn("h.tanggal >=", sql)
        self.assertIn("h.status = 0", sql)

    def test_histori_nota_seimbang(self):
        from apps.transactions.penjualan import histori_nota

        sql, params = self._tangkap(histori_nota, kd_user="UAA002")
        self.assertEqual(sql.count("?"), len(params))
        self.assertEqual(params, ["UAA002"])
        # Didorong ke DALAM _nota_net supaya index (kd_user, tanggal) dipakai
        # untuk MENYARING, bukan memindai lalu membuang.
        self.assertIn("h.kd_user = ?", sql.split(") n ")[0])

    def test_rekap_hari_ini_seimbang(self):
        import datetime as _dt

        from apps.transactions.penjualan import rekap_hari_ini

        sql, params = self._tangkap(
            rekap_hari_ini, kd_user="UAA002", tanggal=_dt.date(2026, 9, 21))
        self.assertEqual(sql.count("?"), len(params))
        self.assertEqual(params[0], "UAA002")
        # Jendelanya TEPAT satu hari, batas atas eksklusif: `tanggal` menyimpan
        # jam, dan `<= 23:59:59` membuang nota di detik terakhir hari itu.
        self.assertEqual(params[2] - params[1], _dt.timedelta(days=1))
        self.assertEqual(params[1], _dt.datetime(2026, 9, 21, 0, 0))
        # Didorong ke DALAM _nota_net — alasan yang sama dengan histori_nota.
        self.assertIn("h.kd_user = ?", sql.split(") n")[0])

    def test_rekap_tanpa_kd_user_tak_menyentuh_server(self):
        """Akun tanpa tautan tak boleh memicu query apa pun — tanpa penyaring
        kd_user, agregatnya akan memulangkan omset SELURUH toko."""
        from apps.transactions.penjualan import rekap_hari_ini

        with patch("core.mssql.cursor") as m:
            hasil = rekap_hari_ini(object(), "   ")
        m.assert_not_called()
        self.assertEqual(hasil["jml_nota"], 0)
        self.assertEqual(hasil["total"], 0.0)

    def test_rekap_tunai_dan_kredit_menutup_semua_nota(self):
        """Tiap nota jatuh ke TEPAT satu kolom: `= 1` dan `<> 1` saling
        melengkapi. Kalau suatu saat jadi `= 0`, nota Lunas hilang dari
        keduanya dan tunai+kredit tak lagi menjumlah ke total."""
        from apps.transactions.penjualan import rekap_hari_ini

        sql, _ = self._tangkap(rekap_hari_ini, kd_user="UAA002")
        self.assertIn("WHEN n.status_raw = 1 THEN", sql)
        self.assertIn("WHEN n.status_raw <> 1 THEN", sql)

    def test_histori_tanpa_penyaring_menolak_jalan(self):
        """Tanpa ini ia akan memindai seluruh t_penjualan (438rb baris)."""
        from apps.transactions.penjualan import histori_nota

        self.assertEqual(histori_nota(object()), [])


class PrefixIzinTests(TestCase):
    """Endpoint baru mewarisi kunci menu layarnya lewat pencocokan prefix."""

    def test_terdaftar_di_bawah_kedua_layar(self):
        for layar, key in (("penjualan", "kasir_penjualan"),
                           ("penjualan-order", "kasir_penjualan_order")):
            for ruas in ("info-customer", "histori-user"):
                self.assertEqual(
                    menu_key_for_path(f"/kasir/{layar}/{ruas}"), key,
                    f"/kasir/{layar}/{ruas} tidak mewarisi izin layarnya")

    def test_tidak_bocor_lewat_layar_lain(self):
        """Retur/pembelian tak punya kotak pelanggan, jadi tak perlu — dan
        mendaftarkannya di sana berarti membuka piutang bagi menu yang tak
        pernah menyentuhnya."""
        from django.urls import NoReverseMatch, reverse

        for layar in ("penjualan-retur", "pembelian", "pembelian-retur"):
            with self.assertRaises(NoReverseMatch):
                reverse(f"kasir_info_customer_{layar}")

    def test_layar_tertutup_ikut_menutup_endpoint(self):
        """Tanpa tautan, seluruh layar penjualan tertutup — termasuk ini."""
        server = _profil_server()
        spv = User.objects.create_user(
            "spv_p", password="rahasia-kuat-123", role=Role.SUPERVISOR,
            server_profile=server)
        self.client.force_login(spv)
        r = self.client.get("/kasir/penjualan/info-customer", {"kd_customer": "CAA111"})
        self.assertEqual(r.status_code, 403)


class BayarNotaTests(TestCase):
    """Uang yang diterima kasir: dicatat saat simpan, dibaca saat cetak.

    `t_penjualan` legacy tak punya kolomnya dan database itu milik bersama,
    jadi angkanya tinggal di pangkal. Yang dijaga di sini bukan aritmetikanya
    (itu di test_penjualan) melainkan hal-hal yang gagal tanpa suara:

    1. **Pangkal yang bermasalah tak boleh menjatuhkan nota yang sudah jadi.**
       Nota sudah di-commit ke MS SQL saat pencatatan bayar dijalankan.
    2. **Nol bukan nilai.** Layar Order tak punya isian bayar sama sekali;
       mencatat "0" di sana berarti mengaku tahu sesuatu yang tak ditanyakan.
    """

    def setUp(self):
        self.server = _profil_server()
        self.kasir = User.objects.create_user(
            "kasir_b", password="rahasia-kuat-123", role=Role.KASIR,
            server_profile=self.server)
        # Request sungguhan, bukan objek tipis: jalur gagalnya memanggil
        # `log_activity`, yang membaca `request.META` untuk IP.
        self.req = RequestFactory().post("/kasir/penjualan/save")
        self.req.user = self.kasir

    def test_tersimpan_dan_terbaca_kembali(self):
        vk._simpan_bayar(self.req, self.server, "SC2609210001", 600000)
        self.assertEqual(
            pj._bayar_tercatat(self.server, "SC2609210001"), 600000.0)

    def test_nol_dan_kosong_tak_dicatat(self):
        for nilai in (0, "", None, "bukan angka"):
            vk._simpan_bayar(self.req, self.server, "SC2609210002", nilai)
        self.assertIsNone(pj._bayar_tercatat(self.server, "SC2609210002"))

    def test_simpan_ulang_memperbarui_bukan_menggandakan(self):
        """Nomor nota unik per server; dua baris untuk satu nota berarti dua
        jawaban berbeda untuk 'berapa yang dibayar'."""
        vk._simpan_bayar(self.req, self.server, "SC2609210003", 500000)
        vk._simpan_bayar(self.req, self.server, "SC2609210003", 700000)
        self.assertEqual(
            BayarNota.objects.filter(no_transaksi="SC2609210003").count(), 1)
        self.assertEqual(
            pj._bayar_tercatat(self.server, "SC2609210003"), 700000.0)

    def test_kegagalan_pangkal_tak_melempar(self):
        """Nota sudah tersimpan di MS SQL saat ini dipanggil — melempar di sini
        membuat kasir mengira notanya gagal, lalu mengetiknya dua kali."""
        with patch.object(BayarNota.objects, "update_or_create",
                          side_effect=RuntimeError("pangkal mati")):
            vk._simpan_bayar(self.req, self.server, "SC2609210004", 100000)
        self.assertIsNone(pj._bayar_tercatat(self.server, "SC2609210004"))

    def test_nota_beda_server_tak_saling_menimpa(self):
        """`no_transaksi` bertabrakan antar server: kode yang sama menunjuk
        nota yang lain di gudang dan di tiap toko."""
        lain = ServerProfile.objects.create(
            name="TOKO B", host="h2", db_name="LAIN", username="sa",
            password_encrypted="x")
        vk._simpan_bayar(self.req, self.server, "SC0001", 111000)
        vk._simpan_bayar(self.req, lain, "SC0001", 222000)
        self.assertEqual(pj._bayar_tercatat(self.server, "SC0001"), 111000.0)
        self.assertEqual(pj._bayar_tercatat(lain, "SC0001"), 222000.0)


class BayarLewatHttpTests(TestCase):
    """Bayar dari layar benar-benar SAMPAI ke pangkal lewat rute simpan.

    `BayarNotaTests` di atas membuktikan helpernya bekerja — bukan bahwa view
    memanggilnya dengan angka yang dikirim layar. Jebakan itu sudah pernah
    terjadi di proyek ini (lihat CLAUDE.md soal `_uang_bespoke`): versi pertama
    tetap hijau padahal penyaringnya sudah dicabut dari view. Karena itu tes ini
    menembak HTTP sungguhan; `buat_nota` dipalsukan supaya MS SQL tak disentuh.
    """

    def setUp(self):
        self.server = _profil_server()
        self.kasir = User.objects.create_user(
            "kasir_http", password="rahasia-kuat-123", role=Role.KASIR,
            server_profile=self.server)
        TautanUser.objects.create(user=self.kasir, profile=self.server,
                                  kd_user="UAA002", kd_divisi="DAA000")
        self.client.force_login(self.kasir)

    def _simpan(self, url, **isi):
        hasil = {"no_transaksi": "SC2609210099", "no_order": "",
                 "total": 500_000.0, "baris": 2}
        data = {"kd_customer": "CAA000", "kd_jenis": "JAA000", "kd_kas": "KAA001",
                "kd_voucher": "VAA000", "items": [{"kd_barang": "X", "qty": 1}]}
        data.update(isi)
        with patch("apps.transactions.penjualan.buat_nota", return_value=hasil), \
             patch("apps.transactions.penjualan.buat_order",
                   return_value={"no_order": "OJ2609210099", "total": 500_000.0, "baris": 2}):
            return self.client.post(url, data, content_type="application/json")

    def test_bayar_dari_layar_tercatat(self):
        self._simpan("/kasir/penjualan/save", bayar=600000)
        b = BayarNota.objects.get(no_transaksi="SC2609210099")
        self.assertEqual(float(b.dibayar), 600000.0)
        self.assertEqual(b.profile_id, self.server.pk)
        self.assertEqual(b.dibuat_oleh_id, self.kasir.pk)

    def test_bayar_nol_tak_mencatat_apa_apa(self):
        """Nol berarti "tak ditanyakan", bukan "dibayar nol" — dan nota tanpa
        catatan bayar mencetak tanpa baris Bayar/Kembali, yang benar."""
        self._simpan("/kasir/penjualan/save", bayar=0)
        self.assertFalse(BayarNota.objects.exists())

    def test_tanpa_kunci_bayar_sama_sekali_tetap_aman(self):
        """Layar lama (bundel belum di-build ulang) tak mengirim kunci ini."""
        self._simpan("/kasir/penjualan/save")
        self.assertFalse(BayarNota.objects.exists())

    def test_layar_order_tak_pernah_mencatat_bayar(self):
        """Order belum ada uang berpindah; uangnya berpindah saat jadi nota."""
        self._simpan("/kasir/penjualan-order/save", bayar=600000)
        self.assertFalse(BayarNota.objects.exists())

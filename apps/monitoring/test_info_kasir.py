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

from django.test import TestCase

from apps.auth_app.models import Role, TautanUser, User
from apps.connections.models import ServerProfile
from apps.core.menus import menu_key_for_path

PROFIL = {"kd_customer": "CAA111", "nama": "TOKO MAJU", "alamat": "Jl. Mawar",
          "hp": "0812", "telepon": "", "point": 12.0, "limit_kredit": 5_000_000.0,
          "disc": 2.5, "status": 1}
PIUTANG = [{"no_transaksi": "SC0001", "tanggal": "2026-01-02", "jatuh_tempo": "2026-02-01",
            "total_penjualan": 900_000.0, "total_cicilan": 100_000.0,
            "sisa_piutang": 800_000.0, "hari_terlambat": 12}]
HISTORI = [{"no_transaksi": "SC0009", "tanggal": "2026-08-01 10:00", "status": "Tunai",
            "nominal": 250_000.0, "customer": "TOKO MAJU"}]


def _profil_server():
    return ServerProfile.objects.create(
        name="TOKO A", host="h", db_name="SOLID_SIM", username="sa",
        password_encrypted="x", is_default=True)


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
        with patch("apps.transactions.penjualan.info_customer", return_value=dict(PROFIL)), \
             patch("apps.transactions.penjualan.piutang_customer",
                   return_value=[dict(r) for r in PIUTANG]), \
             patch("apps.transactions.penjualan.histori_nota",
                   return_value=[dict(r) for r in HISTORI]):
            return json.loads(self.client.get(url, params).content)

    def test_satu_round_trip_membawa_ketiganya(self):
        """Tiga endpoint terpisah = tiga perjalanan WAN untuk satu klik."""
        d = self._get("/kasir/penjualan/info-customer", kd_customer="CAA111")
        self.assertEqual(d["profil"]["nama"], "TOKO MAJU")
        self.assertEqual(len(d["piutang"]), 1)
        self.assertEqual(len(d["histori"]), 1)

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

    def test_kd_user_diambil_dari_tautan_bukan_dari_url(self):
        with patch("apps.transactions.penjualan.histori_nota",
                   return_value=[dict(r) for r in HISTORI]) as m:
            self.client.get("/kasir/penjualan/histori-user", {"kd_user": "UAA999"})
        self.assertEqual(m.call_args.kwargs["kd_user"], "UAA002")

    def test_kolom_uang_dicabut_di_server(self):
        self.spv.hidden_data_keys = ["nominal"]
        self.spv.save()
        with patch("apps.transactions.penjualan.histori_nota",
                   return_value=[dict(r) for r in HISTORI]):
            d = json.loads(self.client.get("/kasir/penjualan/histori-user").content)
        self.assertNotIn("nominal", d["rows"][0])
        self.assertIn("no_transaksi", d["rows"][0])


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

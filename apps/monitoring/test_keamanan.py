"""Tiga invarian keamanan yang tak punya gejala apa pun kalau dilanggar.

Ketiganya lolos dari review manual dengan mudah karena layarnya terlihat
baik-baik saja dalam ketiga kasus: alamat server yang bocor tak pernah dirender,
redirect yang dibajak tetap terasa seperti navigasi biasa, dan password yang
diganti tanpa sandi lama justru berhasil.

1. Prop bersama `connections`/`active_connection` tidak boleh membawa alamat
   server. Ia dikirim di SETIAP render, termasuk halaman /kasir/* yang sengaja
   tak dijaga penjaga Tailscale.
2. `redirect_to` harus path situs ini. Bukan cuma "diawali /": `//evil.com`
   diawali "/" tapi dibaca peramban sebagai host lain.
3. Ganti password sendiri wajib menyertakan password lama.
"""
import json
from ipaddress import ip_network

from django.test import RequestFactory, TestCase, override_settings

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.http import client_ip, redirect_aman

# Kolom yang hanya boleh muncul di layar Kelola Koneksi Server. Digabung jadi satu
# himpunan bernama supaya kolom baru yang sejenis (mis. instance name) cukup
# ditambahkan di satu tempat dan langsung dijaga ketiga jalur di bawah.
RAHASIA = {"host", "port", "db_name", "username"}


class PropKoneksiTests(TestCase):
    """Alamat server tidak boleh ikut prop bersama.

    Alasannya sudah dipakai kodenya sendiri di kartu status server dashboard:
    peta infrastruktur tak dibutuhkan siapa pun untuk MEMAKAI aplikasi. Yang
    dulu terjadi: setiap kasir menerima host, port, nama database, dan username
    (`sa`) server tokonya di dalam HTML tiap halaman yang ia buka.
    """

    def setUp(self):
        self.profil = ServerProfile.objects.create(
            name="UJI", db_type="grosir", host="10.9.9.9", port=1433,
            db_name="grosirUji", username="sa", is_default=True,
        )

    def test_as_dict_tidak_membawa_alamat_server(self):
        self.assertEqual(RAHASIA & set(self.profil.as_dict()), set())

    def test_as_dict_admin_membawa_alamat_server(self):
        # Layar Kelola Koneksi Server memang menampilkan & menyuntingnya; kalau
        # ini ikut dikosongkan, form editnya diam-diam menyimpan host kosong.
        self.assertTrue(RAHASIA <= set(self.profil.as_dict_admin()))

    def test_prop_bersama_di_halaman_kasir_bersih(self):
        kasir = User.objects.create_user(
            "kasir_k", password="rahasia-kuat-123", role=Role.KASIR,
            server_profile=self.profil,
        )
        self.client.force_login(kasir)
        # Halaman kasir mana pun; yang diperiksa prop BERSAMA-nya, bukan isinya.
        props = json.loads(self.client.get(
            "/kasir/stok", HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0",
        ).content)["props"]

        # Diperiksa per prop, bukan dengan mencari kata di seluruh HTML: kata
        # "username" memang muncul sah di `auth_user` (username orangnya
        # sendiri), jadi pencarian polos akan selalu gagal dan tesnya lalu
        # dilonggarkan sampai tak menjaga apa pun.
        self.assertEqual(RAHASIA & set(props["active_connection"]), set())
        for k in props["connections"]:
            self.assertEqual(RAHASIA & set(k), set())

        # Sekaligus dari sisi hasil akhirnya: alamatnya tak boleh muncul di HTML
        # yang benar-benar terkirim, lewat prop mana pun.
        self.assertNotIn("10.9.9.9", self.client.get("/kasir/stok").content.decode())


class RedirectAmanTests(TestCase):
    """`redirect_to` datang dari layar, jadi ia input yang tak dipercaya.

    Bentuk lama di `connections_set_default` meneruskannya apa adanya, dan
    endpoint itu justru dikecualikan dari pemeriksaan menu (_MENU_EXEMPT_RE)
    supaya navbar tetap hidup — jadi ia terjangkau setiap akun yang bisa login.
    """

    def _tujuan(self, nilai):
        return redirect_aman({"redirect_to": nilai}, "/admin-panel/connections")["Location"]

    def test_path_lokal_diikuti(self):
        self.assertEqual(self._tujuan("/kasir/penjualan"), "/kasir/penjualan")
        self.assertEqual(self._tujuan("/admin-panel/dashboard"), "/admin-panel/dashboard")

    def test_host_lain_ditolak(self):
        # `//evil.com` dan `/\evil.com` sama-sama diawali "/" — pemeriksaan
        # startswith("/") buatan sendiri akan meloloskan keduanya.
        for jahat in ("https://evil.com", "//evil.com", "/\\evil.com", "http:/evil.com"):
            self.assertEqual(
                self._tujuan(jahat), "/admin-panel/connections", f"{jahat} lolos")

    def test_kosong_jatuh_ke_bawaan(self):
        self.assertEqual(self._tujuan(""), "/admin-panel/connections")
        self.assertEqual(self._tujuan(None), "/admin-panel/connections")


class ClientIpTests(TestCase):
    """`X-Forwarded-For` hanya boleh dipercaya dari proxy yang kita pasang sendiri.

    Kegagalan yang dijaga di sini tak punya gejala apa pun: begitu aplikasi
    diletakkan di belakang reverse proxy, `REMOTE_ADDR` jadi 127.0.0.1 untuk
    SEMUA permintaan — yang kebetulan ada di `ADMIN_IP_ALLOWLIST` — dan
    `ENFORCE_TAILSCALE=1` berubah jadi hiasan tanpa satu pun galat.

    Sisi sebaliknya sama berbahayanya: kalau headernya dipercaya tanpa syarat,
    siapa pun cukup mengirim `X-Forwarded-For: 100.64.0.1` untuk mengaku datang
    dari jaringan kantor.
    """

    def _ip(self, **meta):
        permintaan = RequestFactory().get("/", **meta)
        return client_ip(permintaan)

    def test_tanpa_proxy_header_diabaikan(self):
        # Bawaan: TRUSTED_PROXIES kosong. Header boleh berisi apa saja.
        self.assertEqual(
            self._ip(REMOTE_ADDR="203.0.113.9", HTTP_X_FORWARDED_FOR="100.64.0.1"),
            "203.0.113.9",
        )

    @override_settings(TRUSTED_PROXIES=[ip_network("127.0.0.1/32")])
    def test_dari_proxy_tepercaya_header_dipakai(self):
        self.assertEqual(
            self._ip(REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="100.64.0.7"),
            "100.64.0.7",
        )

    @override_settings(TRUSTED_PROXIES=[ip_network("127.0.0.1/32")])
    def test_nilai_palsu_di_kiri_tak_terpilih(self):
        # nginx `$proxy_add_x_forwarded_for` MENAMBAHKAN peer asli di ujung
        # kanan, jadi apa pun yang diketik klien selalu berada di kiri. Ditelusuri
        # dari kanan, yang terpilih peer aslinya — bukan pengakuannya.
        self.assertEqual(
            self._ip(REMOTE_ADDR="127.0.0.1",
                     HTTP_X_FORWARDED_FOR="100.64.0.1, 203.0.113.9"),
            "203.0.113.9",
        )

    @override_settings(TRUSTED_PROXIES=[ip_network("127.0.0.1/32")])
    def test_proxy_tepercaya_tanpa_header_jatuh_ke_peer(self):
        self.assertEqual(self._ip(REMOTE_ADDR="127.0.0.1"), "127.0.0.1")

    @override_settings(ENFORCE_TAILSCALE=True)
    def test_penjaga_tailscale_tak_bisa_dikelabui_header(self):
        self.client.force_login(self._boss("boss_ip"))
        r = self.client.get(
            "/admin-panel/dashboard",
            REMOTE_ADDR="203.0.113.9",              # bukan CGNAT, bukan loopback
            HTTP_X_FORWARDED_FOR="100.64.0.1",      # pengakuan "saya dari Tailscale"
        )
        self.assertEqual(r.status_code, 403)

    @override_settings(
        ENFORCE_TAILSCALE=True,
        ADMIN_ALLOWED_NETWORKS=[ip_network("100.64.0.0/10"),
                                ip_network("192.168.7.0/24")],
    )
    def test_rentang_lan_tambahan_diizinkan(self):
        # Kantor yang perangkatnya tak ber-Tailscale dinyatakan LEWAT DAFTAR,
        # bukan lewat jembatan yang meloloskan semua orang diam-diam.
        self.client.force_login(self._boss("boss_lan"))
        self.assertEqual(
            self.client.get("/admin-panel/dashboard", REMOTE_ADDR="192.168.7.31").status_code,
            200,
        )
        # Rentang lain tetap ditolak — daftar tambahan bukan berarti terbuka.
        self.assertEqual(
            self.client.get("/admin-panel/dashboard", REMOTE_ADDR="192.168.9.31").status_code,
            403,
        )

    def _boss(self, nama):
        return User.objects.create_user(
            nama, password="rahasia-kuat-123", role=Role.SUPERADMIN)


class GantiPasswordSendiriTests(TestCase):
    """Peramban yang ditinggal terbuka tak boleh cukup untuk mengambil alih akun."""

    def setUp(self):
        self.u = User.objects.create_user(
            "boss_p", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.client.force_login(self.u)

    def _simpan(self, muatan):
        return self.client.post(
            "/admin-panel/profile/save", muatan,
            content_type="application/json", REMOTE_ADDR="127.0.0.1",
        )

    def test_tanpa_password_lama_ditolak(self):
        self._simpan({"name": "Boss", "username": "boss_p", "password": "sandi-baru-9988"})
        self.u.refresh_from_db()
        self.assertTrue(self.u.check_password("rahasia-kuat-123"))

    def test_password_lama_salah_ditolak(self):
        self._simpan({"name": "Boss", "username": "boss_p",
                      "password": "sandi-baru-9988", "password_lama": "tebakan-salah"})
        self.u.refresh_from_db()
        self.assertTrue(self.u.check_password("rahasia-kuat-123"))

    def test_password_lama_benar_diterima(self):
        self._simpan({"name": "Boss", "username": "boss_p",
                      "password": "sandi-baru-9988", "password_lama": "rahasia-kuat-123"})
        self.u.refresh_from_db()
        self.assertTrue(self.u.check_password("sandi-baru-9988"))

    def test_ubah_nama_tak_menuntut_password_lama(self):
        # Halaman ini lebih sering dipakai untuk memperbaiki nama daripada untuk
        # mengganti sandi; menuntutnya di kedua jalur membuat orang mengira
        # seluruh formulir terkunci.
        self._simpan({"name": "Nama Baru", "username": "boss_p"})
        self.u.refresh_from_db()
        self.assertEqual(self.u.first_name, "Nama")

"""Rute yang baru ditambahkan benar-benar tersambung: Hutang Supplier, kedua
laporan Order, dan jalur tulis Pendapatan Lain-Lain.

Bukan uji angka — angkanya diverifikasi terhadap `mon_t_hutang_aktif` dan tabel
dasar di server nyata. Ini menjaga hal yang paling mudah lupa saat menambah
laporan: satu dari empat tempat (reports/views/urls/menus) tak ikut diubah, dan
halamannya baru ketahuan hilang saat dibuka orang.
"""
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.core.menus import ALL_MENUS

_HALAMAN = (
    "/admin-panel/laporan/hutang",
    "/admin-panel/laporan/order-penjualan",
    "/admin-panel/laporan/order-pembelian",
    "/admin-panel/kas/input/pendapatan",
    "/admin-panel/laporan/laba-rugi",
)
_EXPORT = (
    "/admin-panel/laporan/hutang/export",
    "/admin-panel/laporan/order-penjualan/export",
    "/admin-panel/laporan/order-pembelian/export",
    "/admin-panel/laporan/laba-rugi/export",
)
_MENU_BARU = ("hutang", "order_penjualan", "order_pembelian", "kas_pendapatan", "laba_rugi")


class RuteBaru(TestCase):
    def setUp(self):
        # role=SUPERADMIN, bukan sekadar create_superuser: gerbang menu membaca
        # `role`, jadi superuser Django tanpa role tetap dilempar ke /kasir/stok.
        self.sa = User.objects.create_superuser(
            "sa1", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.client.force_login(self.sa)

    def test_halaman_terpasang(self):
        for url in _HALAMAN:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_export_terpasang(self):
        # Tanpa koneksi aktif jalur export mengalihkan ke halamannya dengan flash
        # — yang dijaga di sini rutenya ada, bukan isi berkasnya.
        for url in _EXPORT:
            self.assertIn(self.client.get(url).status_code, (200, 302), url)

    def test_menu_terdaftar_dan_href_cocok_dengan_rute(self):
        peta = {m["key"]: m["href"] for m in ALL_MENUS}
        for k in _MENU_BARU:
            self.assertIn(k, peta)
            # Href menu yang meleset dari rute = menu yang mengarah ke 404.
            self.assertEqual(self.client.get(peta[k]).status_code, 200, k)

    def test_layar_tulis_pendapatan_wajib_admin_dan_tautan(self):
        m = next(m for m in ALL_MENUS if m["key"] == "kas_pendapatan")
        self.assertTrue(m.get("admin_only"))
        self.assertTrue(m.get("butuh_tautan"))


class LabaRugiIzinUang(TestCase):
    """Laba Rugi berisi rupiah seluruhnya, jadi ia menolak — bukan menampilkan
    tabel bernilai kosong. Yang dijaga: LAYAR dan EXPORT ditolak sama-sama.
    Pembatasan yang lupa dipasang di export sudah dua kali membuat pembatasan di
    layar tak berarti apa-apa."""

    def setUp(self):
        # Role ADMIN, bukan SUPERADMIN: `User.hidden_data()` sengaja mengembalikan
        # himpunan kosong untuk superadmin, jadi menguji dengan superadmin akan
        # hijau tanpa membuktikan apa pun.
        self.u = User.objects.create_user(
            "adm9", password="rahasia-kuat-123", role=Role.ADMIN,
            hidden_data_keys=["nominal"], allowed_menu_keys=["laba_rugi"])
        self.client.force_login(self.u)

    def _req(self):
        return type("R", (), {"user": self.u})()

    def test_izin_uang_menutup_laporan(self):
        from apps.monitoring import views
        self.assertFalse(views._laba_rugi_boleh(self._req()))

    def test_export_ditolak_dengan_pesannya_sendiri(self):
        from apps.monitoring import views
        r = self.client.get("/admin-panel/laporan/laba-rugi/export")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/admin-panel/laporan/laba-rugi")
        # Pesan flash-nya yang membedakan "ditolak karena izin" dari "ditolak
        # karena tak ada koneksi aktif" — keduanya mengalihkan ke URL yang sama.
        self.assertEqual(self.client.session.get("flash_error"), views._LABA_RUGI_DITOLAK)

    def test_akun_tanpa_batasan_tidak_ikut_ditolak(self):
        from apps.monitoring import views
        bebas = User.objects.create_user("adm10", password="rahasia-kuat-123", role=Role.ADMIN)
        self.assertTrue(views._laba_rugi_boleh(type("R", (), {"user": bebas})()))

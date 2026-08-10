"""Layar yang MENULIS ke server legacy hilang saat akunnya belum ditautkan.

Tujuh layar (`penjualan`, `penjualan order`, empat layar Transaksi, dan Koreksi
Stok) memanggil `tautan_wajib()` saat Simpan ditekan. Sebelum ini menunya tetap
terlihat dan halamannya tetap terbuka, jadi penolakannya baru datang setelah
keranjang terisi — dan bunyinya seperti kegagalan sistem, bukan seperti
pengaturan yang kurang.

Yang paling penting dijaga di sini: gerbangnya **per koneksi**. Tautan koneksi A
tidak boleh membuka menu di koneksi B, karena `kd_user` yang sama menunjuk orang
berbeda di server berbeda (lihat apps/auth_app/tautan.py). Dan Cek Stok serta
Cetak Faktur **tidak** ikut digerbangi: keduanya hanya membaca, dan mencabutnya
membuat kasir tanpa tautan tak punya satu pun halaman kasir — landing-nya lalu
jatuh ke Bantuan, yang ada di /admin-panel dan tertutup penjaga Tailscale dari
jaringan toko.
"""
from django.test import TestCase

from apps.auth_app.models import Role, TautanUser, User
from apps.connections.models import ServerProfile
from apps.core.menus import KEYS_BUTUH_TAUTAN, assignable_menus, menus_for
from core import mssql

TULIS = {
    "kasir_penjualan", "kasir_penjualan_order", "kasir_retur_penjualan",
    "kasir_pembelian", "kasir_pembelian_order", "kasir_retur_pembelian",
    "koreksi_stok",
    # Kas: `kd_user` menentukan transaksi tercatat atas nama siapa, dan pada
    # penambahan/mutasi kas `kd_divisi` tautan itu pula yang jadi awalan
    # nomornya — tabelnya sendiri tak punya kolom divisi.
    "kas_biaya_input", "kas_penambahan", "kas_mutasi",
}


def _profil(nama, **kw):
    return ServerProfile.objects.create(
        name=nama, host=f"host-{nama}", db_name="SOLID_SIM",
        username="sa", password_encrypted="x", **kw)


def _keys(user):
    # Memo tautan menempel pada instance user dan berkunci id profil; di test
    # objeknya dipakai ulang lintas koneksi, jadi dibersihkan tiap pemanggilan.
    user._memo_tautan = None
    return {m["key"] for m in menus_for(user)}


class GerbangTautanTests(TestCase):
    def setUp(self):
        self.a = _profil("TOKO A", is_default=True)
        self.b = _profil("TOKO B")
        self.spv = User.objects.create_user(
            "spv_t", password="rahasia-kuat-123", role=Role.SUPERVISOR,
            server_profile=self.a)
        self.boss = User.objects.create_user(
            "boss_t", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        mssql.set_request_profile_id(self.a.id)
        self.addCleanup(mssql.clear_request_profile)

    def _tautkan(self, user, profile, **kw):
        nilai = {"kd_user": "UAA002", "kd_divisi": "DAA000"}
        nilai.update(kw)
        return TautanUser.objects.create(user=user, profile=profile, **nilai)

    def test_layar_tulis_hilang_tanpa_tautan(self):
        keys = _keys(self.spv)
        for k in TULIS & set(menu["key"] for menu in assignable_menus()):
            self.assertNotIn(k, keys, f"{k} masih tampil padahal belum ditautkan")

    def test_layar_baca_tetap_ada_supaya_kasir_tak_terkunci_total(self):
        keys = _keys(self.spv)
        self.assertIn("kasir_stok", keys)
        self.assertIn("kasir_faktur", keys)

    def test_tautan_lengkap_memunculkan_kembali(self):
        self._tautkan(self.spv, self.a)
        keys = _keys(self.spv)
        self.assertIn("kasir_penjualan", keys)
        self.assertIn("kasir_retur_penjualan", keys)

    def test_gerbangnya_per_koneksi(self):
        """Tautan di TOKO A tidak boleh membuka layar saat aktif di TOKO B."""
        self._tautkan(self.spv, self.a)
        self.assertIn("kasir_penjualan", _keys(self.spv))
        mssql.set_request_profile_id(self.b.id)
        self.assertNotIn("kasir_penjualan", _keys(self.spv))

    def test_divisi_kosong_belum_cukup(self):
        """kd_user saja tak cukup — kd_divisi menentukan awalan nomor & stok."""
        self._tautkan(self.spv, self.a, kd_divisi="")
        self.assertNotIn("kasir_penjualan", _keys(self.spv))

    def test_pegawai_tidak_diwajibkan(self):
        """Sejalan dengan tautan_wajib: pegawai cuma isian bawaan form."""
        self._tautkan(self.spv, self.a, kd_pegawai="")
        self.assertIn("kasir_penjualan", _keys(self.spv))

    def test_superadmin_ikut_digerbangi(self):
        """Ia juga tak bisa menyimpan tanpa kd_user di koneksi itu."""
        keys = _keys(self.boss)
        self.assertNotIn("koreksi_stok", keys)
        self.assertNotIn("kasir_penjualan", keys)
        self.assertIn("stock", keys)  # menu baca-saja tetap utuh
        self._tautkan(self.boss, self.a)
        self.assertIn("koreksi_stok", _keys(self.boss))

    def test_tanpa_koneksi_tidak_digerbangi(self):
        """Ketiadaan koneksi masalah lain, dan sudah punya suaranya sendiri.

        Menyembunyikan menu di sini akan menuduh orang belum ditautkan padahal
        yang kurang adalah servernya."""
        mssql.clear_request_profile()
        ServerProfile.objects.all().delete()
        self.assertIn("kasir_penjualan", _keys(self.spv))

    def test_tetap_bisa_diberikan_di_kelola_menu(self):
        """Gerbang ini soal koneksi, bukan soal pemberian menu.

        Menyembunyikannya dari Kelola Menu justru membuat superadmin tak bisa
        memberikan layar itu sebelum tautannya sempat dibuat."""
        assignable = {m["key"] for m in assignable_menus()}
        for k in TULIS:
            self.assertIn(k, assignable)

    def test_daftar_kunci_cocok_dengan_flag(self):
        self.assertEqual(KEYS_BUTUH_TAUTAN, TULIS)


class UrlTertutupTests(TestCase):
    """Menu yang hilang tak boleh bisa dicapai dengan mengetik URL-nya."""

    def setUp(self):
        self.a = _profil("TOKO A", is_default=True)
        self.spv = User.objects.create_user(
            "spv_u", password="rahasia-kuat-123", role=Role.SUPERVISOR,
            server_profile=self.a)
        self.client.force_login(self.spv)

    def test_get_ditolak_dengan_alasan_yang_benar(self):
        resp = self.client.get("/kasir/penjualan")
        self.assertEqual(resp.status_code, 403)
        isi = resp.content.decode()
        self.assertIn("Kelola Tautan User", isi)
        # Bukan pesan menu-dicabut: itu akan mengirim orangnya ke Kelola Menu.
        self.assertNotIn("belum dibuka untuk Anda", isi)

    def test_post_simpan_ikut_tertutup(self):
        resp = self.client.post("/kasir/penjualan/save", {},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_endpoint_cari_ikut_tertutup_lewat_prefix(self):
        """cari-barang membocorkan nama & harga; ia mewarisi kunci layarnya."""
        resp = self.client.get("/kasir/penjualan/cari-barang", {"cari": "a"})
        self.assertEqual(resp.status_code, 403)

    def test_layar_baca_tetap_terbuka(self):
        self.assertEqual(self.client.get("/kasir/stok").status_code, 200)

    def test_terbuka_setelah_ditautkan(self):
        TautanUser.objects.create(
            user=self.spv, profile=self.a, kd_user="UAA002", kd_divisi="DAA000")
        self.assertEqual(self.client.get("/kasir/penjualan").status_code, 200)

    def test_menu_yang_memang_dicabut_tetap_pesan_menu(self):
        """Tautan bukan alasan segalanya: menu yang tak diberikan tetap
        berbunyi seperti menu yang tak diberikan."""
        self.spv.allowed_menu_keys = ["kasir_stok"]
        self.spv.save()
        resp = self.client.get("/kasir/penjualan", follow=True)
        self.assertNotContains(resp, "belum ditautkan untuk koneksi ini",
                               status_code=resp.status_code)

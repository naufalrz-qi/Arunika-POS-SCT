"""Hasil pencarian Koreksi Stok WAJIB membawa satuannya.

Ini menjaga cacat yang pernah lolos ke layar: `inv.cek_stok()` hanya
mengembalikan kd_barang/nama/stok_akhir/stok_min — tak ada kd_satuan sama
sekali. Baris yang masuk grid jadi bersatuan kosong, dan karena `kd_satuan`
wajib terisi sebelum sebuah baris bisa disimpan, layarnya buntu: 300 baris
hasil "Muat semua" berarti 300 dropdown yang harus dibuka satu per satu, tiap
satu round-trip, sebelum Simpan bisa ditekan sekali pun.

Yang menyakitkan, semuanya tetap "berfungsi" di tes lama — jalur tulisnya benar,
yang salah adalah data yang tak pernah sampai ke sana.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.auth_app.models import Role, TautanUser, User
from apps.connections.models import ServerProfile

BARANG = [
    {"kd_barang": "000-06", "nama": "MOBIL R/C", "stok_akhir": 12.0, "stok_min": 1.0},
    {"kd_barang": "1001", "nama": "GASING LAMPU", "stok_akhir": 0.0, "stok_min": 0.0},
]
SATUAN = {
    "000-06": [{"kd_satuan": "SAA000", "satuan": "PCS", "jumlah": 1.0},
               {"kd_satuan": "SAA001", "satuan": "LUSIN", "jumlah": 12.0}],
    "1001": [{"kd_satuan": "SAA000", "satuan": "PCS", "jumlah": 1.0}],
}


class HasilCariMembawaSatuanTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            "boss6", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.client.force_login(self.boss)
        profile = ServerProfile.objects.create(
            name="TOKO A", host="h", db_name="SOLID_SIM", username="sa",
            password_encrypted="x", is_default=True)
        # Koreksi Stok ber-`butuh_tautan`: tanpa baris ini seluruh layarnya
        # (termasuk /cari lewat pencocokan prefix) dijawab 403 oleh penjaga.
        TautanUser.objects.create(
            user=self.boss, profile=profile, kd_user="UAA002", kd_divisi="DAA001")

    def _cari(self, **params):
        with patch("apps.monitoring.views.inv.cek_stok", return_value=list(BARANG)), \
             patch("apps.monitoring.views._satuan_banyak", return_value=SATUAN):
            return self.client.get("/admin-panel/inventory/koreksi-stok/cari",
                                   {"cari": "mobil", **params}).json()

    def test_tiap_baris_punya_satuan_yang_bisa_dipakai(self):
        """Tanpa ini baris masuk grid bersatuan kosong dan Simpan selalu gagal."""
        for r in self._cari()["rows"]:
            self.assertTrue(r["satuan_list"], f"{r['kd_barang']} tanpa satuan")
            self.assertTrue(r["satuan_list"][0]["kd_satuan"].strip())

    def test_satuan_membawa_isi_untuk_konversi(self):
        """`jumlah` yang membuat stok dasar 120 tampil sebagai 10 LUSIN. Tanpa
        ia, layar diam-diam memperlakukan setiap satuan seolah isinya 1."""
        lusin = next(s for s in self._cari()["rows"][0]["satuan_list"]
                     if s["kd_satuan"] == "SAA001")
        self.assertEqual(lusin["jumlah"], 12.0)

    def test_harga_tak_pernah_ikut_terkirim(self):
        """Layar koreksi tak menampilkan harga; kolom yang tak dikirim tak bisa
        bocor lewat pembatasan hidden_data_keys yang terlupakan."""
        for r in self._cari()["rows"]:
            self.assertNotIn("harga_jual", r)
            for s in r["satuan_list"]:
                self.assertNotIn("harga_jual", s)

    def test_terpotong_dilaporkan_bukan_didiamkan(self):
        """Barang yang hilang diam-diam dari daftar opname = selisih yang tak
        pernah dikoreksi."""
        banyak = [{**BARANG[0], "kd_barang": f"B{i}"} for i in range(25)]
        with patch("apps.monitoring.views.inv.cek_stok", return_value=banyak), \
             patch("apps.monitoring.views._satuan_banyak", return_value={}):
            d = self.client.get("/admin-panel/inventory/koreksi-stok/cari",
                                {"cari": "b", "limit": 20}).json()
        self.assertTrue(d["terpotong"])
        self.assertEqual(len(d["rows"]), 20)

    def test_limit_tak_bisa_melewati_batas_muat(self):
        """Kotak cari mengirim limit apa adanya dari URL; tanpa clamp, satu
        permintaan bisa menarik seluruh universe 55rb baris ke layar."""
        from apps.monitoring.views import _BATAS_MUAT

        with patch("apps.monitoring.views.inv.cek_stok") as cek, \
             patch("apps.monitoring.views._satuan_banyak", return_value={}):
            cek.return_value = []
            self.client.get("/admin-panel/inventory/koreksi-stok/cari",
                            {"cari": "x", "limit": "99999"})
        self.assertEqual(cek.call_args.kwargs["limit"], _BATAS_MUAT + 1)


class AksesKoreksiTests(TestCase):
    def test_supervisor_ditolak_dari_pencarian(self):
        """Rutenya mewarisi menu `koreksi_stok` lewat pencocokan prefix."""
        spv = User.objects.create_user(
            "spv6", password="rahasia-kuat-123", role=Role.SUPERVISOR)
        self.client.force_login(spv)
        r = self.client.get("/admin-panel/inventory/koreksi-stok/cari", {"cari": "x"})
        self.assertNotEqual(r.status_code, 200)

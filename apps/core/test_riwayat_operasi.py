"""Riwayat Operasi: satu tabel untuk semua pekerjaan latar.

Dua hal yang dijaga di sini, keduanya sudah pernah salah di tempat lain:

1. **Pencatat tak boleh menjatuhkan yang dicatatnya.** `log_sync` dipanggil dari
   dalam job yang sedang berjalan. Objek profil yang bukan `ServerProfile`
   tersimpan pernah membuatnya melempar `ValueError` dan menggagalkan seluruh
   sapuan harga — sebuah baris log yang membunuh pekerjaannya.

2. **Aturan sunyi.** `harga_sync` berjalan 1.440× sehari. Tanpa penjaga, satu
   baris per sapuan akan menimbun tabel sampai kejadian yang sungguhan tak bisa
   ditemukan — dan tak ada gejalanya sampai seseorang mencoba membacanya
   berbulan-bulan kemudian.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.connections.models import ServerProfile
from apps.core.models import SyncLog, log_sync
from apps.transactions import harga_sync


class ProfilPalsu:
    """Objek berperilaku-profil yang TIDAK tersimpan — persis yang dipakai
    test unit job latar, dan persis yang dulu membuat log_sync melempar."""

    def __init__(self, name):
        self.name = name
        self.pk = 7  # pk terisi pun tetap bukan ServerProfile


class LogSyncTanpaRequest(TestCase):
    def test_tanpa_request_dan_tanpa_user(self):
        log_sync(None, feature="backup", mode="", src=None, dst=None,
                 compared=0, applied=1, username="(terjadwal)")
        baris = SyncLog.objects.get()
        self.assertIsNone(baris.user_id)
        self.assertEqual(baris.username, "(terjadwal)")
        self.assertEqual(baris.feature, "backup")

    def test_profil_palsu_tidak_melempar_dan_namanya_tetap_tersimpan(self):
        log_sync(None, feature="harga_sync", mode="cepat",
                 src=ProfilPalsu("GUDANG"), dst=ProfilPalsu("PRAYA"),
                 compared=3, applied=3, username="(terjadwal)")
        baris = SyncLog.objects.get()
        self.assertIsNone(baris.src_profile_id)
        self.assertIsNone(baris.dst_profile_id)
        # Nama TETAP masuk: kolomnya memang didenormalisasi supaya baris
        # bertahan sesudah profilnya dihapus, jadi kehilangan FK bukan alasan
        # kehilangan informasi.
        self.assertEqual(baris.src_name, "GUDANG")
        self.assertEqual(baris.dst_name, "PRAYA")

    def test_profil_sungguhan_tetap_terhubung(self):
        p = ServerProfile.objects.create(name="GUDANG", host="h", db_name="d", username="u")
        log_sync(None, feature="hub_pull", mode="segar", src=p, dst=None,
                 compared=0, applied=5)
        self.assertEqual(SyncLog.objects.get().src_profile_id, p.pk)

    def test_durasi_tersimpan(self):
        log_sync(None, feature="hub_pull", mode="segar", src=None, dst=None,
                 compared=0, applied=1, duration_ms=1234)
        self.assertEqual(SyncLog.objects.get().duration_ms, 1234)


def _peta(**kv):
    return {tuple(k.split("|")): v for k, v in kv.items()}


class AturanSunyi(TestCase):
    """Sapuan harga yang tidak mengubah apa pun TIDAK boleh menulis baris.

    Ini test inti Fase 1. `_loop_harga` berjalan tiap 60 detik; kalau penjaga
    ini dilepas, tabel riwayat terisi 1.440 baris kosong per hari dan tak ada
    satu pun test lain yang akan gagal karenanya.
    """

    def setUp(self):
        harga_sync._terakhir.clear()
        self.gudang = ProfilPalsu("GUDANG")
        self.toko = ProfilPalsu("TOKO_A")

    def _sapu(self, sumber, toko_harga, **kw):
        def baca(p):
            return sumber if p.name == "GUDANG" else toko_harga

        with patch.object(harga_sync, "baca_harga", side_effect=baca), \
             patch.object(harga_sync, "dorong",
                          return_value={"sku": 1, "per_toko": {"TOKO_A": 1}, "gagal": {}}):
            return harga_sync.sapu(self.gudang, [self.toko], **kw)

    def test_sapuan_tanpa_perubahan_tidak_menulis_apa_pun(self):
        sama = _peta(**{"A1|PCS": 1000})
        self._sapu(sama, dict(sama))            # sapuan pertama (dipaksa penuh), 0 beda
        self.assertEqual(SyncLog.objects.count(), 0)
        self._sapu(sama, dict(sama))            # sapuan cepat berikutnya, tetap 0
        self.assertEqual(SyncLog.objects.count(), 0)

    def test_sapuan_yang_mengubah_menulis_satu_baris(self):
        sumber = _peta(**{"A1|PCS": 1500})
        self._sapu(sumber, _peta(**{"A1|PCS": 1000}))   # toko tertinggal -> 1 SKU beda
        self.assertEqual(SyncLog.objects.count(), 1)
        baris = SyncLog.objects.get()
        self.assertEqual(baris.feature, "harga_sync")
        self.assertEqual(baris.compared_count, 1)
        self.assertEqual(baris.applied_count, 1)

    def test_dry_run_tidak_pernah_menulis(self):
        sumber = _peta(**{"A1|PCS": 1500})
        self._sapu(sumber, _peta(**{"A1|PCS": 1000}), dry_run=True)
        self.assertEqual(SyncLog.objects.count(), 0)

    def test_sumber_tak_terjangkau_tercatat_sebagai_gagal(self):
        import pyodbc

        with patch.object(harga_sync, "baca_harga", side_effect=pyodbc.Error("08001", "mati")):
            harga_sync.sapu(self.gudang, [self.toko], username="(terjadwal)")
        baris = SyncLog.objects.get()
        self.assertEqual(baris.status, "failed")
        self.assertIn("mati", baris.error_message)

    def test_sumber_tak_terjangkau_saat_dry_run_tetap_sunyi(self):
        """Pratinjau yang gagal menyambung tetaplah pratinjau. Barisnya akan
        terbaca sebagai sebar harga yang benar-benar gagal, padahal tak ada
        sebar harga yang dijalankan."""
        import pyodbc

        with patch.object(harga_sync, "baca_harga", side_effect=pyodbc.Error("08001", "mati")):
            harga_sync.sapu(self.gudang, [self.toko], dry_run=True)
        self.assertEqual(SyncLog.objects.count(), 0)


class LayarRiwayatOperasi(TestCase):
    """HTTP sungguhan dengan header partial-reload Inertia.

    Test yang memanggil view-nya langsung membuktikan fungsinya jalan, bukan
    bahwa rutenya memakainya — pelajaran dari `test_uang_e2e.UangBespoke`.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(username="sa", password="x", role="superadmin")
        self.client.force_login(self.user)
        for f, s in (("hub_pull", "ok"), ("harga_sync", "ok"), ("feed_sync", "failed")):
            log_sync(None, feature=f, mode="segar", src=None, dst=None,
                     compared=1, applied=2, status=s, username="(terjadwal)")

    def _props(self, query=""):
        resp = self.client.get(
            f"/admin-panel/master/sync-history{query}",
            HTTP_X_INERTIA="true",
            HTTP_X_INERTIA_PARTIAL_DATA="data",
            HTTP_X_INERTIA_PARTIAL_COMPONENT="Admin/MasterData/SyncHistory",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["props"]["data"]

    def test_tanpa_filter_memuat_semuanya(self):
        self.assertEqual(len(self._props()["rows"]), 3)

    def test_filter_fitur_dipakai_oleh_rutenya(self):
        data = self._props("?feature=hub_pull")
        self.assertEqual([r["feature"] for r in data["rows"]], ["hub_pull"])

    def test_filter_status(self):
        data = self._props("?status=failed")
        self.assertEqual([r["feature"] for r in data["rows"]], ["feed_sync"])

    def test_daftar_fitur_diturunkan_dari_isi_tabel(self):
        self.assertEqual(self._props()["fitur_tersedia"],
                         ["feed_sync", "harga_sync", "hub_pull"])

    def test_hari_nakal_tidak_menjatuhkan_halaman(self):
        self.assertEqual(len(self._props("?hari=bukan-angka")["rows"]), 3)

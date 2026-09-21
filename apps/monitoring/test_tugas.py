"""Runner tugas latar yang dipicu layar Kesehatan Sync.

Yang dijaga di sini adalah hal-hal yang tidak akan terlihat sampai produksi:
kunci satu-tugas-sekaligus, baris yang menggantung sesudah server mati, dan
rute tulis yang bisa dibuka akun non-superadmin.
"""
import threading
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bisnis.siapkan import Ditolak
from apps.connections.models import ServerProfile
from apps.core.models import SyncLog
from apps.monitoring import tugas


def _profil(nama, **kw):
    return ServerProfile.objects.create(
        name=nama, host="h", db_name=f"db_{nama}", username="u", **kw
    )


class RunnerTests(TestCase):
    def setUp(self):
        tugas._thread.clear()
        self.hub = _profil("AMPHOREUS")
        self.cabang = _profil("GUDANG", kode_sumber="GUDANG")

    def test_satu_tugas_dalam_satu_waktu(self):
        """Klik kedua dari tab lain harus DITOLAK, bukan menjalankan run kedua.

        Dua `pull_arsip` pada cabang yang sama menulis tabel yang sama di
        AMPHOREUS dan saling menimpa potongan.
        """
        selesai = threading.Event()
        # Thread yang TIDAK menyentuh database: yang diuji adalah kuncinya, dan
        # thread latar yang menulis SQLite di dalam transaksi TestCase kena
        # "database table is locked" — derau yang tak ada hubungannya dgn kunci.
        t = threading.Thread(target=selesai.wait, args=(5,), daemon=True)
        t.start()
        tugas._thread[999] = t
        try:
            self.assertTrue(tugas.sedang_berjalan())
            with self.assertRaises(Ditolak) as cm:
                tugas.mulai("segar", self.cabang, "sa")
            self.assertIn("berjalan", str(cm.exception).lower())
            self.assertEqual(SyncLog.objects.count(), 0)
        finally:
            selesai.set()
            t.join(timeout=5)
            tugas._thread.clear()

    def test_baris_yatim_jadi_gagal_bukan_menggantung(self):
        """Server mati di tengah tugas meninggalkan baris `berjalan`.

        Tanpa `rapikan_yatim`, baris itu menggantung selamanya DAN kunci
        satu-tugas-sekaligus ikut macet permanen sesudah restart.
        """
        run = SyncLog.objects.create(
            feature="hub_pull", mode="arsip", status=SyncLog.Status.BERJALAN,
            src_name="GUDANG", dst_name="AMPHOREUS",
        )
        tugas._thread.clear()  # persis keadaan sesudah restart
        self.assertEqual(tugas.rapikan_yatim(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, SyncLog.Status.FAILED)
        self.assertIn("Server berhenti", run.error_message)
        self.assertFalse(tugas.sedang_berjalan())

    def test_pencatat_menulis_baris_yang_bisa_dibaca_kembali(self):
        run = SyncLog.objects.create(feature="hub_pull", mode="arsip", detail="[]")
        lapor = tugas._pencatat(run)
        lapor("potongan 2024-01 selesai")
        lapor("potongan 2024-02 selesai")
        run.refresh_from_db()
        teks = [b["teks"] for b in run.items()]
        self.assertEqual(teks, ["potongan 2024-01 selesai", "potongan 2024-02 selesai"])
        self.assertTrue(all("waktu" in b for b in run.items()))

    def test_arsip_wajib_menyebut_cabang(self):
        """Satu klik "arsip semua cabang" = berjam-jam x 9."""
        with self.assertRaises(Ditolak):
            tugas.mulai("arsip", None, "sa")
        self.assertEqual(SyncLog.objects.count(), 0)

    def test_tugas_tak_dikenal_ditolak_sebelum_baris_dibuat(self):
        with self.assertRaises(Ditolak):
            tugas.mulai("bukan-tugas", self.cabang, "sa")
        self.assertEqual(SyncLog.objects.count(), 0)

    def test_hub_belum_ada_ditolak_sebelum_baris_dibuat(self):
        self.hub.delete()
        with self.assertRaises(Ditolak) as cm:
            tugas.mulai("segar", self.cabang, "sa")
        self.assertIn("AMPHOREUS", str(cm.exception))
        self.assertEqual(SyncLog.objects.count(), 0)

    def test_gagal_tercatat_di_baris_yang_sama_bukan_baris_baru(self):
        def meledak(profil, lapor):
            lapor("mulai")
            raise RuntimeError("server jauh mati")

        with patch.dict(tugas.TUGAS, {"segar": ("Tarik segar", "hub_pull", meledak, True)}):
            run = tugas.mulai("segar", self.cabang, "sa", sinkron=True)
        self.assertEqual(SyncLog.objects.count(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, SyncLog.Status.FAILED)
        self.assertIn("server jauh mati", run.error_message)
        self.assertEqual([b["teks"] for b in run.items()], ["mulai"])

    def test_sukses_mengisi_hitungan_dan_durasi(self):
        def cepat(profil, lapor):
            time.sleep(0.01)
            return {"compared": 7, "applied": 42}

        with patch.dict(tugas.TUGAS, {"segar": ("Tarik segar", "hub_pull", cepat, True)}):
            run = tugas.mulai("segar", self.cabang, "sa", sinkron=True)
        run.refresh_from_db()
        self.assertEqual(run.status, SyncLog.Status.OK)
        self.assertEqual((run.compared_count, run.applied_count), (7, 42))
        self.assertGreater(run.duration_ms, 0)


class HubPullTidakMencatatDuaKali(TestCase):
    """`pull_source` punya penulis SyncLog sendiri sejak Fase 1.

    Runner memegang barisnya sendiri sejak sebelum job dimulai, jadi tanpa
    `catat=False` satu klik meninggalkan DUA baris yang menceritakan run yang
    sama — dan yang satu tanpa progres, yang satu tanpa hasil akhir.
    """

    def test_catat_false_mematikan_penulis_internal(self):
        from apps.transactions import hub_pull

        hub = _profil("AMPHOREUS")
        src = _profil("GUDANG", kode_sumber="GUDANG")
        hasil = dict(hub_pull._hasil_kosong(src), header=5, detail=10)
        with patch.object(hub_pull, "pull_segar", return_value=hasil), \
             patch.object(hub_pull, "_simpan_state"):
            hub_pull.pull_source(src, hub, mode="segar", catat=False)
            self.assertEqual(SyncLog.objects.count(), 0)
            hub_pull.pull_source(src, hub, mode="segar")
            self.assertEqual(SyncLog.objects.count(), 1)


class RuteJalankan(TestCase):
    """Rute TULIS tidak boleh bergantung pada penjagaan tak langsung."""

    def setUp(self):
        tugas._thread.clear()
        _profil("AMPHOREUS")
        self.cabang = _profil("GUDANG", kode_sumber="GUDANG")
        U = get_user_model()
        self.admin = U.objects.create_user(username="adm", password="x", role="admin")
        self.sa = U.objects.create_user(username="sa", password="x", role="superadmin")

    def test_admin_ditolak(self):
        self.client.force_login(self.admin)
        resp = self.client.post("/admin-panel/master/sync-health/jalankan",
                                {"tugas": "segar", "profil": self.cabang.pk})
        self.assertNotEqual(resp.status_code, 302)
        self.assertEqual(SyncLog.objects.count(), 0)

    def test_get_ditolak(self):
        self.client.force_login(self.sa)
        resp = self.client.get("/admin-panel/master/sync-health/jalankan")
        self.assertEqual(resp.status_code, 405)

    def test_superadmin_memicu_tugas(self):
        self.client.force_login(self.sa)
        with patch.object(tugas, "mulai", return_value=SyncLog(pk=1)) as m:
            resp = self.client.post("/admin-panel/master/sync-health/jalankan",
                                    {"tugas": "segar", "profil": self.cabang.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(m.call_args[0][0], "segar")
        self.assertEqual(m.call_args[0][1].pk, self.cabang.pk)

    def test_penolakan_jadi_flash_bukan_500(self):
        self.client.force_login(self.sa)
        resp = self.client.post("/admin-panel/master/sync-health/jalankan",
                                {"tugas": "arsip", "profil": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("cabang", self.client.session["flash_error"].lower())

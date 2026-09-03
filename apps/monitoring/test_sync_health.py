"""Kesehatan Sync: klasifikasi status + siapa yang boleh melihatnya.

Halaman ini ada karena selama empat tahun tak ada yang tahu antrean keluar RTL
PUSAT menumpuk sampai sejuta baris. Yang diuji di sini persis dua hal yang
membuatnya berguna: angka mentah berubah jadi status yang benar, dan halaman itu
hanya terbuka untuk superadmin.
"""
import datetime as dt
from unittest.mock import patch

from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.monitoring import services_sync as svc


class KlasifikasiStatusTests(TestCase):
    def test_ambang_antrean(self):
        self.assertEqual(svc._nilai_status(5, svc.ANTRE_OK_MENIT, svc.ANTRE_LAMBAT_MENIT), svc.STATUS_OK)
        self.assertEqual(svc._nilai_status(60, svc.ANTRE_OK_MENIT, svc.ANTRE_LAMBAT_MENIT), svc.STATUS_LAMBAT)
        self.assertEqual(svc._nilai_status(5000, svc.ANTRE_OK_MENIT, svc.ANTRE_LAMBAT_MENIT), svc.STATUS_MATI)

    def test_batas_persis_dihitung_sebagai_tingkat_berikutnya(self):
        """Tepat di ambang = sudah masuk tingkat berikutnya. Kalau `<=`, sebuah
        server yang mangkrak persis 2 jam akan dilaporkan sehat."""
        self.assertEqual(
            svc._nilai_status(svc.ANTRE_OK_MENIT, svc.ANTRE_OK_MENIT, svc.ANTRE_LAMBAT_MENIT),
            svc.STATUS_LAMBAT,
        )
        self.assertEqual(
            svc._nilai_status(svc.ANTRE_LAMBAT_MENIT, svc.ANTRE_OK_MENIT, svc.ANTRE_LAMBAT_MENIT),
            svc.STATUS_MATI,
        )

    def test_tanpa_data_bukan_status(self):
        """Server yang tbl_waktu_get-nya kosong belum tentu sakit — ia belum
        pernah menarik. Sumbu itu tidak ikut menilai, bukan dinilai mati."""
        self.assertIsNone(svc._nilai_status(None, 15, 120))

    def test_terburuk_yang_menang(self):
        self.assertEqual(svc._terburuk(svc.STATUS_OK, svc.STATUS_MATI), svc.STATUS_MATI)
        self.assertEqual(svc._terburuk(svc.STATUS_OK, None), svc.STATUS_OK)
        self.assertEqual(svc._terburuk(None, None), svc.STATUS_OK)

    def test_umur_negatif_tidak_dijepit_ke_nol(self):
        """Jam server tujuan yang lebih maju harus terlihat, bukan disamarkan
        jadi 'baru saja' — selisih jam antar-server justru salah satu penyakit
        yang dicari halaman ini."""
        sekarang = dt.datetime(2026, 8, 1, 10, 0, 0)
        self.assertLess(svc._umur_menit(dt.datetime(2026, 8, 1, 10, 30, 0), sekarang), 0)


class SyncHealthProfilTests(TestCase):
    def setUp(self):
        self.profile = ServerProfile.objects.create(
            name="UJI", host="server-uji", db_name="SOLID_SIM", username="sa"
        )

    def _jalankan(self, mentah):
        with patch.object(svc, "_baca", return_value=mentah), patch.object(svc, "mssql"):
            return svc.sync_health(self.profile)

    def test_antrean_menumpuk_bertahun_dilaporkan_mati(self):
        """Kasus RTL PUSAT yang sebenarnya: sejuta baris sejak 2022."""
        hasil = self._jalankan({
            "antre": 1_043_804,
            "antre_tertua": dt.datetime(2022, 5, 13, 12, 43),
            "antre_terbaru": svc._now_naive(),
            "watermark_get": dt.datetime(2024, 10, 22, 9, 58),
            "feed_id": 1_044_172,
            "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["status"], svc.STATUS_MATI)
        self.assertEqual(hasil["antre"], 1_043_804)
        # Antre DAN watermark sama-sama beku di sini — keduanya harus disebut.
        self.assertEqual(hasil["penyebab"], "tertunggak, tarik terakhir")

    def test_antrean_mati_watermark_sehat_penyebab_tertunggak_saja(self):
        """Kebalikan kasus GUDANG: hanya sumbu antre yang mati, watermark dan
        feed segar. Penyebab tidak boleh ikut menyebut sumbu yang sehat."""
        hasil = self._jalankan({
            "antre": 50,
            "antre_tertua": dt.datetime(2022, 5, 13, 12, 43),
            "antre_terbaru": svc._now_naive(),
            "watermark_get": svc._now_naive(),
            "feed_id": 1_044_172,
            "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["status"], svc.STATUS_MATI)
        self.assertEqual(hasil["penyebab"], "tertunggak")

    def test_antrean_kosong_sehat_walau_baris_tertua_kosong(self):
        """Antrean kosong = tak ada yang tertunggak. Umur baris tertua tak
        berarti apa-apa kalau barisnya memang tidak ada."""
        hasil = self._jalankan({
            "antre": 0,
            "antre_tertua": None,
            "antre_terbaru": None,
            "watermark_get": svc._now_naive(),
            "feed_id": 500,
            "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["status"], svc.STATUS_OK)
        self.assertIsNone(hasil["antre_umur_menit"])

    def test_antrean_sehat_tapi_penarikan_mati_tetap_mati(self):
        """Kasus GUDANG: antreannya bersih, tapi tbl_waktu_get beku 17 bulan.
        Satu sumbu sehat tidak boleh menutupi sumbu yang lain."""
        hasil = self._jalankan({
            "antre": 12,
            "antre_tertua": svc._now_naive(),
            "antre_terbaru": svc._now_naive(),
            "watermark_get": dt.datetime(2025, 2, 28, 8, 0),
            "feed_id": 1_054_652,
            "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["status"], svc.STATUS_MATI)
        self.assertEqual(hasil["penyebab"], "tarik terakhir")

    def test_antrean_kosong_dengan_aktivitas_baru_adalah_bukti_terkirim(self):
        """Baris antrean DIHAPUS begitu terkirim, jadi kosong sendirian tak
        membuktikan apa pun. Yang membuktikan: ada perubahan baru di
        tbl_log_transaksi (tidak dihapus job legacy) DAN antreannya bersih."""
        hasil = self._jalankan({
            "antre": 0, "antre_tertua": None, "antre_terbaru": None,
            "watermark_get": svc._now_naive(),
            "feed_id": 500, "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["bukti"], "aktif")
        self.assertEqual(hasil["status"], svc.STATUS_OK)

    def test_antrean_kosong_tanpa_aktivitas_adalah_tidak_tahu(self):
        """Toko tutup dan trigger mati sama-sama menghasilkan antrean kosong.
        Keduanya tidak boleh terbaca sebagai bukti sehat."""
        import datetime as dt

        hasil = self._jalankan({
            "antre": 0, "antre_tertua": None, "antre_terbaru": None,
            "watermark_get": svc._now_naive(),
            "feed_id": 500, "feed_waktu": dt.datetime(2026, 7, 1, 8, 0),
        })
        self.assertEqual(hasil["bukti"], "sepi")

    def test_antrean_terisi_ditandai_ada_tunggakan(self):
        hasil = self._jalankan({
            "antre": 40, "antre_tertua": svc._now_naive(), "antre_terbaru": svc._now_naive(),
            "watermark_get": svc._now_naive(),
            "feed_id": 500, "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["bukti"], "antre")

    def test_antrean_tak_bergerak_padahal_feed_maju_berarti_mati(self):
        """Deteksi yang tidak bisa dikelabui penghapusan: kedalaman antrean tak
        pernah membuktikan pengirimnya hidup, tapi PERGERAKAN membuktikannya.
        Baris tertua yang sama persis di dua sampel sementara feed bertambah
        berarti ada yang menumpuk dan tak ada yang mengangkut — tertangkap jauh
        sebelum ambang umur 2 jam tercapai."""
        import datetime as dt

        from apps.core.models import SyncHealthSample

        tertua = dt.datetime(2026, 8, 1, 9, 55)
        SyncHealthSample.objects.create(
            profile=self.profile, profile_name="UJI", antre=5,
            antre_tertua=svc._aware(tertua), feed_id=1000, status=svc.STATUS_OK,
        )
        hasil = self._jalankan({
            "antre": 9, "antre_tertua": tertua, "antre_terbaru": svc._now_naive(),
            "watermark_get": svc._now_naive(),
            "feed_id": 1200, "feed_waktu": svc._now_naive(),  # feed maju
        })
        self.assertEqual(hasil["status"], svc.STATUS_MATI)

    def test_antrean_bergerak_tidak_dianggap_mati(self):
        """Baris tertua yang berganti = pengirimnya bekerja. Umurnya masih muda,
        jadi statusnya tetap sehat."""
        import datetime as dt

        from apps.core.models import SyncHealthSample

        SyncHealthSample.objects.create(
            profile=self.profile, profile_name="UJI", antre=5,
            antre_tertua=svc._aware(dt.datetime(2026, 8, 1, 9, 55)),
            feed_id=1000, status=svc.STATUS_OK,
        )
        hasil = self._jalankan({
            "antre": 3, "antre_tertua": svc._now_naive(), "antre_terbaru": svc._now_naive(),
            "watermark_get": svc._now_naive(),
            "feed_id": 1200, "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["status"], svc.STATUS_OK)

    def test_server_mati_jadi_offline_bukan_exception(self):
        """Halaman ini paling dibutuhkan saat ada yang rusak, jadi satu server
        tak terhubung tidak boleh menjatuhkan barisan yang lain."""
        import pyodbc

        with patch.object(svc.mssql, "cursor", side_effect=pyodbc.Error("08001", "timeout")):
            hasil = svc.sync_health(self.profile)
        self.assertEqual(hasil["status"], svc.STATUS_OFFLINE)
        self.assertIn("timeout", hasil["error"])

    def test_yang_terparah_diurut_di_atas(self):
        """Server mati tak boleh terkubur di halaman terakhir daftar abjad."""
        sehat = dict(profile="AAA", status=svc.STATUS_OK)
        mati = dict(profile="ZZZ", status=svc.STATUS_MATI)
        with patch.object(svc, "sync_health", side_effect=[sehat, mati]):
            urut = svc.sync_health_all([self.profile, self.profile])
        self.assertEqual([r["profile"] for r in urut], ["ZZZ", "AAA"])

    def test_sample_disimpan_dengan_waktu_aware(self):
        """USE_TZ=True: menyimpan datetime naif menggeser nilainya tujuh jam."""
        from django.utils import timezone

        from apps.core.models import SyncHealthSample

        hasil = self._jalankan({
            "antre": 3,
            "antre_tertua": dt.datetime(2026, 8, 1, 9, 0),
            "antre_terbaru": dt.datetime(2026, 8, 1, 9, 30),
            "watermark_get": dt.datetime(2026, 8, 1, 9, 30),
            "feed_id": 10,
            "feed_waktu": dt.datetime(2026, 8, 1, 9, 30),
        })
        svc.simpan_sample(hasil)
        sample = SyncHealthSample.objects.get()
        self.assertTrue(timezone.is_aware(sample.antre_tertua))
        self.assertEqual(sample.profile_name, "UJI")

    def test_feed_yang_mundur_dilaporkan_mati_walau_antrean_kosong(self):
        """Pemangkasan feed dulu justru MEMATIKAN deteksi ini tanpa suara:
        `feed_maju` jadi False selamanya dan `_stuck()` pulang None seolah semua
        baik-baik saja. Sekarang mundurnya feed diperiksa lebih dulu dan tanpa
        syarat antrean — server yang antreannya kosong pun tetap tertangkap."""
        from apps.core.models import SyncHealthSample

        SyncHealthSample.objects.create(
            profile=self.profile, profile_name="UJI", antre=0,
            antre_tertua=None, feed_id=5_623_352, status=svc.STATUS_OK,
        )
        hasil = self._jalankan({
            "antre": 0, "antre_tertua": None, "antre_terbaru": None,
            "watermark_get": svc._now_naive(),
            "feed_id": 3_250_652, "feed_waktu": svc._now_naive(),
        })
        self.assertEqual(hasil["status"], svc.STATUS_MATI)


class PeriksaCursorTests(TestCase):
    """Feed BISA kehilangan barisnya: terukur 1.469.155 id lenyap dalam satu blok
    utuh semalam 15-16 Mei 2024 di lini PUSAT, saat database dipisah untuk
    meringankannya. Dua akibatnya tidak memunculkan error apa pun dan sebelumnya
    tampil `ok` dengan ketinggalan 0."""

    def test_cursor_mendahului_ujung_feed_adalah_mati(self):
        """`WHERE id > cursor` tak akan pernah mengembalikan baris lagi — cabang
        itu berhenti mengirim SELAMANYA."""
        status, alasan, lubang = svc._periksa_cursor(5_000_000, 1, 4_000_000)
        self.assertEqual(status, svc.STATUS_MATI)
        self.assertIn("dipangkas", alasan)
        self.assertEqual(lubang, 0)

    def test_cursor_tertinggal_di_belakang_baris_tertua_adalah_lubang(self):
        """Sync tetap jalan dan ketinggalannya wajar, tapi baris di antaranya
        sudah lenyap dan tidak akan terisi sendiri."""
        status, alasan, lubang = svc._periksa_cursor(1_781_496, 3_250_652, 5_623_352)
        self.assertEqual(status, svc.STATUS_MATI)
        self.assertEqual(lubang, 3_250_652 - 1_781_496 - 1)
        self.assertIn("lubang", alasan)

    def test_feed_utuh_tidak_dilaporkan_apa_apa(self):
        self.assertEqual(svc._periksa_cursor(5_623_348, 1, 5_623_352), (None, "", 0))

    def test_cursor_persis_di_bawah_baris_tertua_bukan_lubang(self):
        """Batas: baris berikutnya sesudah cursor memang baris tertua itu
        sendiri, jadi tak ada satu pun yang hilang."""
        self.assertEqual(svc._periksa_cursor(99, 100, 500), (None, "", 0))
        self.assertEqual(svc._periksa_cursor(98, 100, 500)[2], 1)

    def test_cursor_nol_bukan_lubang(self):
        """Cursor 0 = belum pernah sync, bukan tertinggal. Run pertama menetapkan
        posisinya di ujung feed, jadi melaporkannya sebagai lubang jutaan baris
        cuma bikin panik pada hal yang tidak akan terjadi."""
        self.assertEqual(svc._periksa_cursor(0, 3_250_652, 5_623_352), (None, "", 0))


class FanoutHealthTests(TestCase):
    def setUp(self):
        self.src = ServerProfile.objects.create(
            name="GDG", host="h1", db_name="D", username="sa"
        )
        self.tgt = ServerProfile.objects.create(
            name="TOKO", host="h2", db_name="D", username="sa"
        )

    def _jalankan(self, cursor_id, feed_min, feed_id):
        from apps.core.models import FeedSyncCursor

        FeedSyncCursor.objects.create(
            source_profile=self.src, target_profile=self.tgt, last_id=cursor_id, status="ok"
        )
        with patch.object(svc, "_ujung_feed", return_value=(feed_min, feed_id)), \
                patch.object(svc, "mssql"):
            return svc.fanout_health_all(self.src, [self.tgt])[0]

    def test_cursor_mendahului_feed_tidak_lagi_tampil_sehat(self):
        """Regresi: `max(0, feed - cursor)` membuat cabang yang berhenti
        selamanya jadi baris paling sehat di layar — ketinggalan 0, status ok."""
        r = self._jalankan(5_000_000, 1, 4_000_000)
        self.assertEqual(r["status"], svc.STATUS_MATI)
        self.assertLess(r["ketinggalan"], 0)
        self.assertIn("dipangkas", r["error"])

    def test_feed_utuh_tetap_sehat(self):
        r = self._jalankan(5_623_348, 1, 5_623_352)
        self.assertEqual(r["status"], svc.STATUS_OK)
        self.assertEqual(r["ketinggalan"], 4)
        self.assertEqual(r["lubang"], 0)


class SyncHealthAksesTests(TestCase):
    """Superadmin-only. Penegakannya milik middleware (`_menu_allowed`), bukan Vue."""

    def setUp(self):
        self.admin = User.objects.create_user(
            "admin1", password="rahasia-kuat-123", role=Role.ADMIN, allowed_menu_keys=["dashboard"]
        )
        self.admin_penuh = User.objects.create_user(
            "admin2", password="rahasia-kuat-123", role=Role.ADMIN
        )  # allowed_menu_keys kosong = semua menu yang BISA diberikan
        self.superadmin = User.objects.create_user(
            "boss", password="rahasia-kuat-123", role=Role.SUPERADMIN
        )

    def test_admin_dialihkan(self):
        self.client.force_login(self.admin)
        r = self.client.get("/admin-panel/master/sync-health")
        self.assertEqual(r.status_code, 302)

    def test_admin_tanpa_batasan_pun_tetap_tak_bisa(self):
        """Menu superadmin-only tak pernah masuk daftar yang bisa diberikan, jadi
        admin dengan hak default penuh pun tetap tertutup."""
        self.client.force_login(self.admin_penuh)
        self.assertEqual(self.client.get("/admin-panel/master/sync-health").status_code, 302)

    def test_tak_muncul_di_daftar_yang_bisa_diberikan(self):
        from apps.core.menus import assignable_menus

        self.assertNotIn("sync_health", {m["key"] for m in assignable_menus()})

    def test_superadmin_boleh(self):
        self.client.force_login(self.superadmin)
        # Prop-nya deferred, jadi permintaan pertama tak menyentuh MS SQL sama sekali.
        self.assertEqual(self.client.get("/admin-panel/master/sync-health").status_code, 200)

    def test_rute_terpetakan_ke_menunya(self):
        from apps.core.menus import menu_key_for_path

        self.assertEqual(menu_key_for_path("/admin-panel/master/sync-health"), "sync_health")
        # Tetangga dekatnya tidak boleh ikut tertelan.
        self.assertEqual(menu_key_for_path("/admin-panel/master/sync-harga"), "sync_harga")

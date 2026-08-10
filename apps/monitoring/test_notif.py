"""Kotak notif di navbar: milik tiap akun, superadmin melihat semuanya.

Isinya irisan `ActivityLog` — tidak ada model notifikasi tersendiri. Yang
benar-benar ditanyakan orang cuma "ada yang baru sejak terakhir saya lihat?",
dan itu dijawab satu stempel waktu di `User.notif_dibaca_at` ketimbang tabel
status-baca per baris.

Yang dijaga di sini, berurutan dari yang paling mahal kalau salah:

1. Notif tidak boleh bocor antar-akun. Aturannya dipakai bersama dashboard dan
   halaman Log Aktivitas lewat `log_untuk`; tes ini menahan sisi notifnya.
2. Rutenya harus bisa dicapai kasir. Ia ada di AKAR, bukan /admin-panel — kalau
   suatu saat dipindahkan ke sana, penjaga Tailscale akan mematikannya persis
   untuk orang yang paling sering melihat loncengnya, dan gejalanya cuma
   "lencana tak pernah hilang".
"""
import datetime as dt
import json

from django.test import TestCase
from django.utils import timezone

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.models import ActivityLog


class NotifScopeTests(TestCase):
    def setUp(self):
        self.staf = User.objects.create_user(
            "staf_n", password="rahasia-kuat-123", role=Role.ADMIN)
        self.boss = User.objects.create_user(
            "boss_n", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        ActivityLog.objects.create(username="staf_n", action="login", detail="Login berhasil")
        ActivityLog.objects.create(username="orang_lain", action="konfigurasi", detail="Ganti koneksi")

    def _notif(self, user):
        self.client.force_login(user)
        r = self.client.get("/admin-panel/dashboard",
                            HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0")
        return json.loads(r.content)["props"]["notif"]

    def test_admin_hanya_melihat_notifnya_sendiri(self):
        n = self._notif(self.staf)
        self.assertEqual({i["user"] for i in n["items"]}, {"staf_n"})
        self.assertEqual(n["belum"], 1)

    def test_superadmin_melihat_aktivitas_orang_lain(self):
        n = self._notif(self.boss)
        self.assertIn("orang_lain", {i["user"] for i in n["items"]})
        self.assertEqual(n["belum"], 2)

    def test_belum_pernah_dibuka_berarti_semuanya_baru(self):
        self.assertIsNone(self.staf.notif_dibaca_at)
        self.assertTrue(all(i["baru"] for i in self._notif(self.staf)["items"]))

    def test_menandai_dibaca_menol_kan_lencana(self):
        self.client.force_login(self.staf)
        r = self.client.post("/notif/baca")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.staf.refresh_from_db()
        self.assertIsNotNone(self.staf.notif_dibaca_at)
        self.assertEqual(self._notif(self.staf)["belum"], 0)

    def test_yang_datang_sesudah_dibaca_terhitung_baru_lagi(self):
        self.staf.notif_dibaca_at = timezone.now()
        self.staf.save()
        self.assertEqual(self._notif(self.staf)["belum"], 0)
        baru = ActivityLog.objects.create(
            username="staf_n", action="export", detail="Export stok")
        # Waktunya digeser eksplisit, tidak diserahkan ke jam. `timestamp`
        # ber-auto_now_add, dan jam Windows bergerak ~15,6 ms sekali — log ini
        # bisa mendapat cap waktu SAMA PERSIS dengan `notif_dibaca_at` di atas,
        # sehingga "datang sesudah dibaca" jadi tidak sesudah dan testnya
        # lolos-gagal bergantian tanpa ada yang berubah.
        ActivityLog.objects.filter(pk=baru.pk).update(
            timestamp=self.staf.notif_dibaca_at + dt.timedelta(seconds=1))
        n = self._notif(self.staf)
        self.assertEqual(n["belum"], 1)
        self.assertTrue(n["items"][0]["baru"])

    def test_tamu_tak_dapat_apa_apa(self):
        self.client.logout()
        self.assertEqual(self.client.post("/notif/baca").status_code, 302)


class NotifTerjangkauKasirTests(TestCase):
    """Rute tandai-dibaca ada di akar supaya penjaga Tailscale tak mematikannya.

    Kasir di toko tidak berada di rentang CGNAT Tailscale, sedangkan lonceng
    menempel di navbar setiap halaman termasuk layar kasir.
    """

    def setUp(self):
        self.profile = ServerProfile.objects.create(
            name="TOKO A", host="h", db_name="SOLID_SIM", username="sa",
            password_encrypted="x", is_default=True)
        self.kasir = User.objects.create_user(
            "kasir_n", password="rahasia-kuat-123", role=Role.KASIR,
            server_profile=self.profile)
        self.client.force_login(self.kasir)

    def test_kasir_bisa_menandai_dibaca(self):
        with self.settings(ENFORCE_TAILSCALE=True):
            r = self.client.post("/notif/baca")
        self.assertEqual(r.status_code, 200)
        self.kasir.refresh_from_db()
        self.assertIsNotNone(self.kasir.notif_dibaca_at)

    def test_rutenya_di_luar_admin_panel(self):
        from apps.core.menus import menu_key_for_path

        # Kalau suatu saat pindah ke /admin-panel, tes di atas yang gagal duluan;
        # ini menjelaskan kenapa.
        self.assertIsNone(menu_key_for_path("/notif/baca"))

    def test_get_ditolak(self):
        self.assertEqual(self.client.get("/notif/baca").status_code, 405)

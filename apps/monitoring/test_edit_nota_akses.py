"""Edit Nota & Jejak Audit — siapa boleh, dan apa yang tercatat.

Yang dijaga, berurutan dari yang paling mahal kalau salah:

1. **Hak**: Edit Nota bawaan admin dan BUKAN bawaan kasir/supervisor; ke
   supervisor hanya lewat superadmin (`tulis_kritis`). Jejak Audit `teknis`.
2. **Jejak**: setiap edit yang berhasil meninggalkan satu baris `edit_nota`
   berisi koneksi, nomor, alasan, dan isi sebelum/sesudah — dan upaya yang
   DITOLAK ikut tercatat. Tanpa alasan, tak ada yang ditulis ke server.
3. **Uang**: akun yang nilai uangnya disembunyikan ditolak utuh di kedua layar;
   formulir harga tanpa harga tak bisa diisi dengan benar.
4. Riwayat nota bisa dibaca dari layar Edit Nota tanpa menu teknis.
"""
import json
from unittest.mock import patch

from django.test import TestCase

from apps.auth_app.models import Role, TautanUser, User
from apps.connections.models import ServerProfile
from apps.core.menus import ALL_MENUS, default_keys_for, wewenang_beri
from apps.core.models import ActivityLog
from apps.transactions import edit_nota as en

URL = "/admin-panel/penjualan/edit-nota"
MENU = {m["key"]: m for m in ALL_MENUS}


class HakMenuTests(TestCase):
    def test_edit_nota_bawaan_admin_saja(self):
        self.assertIn("edit_nota", default_keys_for(Role.ADMIN))
        self.assertNotIn("edit_nota", default_keys_for(Role.SUPERVISOR))
        self.assertNotIn("edit_nota", default_keys_for(Role.KASIR))

    def test_flag_edit_nota(self):
        m = MENU["edit_nota"]
        self.assertTrue(m.get("tulis_kritis"))
        self.assertTrue(m.get("butuh_tautan"))
        self.assertFalse(m.get("teknis"))

    def test_jejak_audit_teknis_bukan_bawaan_siapa_pun(self):
        self.assertTrue(MENU["jejak_audit"].get("teknis"))
        for peran in (Role.ADMIN, Role.SUPERVISOR, Role.KASIR):
            self.assertNotIn("jejak_audit", default_keys_for(peran))

    def test_hanya_superadmin_memberi_edit_nota_ke_supervisor(self):
        sa = User.objects.create_user("sa_en", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        adm = User.objects.create_user("adm_en", password="rahasia-kuat-123", role=Role.ADMIN,
                                       allowed_menu_keys=["edit_nota", "menus"])
        self.assertIn("edit_nota", wewenang_beri(sa, Role.SUPERVISOR))
        self.assertNotIn("edit_nota", wewenang_beri(adm, Role.SUPERVISOR))
        self.assertNotIn("jejak_audit", wewenang_beri(adm, Role.ADMIN))


class _Dasar(TestCase):
    def setUp(self):
        self.profil = ServerProfile.objects.create(
            name="TOKO EN", host="h", db_name="SOLID_SIM", username="sa", password_encrypted="x")
        self.admin = User.objects.create_user("adm_edit", password="rahasia-kuat-123", role=Role.ADMIN)
        TautanUser.objects.create(user=self.admin, profile=self.profil,
                                  kd_user="UAA009", kd_divisi="DAA000", kd_pegawai="PAA000")
        self.client.force_login(self.admin)
        # Tanpa profil is_default, middleware tak menggerbangi butuh_tautan;
        # view-nya sendiri diarahkan ke profil ini.
        for modul in ("apps.monitoring.views_edit_nota", "apps.monitoring.views_audit"):
            p = patch(f"{modul}._active", return_value=self.profil)
            p.start()
            self.addCleanup(p.stop)

    def _props(self, url, komponen, prop):
        r = self.client.get(url, HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0",
                            HTTP_X_INERTIA_PARTIAL_DATA=prop,
                            HTTP_X_INERTIA_PARTIAL_COMPONENT=komponen)
        self.assertEqual(r.status_code, 200, url)
        return json.loads(r.content)["props"][prop]


HASIL = {
    "no_transaksi": "SC2609100001", "skema": "legacy",
    "sebelum": {"kepala": {"kd_customer": "CAA000"}, "baris": [], "total": 35000.0, "total_hitung": 35000.0},
    "sesudah": {"kepala": {"kd_customer": "CAA001"}, "baris": [], "total": 68000.0},
    "selisih": {"kepala": [{"kolom": "kd_customer", "dari": "CAA000", "ke": "CAA001"}],
                "barang": {"ditambah": [], "dihapus": [], "diubah": [{"kd_barang": "1001"}]}},
    "total_dibuat": False, "log_id": [3, 8], "baris": 2,
}
KIRIM = {"no_transaksi": "SC2609100001", "versi": "v1", "alasan": "salah ketik qty barang",
         "kd_customer": "CAA001", "items": [{"kd_barang": "1001", "kd_satuan": "SAA000", "qty": 5}]}


class SimpanTests(_Dasar):
    def _post(self, data):
        return self.client.post(f"{URL}/save", data=json.dumps(data), content_type="application/json")

    def test_edit_berhasil_tercatat_utuh(self):
        with patch.object(en, "ubah_nota", return_value=HASIL) as ubah:
            r = self._post(KIRIM)
        self.assertEqual(r.status_code, 302)
        kw = ubah.call_args.kwargs
        # Pengedit dari TAUTAN koneksi aktif, bukan dari kiriman layar.
        self.assertEqual(kw["kd_user"], "UAA009")
        self.assertEqual(kw["perubahan"], {"kd_customer": "CAA001"})
        a = ActivityLog.objects.get(action="edit_nota")
        self.assertEqual((a.profile_name, a.jenis_dokumen, a.no_dokumen, a.alasan),
                         ("TOKO EN", "penjualan", "SC2609100001", "salah ketik qty barang"))
        self.assertEqual(json.loads(a.data)["log_id"], [3, 8])
        self.assertTrue(a.hash)
        # Tanpa rupiah di `detail`: kolom itu tampil tanpa penyaring uang.
        self.assertNotIn("68", a.detail)

    def test_tanpa_alasan_tak_ada_yang_ditulis(self):
        with patch.object(en, "ubah_nota") as ubah:
            self._post(dict(KIRIM, alasan="ubah"))
        ubah.assert_not_called()
        self.assertFalse(ActivityLog.objects.filter(action__startswith="edit_nota").exists())

    def test_upaya_ditolak_ikut_tercatat(self):
        with patch.object(en, "ubah_nota", side_effect=en.NotaDitolak("Nota ini sudah punya cicilan piutang.")):
            self._post(KIRIM)
        a = ActivityLog.objects.get(action="edit_nota_ditolak")
        self.assertEqual(a.no_dokumen, "SC2609100001")
        self.assertIn("cicilan", a.detail)
        self.assertEqual(a.alasan, "salah ketik qty barang")

    def test_uang_tersembunyi_ditolak(self):
        self.admin.hidden_data_keys = ["harga_jual"]
        self.admin.save()
        with patch.object(en, "ubah_nota") as ubah:
            self._post(KIRIM)
        ubah.assert_not_called()


class LayarTests(_Dasar):
    def test_halaman_terbuka_untuk_admin(self):
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_nota_dibaca_lewat_service(self):
        nota = {"kepala": {"no_transaksi": "SC1"}, "baris": [], "total": 0, "total_tersimpan": 0,
                "versi": "v", "penghalang": []}
        with patch.object(en, "baca_untuk_edit", return_value=nota), \
             patch("apps.transactions.penjualan.opsi_nota", return_value={}):
            d = self._props(f"{URL}?no=SC1", "Admin/Transaksi/EditNota", "data")
        self.assertEqual(d["nota"]["versi"], "v")

    def test_uang_tersembunyi_layar_ditolak(self):
        self.admin.hidden_data_keys = ["nominal"]
        self.admin.save()
        with patch.object(en, "baca_untuk_edit") as baca:
            d = self._props(f"{URL}?no=SC1", "Admin/Transaksi/EditNota", "data")
        baca.assert_not_called()
        self.assertIn("nilai uang", d["ditolak"])

    def test_riwayat_bisa_dibaca_tanpa_menu_teknis(self):
        with patch("apps.monitoring.views_edit_nota.riwayat_gabungan",
                   return_value={"no": "SC1", "arunika": [], "legacy": {}}) as rg:
            r = self.client.get(f"{URL}/riwayat?no=SC1")
        self.assertEqual(r.status_code, 200)
        rg.assert_called_once()
        # Rute Jejak Audit sendiri tetap tertutup bagi admin tanpa menu teknis.
        self.assertNotEqual(self.client.get("/admin-panel/audit/riwayat?no=SC1").status_code, 200)

    def test_kasir_tanpa_akses_khusus_tak_bisa_membuka(self):
        kasir = User.objects.create_user("ksr_en", password="rahasia-kuat-123", role=Role.KASIR,
                                         server_profile=self.profil)
        self.client.force_login(kasir)
        self.assertNotEqual(self.client.get(URL).status_code, 200)


class JejakAuditTests(_Dasar):
    def setUp(self):
        super().setUp()
        self.sa = User.objects.create_user("sa_audit", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.client.force_login(self.sa)

    def test_superadmin_melihat_jejak_semua_akun(self):
        ActivityLog.objects.create(username="adm_edit", action="edit_nota", no_dokumen="SC1",
                                   profile_name="TOKO EN", alasan="salah ketik")
        ActivityLog.objects.create(username="orang_lain", action="login")
        j = self._props("/admin-panel/audit", "Admin/JejakAudit", "jejak")
        self.assertEqual({r["user"] for r in j["rows"]}, {"adm_edit", "orang_lain"})

    def test_penyaring_di_server(self):
        ActivityLog.objects.create(username="adm_edit", action="edit_nota", no_dokumen="SC1")
        ActivityLog.objects.create(username="adm_edit", action="login")
        j = self._props("/admin-panel/audit?aksi=edit_nota", "Admin/JejakAudit", "jejak")
        self.assertEqual([r["aksi"] for r in j["rows"]], ["edit_nota"])
        self.assertEqual(j["total"], 1)

    def test_penyaring_tanggal_di_server(self):
        # `timestamp__date` di MS SQL + USE_TZ: diuji di mesin DB sungguhan,
        # bukan diasumsikan — tanggal lokal (Asia/Jakarta), bukan UTC.
        import datetime as dt

        from django.utils import timezone
        ActivityLog.objects.create(username="adm_edit", action="edit_nota", no_dokumen="SC1")
        hari_ini = timezone.localdate()
        besok = hari_ini + dt.timedelta(days=1)
        j = self._props(f"/admin-panel/audit?dari={hari_ini}&sampai={hari_ini}", "Admin/JejakAudit", "jejak")
        self.assertEqual(j["total"], 1)
        j = self._props(f"/admin-panel/audit?dari={besok}", "Admin/JejakAudit", "jejak")
        self.assertEqual(j["total"], 0)

    def test_detail_membawa_isi_sebelum_sesudah(self):
        a = ActivityLog.objects.create(username="adm_edit", action="edit_nota",
                                       data=json.dumps(HASIL))
        r = self.client.get(f"/admin-panel/audit/detail?id={a.pk}")
        self.assertEqual(r.json()["data"]["sesudah"]["total"], 68000.0)

    def test_periksa_rantai(self):
        ActivityLog.objects.create(username="x", action="login")
        r = self.client.get("/admin-panel/audit/periksa")
        self.assertIsNone(r.json()["putus"])

    def test_admin_tanpa_menu_teknis_ditolak(self):
        self.client.force_login(self.admin)
        self.assertNotEqual(self.client.get("/admin-panel/audit").status_code, 200)

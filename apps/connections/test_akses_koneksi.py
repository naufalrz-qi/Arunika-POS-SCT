"""Akses koneksi non-produksi — spec 2026-09-22 §4."""
import importlib
import json
from unittest.mock import patch

from django.apps import apps as django_apps
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.connections.akses import boleh_pakai, koneksi_boleh, profil_untuk_sesi
from apps.connections.models import Lingkungan, ServerProfile

PW = "rahasia-kuat-123"


def _profil(nama, lingkungan=Lingkungan.PRODUKSI, **kw):
    return ServerProfile.objects.create(name=nama, host="h", db_name="d", username="u",
                                        lingkungan=lingkungan, **kw)


class KoneksiBolehTests(TestCase):
    def setUp(self):
        self.prod = _profil("PUSAT", is_default=True)
        self.uji = _profil("Testing", Lingkungan.UJI)
        self.internal = _profil("AMPHOREUS", Lingkungan.INTERNAL)
        self.boss = User.objects.create_user("boss", password=PW, role=Role.SUPERADMIN)
        self.adm = User.objects.create_user("adm", password=PW, role=Role.ADMIN)
        self.kasir = User.objects.create_user("kasir", password=PW, role=Role.KASIR,
                                              server_profile=self.uji)

    def _ids(self, user):
        return set(koneksi_boleh(user).values_list("pk", flat=True))

    def test_superadmin_semua(self):
        self.assertEqual(self._ids(self.boss), {self.prod.pk, self.uji.pk, self.internal.pk})

    def test_admin_hanya_produksi(self):
        self.assertEqual(self._ids(self.adm), {self.prod.pk})

    def test_admin_ditambah_koneksi_khusus(self):
        self.adm.koneksi_khusus.add(self.internal)
        self.assertEqual(self._ids(self.adm), {self.prod.pk, self.internal.pk})
        self.assertTrue(boleh_pakai(self.adm, self.internal))
        self.assertFalse(boleh_pakai(self.adm, self.uji))

    def test_kasir_terkunci_ke_servernya_apa_pun_labelnya(self):
        self.assertEqual(self._ids(self.kasir), {self.uji.pk})

    def test_pilihan_sesi_ilegal_jatuh_ke_default(self):
        self.assertEqual(profil_untuk_sesi(self.adm, self.internal.pk), self.prod.pk)
        self.assertEqual(profil_untuk_sesi(self.adm, None), self.prod.pk)
        self.assertEqual(profil_untuk_sesi(self.adm, self.prod.pk), self.prod.pk)

    def test_superadmin_pilihannya_dihormati(self):
        self.assertEqual(profil_untuk_sesi(self.boss, self.internal.pk), self.internal.pk)

    def test_tanpa_koneksi_yang_diizinkan_hasilnya_none(self):
        self.prod.lingkungan = Lingkungan.UJI
        self.prod.save(update_fields=["lingkungan"])
        self.assertIsNone(profil_untuk_sesi(self.adm, None))

    def test_default_nonproduksi_diabaikan_pakai_urutan_pertama(self):
        """M2 — `is_default` kebetulan jatuh di profil non-produksi (mis. sehabis
        migrasi data): admin tak boleh mendarat di sana. Jatuh ke produksi
        pertama menurut Meta.ordering ["db_type", "name"], bukan sembarang."""
        self.prod.is_default = False
        self.prod.save(update_fields=["is_default"])
        self.internal.is_default = True
        self.internal.save(update_fields=["is_default"])
        # Sama db_type (bawaan GROSIR) dengan self.prod ("PUSAT"), tapi lebih
        # awal menurut abjad — jadi urutannya benar-benar diuji, bukan kebetulan
        # profil pertama yang dibuat.
        duluan = _profil("AAA-Duluan")
        self.assertEqual(profil_untuk_sesi(self.adm, None), duluan.pk)


class MigrasiTandaiHubTests(TestCase):
    def test_profil_hub_ditandai_internal(self):
        hub = _profil("AMPHOREUS")
        lain = _profil("GUDANG")
        mig = importlib.import_module("apps.connections.migrations.0008_lingkungan_internal")
        with patch.dict("os.environ", {"HUB_NAME": "AMPHOREUS"}):
            mig.tandai(django_apps, None)
        hub.refresh_from_db()
        lain.refresh_from_db()
        self.assertEqual(hub.lingkungan, Lingkungan.INTERNAL)
        self.assertEqual(lain.lingkungan, Lingkungan.PRODUKSI)


def _props(client, url="/admin-panel/profile"):
    r = client.get(url, HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0")
    return json.loads(r.content)["props"]


class PenegakanKoneksiTests(TestCase):
    def setUp(self):
        self.prod = _profil("PUSAT", is_default=True)
        self.uji = _profil("Testing", Lingkungan.UJI)
        self.internal = _profil("AMPHOREUS", Lingkungan.INTERNAL)
        self.boss = User.objects.create_user("boss", password=PW, role=Role.SUPERADMIN)
        self.adm = User.objects.create_user("adm", password=PW, role=Role.ADMIN,
                                            allowed_menu_keys=["dashboard", "users", "menus"])
        self.kasir = User.objects.create_user("kasir", password=PW, role=Role.KASIR,
                                              server_profile=self.prod)

    def test_daftar_koneksi_tersaring(self):
        self.client.force_login(self.adm)
        self.assertEqual({c["id"] for c in _props(self.client)["connections"]}, {self.prod.pk})
        self.client.force_login(self.boss)
        self.assertEqual(len(_props(self.client)["connections"]), 3)

    def test_pilihan_sesi_ilegal_diganti_default_dan_dibuang(self):
        self.client.force_login(self.adm)
        s = self.client.session
        s["active_profile_id"] = self.internal.pk
        s.save()
        self.assertEqual(_props(self.client)["active_connection"]["id"], self.prod.pk)
        self.assertNotIn("active_profile_id", self.client.session)

    def test_set_default_ditolak_tanpa_izin(self):
        self.client.force_login(self.adm)
        with patch("apps.connections.views.mssql.test_profile") as tes:
            self.client.post(f"/admin-panel/connections/{self.uji.pk}/set-default")
        tes.assert_not_called()
        self.assertNotEqual(self.client.session.get("active_profile_id"), self.uji.pk)

    def test_set_default_diterima_setelah_diberi(self):
        self.adm.koneksi_khusus.add(self.uji)
        self.client.force_login(self.adm)
        with patch("apps.connections.views.mssql.test_profile",
                   return_value={"ok": True, "message": ""}):
            self.client.post(f"/admin-panel/connections/{self.uji.pk}/set-default")
        self.assertEqual(self.client.session.get("active_profile_id"), self.uji.pk)

    def test_admin_tak_bisa_mengunci_kasir_ke_uji(self):
        self.client.force_login(self.adm)
        self.client.post("/admin-panel/users/save", {
            "id": self.kasir.pk, "username": "kasir", "name": "Kasir", "role": "kasir",
            "server_profile_id": str(self.uji.pk)})
        self.kasir.refresh_from_db()
        self.assertEqual(self.kasir.server_profile_id, self.prod.pk)

    def test_nilai_nonprod_yang_tak_berubah_diterima(self):
        self.kasir.server_profile = self.uji
        self.kasir.save(update_fields=["server_profile"])
        self.client.force_login(self.adm)
        self.client.post("/admin-panel/users/save", {
            "id": self.kasir.pk, "username": "kasir", "name": "Ganti Nama", "role": "kasir",
            "server_profile_id": str(self.uji.pk)})
        self.kasir.refresh_from_db()
        self.assertEqual(self.kasir.first_name, "Ganti")
        self.assertEqual(self.kasir.server_profile_id, self.uji.pk)

    def test_superadmin_memberi_koneksi_khusus_lewat_kelola_menu(self):
        self.client.force_login(self.boss)
        self.client.post("/admin-panel/menus/save", {
            "user_id": self.adm.pk, "menu_keys": ["dashboard"], "data_keys": [],
            "koneksi_khusus": [self.internal.pk, self.prod.pk]}, content_type="application/json")
        self.assertEqual(set(self.adm.koneksi_khusus.values_list("pk", flat=True)),
                         {self.internal.pk})

    def test_admin_tak_bisa_memberi_koneksi_khusus(self):
        adm2 = User.objects.create_user("adm2", password=PW, role=Role.ADMIN)
        self.client.force_login(self.adm)
        self.client.post("/admin-panel/menus/save", {
            "user_id": adm2.pk, "menu_keys": [], "data_keys": [],
            "koneksi_khusus": [self.internal.pk]}, content_type="application/json")
        self.assertFalse(adm2.koneksi_khusus.exists())

    def test_kelola_menu_mengirim_koneksi_nonprod_hanya_ke_superadmin(self):
        self.client.force_login(self.boss)
        ids = {k["id"] for k in _props(self.client, "/admin-panel/menus")["koneksi_nonprod"]}
        self.assertEqual(ids, {self.uji.pk, self.internal.pk})
        self.client.force_login(self.adm)
        self.assertEqual(_props(self.client, "/admin-panel/menus")["koneksi_nonprod"], [])


class PergerakanHargaKoneksiTests(TestCase):
    """F4/ruling R10 — Pergerakan Harga tak boleh membaca live dari, atau
    menyebut nama, koneksi di luar `koneksi_boleh(request.user)`."""

    def setUp(self):
        self.prod = _profil("PUSAT", is_default=True)
        self.internal = _profil("AMPHOREUS", Lingkungan.INTERNAL)
        self.adm = User.objects.create_user(
            "adm_ph", password=PW, role=Role.ADMIN,
            allowed_menu_keys=["dashboard", "pergerakan_harga"])

    def _url(self):
        return f"/admin-panel/master/pergerakan-harga?profile={self.internal.pk}"

    def _shell(self):
        """Render awal (non-partial): berisi prop `profiles`, TANPA memicu
        `load_data()` — itu prop deferred, dipanggil hanya lewat partial reload."""
        self.client.force_login(self.adm)
        return json.loads(self.client.get(
            self._url(), HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0").content)["props"]

    def _partial(self):
        """Partial reload prop `data` — inilah yang memanggil `master.saran_harga`."""
        self.client.force_login(self.adm)
        return self.client.get(
            self._url(), HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION="1.0",
            HTTP_X_INERTIA_PARTIAL_DATA="data",
            HTTP_X_INERTIA_PARTIAL_COMPONENT="Admin/MasterData/PergerakanHarga")

    def test_profile_di_luar_wewenang_diabaikan(self):
        props = self._shell()
        # Diperlakukan seperti id tak dikenal: dropdown tak menyebut nama
        # server internal ke admin yang tak berhak.
        self.assertNotIn(self.internal.pk, [int(p["value"]) for p in props["profiles"]])

        with patch("apps.monitoring.views.master.saran_harga",
                   return_value={"rows": [], "sumber": "", "gudang": "", "pesan": ""}) as saran:
            self._partial()
        # Jatuh ke koneksi aktif (produksi), bukan dilempar ke server internal
        # yang diminta lewat ?profile= di URL.
        saran.assert_called_once_with(self.prod)

    def test_profile_di_dalam_wewenang_tetap_dipakai(self):
        """Perilaku yang ADA tak berubah untuk profil yang memang diizinkan."""
        self.adm.koneksi_khusus.add(self.internal)
        with patch("apps.monitoring.views.master.saran_harga",
                   return_value={"rows": [], "sumber": "", "gudang": "", "pesan": ""}) as saran:
            self._partial()
        saran.assert_called_once_with(self.internal)

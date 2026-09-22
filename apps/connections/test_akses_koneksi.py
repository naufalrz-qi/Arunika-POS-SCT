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

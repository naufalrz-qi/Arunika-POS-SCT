"""Jejak audit: kolom perubahan dokumen + rantai hash di `ActivityLog`.

Yang dijaga, berurutan dari yang paling mahal kalau salah:

1. Baris yang diubah atau dihapus LANGSUNG di database terdeteksi. Itu satu-
   satunya janji rantai hash; kalau `cek_jejak` diam atas baris yang disunting,
   seluruh fitur ini cuma hiasan.
2. Baris yang tak disentuh siapa pun TIDAK dilaporkan rusak — termasuk IPv6
   yang dinormalkan kolomnya dan akun/profil yang sudah dihapus. Alarm palsu
   membuat orang berhenti membaca alarmnya.
3. Pemanggil lama `log_activity(request, aksi, detail)` tetap jalan tanpa
   menyebut satu pun argumen baru.
"""
import json
from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.models import (ActivityLog, RantaiJejak, hash_jejak, KOLOM_HASH,
                              log_activity, log_untuk, periksa_rantai)


def _req(user=None, ip="10.0.0.5"):
    return SimpleNamespace(user=user or SimpleNamespace(is_authenticated=False),
                           META={"REMOTE_ADDR": ip})


class KolomAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm_j", password="rahasia-kuat-123", role=Role.ADMIN)
        self.profil = ServerProfile.objects.create(
            name="TOKO J", host="h", db_name="SOLID_SIM", username="sa", password_encrypted="x")

    def test_pemanggil_lama_tetap_jalan(self):
        a = log_activity(_req(self.admin), "login", "Login berhasil")
        self.assertEqual((a.action, a.detail, a.profile_name, a.no_dokumen, a.data),
                         ("login", "Login berhasil", "", "", ""))

    def test_dokumen_alasan_dan_data_tersimpan_utuh(self):
        data = {"skema": "legacy", "sebelum": {"keterangan": "x" * 600}}
        a = log_activity(_req(self.admin), "edit_nota", "Nota SC1 diedit",
                         profile=self.profil, dokumen=("penjualan", " SC1 "),
                         alasan="  salah ketik qty  ", data=data)
        a.refresh_from_db()
        self.assertEqual((a.profile_id, a.profile_name), (self.profil.id, "TOKO J"))
        self.assertEqual((a.jenis_dokumen, a.no_dokumen, a.alasan),
                         ("penjualan", "SC1", "salah ketik qty"))
        # Isi panjang TIDAK ikut terpotong 255 seperti `detail`.
        self.assertEqual(json.loads(a.data), data)

    def test_profil_dihapus_jejak_tetap_bernama(self):
        a = log_activity(_req(self.admin), "edit_nota", profile=self.profil,
                         dokumen=("penjualan", "SC1"))
        self.profil.delete()
        a.refresh_from_db()
        self.assertIsNone(a.profile_id)
        self.assertEqual(a.profile_name, "TOKO J")

    def test_log_untuk_tak_berubah(self):
        log_activity(_req(self.admin), "edit_nota", profile=self.profil, dokumen=("penjualan", "SC1"))
        ActivityLog.objects.create(username="orang_lain", action="login")
        self.assertEqual({a.username for a in log_untuk(self.admin)}, {"adm_j"})


class RantaiHashTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm_r", password="rahasia-kuat-123", role=Role.ADMIN)

    def _tiga(self):
        return [log_activity(_req(self.admin), "uji", f"baris {i}") for i in range(3)]

    def test_baris_baru_berantai(self):
        a, b, c = self._tiga()
        self.assertEqual(a.hash_prev, "")
        self.assertEqual(b.hash_prev, a.hash)
        self.assertEqual(c.hash_prev, b.hash)
        kepala = RantaiJejak.objects.get(kunci="utama")
        self.assertEqual((kepala.hash_terakhir, kepala.id_terakhir), (c.hash, c.pk))

    def test_rantai_utuh_lolos(self):
        self._tiga()
        self.assertEqual(periksa_rantai(), {"jumlah": 3, "putus": None})

    def test_create_langsung_ikut_berantai(self):
        # bisnis/transfer.py menulis lewat objects.create, bukan log_activity.
        a = log_activity(_req(self.admin), "uji")
        b = ActivityLog.objects.create(username="sistem", action="transfer_arunika")
        self.assertEqual(b.hash_prev, a.hash)

    def test_ipv6_yang_dinormalkan_bukan_kerusakan(self):
        log_activity(_req(self.admin, ip="0:0:0:0:0:0:0:1"), "uji")
        self.assertIsNone(periksa_rantai()["putus"])

    def test_akun_dihapus_bukan_kerusakan(self):
        self._tiga()
        self.admin.delete()
        self.assertIsNone(periksa_rantai()["putus"])

    def test_baris_diubah_terdeteksi(self):
        a, b, c = self._tiga()
        ActivityLog.objects.filter(pk=b.pk).update(detail="dikarang belakangan")
        self.assertEqual(periksa_rantai()["putus"]["id"], b.pk)

    def test_baris_tengah_dihapus_terdeteksi(self):
        a, b, c = self._tiga()
        ActivityLog.objects.filter(pk=b.pk).delete()
        self.assertEqual(periksa_rantai()["putus"]["id"], c.pk)

    def test_ekor_dihapus_terdeteksi(self):
        a, b, c = self._tiga()
        ActivityLog.objects.filter(pk=c.pk).delete()
        putus = periksa_rantai()["putus"]
        self.assertEqual(putus["id"], c.pk)
        self.assertIn("ekor", putus["sebab"])

    def test_baris_lama_tanpa_hash_di_luar_rantai(self):
        # Baris dari sebelum migrasi 0019 (dan salinan pindah_pangkal lewat
        # bulk_create) tak punya hash; mereka tak boleh dilaporkan rusak.
        ActivityLog.objects.bulk_create([ActivityLog(username="lama", action="login")])
        self._tiga()
        self.assertEqual(periksa_rantai(), {"jumlah": 3, "putus": None})

    def test_kepala_rantai_dibuat_ulang_bila_hilang(self):
        RantaiJejak.objects.all().delete()
        a = log_activity(_req(self.admin), "uji")
        self.assertEqual(a.hash_prev, "")
        self.assertEqual(RantaiJejak.objects.get().id_terakhir, a.pk)

    def test_hash_dari_isi_database(self):
        a = log_activity(_req(self.admin), "uji", "x")
        isi = ActivityLog.objects.values(*KOLOM_HASH).get(pk=a.pk)
        self.assertEqual(hash_jejak(isi), a.hash)


class PerintahCekJejakTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm_c", password="rahasia-kuat-123", role=Role.ADMIN)

    def test_utuh(self):
        log_activity(_req(self.admin), "uji")
        out = StringIO()
        call_command("cek_jejak", stdout=out)
        self.assertIn("Rantai utuh", out.getvalue())

    def test_putus_keluar_dengan_kode_1(self):
        a = log_activity(_req(self.admin), "uji")
        ActivityLog.objects.filter(pk=a.pk).update(action="lain")
        out = StringIO()
        with self.assertRaises(SystemExit) as e:
            call_command("cek_jejak", stdout=out)
        self.assertEqual(e.exception.code, 1)
        self.assertIn(f"#{a.pk}", out.getvalue())

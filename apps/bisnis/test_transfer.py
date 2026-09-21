"""Transfer ke Arunika — validasi, orkestrasi, dan gerbang layar, tanpa MS SQL.

Ketiga fungsi layanan (salin, siapkan, muat) di-mock: yang diuji di sini URUTAN,
pencatatan progres, dan arah kegagalannya. Kebenaran datanya dibuktikan terpisah
dengan perbandingan baris-per-baris terhadap server sungguhan.
"""
import datetime as dt
import threading
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.auth_app.models import Role, User
from apps.bisnis import transfer
from apps.bisnis.siapkan import Ditolak
from apps.connections.models import Lingkungan, ServerProfile
from apps.core.models import ActivityLog, TransferArunika


class Slug(SimpleTestCase):
    def test_bentuk(self):
        self.assertEqual(transfer.slug("Arunika Pusat 2025!"), "arunika_pusat_2025")
        self.assertEqual(transfer.slug("  --  "), "")

    def test_dipotong_tanpa_garis_bawah_di_ujung(self):
        s = transfer.slug("a" * 39 + " b")
        self.assertLessEqual(len(s), transfer.PANJANG_SLUG)
        self.assertFalse(s.endswith("_"))

    def test_nama_database_aman_dikutip(self):
        """Slug hanya [a-z0-9_], jadi `]` tak mungkin lolos ke `CREATE DATABASE [..]`."""
        for n in transfer.nama_database(transfer.slug("x]; DROP DATABASE y --")).values():
            self.assertRegex(n, r"^[a-z0-9_]+$")


def _profil(nama, **kw):
    base = dict(host="localhost", db_name="db_" + transfer.slug(nama), username="sa",
                password_encrypted="terenkripsi", lingkungan=Lingkungan.UJI)
    return ServerProfile.objects.create(name=nama, **(base | kw))


# Waktu LOKAL, seperti yang disimpan legacy dan dibuat sadar-zona oleh
# `tutup_buku_terakhir`. Versi pertama fixture ini memakai 23:59:59 UTC -- yang
# dalam waktu lokal sudah 1 Januari 2026, jadi `stok_benar` benar menolaknya.
TUTUP = timezone.make_aware(dt.datetime(2025, 12, 31, 23, 59, 59))


@patch.object(transfer, "tutup_buku_terakhir", return_value=TUTUP)
@patch.object(transfer, "database_ada", return_value=False)
class Validasi(TestCase):
    def setUp(self):
        self.pusat = _profil("PUSAT", host="SERVER-TOYS", db_name="SOLID_SIM",
                             lingkungan=Lingkungan.PRODUKSI)
        self.lokal = _profil("Testing", db_name="grosirPusat")

    def _v(self, **kw):
        arg = dict(nama="Arunika Pusat 2025", sumber_id=self.pusat.pk, dari="2025-01-01",
                   sampai="2025-12-31", instans_id=self.lokal.pk) | kw
        return transfer.validasi(**arg)

    def test_valid(self, _, _tutup):
        v = self._v()
        self.assertEqual((v["slug"], v["sumber"], v["instans"]),
                         ("arunika_pusat_2025", self.pusat, self.lokal))
        self.assertEqual(v["dari"], dt.date(2025, 1, 1))
        self.assertEqual(v["tutup_buku"], TUTUP)

    def test_sumber_tak_terjangkau_ditolak_sebelum_membuat_apa_pun(self, _, tutup):
        import pyodbc
        tutup.side_effect = pyodbc.OperationalError("08001", "tak terjangkau")
        with self.assertRaises(Ditolak):
            self._v()
        self.assertEqual(ServerProfile.objects.count(), 2)

    def test_nama_kosong(self, _, _tutup):
        with self.assertRaises(Ditolak):
            self._v(nama="  !! ")

    def test_tanggal_terbalik(self, _, _tutup):
        with self.assertRaises(Ditolak):
            self._v(dari="2025-12-31", sampai="2025-01-01")

    def test_sumber_arunika_murni_ditolak(self, _, _tutup):
        """Profil tanpa legacy tak punya tabel apa pun untuk disalin."""
        murni = _profil("arunika lama", db_name=transfer.TANPA_LEGACY)
        with self.assertRaises(Ditolak):
            self._v(sumber_id=murni.pk)

    def test_sumber_hub_ditolak(self, _, _tutup):
        hub = _profil("AMPHOREUS", host="SERVER-RETAIL", lingkungan=Lingkungan.PRODUKSI)
        with self.assertRaises(Ditolak):
            self._v(sumber_id=hub.pk)

    def test_instans_produksi_ditolak(self, _, _tutup):
        """Database baru tak boleh dibuat di server produksi, sekalipun lewat form."""
        with self.assertRaises(Ditolak):
            self._v(instans_id=self.pusat.pk)

    def test_nama_profil_bentrok(self, _, _tutup):
        _profil("Arunika Pusat 2025 (legacy)")
        with self.assertRaises(Ditolak):
            self._v()

    def test_database_sudah_ada(self, ada, _tutup):
        ada.side_effect = lambda _p, db: db == "arunika_arunika_pusat_2025"
        with self.assertRaisesRegex(Ditolak, "arunika_arunika_pusat_2025"):
            self._v()


class Orkestrasi(TestCase):
    def setUp(self):
        self.pusat = _profil("PUSAT", host="SERVER-TOYS", db_name="SOLID_SIM",
                             lingkungan=Lingkungan.PRODUKSI, db_type="grosir")
        self.lokal = _profil("Testing", db_name="grosirPusat", password_encrypted="rahasia-lokal")
        self.data = dict(nama="Uji Satu", slug="uji_satu", sumber=self.pusat, instans=self.lokal,
                         dari=dt.date(2025, 1, 1), sampai=dt.date(2025, 1, 31))
        self.urutan = []

    def _salin(self, sumber, tujuan, dari, sampai, lapor):
        self.urutan.append(("salin", sumber.name, tujuan.db_name))
        lapor({"jenis": "langkah", "nama": "t_penjualan", "kelas": "kepala", "baris": 9456,
               "detik": 0.1, "dilewati": 0, "alasan": {}})

    def _siapkan(self, profil, db, mode, lapor):
        self.urutan.append(("siapkan", profil.name, db, mode))
        profil.db_arunika = db
        profil.save(update_fields=["db_arunika"])
        lapor({"jenis": "info", "pesan": "2. migrate OK"})

    def _muat(self, sumber, tujuan, dari, sampai, lapor):
        self.urutan.append(("muat", sumber.name, tujuan.name))
        lapor({"jenis": "langkah", "nama": "barang", "baris": 100, "detik": 1.0,
               "dilewati": 2, "alasan": {"satuan_dasar_kode kosong (wajib)": 2}})

    def _jalan(self, **ganti):
        with patch.object(transfer.salin_legacy, "salin", ganti.get("salin", self._salin)), \
             patch.object(transfer, "siapkan_arunika", ganti.get("siapkan", self._siapkan)), \
             patch.object(transfer.muat, "muat_semua", ganti.get("muat", self._muat)):
            transfer.mulai(self.data, "boss", sinkron=True)
        return TransferArunika.objects.get()

    def test_urutan_dan_hasil(self):
        run = self._jalan()
        self.assertEqual(self.urutan, [
            ("salin", "PUSAT", "legacy_uji_satu"),
            ("siapkan", "Uji Satu (legacy)", "arunika_uji_satu_sumber", "legacy"),
            ("siapkan", "Uji Satu", "arunika_uji_satu", "arunika"),
            ("muat", "Uji Satu (legacy)", "Uji Satu"),
        ])
        self.assertEqual(run.status, TransferArunika.SELESAI)
        self.assertIsNotNone(run.selesai_pada)
        # Total hanya dari tahap Isi: baris salinan legacy bukan baris Arunika.
        self.assertEqual((run.total_baris, run.total_dilewati), (100, 2))
        self.assertEqual([l["tahap"] for l in run.langkah], ["Salin legacy", "Isi"])
        self.assertEqual(run.langkah[1]["alasan"], {"satuan_dasar_kode kosong (wajib)": 2})

    def test_profil_baru_uji_di_instans_lokal(self):
        run = self._jalan()
        legacy, tujuan = run.profil_legacy, run.profil_arunika
        for p in (legacy, tujuan):
            self.assertEqual(p.lingkungan, Lingkungan.UJI)
            self.assertEqual((p.host, p.username, p.password_encrypted),
                             ("localhost", "sa", "rahasia-lokal"))
            self.assertEqual(p.db_type, "grosir")
        self.assertEqual(legacy.db_name, "legacy_uji_satu")
        self.assertEqual(tujuan.db_name, transfer.TANPA_LEGACY)

    def test_galat_tercatat_dan_berhenti(self):
        def gagal(*_a, **_k):
            raise Ditolak("Server 'PUSAT' tak punya tabel yang dibutuhkan")
        run = self._jalan(salin=gagal)
        self.assertEqual(run.status, TransferArunika.GAGAL)
        self.assertIn("tak punya tabel", run.pesan_galat)
        self.assertIsNotNone(run.profil_legacy)
        self.assertIsNone(run.profil_arunika)
        self.assertEqual(self.urutan, [])

    def test_galat_tak_terduga_tetap_tercatat(self):
        """Di thread latar, galat yang tak ditangkap hilang tanpa jejak di layar."""
        def meledak(*_a, **_k):
            raise KeyError("x")
        run = self._jalan(muat=meledak)
        self.assertEqual(run.status, TransferArunika.GAGAL)
        self.assertIn("KeyError", run.pesan_galat)

    def test_log_aktivitas_milik_pemulai(self):
        self._jalan()
        log = ActivityLog.objects.get(action="transfer_arunika")
        self.assertEqual(log.username, "boss")

    def test_satu_sekaligus(self):
        berhenti = threading.Event()
        t = threading.Thread(target=berhenti.wait, daemon=True)
        t.start()
        transfer._thread[9999] = t
        try:
            with self.assertRaises(Ditolak):
                transfer.mulai(self.data, "boss", sinkron=True)
        finally:
            berhenti.set()
            transfer._thread.pop(9999, None)
        self.assertFalse(TransferArunika.objects.exists())

    def test_yatim_jadi_terputus(self):
        run = TransferArunika.objects.create(nama="lama", dari=dt.date(2025, 1, 1),
                                             sampai=dt.date(2025, 1, 2))
        self.assertEqual(transfer.rapikan_yatim(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, TransferArunika.TERPUTUS)


class StokBenar(SimpleTestCase):
    """Stok profil legacy berjangkar di tutup buku sumber: di luar rentang, salah.
    Terukur pada salinan PUSAT Januari 2025 -- 31 Des 2025 nol beda, 31 Jan 2025
    beda di 9.741 barang."""

    def _run(self, dari, sampai, tutup):
        return TransferArunika(nama="x", dari=dari, sampai=sampai, tutup_buku=tutup)

    def test_rentang_mencakup_tutup_buku(self):
        self.assertTrue(self._run(dt.date(2025, 1, 1), dt.date(2025, 12, 31), TUTUP).stok_benar)

    def test_rentang_sebelum_tutup_buku(self):
        self.assertFalse(self._run(dt.date(2025, 1, 1), dt.date(2025, 1, 31), TUTUP).stok_benar)

    def test_tanpa_tutup_buku_tak_diketahui(self):
        self.assertIsNone(self._run(dt.date(2025, 1, 1), dt.date(2025, 1, 31), None).stok_benar)


class GerbangLayar(TestCase):
    URL = "/admin-panel/master/transfer-arunika"

    def setUp(self):
        self.boss = User.objects.create_user("boss9", password="rahasia-kuat-123",
                                             role=Role.SUPERADMIN)
        self.admin = User.objects.create_user("admin9", password="rahasia-kuat-123",
                                              role=Role.ADMIN)

    def test_admin_biasa_tidak_boleh_membuka(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 302)
        self.assertNotEqual(r["Location"], self.URL)

    def test_admin_biasa_tidak_boleh_memulai(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.URL + "/mulai", {"nama": "x"}, content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TransferArunika.objects.exists())

    def test_superadmin_boleh_membuka(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_input_tak_valid_tak_membuat_apa_pun(self):
        self.client.force_login(self.boss)
        r = self.client.post(self.URL + "/mulai", {"nama": "", "sumber": "", "dari": "x"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(TransferArunika.objects.exists())
        self.assertFalse(ServerProfile.objects.exists())

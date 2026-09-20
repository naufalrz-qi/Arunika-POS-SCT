"""Cadangan, verifikasinya, dan invarian "tidak ada restore".

Test paling penting di berkas ini bukan yang membuktikan cadangan berhasil,
melainkan yang membuktikan **verifikasi bisa berkata TIDAK**. Verifikasi yang
selalu menjawab "ok" lebih berbahaya daripada tidak ada verifikasi sama sekali,
karena ia memberi keyakinan palsu pada berkas yang sudah rusak.
"""
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bisnis.siapkan import Ditolak
from apps.connections.models import ServerProfile
from apps.core import cadangan as cad
from apps.core.management.commands import backup_db
from apps.core.models import CadanganBerkas, SyncLog


class VerifikasiDiInstansYangMenulisnya(TestCase):
    """Cadangan pangkal diverifikasi lewat koneksi Django, AMPHOREUS lewat hub.

    Ini bukan rapi-rapi: berkas `.bak` hanya bisa dibaca oleh instans yang
    menulisnya. Pangkal ada di mesin aplikasi, AMPHOREUS di SERVER-RETAIL.
    Versi lama mengirim SEMUA verifikasi ke cursor AMPHOREUS, jadi cadangan
    pangkal yang sehat akan dilaporkan rusak — persis keyakinan palsu yang
    modul ini ada untuk mencegahnya, hanya terbalik arahnya.
    """

    def _baris(self, jenis, profile=None) -> CadanganBerkas:
        return CadanganBerkas.objects.create(
            jenis=jenis, profile=profile, nama_berkas="db-uji.bak",
            path="D:/backup/db-uji.bak",
        )

    def test_jenis_menentukan_instansnya(self):
        """Perutean, bukan SQL-nya: PANGKAL ke koneksi sendiri, AMPHOREUS ke hub."""
        profil = ServerProfile.objects.create(
            name="AMPHOREUS", host="SERVER-RETAIL", db_name="AMPHOREUS", username="sa")
        with patch.object(cad, "_cek_pangkal", return_value=(True, "jalur-pangkal")), \
             patch.object(cad, "_cek_mssql", return_value=(True, "jalur-hub")):
            pangkal = cad.verifikasi(self._baris(cad.PANGKAL).pk)
            hub = cad.verifikasi(self._baris(cad.AMPHOREUS, profil).pk)
        self.assertEqual(pangkal.verifikasi_pesan, "jalur-pangkal")
        self.assertEqual(hub.verifikasi_pesan, "jalur-hub")

    def test_sql_pangkal_memakai_cursor_django(self):
        dieksekusi = []

        class Kursor:
            def execute(self, sql, params=None):
                dieksekusi.append((sql, params))

            def nextset(self):
                return False

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class Koneksi:
            def cursor(self):
                return Kursor()

        baris = self._baris(cad.PANGKAL)
        with patch.object(cad, "connection", Koneksi()), \
             patch.object(cad, "_hub", side_effect=AssertionError("jalur pangkal tak boleh memanggil _hub()")):
            ok, pesan = cad._cek_pangkal(baris)
        self.assertTrue(ok)
        sql, params = dieksekusi[0]
        self.assertIn("RESTORE VERIFYONLY", sql)
        self.assertIn("WITH CHECKSUM", sql)
        # `%s`, bukan `?`: ini cursor Django, bukan pyodbc mentah.
        self.assertIn("FROM DISK = %s", sql)
        self.assertEqual(params, [baris.path])

    def test_kegagalan_instans_bukan_ok(self):
        """Verifikasi yang selalu menjawab "ok" lebih berbahaya daripada tak ada
        verifikasi."""
        import pyodbc

        def meledak(*a, **k):
            raise pyodbc.Error("42000", "[42000] RESTORE VERIFYONLY gagal")

        with patch.object(cad, "_cek_pangkal", side_effect=meledak):
            hasil = cad.verifikasi(self._baris(cad.PANGKAL).pk)
        self.assertIs(hasil.verifikasi_ok, False)
        self.assertNotEqual(hasil.verifikasi_pesan, "ok")
        self.assertIsNotNone(hasil.verifikasi_at)


class PenjagaLegacy(TestCase):
    """14 profil legacy tidak boleh bisa jadi sasaran cadangan, dengan cara apa pun."""

    def test_jalankan_hub_tidak_menerima_profil(self):
        """Bukan sekadar konvensi: fungsinya memang tak punya parameter profil,
        jadi form yang dipalsukan pun tak punya tempat untuk menaruh sasaran."""
        import inspect

        params = list(inspect.signature(cad.jalankan_hub).parameters)
        self.assertEqual(params, ["username"])

    def test_hub_belum_ada_ditolak(self):
        with self.assertRaises(Ditolak) as cm:
            cad.jalankan_hub("sa")
        self.assertIn("AMPHOREUS", str(cm.exception))

    def test_verifikasi_menolak_baris_yang_bukan_hub(self):
        hub = ServerProfile.objects.create(name="AMPHOREUS", host="h", db_name="amphoreus", username="u")
        legacy = ServerProfile.objects.create(name="GUDANG", host="h2", db_name="SOLID_SIM", username="u")
        baris = CadanganBerkas.objects.create(
            jenis=cad.AMPHOREUS, profile=legacy, nama_berkas="db-x.bak", path="D:/b/db-x.bak",
        )
        hasil = cad.verifikasi(baris.pk)
        self.assertIs(hasil.verifikasi_ok, False)
        self.assertIn("bukan cadangan AMPHOREUS", hasil.verifikasi_pesan)
        self.assertTrue(hub.pk)  # hub ada, jadi penolakannya bukan karena hub hilang


class TidakAdaJalurRestore(TestCase):
    """Invarian yang dibeli dengan satu keputusan sadar, bukan kelupaan.

    Kalau suatu hari seseorang menambahkan `RESTORE DATABASE` ke sebuah view
    "supaya praktis", test ini yang menghentikannya — bukan review.
    """

    def test_restore_hanya_ada_sebagai_teks_runbook(self):
        """Dipindai lewat AST, bukan teks mentah.

        Versi pertama memindai isi berkas apa adanya dan langsung menyala pada
        sebuah KOMENTAR yang menjelaskan aturan ini. Invarian yang menyala untuk
        komentar akan dilemahkan orang pertama yang terganggu olehnya — dan
        invarian yang dilemahkan tak menjaga apa pun. SQL hanya bisa dieksekusi
        dari string literal, dan komentar tidak masuk AST.
        """
        import ast

        akar = Path(__file__).resolve().parent.parent.parent
        pola = re.compile(r"RESTORE\s+(DATABASE|LOG)\b", re.I)
        pelanggar = []
        for f in (list(akar.glob("apps/**/*.py")) + list(akar.glob("core/**/*.py"))
                  + list(akar.glob("config/**/*.py"))):
            if f.name in ("cadangan.py", "test_cadangan.py"):
                continue  # RUNBOOK dan test ini sendiri
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and pola.search(node.value):
                    pelanggar.append(f"{f.relative_to(akar)}:{node.lineno}")
        # Vue tak punya alasan apa pun memuat SQL, jadi di sana teks mentah cukup.
        for f in akar.glob("frontend/**/*.vue"):
            if pola.search(f.read_text(encoding="utf-8")):
                pelanggar.append(str(f.relative_to(akar)))
        self.assertEqual(pelanggar, [], f"RESTORE DATABASE muncul di luar RUNBOOK: {pelanggar}")

    def test_runbook_memang_memuat_langkahnya(self):
        """Sisi lain invarian yang sama: kalau runbook-nya kosong, pengecualian
        di atas cuma menyembunyikan ketiadaan prosedur."""
        self.assertIn("RESTORE DATABASE", cad.RUNBOOK)
        self.assertIn("POS_FERNET_KEY", cad.RUNBOOK)
        self.assertIn("pull_hub", cad.RUNBOOK)

    def test_tidak_ada_rute_restore(self):
        from apps.monitoring import urls as u

        self.assertEqual(
            [p.name for p in u.urlpatterns if p.name and "restore" in p.name.lower()], [],
        )


class _KursorPalsu:
    """Cursor palsu yang menghitung `nextset()` — lihat KeluaranBackupDihabiskan."""

    def __init__(self, sisa_result_set: int = 2):
        self.dieksekusi = []
        self.sisa = sisa_result_set
        self.nextset_dipanggil = 0

    def execute(self, sql, params=None):
        self.dieksekusi.append((sql, params))

    def nextset(self):
        self.nextset_dipanggil += 1
        self.sisa -= 1
        return self.sisa > 0


class JalurMssqlCadangan(TestCase):
    def test_checksum_wajib_ada(self):
        """Tanpa CHECKSUM saat backup, RESTORE VERIFYONLY hanya memeriksa header
        dan akan bilang "ok" untuk berkas yang halamannya rusak."""
        kur = _KursorPalsu()
        backup_db.backup_mssql(kur, "AMPHOREUS", Path("D:/b"))
        self.assertIn("WITH INIT, CHECKSUM", kur.dieksekusi[0][0])

    def test_placeholder_mengikuti_gaya_cursor(self):
        """pyodbc memakai `?`, cursor Django `%s`. Menebaknya dari bentuk objek
        akan diam-diam salah di salah satu jalur, dan baru terlihat saat
        cadangan dijalankan sungguhan."""
        a, b = _KursorPalsu(), _KursorPalsu()
        backup_db.backup_mssql(a, "A", Path("D:/b"))
        backup_db.backup_mssql(b, "A", Path("D:/b"), ph="?")
        self.assertIn("TO DISK = %s", a.dieksekusi[0][0])
        self.assertIn("TO DISK = ?", b.dieksekusi[0][0])

    def test_keluaran_backup_dihabiskan(self):
        """`BACKUP` mengirim pesan progresnya sebagai result set, dan baru selesai
        setelah semuanya dihabiskan.

        Tanpa `nextset()`, menutup cursor MEMBATALKAN statement-nya: tak ada
        berkas, tak ada baris di `msdb.dbo.backupset`, dan **tak ada galat sama
        sekali** — layar Cadangan menampilkan baris baru untuk berkas yang tidak
        pernah ada. Terukur di mesin ini: berkas 0 byte tanpa ini, 238 MB
        dengannya.
        """
        kur = _KursorPalsu(sisa_result_set=3)
        backup_db.backup_mssql(kur, "A", Path("D:/b"))
        self.assertEqual(kur.nextset_dipanggil, 3, "result set BACKUP tidak dihabiskan")

    def test_nama_database_nakal_ditolak(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            backup_db.backup_mssql(None, "A]; DROP DATABASE B--", Path("D:/b"))


class CatatIdempoten(TestCase):
    def test_cadangan_ulang_memperbarui_baris_bukan_menambah(self):
        """Cadangan harian menimpa berkas bertanggal sama. Baris kedua akan
        menunjuk berkas yang isinya sudah berganti — dan membawa serta hasil
        verifikasi isi LAMA."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            berkas = Path(d) / "db-uji.bak"
            berkas.write_bytes(b"x")
            a = cad.catat(cad.PANGKAL, None, berkas, "sa")
            with patch.object(cad, "_cek_pangkal", return_value=(True, "ok")):
                cad.verifikasi(a.pk)
            b = cad.catat(cad.PANGKAL, None, berkas, "sa")
        self.assertEqual(CadanganBerkas.objects.count(), 1)
        self.assertEqual(a.pk, b.pk)
        self.assertIsNone(b.verifikasi_ok, "verifikasi isi lama harus ikut direset")


class RuteCadangan(TestCase):
    def setUp(self):
        U = get_user_model()
        self.admin = U.objects.create_user(username="adm", password="x", role="admin")
        self.sa = U.objects.create_user(username="sa", password="x", role="superadmin")

    def test_admin_ditolak_di_ketiga_rute(self):
        self.client.force_login(self.admin)
        self.assertNotEqual(self.client.get("/admin-panel/pengaturan/cadangan").status_code, 200)
        for rute in ("jalankan", "verifikasi"):
            resp = self.client.post(f"/admin-panel/pengaturan/cadangan/{rute}", {"jenis": "pangkal", "id": "1"})
            self.assertNotEqual(resp.status_code, 302)
        self.assertEqual(CadanganBerkas.objects.count(), 0)

    def test_tombol_layar_mengirim_json(self):
        """Layar memakai Inertia `useForm.post`, yang mengirim **body JSON** —
        dan untuk body JSON `request.POST` selalu kosong.

        Test lain di berkas ini mengirim form-encoded seperti `Client.post`
        bawaan, jadi semuanya hijau sementara tombolnya di layar selalu dijawab
        "Jenis cadangan tidak dikenal". Ditemukan dengan mengklik tombolnya
        sungguhan, bukan oleh test.
        """
        import json
        import tempfile

        def palsu(cur, nama_db, tujuan, ph="%s"):
            tujuan.mkdir(parents=True, exist_ok=True)
            berkas = tujuan / "db-uji.bak"
            berkas.write_bytes(b"x")
            return berkas

        self.client.force_login(self.sa)
        with tempfile.TemporaryDirectory() as d, \
             patch.dict("os.environ", {"BACKUP_DIR": d}), \
             patch.object(backup_db, "backup_mssql", side_effect=palsu):
            resp = self.client.post(
                "/admin-panel/pengaturan/cadangan/jalankan",
                data=json.dumps({"jenis": "pangkal"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("flash_error", self.client.session)
        self.assertEqual(CadanganBerkas.objects.count(), 1)

        baris = CadanganBerkas.objects.get()
        with patch.object(cad, "_cek_pangkal", return_value=(True, "ok")):
            resp = self.client.post(
                "/admin-panel/pengaturan/cadangan/verifikasi",
                data=json.dumps({"id": baris.pk}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 302)
        baris.refresh_from_db()
        self.assertIs(baris.verifikasi_ok, True)

    def test_jenis_tak_dikenal_jadi_flash_bukan_500(self):
        self.client.force_login(self.sa)
        resp = self.client.post("/admin-panel/pengaturan/cadangan/jalankan", {"jenis": "legacy"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("tidak dikenal", self.client.session["flash_error"])
        self.assertEqual(CadanganBerkas.objects.count(), 0)

    def test_cadangan_pangkal_lewat_web_mencatat_riwayat(self):
        # `BACKUP DATABASE` sungguhan menulis berkas ratusan MB di mesin SQL
        # Server; yang diuji di sini RUTE-nya, bukan backup-nya.
        import tempfile

        def palsu(cur, nama_db, tujuan, ph="%s"):
            tujuan.mkdir(parents=True, exist_ok=True)
            berkas = tujuan / "db-uji.bak"
            berkas.write_bytes(b"x")
            return berkas

        self.client.force_login(self.sa)
        with tempfile.TemporaryDirectory() as d, \
             patch.dict("os.environ", {"BACKUP_DIR": d}), \
             patch.object(backup_db, "backup_mssql", side_effect=palsu):
            resp = self.client.post("/admin-panel/pengaturan/cadangan/jalankan", {"jenis": "pangkal"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CadanganBerkas.objects.count(), 1)
        baris = SyncLog.objects.get(feature="backup")
        self.assertEqual(baris.mode, "pangkal")
        self.assertEqual(baris.username, "sa")

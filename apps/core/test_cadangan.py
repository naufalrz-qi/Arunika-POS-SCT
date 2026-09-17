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
from django.db import connection
from django.test import TestCase, TransactionTestCase

from apps.bisnis.siapkan import Ditolak
from apps.connections.models import ServerProfile
from apps.core import cadangan as cad
from apps.core.management.commands import backup_db
from apps.core.models import CadanganBerkas, SyncLog


class VerifikasiSqlite(TransactionTestCase):
    """TransactionTestCase, bukan TestCase: `VACUUM INTO` ditolak SQLite kalau
    dijalankan di dalam transaksi, dan TestCase membungkus tiap test dalam satu."""

    def _baris(self, berkas: Path) -> CadanganBerkas:
        return CadanganBerkas.objects.create(
            jenis=cad.PANGKAL, nama_berkas=berkas.name, path=str(berkas),
            ukuran_byte=berkas.stat().st_size if berkas.exists() else 0,
        )

    def test_berkas_rusak_terdeteksi(self):
        """Ini test inti. Kalau ia hijau pada berkas sampah, verifikasinya bohong."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            berkas = Path(d) / "db-rusak.sqlite3"
            berkas.write_bytes(b"ini jelas bukan berkas sqlite")
            hasil = cad.verifikasi(self._baris(berkas).pk)
        self.assertIs(hasil.verifikasi_ok, False)
        self.assertTrue(hasil.verifikasi_pesan)
        self.assertNotEqual(hasil.verifikasi_pesan, "ok")
        self.assertIsNotNone(hasil.verifikasi_at)

    def test_berkas_sehat_lulus(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            berkas = backup_db.backup_sqlite(connection, Path(d))
            hasil = cad.verifikasi(self._baris(berkas).pk)
        self.assertIs(hasil.verifikasi_ok, True)
        self.assertEqual(hasil.verifikasi_pesan, "ok")

    def test_berkas_hilang_bukan_ok(self):
        hasil = cad.verifikasi(self._baris(Path("Z:/tidak/ada/db-x.sqlite3")).pk)
        self.assertIs(hasil.verifikasi_ok, False)

    def test_verifikasi_tidak_menulis_wal_di_folder_cadangan(self):
        """`mode=ro` lewat URI. Tanpa itu sqlite bisa membuat -wal/-shm di
        sebelah berkas cadangan — menulis ke folder cadangan justru saat sedang
        memeriksanya."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            berkas = backup_db.backup_sqlite(connection, Path(d))
            cad.verifikasi(self._baris(berkas).pk)
            sisa = sorted(p.name for p in Path(d).iterdir())
        self.assertEqual(sisa, [berkas.name])


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


class JalurMssqlCadangan(TestCase):
    def test_checksum_wajib_ada(self):
        """Tanpa CHECKSUM saat backup, RESTORE VERIFYONLY hanya memeriksa header
        dan akan bilang "ok" untuk berkas yang halamannya rusak."""
        dieksekusi = []

        class Kursor:
            def execute(self, sql, params=None):
                dieksekusi.append(sql)

        backup_db.backup_mssql(Kursor(), "AMPHOREUS", Path("D:/b"))
        self.assertIn("WITH INIT, CHECKSUM", dieksekusi[0])

    def test_placeholder_mengikuti_gaya_cursor(self):
        """pyodbc memakai `?`, cursor Django `%s`. Menebaknya dari bentuk objek
        akan diam-diam salah di salah satu jalur, dan baru terlihat saat
        cadangan dijalankan sungguhan."""
        dieksekusi = []

        class Kursor:
            def execute(self, sql, params=None):
                dieksekusi.append(sql)

        backup_db.backup_mssql(Kursor(), "A", Path("D:/b"))
        backup_db.backup_mssql(Kursor(), "A", Path("D:/b"), ph="?")
        self.assertIn("TO DISK = %s", dieksekusi[0])
        self.assertIn("TO DISK = ?", dieksekusi[1])

    def test_nama_database_nakal_ditolak(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            backup_db.backup_mssql(None, "A]; DROP DATABASE B--", Path("D:/b"))


class CatatIdempoten(TransactionTestCase):
    """TransactionTestCase — alasan yang sama: memanggil `backup_sqlite` sungguhan."""

    def test_cadangan_ulang_memperbarui_baris_bukan_menambah(self):
        """Cadangan harian menimpa berkas bertanggal sama. Baris kedua akan
        menunjuk berkas yang isinya sudah berganti — dan membawa serta hasil
        verifikasi isi LAMA."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            berkas = backup_db.backup_sqlite(connection, Path(d))
            a = cad.catat(cad.PANGKAL, None, berkas, "sa")
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

    def test_jenis_tak_dikenal_jadi_flash_bukan_500(self):
        self.client.force_login(self.sa)
        resp = self.client.post("/admin-panel/pengaturan/cadangan/jalankan", {"jenis": "legacy"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("tidak dikenal", self.client.session["flash_error"])
        self.assertEqual(CadanganBerkas.objects.count(), 0)

    def test_cadangan_pangkal_lewat_web_mencatat_riwayat(self):
        # VACUUM INTO tak bisa jalan di dalam transaksi TestCase, jadi jalur
        # cadangannya dipalsukan; yang diuji di sini RUTE-nya, bukan VACUUM.
        import tempfile

        def palsu(conn, tujuan):
            tujuan.mkdir(parents=True, exist_ok=True)
            berkas = tujuan / "db-uji.sqlite3"
            berkas.write_bytes(b"x")
            return berkas

        self.client.force_login(self.sa)
        with tempfile.TemporaryDirectory() as d, \
             patch.dict("os.environ", {"BACKUP_DIR": d}), \
             patch.object(backup_db, "backup_sqlite", side_effect=palsu):
            resp = self.client.post("/admin-panel/pengaturan/cadangan/jalankan", {"jenis": "pangkal"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CadanganBerkas.objects.count(), 1)
        baris = SyncLog.objects.get(feature="backup")
        self.assertEqual(baris.mode, "pangkal")
        self.assertEqual(baris.username, "sa")

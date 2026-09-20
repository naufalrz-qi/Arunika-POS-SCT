"""Kontrak `backup_db` sesudah basis data aplikasi bisa pindah ke MS SQL.

Perintah ini punya satu sifat yang membuatnya layak diuji meski pendek: ia
tidak boleh **diam-diam tidak mencadangkan apa pun**. Yang dijaganya adalah
satu-satunya data di sistem ini yang tak punya salinan di server mana pun --
akun, hak menu, dan `TautanUser` (pekerjaan manual belasan baris per orang).
Cadangan yang gagal tanpa suara persis sama buruknya dengan tidak ada cadangan,
dan baru ketahuan pada hari orang membutuhkannya.

Tiga hal yang diuji, semuanya tanpa SQL Server sungguhan:

1. Mesin yang tak dikenal **berhenti dengan galat**, bukan sukses palsu.
2. `WITH INIT` ada di perintah MS SQL. Tanpa itu `BACKUP DATABASE` MENAMBAHKAN
   set cadangan ke berkas yang sama alih-alih menimpanya, dan berkas harian
   tumbuh selamanya tanpa satu pun tanda.
3. Nama database dikurung `[ ]`, dan nama yang tak bisa dikutip aman ditolak --
   nama database tidak bisa jadi parameter, jadi ia satu-satunya bagian yang
   disisipkan ke string SQL.
"""
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase


class _CursorPalsu:
    """Cursor secukupnya: merekam SQL + params, tak menyentuh database apa pun."""

    def __init__(self, rekaman):
        self.rekaman = rekaman

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.rekaman.append((sql, params))

    def nextset(self):
        # BACKUP mengirim pesan progres sebagai result set dan HARUS dihabiskan;
        # lihat `backup_db.backup_mssql`. Palsu ini tak punya apa-apa lagi.
        return False


def _jalankan(vendor, nama_db="arunika", **opts):
    """Jalankan backup_db terhadap koneksi palsu; pulangkan SQL yang dijalankan."""
    rekaman = []
    conn = mock.MagicMock()
    conn.vendor = vendor
    conn.settings_dict = {"NAME": nama_db}
    # MagicMock memulangkan objek truthy untuk atribut apa pun, dan penjaga
    # "jangan BACKUP di dalam transaksi" membaca yang ini.
    conn.in_atomic_block = False
    conn.cursor.return_value = _CursorPalsu(rekaman)
    with mock.patch("apps.core.management.commands.backup_db.connection", conn):
        call_command("backup_db", "--dir", r"D:\backup\arunika", "--keep-days", "0", **opts)
    return rekaman


class MesinTakDikenal(SimpleTestCase):
    def test_berhenti_dengan_galat(self):
        """Sukses palsu di sini berarti tak ada cadangan, dan tak ada yang tahu."""
        with self.assertRaises(CommandError) as ctx:
            _jalankan("postgresql")
        self.assertIn("postgresql", str(ctx.exception))


class JalurMssql(TestCase):
    """TestCase, bukan SimpleTestCase: `backup_db` sekarang mencatat berkas
    hasilnya ke `CadanganBerkas`, supaya layar Cadangan & Pemulihan menampilkan
    cadangan dari Task Scheduler juga — bukan cuma yang dipicu dari web."""

    def test_with_init_wajib_ada(self):
        """Tanpa WITH INIT, berkas harian tumbuh selamanya tanpa satu pun tanda."""
        sql, params = _jalankan("microsoft")[0]
        self.assertIn("WITH INIT", sql)
        self.assertEqual(params, [r"D:\backup\arunika\db-" + _tanggal() + ".bak"])

    def test_nama_database_dikurung(self):
        sql, _ = _jalankan("microsoft", nama_db="arunika")[0]
        self.assertIn("BACKUP DATABASE [arunika]", sql)

    def test_vendor_mssql_juga_diterima(self):
        """Nama vendor mssql-django boleh berubah; perintah ini tak boleh ikut patah."""
        self.assertIn("BACKUP DATABASE", _jalankan("mssql")[0][0])

    def test_nama_database_nakal_ditolak(self):
        """`]` akan menutup kurung lebih awal; nama database tak bisa jadi parameter."""
        with self.assertRaises(CommandError):
            _jalankan("microsoft", nama_db="arunika]; DROP DATABASE x --")


def _tanggal():
    import datetime as dt

    return f"{dt.date.today():%Y%m%d}"

"""Cadangan basis data pangkal — satu berkas per hari, plus pemangkasan retensi.

Yang hilang bersama basis data pangkal bukan cuma "data aplikasi": seluruh akun
beserta hak menunya, seluruh `TautanUser` (tautan ke user legacy PER KONEKSI —
pekerjaan manual belasan baris per orang yang tak bisa direkonstruksi dari mana
pun), seluruh audit trail, seluruh cursor sync, dan seluruh password koneksi
terenkripsi. Data bisnisnya sendiri aman di MS SQL cabang; yang di sini justru
satu-satunya yang tak punya salinan di tempat lain.

`BACKUP DATABASE`, dan ada satu perbedaan yang mudah menjebak: **berkasnya
ditulis di mesin SQL SERVER, bukan di mesin yang menjalankan perintah ini.**
Path `--dir` diartikan oleh SQL Server, akun layanannya yang harus punya izin
tulis di sana, dan pemangkasan retensi hanya bisa dilakukan kalau folder itu
kebetulan juga terjangkau dari mesin ini (mesin yang sama, atau share UNC).

Jalur SQLite (`VACUUM INTO`) sudah dihapus bersama SQLite itu sendiri. Berkas
`db-YYYYMMDD.sqlite3` dari pemasangan lama tetap bisa dibaca — bukan oleh
perintah ini, melainkan `manage.py pindah_pangkal`.

`COMPRESSION` sengaja tidak dipakai: SQL Server Express tidak mendukungnya, dan
Express justru edisi yang paling mungkin dipakai pemasangan kecil.

Yang TIDAK dicadangkan di sini, dan wajib disimpan terpisah oleh manusia:
`POS_FERNET_KEY`. Tanpa kuncinya, password koneksi di dalam cadangan ini tetap
terenkripsi selamanya — cadangan yang lengkap tapi tak bisa dipakai.

Jadwalkan lewat Windows Task Scheduler:
    manage.py backup_db --dir D:\\backup\\arunika --keep-days 30
"""
import datetime as dt
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# mssql-django melaporkan dirinya "microsoft"; "mssql" ikut diterima supaya
# perintah ini tidak diam-diam menolak kalau namanya berubah.
_VENDOR_MSSQL = ("microsoft", "mssql")


# --- Fungsi modul: dipakai perintah ini DAN jalur web (apps/core/cadangan.py) --
#
# Diangkat dari method Command supaya SQL cadangan hanya ada di satu tempat.
# `backup_mssql` menerima CURSOR, bukan `connection` — itulah satu perubahan
# yang membuka jalur AMPHOREUS: pusat itu database MS SQL yang bukan basis data
# pangkal, jadi ia dicapai lewat `mssql.cursor(profil)`, bukan lewat koneksi
# Django. Pemeriksaan `]` ikut pindah ke dalam, jadi jalur web mewarisi
# penjagaannya tanpa menyalinnya.

def backup_mssql(cur, nama_db: str, tujuan: Path, ph: str = "%s") -> Path:
    """`ph` adalah gaya placeholder cursor yang diberikan.

    Cursor Django (mssql-django) memakai `%s` dan menerjemahkannya sendiri;
    cursor pyodbc mentah — yang dipakai jalur AMPHOREUS lewat `mssql.cursor()` —
    memakai `?`. Menebaknya dari bentuk objek cursor akan diam-diam salah pada
    salah satu jalur, dan salahnya baru terlihat saat cadangan dijalankan
    sungguhan, bukan saat test.
    """
    # JANGAN mkdir: path ini milik mesin SQL Server, bukan mesin ini. Membuat
    # folder lokal bernama sama hanya akan menyamarkan salah setel jadi
    # "berhasil tapi kok kosong".
    if "]" in nama_db:
        raise CommandError(f"Nama database memuat ']' dan tidak bisa dikutip aman: {nama_db!r}")
    berkas = tujuan / f"db-{dt.date.today():%Y%m%d}.bak"
    # Nama database TIDAK bisa jadi parameter (BACKUP DATABASE ? ditolak parser
    # T-SQL), jadi ia dikurung [ ] setelah diperiksa di atas. Path-nya tetap
    # parameter — path Windows penuh backslash.
    #
    # WITH INIT menimpa isi berkas yang sudah ada. Tanpa itu, BACKUP MENAMBAHKAN
    # set cadangan baru ke berkas yang sama, dan berkas harian akan tumbuh
    # selamanya tanpa ada yang menyadarinya.
    #
    # CHECKSUM bukan hiasan: tanpa checksum yang ditulis SAAT backup,
    # `RESTORE VERIFYONLY` hanya memeriksa header dan struktur set cadangan — ia
    # akan menjawab "ok" untuk berkas yang halamannya sudah rusak. Verifikasi
    # yang selalu bilang ok lebih berbahaya daripada tidak ada verifikasi, karena
    # ia memberi keyakinan palsu. Didukung semua edisi termasuk Express, tidak
    # seperti COMPRESSION.
    cur.execute(f"BACKUP DATABASE [{nama_db}] TO DISK = {ph} WITH INIT, CHECKSUM", [str(berkas)])
    # WAJIB, dan ini bukan kerapian: BACKUP mengirim pesan progresnya sebagai
    # RESULT SET, dan pekerjaannya baru benar-benar selesai setelah semuanya
    # dihabiskan. Cursor yang ditutup lebih dulu membuat ODBC MEMBATALKAN
    # statement-nya — tanpa berkas, tanpa baris di msdb.dbo.backupset, dan
    # TANPA SATU PUN GALAT. Terukur: perintah yang sama menghasilkan berkas 238
    # MB begitu `nextset()` dihabiskan, dan nol byte tanpa itu.
    while cur.nextset():
        pass
    return berkas


def pangkas_berkas(tujuan: Path, berkas: Path, sufiks: str, hari: int) -> int:
    """Hapus cadangan lebih tua dari `hari`. Mengembalikan jumlah yang dibuang."""
    if hari <= 0 or not tujuan.is_dir():
        return 0
    batas = dt.datetime.now().timestamp() - hari * 86400
    dibuang = 0
    for lama in tujuan.glob(f"db-*.{sufiks}"):
        if lama != berkas and lama.stat().st_mtime < batas:
            lama.unlink()
            dibuang += 1
    return dibuang


class Command(BaseCommand):
    help = "Cadangkan basis data pangkal ke berkas bertanggal (BACKUP DATABASE) + pangkas yang lama."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=os.environ.get("BACKUP_DIR", str(settings.BASE_DIR / "backup")),
            help="Folder tujuan. Default: BACKUP_DIR di .env, atau <proyek>/backup.",
        )
        parser.add_argument(
            "--keep-days", type=int, default=30,
            help="Hapus cadangan yang lebih tua dari N hari. 0 = jangan pangkas.",
        )

    def handle(self, *args, **options):
        tujuan = Path(options["dir"])
        # Penjagaan vendor DIPERTAHANKAN walau settings kini hanya mengizinkan
        # MS SQL: ENGINE yang salah setel harus berhenti di sini dengan pesan,
        # bukan menghasilkan "berhasil" tanpa satu berkas pun.
        if connection.vendor not in _VENDOR_MSSQL:
            raise CommandError(
                f"Basis data pangkal bukan MS SQL ({connection.vendor}). "
                "Cadangkan sendiri dengan alat bawaan mesinnya."
            )
        # SQL Server menolak BACKUP di dalam transaksi (galat 3021). Dicegat di
        # sini supaya pesannya menyebut sebabnya, bukan kode galat ODBC.
        if connection.in_atomic_block:
            raise CommandError(
                "BACKUP DATABASE tidak bisa dijalankan di dalam transaksi. "
                "Jalankan perintah ini di luar `atomic()`."
            )
        with connection.cursor() as cur:
            berkas = backup_mssql(cur, connection.settings_dict["NAME"], tujuan)
        sufiks = "bak"
        self.stdout.write(self.style.SUCCESS(f"Cadangan: {berkas} (di mesin SQL Server)"))
        if not berkas.exists():
            self.stdout.write(
                "Catatan: berkasnya tidak terlihat dari mesin ini, jadi ukuran dan "
                "pemangkasan retensi dilewati. Itu wajar kalau SQL Server ada di "
                "mesin lain; verifikasi cadangannya di sana."
            )

        # Dicatat ke `CadanganBerkas` supaya layar Cadangan & Pemulihan
        # menampilkan berkas dari tugas TERJADWAL juga, bukan cuma yang dipicu
        # dari web. Daftar yang hanya memuat separuh cadangan lebih menyesatkan
        # daripada tidak ada daftar sama sekali.
        from apps.core import cadangan

        cadangan.catat(cadangan.PANGKAL, None, berkas, username="(cli)")

        dibuang = pangkas_berkas(tujuan, berkas, sufiks, options["keep_days"])
        if dibuang:
            self.stdout.write(f"Dipangkas: {dibuang} cadangan lebih tua dari {options['keep_days']} hari.")

        # ASCII, bukan em-dash: keluaran ini dibaca di konsol Windows (cp1252),
        # yang mencetak U+2014 sebagai sampah. Aturan yang sama dengan
        # `FeedSyncCursor.__str__` di apps/core/models.py.
        self.stdout.write(self.style.WARNING(
            "Ingat: POS_FERNET_KEY TIDAK ikut di berkas ini. Simpan salinannya "
            "terpisah. Tanpa kuncinya, password koneksi di cadangan ini tak bisa dibuka."
        ))

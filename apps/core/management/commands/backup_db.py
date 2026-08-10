"""Cadangan `db.sqlite3` — satu berkas per hari, plus pemangkasan retensi.

Yang hilang bersama satu berkas `db.sqlite3` bukan cuma "data aplikasi": seluruh
akun beserta hak menunya, seluruh `TautanUser` (tautan ke user legacy PER
KONEKSI — pekerjaan manual belasan baris per orang yang tak bisa direkonstruksi
dari mana pun), seluruh audit trail, seluruh cursor sync, dan seluruh password
koneksi terenkripsi. Data bisnisnya sendiri aman di MS SQL; yang di sini justru
satu-satunya yang tak punya salinan di tempat lain.

`VACUUM INTO`, bukan `shutil.copy`. Pada mode WAL — dan aplikasi ini memakainya
(`config/settings.py` `_enable_sqlite_wal`) — menyalin berkas `.sqlite3` saja
saat server hidup menghasilkan salinan yang KEHILANGAN semua transaksi yang masih
duduk di `-wal` dan belum ter-checkpoint. `VACUUM INTO` mengambil kunci baca,
menulis satu berkas yang konsisten, dan tidak menghentikan siapa pun.

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


class Command(BaseCommand):
    help = "Salin db.sqlite3 ke berkas cadangan bertanggal (VACUUM INTO) + pangkas yang lama."

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
        if connection.vendor != "sqlite":
            raise CommandError(f"Basis data aplikasi bukan SQLite ({connection.vendor}).")

        tujuan = Path(options["dir"])
        tujuan.mkdir(parents=True, exist_ok=True)
        berkas = tujuan / f"db-{dt.date.today():%Y%m%d}.sqlite3"
        # VACUUM INTO menolak menimpa berkas yang sudah ada; dijalankan dua kali
        # dalam sehari itu wajar (uji coba, restart), dan gagal karenanya bukan
        # perilaku yang berguna untuk tugas terjadwal.
        if berkas.exists():
            berkas.unlink()

        with connection.cursor() as cur:
            # Parameter, bukan f-string: path Windows memuat backslash, dan nama
            # folder yang memuat kutip tunggal akan mematahkan literal SQL.
            cur.execute("VACUUM INTO %s", [str(berkas)])

        ukuran = berkas.stat().st_size / 1_048_576
        self.stdout.write(self.style.SUCCESS(f"Cadangan: {berkas} ({ukuran:.1f} MB)"))

        hari = options["keep_days"]
        if hari > 0:
            batas = dt.datetime.now().timestamp() - hari * 86400
            dibuang = 0
            for lama in tujuan.glob("db-*.sqlite3"):
                if lama != berkas and lama.stat().st_mtime < batas:
                    lama.unlink()
                    dibuang += 1
            if dibuang:
                self.stdout.write(f"Dipangkas: {dibuang} cadangan lebih tua dari {hari} hari.")

        # ASCII, bukan em-dash: keluaran ini dibaca di konsol Windows (cp1252),
        # yang mencetak U+2014 sebagai sampah. Aturan yang sama dengan
        # `FeedSyncCursor.__str__` di apps/core/models.py.
        self.stdout.write(self.style.WARNING(
            "Ingat: POS_FERNET_KEY TIDAK ikut di berkas ini. Simpan salinannya "
            "terpisah. Tanpa kuncinya, password koneksi di cadangan ini tak bisa dibuka."
        ))

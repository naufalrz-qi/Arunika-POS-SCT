"""Cadangan pangkal + AMPHOREUS, verifikasinya, dan runbook pemulihannya.

## Apa yang dicadangkan, dan kenapa hanya dua

- **Pangkal** — akun, hak menu, `TautanUser`, seluruh riwayat, password koneksi
  terenkripsi. Satu-satunya data di seluruh sistem yang TIDAK punya salinan di
  mana pun.
- **AMPHOREUS** — pusat data milik kita sendiri. Bisa dibangun ulang dari
  cabang, tapi "bisa" itu berarti menjalankan ulang tarik arsip selama
  berjam-jam untuk sembilan cabang. Sampai sekarang ia tidak punya cadangan apa
  pun dan tidak disebut di dokumen mana pun.

Ke-14 server legacy TIDAK dicadangkan dari sini. Itu mesin milik vendor POS
lama, dan berkas cadangannya ditulis di mesin mereka.

## Kenapa tidak ada RESTORE di sini

Tidak ada fungsi restore, tidak ada endpoint restore, tidak ada tombol restore.
Alasannya bukan kehati-hatian umum, melainkan satu hal yang konkret: proses yang
akan menjalankan restore pangkal adalah proses yang SEDANG MEMEGANG koneksi ke
database yang ditimpanya. Gagal di tengah berarti tidak ada seorang pun yang
bisa login — termasuk untuk memperbaikinya.

Yang ada di sini adalah `RUNBOOK`: teks langkah-per-langkah yang ditampilkan di
layar dan bisa disalin. `apps/core/test_cadangan.py` memastikan `RESTORE
DATABASE` tidak pernah muncul di kode mana pun kecuali sebagai teks di dalamnya.

## Penjaga legacy

`jalankan_hub()` TIDAK menerima parameter profil. Sasarannya ditentukan
`HUB_NAME` dan dicocokkan tepat; layar pun tidak punya pemilih server sama
sekali, hanya dua tombol tetap. Tidak ada jalan masuk yang bisa menunjuk salah
satu dari 14 profil legacy, bahkan kalau seseorang memalsukan form-nya.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pyodbc
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.bisnis.siapkan import Ditolak
from apps.core.management.commands import backup_db
from apps.core.models import CadanganBerkas, log_sync
from core import mssql

PANGKAL = CadanganBerkas.PANGKAL
AMPHOREUS = CadanganBerkas.AMPHOREUS

_VENDOR_MSSQL = backup_db._VENDOR_MSSQL


def _folder(env: str = "BACKUP_DIR") -> Path:
    return Path(os.environ.get(env) or os.environ.get("BACKUP_DIR")
                or str(settings.BASE_DIR / "backup"))


def _hub():
    """Profil pusat, dan HANYA itu.

    Dicocokkan tepat dengan `HUB_NAME`. Ini penjaga tunggal yang memastikan
    fungsi cadangan tidak pernah bisa menunjuk server legacy — bukan daftar
    hitam yang harus dijaga tetap lengkap, melainkan daftar putih beranggota
    satu yang isinya ditentukan env, bukan input pengguna.
    """
    from apps.connections.models import ServerProfile

    nama = os.environ.get("HUB_NAME", "AMPHOREUS")
    hub = ServerProfile.objects.filter(name=nama).first()
    if hub is None:
        raise Ditolak(f"Profil pusat '{nama}' belum ada. Buat dulu di Kelola Koneksi.")
    return hub


def catat(jenis: str, profile, berkas: Path, username: str = "") -> CadanganBerkas:
    """Catat satu berkas cadangan. Idempoten per (jenis, path).

    `update_or_create`, bukan `create`: cadangan harian menimpa berkas
    bertanggal sama (VACUUM INTO menghapus dulu, BACKUP pakai WITH INIT), jadi
    baris kedua akan menunjuk berkas yang isinya sudah berganti — dan hasil
    verifikasi lama ikut terbawa ke isi baru.
    """
    baris, _ = CadanganBerkas.objects.update_or_create(
        jenis=jenis, path=str(berkas),
        defaults={
            "profile": profile,
            "nama_berkas": berkas.name,
            # 0 kalau tak terjangkau dari mesin ini — itu KEADAAN NORMAL untuk
            # .bak yang ditulis SQL Server di mesin lain, bukan kegagalan.
            "ukuran_byte": berkas.stat().st_size if berkas.exists() else 0,
            "dibuat_at": timezone.now(),
            "dibuat_oleh": username,
            # Isi berkas berganti, jadi verifikasi lama tak berlaku lagi.
            "verifikasi_at": None,
            "verifikasi_ok": None,
            "verifikasi_pesan": "",
        },
    )
    return baris


def jalankan_pangkal(username: str = "") -> CadanganBerkas:
    """Cadangkan basis data pangkal — SQLite atau MS SQL, mengikuti vendornya."""
    tujuan = _folder()
    if connection.vendor == "sqlite":
        berkas = backup_db.backup_sqlite(connection, tujuan)
    elif connection.vendor in _VENDOR_MSSQL:
        with connection.cursor() as cur:
            berkas = backup_db.backup_mssql(cur, connection.settings_dict["NAME"], tujuan)
    else:
        raise Ditolak(
            f"Basis data aplikasi bukan SQLite maupun MS SQL ({connection.vendor}). "
            "Cadangkan sendiri dengan alat bawaan mesinnya."
        )
    return catat(PANGKAL, None, berkas, username)


def jalankan_hub(username: str = "") -> CadanganBerkas:
    """Cadangkan AMPHOREUS lewat `BACKUP DATABASE` di instans yang menampungnya.

    Berkasnya ditulis DI MESIN SQL SERVER. Kalau instansnya di mesin lain, path
    `BACKUP_DIR_HUB` diartikan di sana dan berkasnya tidak akan terlihat dari
    sini — `ukuran_byte` 0 mengatakan itu, dan layar menampilkannya apa adanya
    alih-alih diam.
    """
    hub = _hub()
    tujuan = _folder("BACKUP_DIR_HUB")
    with mssql.cursor(hub) as cur:
        # `ph="?"` — cursor pyodbc mentah, bukan cursor Django.
        berkas = backup_db.backup_mssql(cur, hub.db_name, tujuan, ph="?")
    return catat(AMPHOREUS, hub, berkas, username)


def verifikasi(cadangan_id: int) -> CadanganBerkas:
    """Periksa apakah berkas cadangan benar-benar bisa dibaca kembali.

    Dua jalur, dua alat:

    - **SQLite** — `PRAGMA integrity_check` pada berkasnya, dibuka READ-ONLY
      lewat URI `file:...?mode=ro`. Tanpa `mode=ro`, sqlite bisa membuat
      `-wal`/`-shm` di sebelah berkas cadangan: menulis ke folder cadangan
      justru saat sedang memeriksanya.
    - **MS SQL** — `RESTORE VERIFYONLY ... WITH CHECKSUM`. Ia TIDAK memulihkan
      apa pun, tidak menyentuh database target, tidak membuat atau menimpa
      database mana pun; ia membaca perangkat cadangan dan memeriksa bahwa set
      cadangannya lengkap serta terbaca. `WITH CHECKSUM` memverifikasi checksum
      HALAMAN, bukan cuma header — dan itu baru berarti karena kita menulis
      `WITH ... CHECKSUM` saat backup.

      Satu syarat yang bisa menggigit: `VERIFYONLY` butuh izin setingkat
      `CREATE DATABASE` pada instansnya. Kalau akun profil AMPHOREUS tak
      punya, kegagalannya muncul sebagai `verifikasi_ok=False` dengan pesan
      pyodbc yang jelas — bukan diam.
    """
    baris = CadanganBerkas.objects.get(pk=cadangan_id)
    ok, pesan = False, ""
    try:
        if baris.jenis == PANGKAL and baris.path.endswith(".sqlite3"):
            ok, pesan = _cek_sqlite(Path(baris.path))
        else:
            ok, pesan = _cek_mssql(baris)
    except Ditolak as exc:
        pesan = str(exc)
    except pyodbc.Error as exc:
        pesan = mssql.friendly_error(exc, "Verifikasi gagal")
    except Exception as exc:  # berkas hilang, izin folder, dll
        pesan = f"{type(exc).__name__}: {exc}"
    baris.verifikasi_ok = ok
    baris.verifikasi_pesan = (pesan or ("ok" if ok else "gagal tanpa pesan"))[:255]
    baris.verifikasi_at = timezone.now()
    baris.save(update_fields=["verifikasi_ok", "verifikasi_pesan", "verifikasi_at"])
    return baris


def _cek_sqlite(berkas: Path) -> tuple[bool, str]:
    if not berkas.exists():
        return False, "Berkasnya tidak ada di path yang tercatat."
    con = sqlite3.connect(f"file:{berkas}?mode=ro", uri=True)
    try:
        hasil = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    return hasil == "ok", hasil


def _cek_mssql(baris: CadanganBerkas) -> tuple[bool, str]:
    hub = _hub()
    if baris.profile_id and baris.profile_id != hub.pk:
        raise Ditolak("Baris ini bukan cadangan AMPHOREUS; verifikasi ditolak.")
    with mssql.cursor(hub) as cur:
        cur.execute("RESTORE VERIFYONLY FROM DISK = ? WITH CHECKSUM", [baris.path])
    return True, "ok"


def daftar() -> list[dict]:
    """Isi layar Cadangan & Pemulihan. Murni SQLite + satu `os.path.exists`."""
    keluar = []
    for c in CadanganBerkas.objects.select_related("profile")[:200]:
        p = Path(c.path)
        keluar.append({
            "id": c.pk,
            "jenis": c.get_jenis_display(),
            "jenis_kode": c.jenis,
            "nama_berkas": c.nama_berkas,
            "path": c.path,
            "ukuran_mb": round(c.ukuran_byte / 1_048_576, 1) if c.ukuran_byte else 0,
            "umur_hari": (timezone.now() - c.dibuat_at).days,
            "dibuat_at": timezone.localtime(c.dibuat_at).strftime("%d/%m/%Y %H:%M"),
            "dibuat_oleh": c.dibuat_oleh or "—",
            # None = belum pernah diperiksa. Bukan "gagal".
            "verifikasi_ok": c.verifikasi_ok,
            "verifikasi_pesan": c.verifikasi_pesan,
            "verifikasi_at": (timezone.localtime(c.verifikasi_at).strftime("%d/%m %H:%M")
                              if c.verifikasi_at else ""),
            # Berkas AMPHOREUS memang sering tak terjangkau dari mesin ini, jadi
            # "hilang" hanya berarti sesuatu untuk cadangan pangkal.
            "ada": p.exists() if c.jenis == PANGKAL else None,
        })
    return keluar


def catat_riwayat(baris: CadanganBerkas, username: str) -> None:
    """Satu baris di Riwayat Operasi, supaya cadangan ikut di garis waktu."""
    log_sync(
        None, feature="backup", mode=baris.jenis, src=baris.profile, dst=None,
        compared=0, applied=1, username=username,
        items=[{"teks": f"{baris.nama_berkas} -> {baris.path}"},
               {"teks": f"Ukuran: {baris.ukuran_byte:,} byte"
                        if baris.ukuran_byte else
                        "Ukuran: tak terjangkau dari mesin ini (ditulis di mesin SQL Server)"}],
    )


RUNBOOK = """PEMULIHAN DARI CADANGAN

Baca seluruhnya sebelum menjalankan langkah mana pun. Tidak ada tombol restore
di aplikasi ini, dan itu disengaja: proses yang menjalankan restore pangkal
adalah proses yang sedang memegang koneksi ke database yang ditimpanya. Gagal di
tengah berarti tidak ada seorang pun yang bisa login, termasuk untuk membetulkan.

LANGKAH 0 - KUNCI DULU, BARU DATABASE
  POS_FERNET_KEY TIDAK ADA di cadangan mana pun. Tanpa kuncinya, 14 password
  koneksi di dalam cadangan tetap terenkripsi selamanya: databasenya pulih
  utuh, tapi aplikasi tidak bisa menghubungi satu server pun.
  Pastikan salinan kuncinya ada sebelum melanjutkan.

A. PANGKAL, SQLite (POS_APP_DB_ENGINE=sqlite)
  1. Hentikan layanan waitress. Pastikan tidak ada proses python yang memegang
     db.sqlite3.
  2. Pindahkan db.sqlite3 yang rusak ke nama lain (jangan hapus - ia masih
     bisa jadi bahan pemeriksaan).
  3. Hapus sisa db.sqlite3-wal dan db.sqlite3-shm kalau ada. Berkas -wal milik
     database LAMA; membiarkannya di sebelah database hasil pulih membuat
     sqlite menggabungkan dua database berbeda.
  4. Salin db-YYYYMMDD.sqlite3 dari folder cadangan menjadi db.sqlite3.
  5. venv\\Scripts\\python.exe manage.py migrate --check
     Kalau ia mengeluh ada migrasi tertunda, cadangan itu lebih tua daripada
     kode yang terpasang: jalankan manage.py migrate.
  6. Nyalakan waitress. Login, lalu buka Kelola Tautan User dan pastikan
     jumlah barisnya masuk akal - itu data yang paling mahal di berkas ini.

B. PANGKAL, MS SQL (POS_APP_DB_ENGINE=mssql)
  Dijalankan di SSMS, DI MESIN SQL SERVER, bukan dari aplikasi:
     RESTORE DATABASE [nama_db] FROM DISK = 'D:\\backup\\arunika\\db-YYYYMMDD.bak'
       WITH REPLACE, RECOVERY;
  Hentikan waitress dulu: RESTORE menolak berjalan selama masih ada koneksi
  aktif ke database itu.

C. AMPHOREUS
  1. RESTORE seperti B, memakai berkas .bak AMPHOREUS.
  2. Sesudah pulih, isi ulang jendela segarnya:
       manage.py pull_hub --mode segar --hari 30
  3. Tarik arsip TIDAK perlu diulang selama HubPullState ikut pulih bersama
     pangkal - penanda arsip_sampai ada di sana, bukan di AMPHOREUS. Kalau
     pangkal dan AMPHOREUS dipulihkan dari tanggal yang berbeda, jalankan
       manage.py pull_hub --mode cocok
     dan biarkan ia menemukan hari-hari yang tidak cocok.

SESUDAH PEMULIHAN APA PUN
  Buka Kesehatan Sync. Blok Penjadwal harus menunjukkan tick utama hidup, dan
  blok Pusat AMPHOREUS harus memuat sembilan cabang. Kalau blok pusatnya hilang
  sama sekali, profil AMPHOREUS atau kode_sumber cabang belum ikut pulih.
"""

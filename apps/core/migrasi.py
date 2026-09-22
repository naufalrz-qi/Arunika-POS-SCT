"""Terapkan migrasi dari panel, supaya rilis rutin tak butuh terminal.

Setup awal tetap lewat terminal: `migrate` yang pertama membuat tabel login itu
sendiri, jadi belum ada panel untuk dibuka. Yang dipindah ke sini hanya rilis
rutin — kode baru ditarik, waitress dijalankan ulang, lalu superadmin menerapkan
skemanya dari Pengaturan › Pembaruan Database.

Dua jenis sasaran, dan perlakuannya BERBEDA:

- **Pangkal** (`default`): `migrate` penuh, semua app. `bisnis` ikut tercatat di
  sini sebagai no-op — router melarang tabelnya dibuat di pangkal, tapi Django
  tetap mencatat migrasinya sebagai sudah jalan (21 baris di pangkal saat modul
  ini ditulis). Justru itu yang berguna: migrasi `bisnis` baru ikut tampak
  tertunda DI PANGKAL, jadi penanda di atas halaman menangkap kedua jenis rilis
  tanpa menghubungi DB Arunika mana pun.
- **DB Arunika** (tiap profil ber-`db_arunika`): hanya `migrate bisnis`. BUKAN
  `siapkan.siapkan_arunika`: fungsi itu ikut memasang ulang view adapter menurut
  `mode`, dan mode tiap DB tak disimpan di mana pun — memanggilnya dengan mode
  yang salah diam-diam membalik sumber baca laporannya. Skema saja yang tak
  bergantung mode. Rencananya pun disaring ke `bisnis`: DB itu hanya pernah
  menerima app itu, jadi `auth`/`core`/dst. akan tampak tertunda selamanya kalau
  tak disaring.

DB Arunika yang belum ada BUKAN galat — tak ada yang perlu dimigrasi. Membuatnya
adalah pekerjaan Transfer ke Arunika, yang tahu mode-nya. Keadaan itu nyata, bukan
teori: saat modul ini ditulis kedua profil uji menunjuk DB Arunika yang tak ada.

Sinkron, bukan thread seperti `apps/monitoring/tugas.py`: migrasi aplikasi ini
berukuran detik (`core.0018` jauh di bawah satu detik), dan tugas latar di sana
ada untuk pekerjaan berjam-jam. Kalau suatu rilis membawa migrasi data yang
panjang, pindahkan `jalankan` ke pola tugas itu.

Satu batas yang harus diketahui: kalau migrasi yang tertunda mengubah tabel yang
dibaca SETIAP halaman (akun, sesi, log aktivitas untuk lonceng notif), halaman
login pun bisa gagal sebelum migrasinya sempat diterapkan dari sini. Untuk rilis
seperti itu, terminal tetap jalan keluarnya: `manage.py migrate`.
"""
from __future__ import annotations

import threading

from django.core.management import call_command
from django.db import connections
from django.db.migrations.executor import MigrationExecutor

from apps.bisnis.siapkan import Ditolak, database_ada
from apps.core import db_alias
from core import mssql

APP_ARUNIKA = "bisnis"

# ponytail: kunci sebatas proses. Waitress di sini satu proses banyak thread
# (PRODUCTION.md), jadi dua klik bersamaan tertahan di sini; `manage.py migrate`
# dari terminal pada detik yang sama tetap bisa balapan. Ganti ke sp_getapplock
# kalau suatu saat ada lebih dari satu proses web.
_kunci = threading.Lock()


def tertunda(alias: str = "default", app: str | None = None) -> list[str]:
    """Migrasi yang belum diterapkan di `alias`, berurutan seperti akan dijalankan.

    Sama persis dengan yang dihitung `migrate --plan`: rencana menuju seluruh
    leaf node, dikurangi yang sudah tercatat di `django_migrations` alias itu.
    """
    ex = MigrationExecutor(connections[alias])
    return [
        f"{m.app_label}.{m.name}"
        for m, mundur in ex.migration_plan(ex.loader.graph.leaf_nodes())
        if not mundur and (app is None or m.app_label == app)
    ]


def sasaran() -> list:
    """Pangkal lebih dulu, lalu tiap profil yang punya DB Arunika.

    `None` berarti pangkal. Urutannya disengaja: pangkal yang dibutuhkan
    aplikasi untuk hidup, dan migrasi `bisnis` tak bergantung padanya.
    """
    from apps.connections.models import ServerProfile

    return [None, *ServerProfile.objects.exclude(db_arunika="").order_by("name")]


def _label(profil) -> str:
    return "Pangkal" if profil is None else f"Arunika — {profil.name}"


def _pesan(exc) -> str:
    # Django membungkus galat pyodbc (InterfaceError dst.); teks yang berguna
    # bagi manusia ada di galat aslinya.
    asli = exc.__cause__ or exc
    return mssql.friendly_error(asli, "Gagal")[:300]


def _periksa(profil) -> dict:
    """Satu baris keadaan: `ok` (dengan daftar tertunda), `belum_ada`, atau `galat`."""
    baris = {
        "sasaran": _label(profil),
        "db": "(basis data aplikasi)" if profil is None else profil.db_arunika,
        "keadaan": "ok", "pesan": "", "tertunda": [], "diterapkan": [],
    }
    if profil is None:
        baris["tertunda"] = tertunda()
        return baris
    try:
        if not database_ada(profil, profil.db_arunika):
            baris["keadaan"] = "belum_ada"
            baris["pesan"] = ("Database ini belum dibuat, jadi tak ada yang perlu "
                              "dimigrasi. Siapkan lewat Transfer ke Arunika.")
            return baris
        alias = db_alias.daftarkan(profil)
        try:
            baris["tertunda"] = tertunda(alias, app=APP_ARUNIKA)
        finally:
            connections[alias].close()
    except Exception as exc:  # server jauh mati tak boleh menjatuhkan baris lain
        baris["keadaan"], baris["pesan"] = "galat", _pesan(exc)
    return baris


def status() -> list[dict]:
    return [_periksa(p) for p in sasaran()]


def _terapkan(profil) -> dict:
    baris = _periksa(profil)
    if baris["keadaan"] != "ok" or not baris["tertunda"]:
        return baris
    alias = "default" if profil is None else db_alias.daftarkan(profil)
    app = None if profil is None else APP_ARUNIKA
    sebelum = baris["tertunda"]
    try:
        call_command("migrate", *([app] if app else []), database=alias,
                     interactive=False, verbosity=0)
    except Exception as exc:
        baris["keadaan"], baris["pesan"] = "galat", _pesan(exc)
    finally:
        # Dihitung ulang, bukan diasumsikan: kalau gagal di tengah, sebagian
        # migrasi sudah jadi dan yang tersisa harus tampil apa adanya.
        try:
            baris["tertunda"] = tertunda(alias, app=app)
        except Exception:
            baris["tertunda"] = sebelum
        if profil is not None:
            connections[alias].close()
    baris["diterapkan"] = [m for m in sebelum if m not in baris["tertunda"]]
    return baris


def jalankan() -> list[dict]:
    """Terapkan semua yang tertunda di semua sasaran. Satu sasaran gagal tak
    menghentikan yang lain — masing-masing melaporkan dirinya sendiri."""
    if not _kunci.acquire(blocking=False):
        raise Ditolak("Migrasi sedang berjalan dari sesi lain. Tunggu sampai "
                      "selesai, lalu muat ulang halaman ini.")
    try:
        return [_terapkan(p) for p in sasaran()]
    finally:
        _kunci.release()

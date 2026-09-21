"""Siapkan database Arunika pendamping untuk sebuah `ServerProfile`.

Badan perintah `init_arunika`, dipindah ke sini supaya layar Transfer ke Arunika
bisa memanggilnya tanpa `call_command` dan membaca progresnya langkah demi langkah.

Tiga langkah, idempoten, dan **tidak satu pun menyentuh database legacy**:

  1. `CREATE DATABASE` pendamping bila belum ada
  2. `migrate` skema Arunika ke sana lewat alias runtime
  3. Pasang view adapter `arunika_src.*` (+ iTVF `pergerakan_stok` di mode legacy)

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from __future__ import annotations

from django.core.management import call_command
from django.db import connections

from apps.bisnis import adapter, master_src
from apps.core import db_alias
from core import mssql
from core.encryption import decrypt_checked

# Nama bawaan database pendamping. Bukan `db_name` + akhiran: nama database
# legacy sama (`SOLID_SIM`) di seluruh cabang, jadi akhiran tak menambah apa pun.
NAMA_BAWAAN = "arunika"


class Ditolak(Exception):
    """Galat yang pesannya untuk MANUSIA: perintah terminal menampilkannya sebagai
    CommandError, layar Transfer ke Arunika sebagai pesan galat jalan itu."""


def diam(_peristiwa: dict) -> None:
    """`lapor` bawaan: buang semua peristiwa."""


def sql_buat_database(db: str) -> str:
    if "]" in db:
        raise Ditolak(f"Nama database tak bisa dikutip aman: {db!r}")
    return f"CREATE DATABASE [{db}]"


def database_ada(profil, db: str) -> bool:
    pw = decrypt_checked(profil.password_encrypted)
    conn = mssql._connect(profil.host, profil.port, "master", profil.username, pw)
    try:
        cur = conn.cursor()
        cur.execute("SELECT DB_ID(?)", [db])
        return cur.fetchone()[0] is not None
    finally:
        conn.close()


def siapkan_arunika(profil, db: str | None = None, mode: str = "legacy",
                    lapor=diam, kering: bool = False) -> dict:
    """Jalankan ketiga langkah untuk `profil`. Pulangkan ringkasannya.

    `profil.db_arunika` di-set ke `db` (dan disimpan, kecuali `kering`) SEBELUM
    alias didaftarkan, karena alias dibangun dari kolom itu.
    """
    if mode not in master_src.MODE:
        raise Ditolak(f"Mode tak dikenal: {mode!r}")
    db = (db or profil.db_arunika or NAMA_BAWAAN).strip()
    sql_buat = sql_buat_database(db)
    if db.lower() == (profil.db_name or "").lower():
        raise Ditolak(
            f"Database pendamping tak boleh sama dengan database legacy ({db!r}). "
            "Seluruh rancangan ini bertumpu pada keduanya terpisah."
        )
    hasil = {"db": db, "mode": mode, "tabel": 0, "view": [], "itvf": False}

    # --- 1. Database pendamping ---------------------------------------
    ada = database_ada(profil, db)
    if ada:
        lapor({"jenis": "info", "pesan": f"1. database [{db}] sudah ada"})
    elif kering:
        lapor({"jenis": "info", "pesan": f"1. AKAN membuat database [{db}]"})
    else:
        pw = decrypt_checked(profil.password_encrypted)
        conn = mssql._connect(profil.host, profil.port, "master", profil.username, pw)
        try:
            conn.cursor().execute(sql_buat)
        finally:
            conn.close()
        lapor({"jenis": "info", "pesan": f"1. database [{db}] dibuat"})
    if kering and not ada:
        lapor({"jenis": "info", "pesan": "   (langkah 2-3 dilewati: databasenya belum ada)"})
        return hasil

    semula, profil.db_arunika = profil.db_arunika, db
    if not kering and semula != db:
        profil.save(update_fields=["db_arunika"])
        lapor({"jenis": "info", "pesan": f"   db_arunika profil di-set ke '{db}'"})

    alias = db_alias.daftarkan(profil)

    # --- 2. Migrasi ----------------------------------------------------
    if kering:
        lapor({"jenis": "info", "pesan": f"2. AKAN migrate 'bisnis' ke alias {alias}"})
        lapor({"jenis": "info", "pesan": (
            f"3. AKAN memasang {len(master_src.daftar())} view + 1 iTVF "
            f"{master_src.SKEMA}.* (mode {mode})")})
        return hasil
    call_command("migrate", "bisnis", database=alias, verbosity=0)
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME NOT LIKE 'django_%'"
        )
        hasil["tabel"] = cur.fetchone()[0]
    lapor({"jenis": "info", "pesan": f"2. migrate OK -> {hasil['tabel']} tabel di [{db}]"})

    # --- 3. View adapter ------------------------------------------------
    sumber = profil.db_name if mode == "legacy" else None
    with connections[alias].cursor() as cur:
        hasil["view"] = master_src.pasang(cur, mode, sumber)
        lapor({"jenis": "info", "pesan": (
            f"3. {len(hasil['view'])} view {master_src.SKEMA}.* dipasang (mode {mode}): "
            + ", ".join(hasil["view"]))})
        # Buku besar stok: iTVF, bukan view, karena filternya berparameter dan
        # harus menembus tabel ratusan ribu baris. Hanya untuk mode legacy -- di
        # mode Arunika `pergerakan_stok` sudah tabel nyata.
        if mode == "legacy":
            adapter.pasang(cur, sumber)
            hasil["itvf"] = True
            lapor({"jenis": "info", "pesan": f"4. iTVF {adapter.SKEMA}.pergerakan_stok dipasang"})
    return hasil

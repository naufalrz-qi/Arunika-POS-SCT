"""Mendaftarkan `ServerProfile` sebagai alias `DATABASES` Django saat runtime.

## Kenapa ini perlu ada

Skema bisnis Arunika (`apps/bisnis/models.py`) dikelola migrasi Django, dan
migrasi menyasar sebuah **alias database di settings**. Tapi server bisnis di
aplikasi ini tidak ada di settings: ia dipilih saat runtime dari baris
`ServerProfile` yang password-nya terenkripsi. Modul ini menjembatani keduanya
sehingga `migrate --database=cabang_<kode>` bisa dijalankan terhadap server mana
pun yang terdaftar.

## Yang harus diketahui sebelum mengubahnya

`django.db.connections` **tidak membaca ulang `settings.DATABASES`.** Ia sebuah
`ConnectionHandler` yang menyimpan hasil `configure_settings()` di
`cached_property`, jadi menambah entri ke `settings.DATABASES` saja tidak
berpengaruh apa pun -- alias barunya tetap `ConnectionDoesNotExist`, dan itu
gagal dengan cara yang membingungkan karena settings-nya JELAS berisi entri itu.
Karena itu keduanya diisi: `settings.DATABASES` untuk kode yang membaca settings
langsung, dan `connections.settings` untuk handler yang sesungguhnya dipakai.

`configure_settings()` juga yang mengisi kunci wajib yang tak pernah kita tulis
sendiri (`ATOMIC_REQUESTS`, `AUTOCOMMIT`, `CONN_MAX_AGE`, `TIME_ZONE`, `TEST`,
...). Memanggilnya jauh lebih aman daripada menyalin daftar default Django ke
sini, yang akan menyimpang diam-diam pada rilis berikutnya.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from django.conf import settings
from django.db import connections

from core.encryption import decrypt_checked
from core.mssql import _detect_driver

PREFIX = "cabang_"


def nama_alias(profile) -> str:
    """Alias untuk sebuah profil. `kode_sumber` kalau ada, kalau tidak `id`.

    Sengaja tidak diturunkan dari `name`: nama profil bisa memuat spasi dan
    diubah kapan saja lewat layar Koneksi, sementara alias yang berubah membuat
    `django_migrations` di server itu seolah milik alias lain.
    """
    kunci = (profile.kode_sumber or "").strip() or f"id{profile.id}"
    return f"{PREFIX}{kunci}"


def daftarkan(profile) -> str:
    """Daftarkan `profile` sebagai alias DATABASES. Pulangkan nama aliasnya.

    Idempoten: alias yang sudah terdaftar dipulangkan apa adanya, tanpa
    menyambung ulang.
    """
    alias = nama_alias(profile)
    if alias in connections.settings:
        return alias

    # Database PENDAMPING, bukan `db_name`. Skema Arunika tidak pernah tinggal
    # di dalam database legacy — lihat catatan di `ServerProfile.db_arunika`.
    db = (profile.db_arunika or "").strip()
    if not db:
        raise ValueError(
            f"Profil '{profile.name}' belum punya database Arunika (db_arunika kosong). "
            "Jalankan `manage.py init_arunika` lebih dulu."
        )

    konfigurasi = {
        "ENGINE": "mssql",
        "NAME": db,
        "HOST": profile.host,
        "PORT": str(profile.port or ""),
        "USER": profile.username,
        # Didekripsi CHECKED, sama seperti `mssql.cursor()`: POS_FERNET_KEY yang
        # rusak atau dirotasi harus meledak di sini, bukan menyambung dengan
        # password kosong lalu muncul sebagai galat login yang membingungkan.
        "PASSWORD": decrypt_checked(profile.password_encrypted),
        "OPTIONS": {"driver": _detect_driver()},
    }

    # configure_settings() butuh SELURUH dict database -- ia menolak dict tanpa
    # kunci "default" ("You must define a 'default' database"). Karena itu yang
    # dikirim adalah salinan settings yang ada PLUS alias baru, lalu diambil
    # satu entri saja. Ia sekaligus mengisi kunci wajib yang tak pernah kita
    # tulis sendiri (ATOMIC_REQUESTS, AUTOCOMMIT, CONN_MAX_AGE, TIME_ZONE,
    # TEST, ...), yang jauh lebih aman daripada menyalin daftar default Django
    # ke sini dan membiarkannya menyimpang pada rilis berikutnya.
    lengkap = connections.configure_settings(
        {**connections.settings, alias: konfigurasi}
    )[alias]
    connections.settings[alias] = lengkap
    settings.DATABASES[alias] = lengkap
    return alias


def lupakan(alias: str) -> None:
    """Tutup dan cabut sebuah alias. Dipakai test; aman kalau alias tak ada."""
    if alias in connections:
        connections[alias].close()
        del connections[alias]
    connections.settings.pop(alias, None)
    settings.DATABASES.pop(alias, None)

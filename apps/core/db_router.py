"""Tabel siapa dibuat di database mana.

## Kenapa ini ada

`apps/bisnis/models.py` adalah skema Arunika, dan tempatnya di database Arunika milik
tiap cabang (alias runtime `cabang_*`, lihat `apps/core/db_alias.py`). Tanpa router,
`manage.py migrate` biasa ikut membuat ke-18 tabelnya di pangkal, tempat tak satu pun
dari tabel itu akan pernah berisi satu baris pun.

Sebaliknya juga berlaku, dan ini yang lebih penting: tanpa router,
`migrate --database=cabang_x` tanpa nama app akan menumpahkan auth, sesi, dan log
Django ke dalam database Arunika sebuah cabang.

## Kenapa ada pengecualian untuk test

`apps/bisnis/test_pergerakan.py` adalah `TestCase` yang membuat `Satuan`, `Barang`, dan
`PergerakanStok` lewat ORM di koneksi **default** — aturan buku besar diuji di sana, dan
memindahkannya ke alias tersendiri berarti mengarang satu entri `DATABASES` baru hanya
demi test. Jadi di dalam test, tabel bisnis tetap dibuat di database test.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from django.conf import settings


class PangkalRouter:
    """Pangkal untuk app Django, `cabang_*` untuk `bisnis`."""

    def allow_migrate(self, db, app_label, **hints):
        from apps.core.db_alias import PREFIX  # noqa: PLC0415 — dibaca saat migrate, bukan saat settings

        if app_label == "bisnis":
            return db.startswith(PREFIX) or getattr(settings, "TESTING", False)
        return db == "default"

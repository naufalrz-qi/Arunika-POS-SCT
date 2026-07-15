"""Snapshot saldo stok: bangun ulang PENUH set `pos_stok_snapshot` di DB legacy.

    python manage.py snapshot_stok                 # koneksi aktif
    python manage.py snapshot_stok --profile 3     # ServerProfile id tertentu

Rolling snapshot (satu set per server), dipakai jalur baca stok (Stok Akhir,
Mutasi, dst.) sebagai stok awal supaya tak re-agregasi seluruh histori sejak
tutup buku. Rebuild penuh & self-correcting — aman dijalankan berulang.

Dijalankan terjadwal (scheduler in-process, atau Windows Task Scheduler sekali/
hari dini hari). Marker StokSnapshotRun menjaga cukup sekali/hari.
"""
import pyodbc
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.connections.models import ServerProfile
from apps.core.models import StokSnapshotRun
from apps.inventory.services import snapshot_stok
from core import mssql


class Command(BaseCommand):
    help = "Bangun ulang snapshot saldo stok (pos_stok_snapshot) untuk sebuah koneksi."

    def add_arguments(self, parser):
        parser.add_argument("--profile", type=int, default=None, help="ServerProfile id (default: koneksi aktif)")

    def handle(self, *args, **opts):
        if opts["profile"]:
            profile = ServerProfile.objects.filter(pk=opts["profile"]).first()
            if not profile:
                raise CommandError(f"Profile {opts['profile']} tidak ditemukan.")
        else:
            profile = mssql.get_active_profile()
            if not profile:
                raise CommandError("Tidak ada koneksi aktif.")

        self.stdout.write(f"Snapshot stok: {profile.name} (rebuild penuh, bisa lama)…")
        try:
            res = snapshot_stok(profile)
        except pyodbc.Error as exc:
            raise CommandError(f"Gagal snapshot stok {profile.name}: {exc.args[-1] if exc.args else exc}")

        StokSnapshotRun.objects.update_or_create(
            profile=profile, run_date=timezone.localdate(),
            defaults={"profile_name": profile.name, "rows": res["rows"]},
        )
        self.stdout.write(
            self.style.SUCCESS(f"  {res['rows']} baris saldo ditulis (tanggal {res['tanggal']:%Y-%m-%d %H:%M}).")
        )

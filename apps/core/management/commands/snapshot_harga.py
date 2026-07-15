"""Snapshot harga harian: deteksi perubahan harga_jual per SKU per koneksi.

    python manage.py snapshot_harga                 # koneksi aktif
    python manage.py snapshot_harga --profile 3     # ServerProfile id tertentu
    python manage.py snapshot_harga --prune-days 180  # hapus log > 180 hari lalu snapshot

Diff-only: bandingkan harga sekarang dengan baseline tersimpan (BarangHargaState);
hanya perubahan yang dicatat (BarangHargaChange). Idempotent — run kedua di hari
sama tanpa perubahan di server menghasilkan 0 perubahan.

Dijalankan terjadwal (Windows Task Scheduler, sekali/hari) — stack ini tak punya
Celery/queue (lihat context.md). Hasilnya tampil di halaman "Perubahan Harga Harian".
"""
import pyodbc
from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.master_data.services import snapshot_harga_changes


class Command(BaseCommand):
    help = "Deteksi & catat perubahan harga_jual harian per SKU (diff vs baseline tersimpan)."

    def add_arguments(self, parser):
        parser.add_argument("--profile", type=int, default=None, help="ServerProfile id (default: koneksi aktif)")
        parser.add_argument("--prune-days", type=int, default=None, help="Hapus log perubahan lebih lama dari N hari")

    def handle(self, *args, **opts):
        if opts["prune_days"]:
            from datetime import timedelta

            from django.utils import timezone

            from apps.core.models import BarangHargaChange

            cutoff = timezone.now() - timedelta(days=opts["prune_days"])
            n, _ = BarangHargaChange.objects.filter(detected_at__lt=cutoff).delete()
            self.stdout.write(f"Prune: {n} baris log dihapus (> {opts['prune_days']} hari).")

        if opts["profile"]:
            profiles = list(ServerProfile.objects.filter(pk=opts["profile"]))
            if not profiles:
                raise CommandError(f"Profile {opts['profile']} tidak ditemukan.")
        else:
            profiles = list(ServerProfile.objects.all())
            if not profiles:
                raise CommandError("Belum ada profil koneksi.")

        failed = 0
        for profile in profiles:
            self.stdout.write(f"Snapshot harga: {profile.name}")
            try:
                res = snapshot_harga_changes(profile)
            except pyodbc.Error as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  gagal: {exc.args[-1] if exc.args else exc}"))
                continue
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {res['changes']} perubahan, {res['seeded']} SKU baru di-seed, {res['total']} SKU dibaca."
                )
            )
        if failed:
            raise CommandError(f"{failed} dari {len(profiles)} profil gagal.")

"""Snapshot saldo stok (dua lapis: base beku + live) untuk SEMUA server.

    python manage.py snapshot_stok                 # semua profil
    python manage.py snapshot_stok --profile 3     # satu profil
    python manage.py snapshot_stok --base          # paksa rebuild base beku

Base = saldo ~13 bln lalu (immutable, rebuild bulanan/dipaksa). Live = base +
delta sejak base (rebuild tiap run). Jalur baca (Stok Akhir dkk) pakai live +
delta kecil → detik-an. Rebuild self-correcting untuk edit dalam window base.

Dijalankan terjadwal (scheduler in-process saat server hidup) atau manual di
lokasi. Aman diulang. Satu profil gagal (server mati) tak menghentikan lainnya.
"""
import pyodbc
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.connections.models import ServerProfile
from apps.core.models import StokSnapshotBaseRun, StokSnapshotRun
from apps.inventory.services import _base_date, snapshot_stok, snapshot_stok_base


class Command(BaseCommand):
    help = "Bangun snapshot saldo stok (base beku + live) untuk semua/satu server."

    def add_arguments(self, parser):
        parser.add_argument("--profile", type=int, default=None, help="ServerProfile id (default: SEMUA profil)")
        parser.add_argument("--base", action="store_true", help="Paksa rebuild base beku (scan penuh sejak tutup buku)")

    def handle(self, *args, **opts):
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
            try:
                self._run_one(profile, force_base=opts["base"])
            except pyodbc.Error as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  {profile.name}: gagal — {exc.args[-1] if exc.args else exc}"))
        if failed:
            raise CommandError(f"{failed} dari {len(profiles)} profil gagal.")

    def _run_one(self, profile, force_base):
        base_month = _base_date().strftime("%Y-%m")
        need_base = force_base or not StokSnapshotBaseRun.objects.filter(profile=profile, base_month=base_month).exists()
        if need_base:
            self.stdout.write(f"Snapshot base: {profile.name} (scan penuh, bisa lama)…")
            resb = snapshot_stok_base(profile)
            StokSnapshotBaseRun.objects.update_or_create(
                profile=profile, base_month=base_month,
                defaults={"profile_name": profile.name, "rows": resb["rows"]},
            )
            self.stdout.write(self.style.SUCCESS(f"  base {resb['rows']} baris (as-of {resb['base_date']:%Y-%m-%d})."))

        self.stdout.write(f"Snapshot live: {profile.name}…")
        res = snapshot_stok(profile)
        StokSnapshotRun.objects.update_or_create(
            profile=profile, run_date=timezone.localdate(),
            defaults={"profile_name": profile.name, "rows": res["rows"]},
        )
        self.stdout.write(self.style.SUCCESS(f"  live {res['rows']} baris (as-of {res['tanggal']:%Y-%m-%d %H:%M})."))

"""Incremental CDC sync: legacy server -> report_source replica.

    python manage.py sync_cdc                    # active connection, incremental
    python manage.py sync_cdc --profile 3        # specific ServerProfile id
    python manage.py sync_cdc --backfill          # full copy first (run once,
                                                   # or after a replica rebuild)

Prerequisite: `report_source` must be set on the profile (Kelola Server page),
and CDC must already be enabled on the legacy server for every table in
apps.transactions.cdc_sync.CDC_TABLE_SPECS (DBA step, see that module's
docstring) — this command does not enable CDC itself.

Meant to run on a schedule (Windows Task Scheduler, every 1-2 minutes) once
Phase A (CDC enabled on the legacy server) is done; see the CDC-based
reporting replica plan.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions.cdc_sync import SYNC_ORDER, backfill_table, sync_all
from core import mssql


class Command(BaseCommand):
    help = "Sync legacy transaction/master tables into report_source via CDC (idempotent, resumable)."

    def add_arguments(self, parser):
        parser.add_argument("--profile", type=int, default=None, help="ServerProfile id (default: active)")
        parser.add_argument(
            "--backfill", action="store_true",
            help="Full copy of every table before incremental sync (run once, or to rebuild the replica).",
        )

    def handle(self, *args, **opts):
        if opts["profile"]:
            profile = ServerProfile.objects.filter(pk=opts["profile"]).first()
            if not profile:
                raise CommandError(f"Profile {opts['profile']} tidak ditemukan.")
        else:
            profile = mssql.get_active_profile()
            if not profile:
                raise CommandError("Tidak ada koneksi aktif.")

        target = mssql.get_report_source(profile)
        if not target:
            raise CommandError(f"{profile.name}: report_source belum diset (Kelola Server).")

        self.stdout.write(f"Server: {profile.name} -> replica: {target.name}")

        if opts["backfill"]:
            for table_name in SYNC_ORDER:
                self.stdout.write(f"  backfill {table_name}...")
                try:
                    n = backfill_table(profile, table_name)
                except RuntimeError as exc:
                    # e.g. a table not yet provisioned on the replica — show the
                    # actionable message, not a traceback.
                    raise CommandError(str(exc))
                self.stdout.write(f"    {n} baris disalin.")

        results = sync_all(profile)
        failed = [r for r in results if r["status"] == "failed"]
        for r in results:
            if r["status"] == "ok":
                self.stdout.write(f"  {r['table']}: {r['applied']} perubahan diterapkan.")
            elif r["status"] == "nothing_to_sync":
                self.stdout.write(f"  {r['table']}: sudah terbaru.")
            else:
                self.stderr.write(f"  {r['table']}: GAGAL — {r['error']}")

        if failed:
            raise CommandError(f"{len(failed)} tabel gagal sync — cek CDC sudah aktif untuk tabel tsb.")

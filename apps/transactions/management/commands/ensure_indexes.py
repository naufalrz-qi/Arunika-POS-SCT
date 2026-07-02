"""Create the report/stock indexes on the legacy t_* tables (manual run).

Indexes are also built automatically in the background the first time a
connection becomes active (see apps/transactions/indexes.py); this command is
for off-hours runs or when the SQL login needs a DBA.

    python manage.py ensure_indexes              # active connection
    python manage.py ensure_indexes --profile 3  # specific ServerProfile id
"""
from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions.indexes import ensure_indexes
from core import mssql


class Command(BaseCommand):
    help = "Create dashboard/report indexes on the legacy t_* tables (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--profile", type=int, default=None, help="ServerProfile id (default: active)")

    def handle(self, *args, **opts):
        if opts["profile"]:
            profile = ServerProfile.objects.filter(pk=opts["profile"]).first()
            if not profile:
                raise CommandError(f"Profile {opts['profile']} tidak ditemukan.")
        else:
            profile = mssql.get_active_profile()
            if not profile:
                raise CommandError("Tidak ada koneksi aktif.")

        self.stdout.write(f"Server: {profile.name}")
        failed = ensure_indexes(profile, out=self.stdout.write)
        if failed:
            self.stderr.write("\nIndex berikut belum dibuat. Jalankan lewat DBA di SSMS:")
            for _, ddl in failed:
                self.stderr.write(f"  {ddl};")
            raise CommandError(f"{len(failed)} index gagal dibuat.")

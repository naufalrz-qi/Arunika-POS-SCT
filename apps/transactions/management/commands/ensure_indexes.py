"""Create the indexes the dashboard/report queries need on the legacy t_* tables.

Idempotent — safe to re-run. Run once per server profile that backs reports:

    python manage.py ensure_indexes              # active connection
    python manage.py ensure_indexes --profile 3  # specific ServerProfile id

Offline index build (~1 min on the 3.18M-row detail heap, brief table lock) —
run off-hours. If the SQL login lacks CREATE INDEX rights, the raw SQL is
printed so a DBA can run it in SSMS.
"""
import pyodbc
from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from core import mssql

# name -> DDL. The date index on the 504k-row header is the whole fix: it turns
# the dashboard's day-filter from a 45s table scan into a 0.7s seek. The detail
# table (3.18M-row heap) is fine hash-joined once per query — no index needed,
# and it can't take one anyway (its computed `total` column references UDF
# GetHargaBersih, created with ANSI_NULLS/QUOTED_IDENTIFIER OFF → error 1935).
INDEXES = {
    "IX_tpenjualan_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_tanggal ON t_penjualan (tanggal)"
    ),
}


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
        failed = []
        with mssql.cursor(profile) as cur:
            # These SET options must be ON to index a table with computed columns.
            cur.execute("SET ANSI_NULLS ON")
            cur.execute("SET QUOTED_IDENTIFIER ON")
            for name, ddl in INDEXES.items():
                cur.execute("SELECT 1 FROM sys.indexes WHERE name = ?", [name])
                if cur.fetchone():
                    self.stdout.write(f"  {name}: sudah ada, lewati.")
                    continue
                self.stdout.write(f"  {name}: membuat (bisa ~1 mnt)…")
                try:
                    cur.execute(ddl)
                    self.stdout.write(self.style.SUCCESS(f"  {name}: OK."))
                except pyodbc.Error as exc:
                    msg = exc.args[-1] if exc.args else exc
                    self.stderr.write(self.style.ERROR(f"  {name}: GAGAL — {msg}"))
                    failed.append((name, ddl))

        if failed:
            self.stderr.write("\nIndex berikut belum dibuat. Jalankan lewat DBA di SSMS:")
            for _, ddl in failed:
                self.stderr.write(f"  {ddl};")
            raise CommandError(f"{len(failed)} index gagal dibuat.")

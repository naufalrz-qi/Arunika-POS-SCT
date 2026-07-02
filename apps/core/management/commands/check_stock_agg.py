"""Self-check: SQL-side movement aggregation == Python-side aggregation.

Run against the active connection after schema/data changes on the legacy DB:
    python manage.py check_stock_agg
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.services import _f, _fetch_movements, _k, _movement_sums, _unit_factors
from core import mssql


class Command(BaseCommand):
    help = "Verify _movement_sums (SQL GROUP BY) matches Python aggregation of _fetch_movements."

    def handle(self, *args, **options):
        profile = mssql.get_active_profile()
        if not profile:
            raise CommandError("Tidak ada koneksi aktif.")
        date_to = dt.datetime.now()

        with mssql.cursor(profile) as cur:
            factors = _unit_factors(cur)
            moves = _fetch_movements(cur, date_to=date_to)
            agg_py: dict = {}
            for m in moves:
                f = factors.get((_k(m["kd_barang"]), _k(m["kd_satuan"])), 1.0)
                key = (_k(m["kd_divisi"]), _k(m["kd_barang"]))
                agg_py[key] = agg_py.get(key, 0.0) + f * (_f(m["debet"]) - _f(m["kredit"]))

            sums = _movement_sums(cur, date_to=date_to)

        # SQL may return several case/padding variants of the same CI key; merge.
        agg_sql: dict = {}
        for r in sums:
            key = (_k(r["kd_divisi"]), _k(r["kd_barang"]))
            agg_sql[key] = agg_sql.get(key, 0.0) + _f(r["stok_awal"]) + _f(r["masuk"]) - _f(r["keluar"])
        bad = [
            k for k in set(agg_py) | set(agg_sql)
            if abs(agg_py.get(k, 0.0) - agg_sql.get(k, 0.0)) > 0.001
        ]
        if bad:
            for k in bad[:10]:
                self.stderr.write(f"  {k}: py={agg_py.get(k)} sql={agg_sql.get(k)}")
            raise CommandError(f"{len(bad)} key beda (dari {len(agg_py)}).")
        self.stdout.write(self.style.SUCCESS(f"OK: {len(agg_py)} key identik ({len(moves)} movement)."))

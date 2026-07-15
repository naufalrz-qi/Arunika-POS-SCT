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

        # --- Snapshot check: snapshot+delta == full recompute (Fase 1 §1.6) ---
        from apps.inventory.services import _snapshot_meta

        with mssql.cursor(profile) as cur:
            if _snapshot_meta(cur) is None:
                self.stdout.write("Snapshot: pos_stok_snapshot belum ada/kosong — lewati cek snapshot.")
                return
            snap = {  # jalur snapshot+delta
                (_k(r["kd_divisi"]), _k(r["kd_barang"])): _f(r["stok_awal"]) + _f(r["masuk"]) - _f(r["keluar"])
                for r in _movement_sums(cur, date_to=date_to, use_snapshot=True)
            }
        # agg_sql di atas = jalur penuh (use_snapshot default True tapi tanpa snapshot
        # saat itu?) — hitung ulang penuh eksplisit untuk perbandingan yang jelas.
        with mssql.cursor(profile) as cur:
            full = {
                (_k(r["kd_divisi"]), _k(r["kd_barang"])): _f(r["stok_awal"]) + _f(r["masuk"]) - _f(r["keluar"])
                for r in _movement_sums(cur, date_to=date_to, use_snapshot=False)
            }
        bad2 = [k for k in set(snap) | set(full) if abs(snap.get(k, 0.0) - full.get(k, 0.0)) > 0.001]
        if bad2:
            for k in bad2[:10]:
                self.stderr.write(f"  {k}: snapshot={snap.get(k)} full={full.get(k)}")
            raise CommandError(f"Snapshot: {len(bad2)} key beda vs recompute penuh (dari {len(full)}).")
        self.stdout.write(self.style.SUCCESS(f"Snapshot OK: {len(full)} key identik (snapshot+delta == penuh)."))

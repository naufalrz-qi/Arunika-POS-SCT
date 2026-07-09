"""Read services for legacy transactions (t_*), via raw pyodbc.

PRD §5.3/§8.3: fetch tables at row level, then count / sum / bucket in Python.

Dashboard KPIs are queried live. Fast because of index IX_tpenjualan_tanggal on
t_penjualan(tanggal), which turns the day-filter from a 45s scan into a 0.7s
seek — see `ensure_indexes` command.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from core import mssql
from apps.core.reporting import dictify as _dictify


def _f(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def dashboard_summary(profile, day: dt.date | None = None) -> dict:
    """Today's sales KPIs + hourly histogram. One indexed JOIN aggregate + one
    grouped query — sub-second with the report indexes in place."""
    day = day or dt.date.today()
    start = dt.datetime.combine(day, dt.time.min)
    end = start + dt.timedelta(days=1)

    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT COUNT(DISTINCT h.no_transaksi) AS tx, "
            "SUM(d.qty) AS items, SUM(d.total) AS revenue "
            "FROM t_penjualan h JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi "
            "WHERE h.tanggal >= ? AND h.tanggal < ?",
            [start, end],
        )
        agg = _dictify(cur)[0]

        cur.execute(
            "SELECT DATEPART(HOUR, h.tanggal) AS hour, COUNT(DISTINCT h.no_transaksi) AS count "
            "FROM t_penjualan h "
            "WHERE h.tanggal >= ? AND h.tanggal < ? "
            "GROUP BY DATEPART(HOUR, h.tanggal)",
            [start, end],
        )
        counts_by_hour = {int(r["hour"]): int(r["count"]) for r in _dictify(cur)}

    hourly = [
        {"hour": f"{h:02d}", "count": counts_by_hour.get(h, 0)}
        for h in range(24)
        if counts_by_hour.get(h, 0) > 0 or 8 <= h <= 20
    ]

    return {
        "total_transactions": int(_f(agg["tx"])),
        "total_items": round(_f(agg["items"])),
        "revenue": round(_f(agg["revenue"])),
        "hourly_transactions": hourly,
    }


"""Report/stock indexes on the legacy t_* tables, auto-ensured per connection.

Every profile that becomes active gets the missing indexes built once per
process, in a background thread (index build can take ~1 min on big tables —
never block a request on it). `manage.py ensure_indexes` reuses the same list
for manual/off-hours runs.
"""
import logging
import threading

import pyodbc

from core import mssql

log = logging.getLogger(__name__)

# name -> DDL. The date index on the header tables is the whole fix: it turns
# day-range filters from full scans into seeks. Detail tables are fine
# hash-joined once per query — and the 3.18M-row penjualan detail heap can't
# take an index anyway (computed `total` column references UDF GetHargaBersih,
# created with ANSI_NULLS/QUOTED_IDENTIFIER OFF → error 1935).
INDEXES = {
    "IX_tpenjualan_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_tanggal ON t_penjualan (tanggal)"
    ),
    # Monitoring Stok / Stok Akhir: the movement UNION filters every header on
    # tanggal > tutup_buku — these turn those scans into seeks.
    "IX_tpembelian_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_tanggal ON t_pembelian (tanggal)"
    ),
    "IX_tpenjualan_retur_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_retur_tanggal ON t_penjualan_retur (tanggal)"
    ),
    "IX_tpembelian_retur_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_retur_tanggal ON t_pembelian_retur (tanggal)"
    ),
    "IX_tmutasi_stok_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tmutasi_stok_tanggal ON t_mutasi_stok (tanggal)"
    ),
    "IX_topname_stok_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_topname_stok_tanggal ON t_opname_stok (tanggal)"
    ),
}


def ensure_indexes(profile, out=None) -> list[tuple[str, str]]:
    """Create missing indexes on `profile`'s DB. Returns [(name, ddl)] failures.

    Idempotent. `out` (optional callable) receives progress lines for the CLI.
    """
    say = out or (lambda msg: None)
    failed = []
    with mssql.cursor(profile) as cur:
        # These SET options must be ON to index a table with computed columns.
        cur.execute("SET ANSI_NULLS ON")
        cur.execute("SET QUOTED_IDENTIFIER ON")
        for name, ddl in INDEXES.items():
            cur.execute("SELECT 1 FROM sys.indexes WHERE name = ?", [name])
            if cur.fetchone():
                say(f"  {name}: sudah ada, lewati.")
                continue
            say(f"  {name}: membuat (bisa ~1 mnt)…")
            try:
                cur.execute(ddl)
                say(f"  {name}: OK.")
                log.info("Index %s dibuat di %s", name, profile.name)
            except pyodbc.Error as exc:
                msg = str(exc.args[-1] if exc.args else exc)
                if "already exists" in msg:  # lost a race with another builder
                    say(f"  {name}: sudah ada, lewati.")
                    continue
                say(f"  {name}: GAGAL — {msg}")
                log.warning("Index %s gagal di %s: %s", name, profile.name, msg)
                failed.append((name, ddl))
    return failed


# Profiles already ensured this process — don't re-check on every request.
_ensured: set = set()
_lock = threading.Lock()


def ensure_indexes_async(profile) -> None:
    """Fire-and-forget index build for a newly active connection."""
    key = (profile.host, profile.port, profile.db_name)
    with _lock:
        if key in _ensured:
            return
        _ensured.add(key)
    threading.Thread(target=_safe_ensure, args=(profile,), daemon=True).start()


def _safe_ensure(profile):
    try:
        ensure_indexes(profile)
    except Exception:  # never let index upkeep break anything
        log.exception("ensure_indexes gagal untuk %s", profile.name)

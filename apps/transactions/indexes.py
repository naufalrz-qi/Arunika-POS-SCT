"""Report/stock indexes on the legacy t_*/m_* tables — manual only.

Run via the "Cek Indexing" button on the Kelola Server page (Admin/Connections)
or `manage.py ensure_indexes` for off-hours/DBA runs. Index build can take ~1
min on big tables, so it is never triggered automatically on connection
activation — the operator decides when to run it.
"""
import logging

import pyodbc

from core import mssql

log = logging.getLogger(__name__)

# name -> DDL. The date index on the header tables is the whole fix: it turns
# day-range filters from full scans into seeks. Detail tables (t_*_detail) are
# NOT indexable here — the 3.18M-row penjualan detail heap (and, presumably,
# its sibling detail tables) has a computed `total` column referencing a UDF
# created with ANSI_NULLS/QUOTED_IDENTIFIER OFF, which blocks CREATE INDEX
# with SQL Server error 1935. That's a legacy-schema limitation, not something
# safe to fix from the app.
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
    # --- Additional candidates (unverified against a live query plan — no MS
    # SQL Server reachable in dev; additive/reversible via manual DROP INDEX if
    # a candidate turns out not to help on a given server). All target tables
    # outside the t_*_detail computed-column restriction above.
    "IX_mbarangdivisi_barang_divisi": (
        # _movement_sql's [0] "Stok Awal" block filters bd.kd_barang/bd.kd_divisi
        # (services.py _movement_sql); list_barang_edit also reads this table.
        "CREATE NONCLUSTERED INDEX IX_mbarangdivisi_barang_divisi ON m_barang_divisi (kd_barang, kd_divisi)"
    ),
    "IX_topname_stok_tanggal_divisi_barang": (
        # Complements IX_topname_stok_tanggal: _movement_sql's [3/4] Opname block
        # also filters kd_divisi/kd_barang when stock_card/barang_histori scope
        # to one product or division.
        "CREATE NONCLUSTERED INDEX IX_topname_stok_tanggal_divisi_barang ON t_opname_stok (tanggal, kd_divisi, kd_barang)"
    ),
    "IX_tmutasistok_divisi": (
        # _movement_sql's [1]/[2] Mutasi Keluar/Masuk blocks filter
        # kd_divisi_asal/kd_divisi_tujuan in addition to tanggal.
        "CREATE NONCLUSTERED INDEX IX_tmutasistok_divisi ON t_mutasi_stok (kd_divisi_asal, kd_divisi_tujuan)"
    ),
    "IX_mbarangsatuan_barang_satuan": (
        # Supports the bs join in _movement_sums and the unit-price join in
        # _purchase_prices (both in apps/inventory/services.py).
        "CREATE NONCLUSTERED INDEX IX_mbarangsatuan_barang_satuan ON m_barang_satuan (kd_barang, kd_satuan)"
    ),
}


def ensure_indexes(profile, out=None):
    """Create missing indexes on `profile`'s DB.

    Idempotent. `out` (optional callable) receives progress lines for the CLI.
    Returns `(failed, results)`:
      - `failed`: list[(name, ddl)] — kept for backward compatibility with the
        CLI command's error report.
      - `results`: list[dict] — {name, status: "exists"|"created"|"failed",
        detail} per index, for structured UI display (Kelola Server button).
    """
    say = out or (lambda msg: None)
    failed = []
    results = []
    with mssql.cursor(profile) as cur:
        # These SET options must be ON to index a table with computed columns.
        cur.execute("SET ANSI_NULLS ON")
        cur.execute("SET QUOTED_IDENTIFIER ON")
        for name, ddl in INDEXES.items():
            cur.execute("SELECT 1 FROM sys.indexes WHERE name = ?", [name])
            if cur.fetchone():
                say(f"  {name}: sudah ada, lewati.")
                results.append({"name": name, "status": "exists", "detail": ""})
                continue
            say(f"  {name}: membuat (bisa ~1 mnt)…")
            try:
                cur.execute(ddl)
                say(f"  {name}: OK.")
                log.info("Index %s dibuat di %s", name, profile.name)
                results.append({"name": name, "status": "created", "detail": ""})
            except pyodbc.Error as exc:
                msg = str(exc.args[-1] if exc.args else exc)
                if "already exists" in msg:  # lost a race with another builder
                    say(f"  {name}: sudah ada, lewati.")
                    results.append({"name": name, "status": "exists", "detail": ""})
                    continue
                say(f"  {name}: GAGAL — {msg}")
                log.warning("Index %s gagal di %s: %s", name, profile.name, msg)
                failed.append((name, ddl))
                results.append({"name": name, "status": "failed", "detail": msg})
    return failed, results

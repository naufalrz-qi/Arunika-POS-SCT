"""Report/stock indexes on the legacy t_* tables, auto-ensured per connection.

Every profile that becomes active gets the missing indexes built once per
process, in a background thread (index build can take ~1 min on big tables —
never block a request on it). `manage.py ensure_indexes` reuses the same list
for manual/off-hours runs.
"""
import logging
import os
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
    # --- existing date indexes (movement engine + report ranges) -----------
    "IX_tpenjualan_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_tanggal ON t_penjualan (tanggal)"
    ),
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
    # --- report composites on t_penjualan (per divisi/customer/user/kas) ---
    "IX_tpenjualan_divisi_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_divisi_tanggal ON t_penjualan (kd_divisi, tanggal)"
    ),
    "IX_tpenjualan_customer_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_customer_tanggal ON t_penjualan (kd_customer, tanggal)"
    ),
    "IX_tpenjualan_user_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_user_tanggal ON t_penjualan (kd_user, tanggal)"
    ),
    "IX_tpenjualan_kas_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_kas_tanggal ON t_penjualan (kd_kas, tanggal)"
    ),
    "IX_tpenjualan_voucher": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_voucher ON t_penjualan (kd_voucher)"
    ),
    # --- detail joins. NOTE: t_penjualan_detail / t_pembelian_detail carry a
    # computed UDF column created with wrong SET options — CREATE INDEX may
    # fail with error 1935 on some servers. ensure_indexes() logs the failure
    # and continues; that is expected, not a bug.
    "IX_tpenjualan_detail_nota": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_detail_nota ON t_penjualan_detail (no_transaksi)"
    ),
    "IX_tpenjualan_detail_barang": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_detail_barang ON t_penjualan_detail (kd_barang)"
    ),
    "IX_tpembelian_detail_nota": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_detail_nota ON t_pembelian_detail (no_transaksi)"
    ),
    "IX_tpembelian_detail_barang": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_detail_barang ON t_pembelian_detail (kd_barang)"
    ),
    # --- pembelian composites ----------------------------------------------
    "IX_tpembelian_supplier_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_supplier_tanggal ON t_pembelian (kd_supplier, tanggal)"
    ),
    "IX_tpembelian_divisi_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_divisi_tanggal ON t_pembelian (kd_divisi, tanggal)"
    ),
    # --- retur details -------------------------------------------------------
    "IX_tpenjualan_retur_detail_nota": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_retur_detail_nota ON t_penjualan_retur_detail (no_retur)"
    ),
    "IX_tpenjualan_retur_detail_barang": (
        "CREATE NONCLUSTERED INDEX IX_tpenjualan_retur_detail_barang ON t_penjualan_retur_detail (kd_barang)"
    ),
    "IX_tpembelian_retur_detail_nota": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_retur_detail_nota ON t_pembelian_retur_detail (no_retur)"
    ),
    "IX_tpembelian_retur_detail_barang": (
        "CREATE NONCLUSTERED INDEX IX_tpembelian_retur_detail_barang ON t_pembelian_retur_detail (kd_barang)"
    ),
    # --- movement engine details ---------------------------------------------
    "IX_tmutasi_stok_detail_nota": (
        "CREATE NONCLUSTERED INDEX IX_tmutasi_stok_detail_nota ON t_mutasi_stok_detail (no_transaksi)"
    ),
    "IX_tmutasi_stok_detail_barang": (
        "CREATE NONCLUSTERED INDEX IX_tmutasi_stok_detail_barang ON t_mutasi_stok_detail (kd_barang)"
    ),
    "IX_topname_stok_barang": (
        "CREATE NONCLUSTERED INDEX IX_topname_stok_barang ON t_opname_stok (kd_barang)"
    ),
    # --- kas harian ------------------------------------------------------------
    "IX_tmutasi_kas_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tmutasi_kas_tanggal ON t_mutasi_kas (tanggal)"
    ),
    "IX_tpenambahan_kas_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpenambahan_kas_tanggal ON t_penambahan_kas (tanggal)"
    ),
    "IX_tbiaya_operasional_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tbiaya_operasional_tanggal ON t_biaya_operasional (tanggal)"
    ),
    "IX_tpendapatan_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpendapatan_tanggal ON t_pendapatan (tanggal)"
    ),
    # --- shift -------------------------------------------------------------------
    "IX_tpegawai_ganti_shift_tanggal": (
        "CREATE NONCLUSTERED INDEX IX_tpegawai_ganti_shift_tanggal ON t_pegawai_ganti_shift (tanggal)"
    ),
    # --- master search/filter ------------------------------------------------
    "IX_mbarang_kategori": (
        "CREATE NONCLUSTERED INDEX IX_mbarang_kategori ON m_barang (kd_kategori)"
    ),
    "IX_mbarang_nama": (
        "CREATE NONCLUSTERED INDEX IX_mbarang_nama ON m_barang (nama)"
    ),
    "IX_mcustomer_nama": (
        "CREATE NONCLUSTERED INDEX IX_mcustomer_nama ON m_customer (nama)"
    ),
    # --- movement engine composites (apps/inventory/services.py _movement_sql) --
    "IX_mbarangdivisi_barang_divisi": (
        # [0] "Stok Awal" block filters bd.kd_barang/bd.kd_divisi; also read in
        # full by list_barang_edit (apps/master_data/services.py).
        "CREATE NONCLUSTERED INDEX IX_mbarangdivisi_barang_divisi ON m_barang_divisi (kd_barang, kd_divisi)"
    ),
    "IX_topname_stok_tanggal_divisi_barang": (
        # Complements IX_topname_stok_tanggal/IX_topname_stok_barang: the Opname
        # movement block filters kd_divisi/kd_barang together with tanggal when
        # stock_card/barang_histori scope to one product or division.
        "CREATE NONCLUSTERED INDEX IX_topname_stok_tanggal_divisi_barang ON t_opname_stok (tanggal, kd_divisi, kd_barang)"
    ),
    "IX_tmutasistok_divisi": (
        # Mutasi Keluar/Masuk blocks filter kd_divisi_asal/kd_divisi_tujuan in
        # addition to tanggal.
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
      - `failed`: list[(name, ddl)] — kept for the CLI command's error report.
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


# Profiles already ensured this process — don't re-check on every request.
_ensured: set = set()
_lock = threading.Lock()


def ensure_indexes_async(profile) -> None:
    """Fire-and-forget index build for a newly active/registered connection.

    Disabled entirely when POS_AUTO_INDEX=0 (DBA wants manual off-hours runs
    via `manage.py ensure_indexes`, PRD §9)."""
    if os.environ.get("POS_AUTO_INDEX", "1").lower() in ("0", "false", "no", "off"):
        return
    key = (profile.host, profile.port, profile.db_name)
    with _lock:
        if key in _ensured:
            return
        _ensured.add(key)
    threading.Thread(target=_safe_ensure, args=(profile,), daemon=True).start()


def _safe_ensure(profile):
    try:
        failed, _results = ensure_indexes(profile)
        if failed:
            detail = f"Index {profile.name}: gagal {', '.join(n for n, _ in failed)}"
        else:
            detail = f"Index {profile.name}: registry lengkap"
        _log_result(detail)
    except Exception:  # never let index upkeep break anything
        log.exception("ensure_indexes gagal untuk %s", profile.name)
        _log_result(f"Index {profile.name}: exception (lihat log server)")


def _log_result(detail: str) -> None:
    """Audit-trail the background build (no request object in this thread)."""
    try:
        from apps.core.models import ActivityLog

        ActivityLog.objects.create(username="system", action="index", detail=detail[:255])
    except Exception:
        log.exception("Gagal mencatat hasil index ke ActivityLog")

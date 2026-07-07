"""Incremental sync of legacy transaction/master tables into a reporting
replica, via SQL Server Change Data Capture (CDC).

Why CDC and not classic transactional replication: `t_penjualan_detail` (the
biggest, most joined table — 3M+ rows) is a heap with no primary key, and the
computed `total` column (built with wrong ANSI_NULLS/QUOTED_IDENTIFIER
settings, see apps/transactions/indexes.py) blocks adding one without risking
the legacy POS app that owns this schema. CDC reads the transaction log and
does NOT require a primary key for `fn_cdc_get_all_changes_*` (only the
`fn_cdc_get_net_changes_*` variant does, which we don't use) — so it works
against this schema unmodified.

Prerequisite (done once by a DBA on the legacy server, NOT by this code):
    EXEC sys.sp_cdc_enable_db;
    EXEC sys.sp_cdc_enable_table @source_schema='dbo', @source_name='<table>',
        @role_name=NULL;
This module assumes the default capture instance name SQL Server gives when
`@capture_instance` isn't overridden: `<schema>_<table>`, e.g.
`dbo_t_penjualan`. If a DBA registered a custom name, update `CDC_TABLE_SPECS`.

Two apply strategies, per table shape:
- `key_columns`: the table has a real natural key (kd_barang, no_transaksi,
  ...). Apply each changed row as delete-by-key then (for insert/update)
  re-insert — a plain upsert without needing MERGE/PK.
- `parent_key`/`parent_table`: detail/child tables (t_penjualan_detail, ...)
  have NO reliable per-row key (a nota can legitimately have two lines for the
  same kd_barang). Instead of matching rows, collect the distinct parent keys
  touched by the changeset, delete all of that parent's rows in the replica,
  and re-fetch+re-insert the CURRENT full row set for that parent straight
  from the source — cheap (indexed point lookup by no_transaksi/no_retur) and
  always exactly matches source state, including deletes (an emptied nota
  re-fetches as zero rows).
"""
from __future__ import annotations

import pyodbc
from django.utils import timezone

from apps.core.models import CdcSyncCursor
from core import mssql

CDC_OP_DELETE = 1
CDC_OP_INSERT = 2
CDC_OP_UPDATE_BEFORE = 3
CDC_OP_UPDATE_AFTER = 4

CDC_TABLE_SPECS = {
    # --- header tables: real natural key -----------------------------------
    "t_penjualan": {"capture_instance": "dbo_t_penjualan", "key_columns": ["no_transaksi"]},
    "t_penjualan_retur": {"capture_instance": "dbo_t_penjualan_retur", "key_columns": ["no_retur"]},
    "t_pembelian": {"capture_instance": "dbo_t_pembelian", "key_columns": ["no_transaksi"]},
    "t_pembelian_retur": {"capture_instance": "dbo_t_pembelian_retur", "key_columns": ["no_retur"]},
    # --- detail tables: no reliable per-row key, sync by parent -------------
    "t_penjualan_detail": {
        "capture_instance": "dbo_t_penjualan_detail", "parent_key": "no_transaksi", "parent_table": "t_penjualan",
    },
    "t_penjualan_retur_detail": {
        "capture_instance": "dbo_t_penjualan_retur_detail", "parent_key": "no_retur", "parent_table": "t_penjualan_retur",
    },
    "t_pembelian_detail": {
        "capture_instance": "dbo_t_pembelian_detail", "parent_key": "no_transaksi", "parent_table": "t_pembelian",
    },
    "t_pembelian_retur_detail": {
        "capture_instance": "dbo_t_pembelian_retur_detail", "parent_key": "no_retur", "parent_table": "t_pembelian_retur",
    },
    # --- master tables: real natural key ------------------------------------
    "m_barang": {"capture_instance": "dbo_m_barang", "key_columns": ["kd_barang"]},
    "m_barang_satuan": {"capture_instance": "dbo_m_barang_satuan", "key_columns": ["kd_barang", "kd_satuan"]},
    "m_barang_stok_akhir": {"capture_instance": "dbo_m_barang_stok_akhir", "key_columns": ["kd_barang", "kd_divisi"]},
    "m_customer": {"capture_instance": "dbo_m_customer", "key_columns": ["kd_customer"]},
    "m_supplier": {"capture_instance": "dbo_m_supplier", "key_columns": ["kd_supplier"]},
    "m_divisi": {"capture_instance": "dbo_m_divisi", "key_columns": ["kd_divisi"]},
    "m_kategori": {"capture_instance": "dbo_m_kategori", "key_columns": ["kd_kategori"]},
    "m_kota": {"capture_instance": "dbo_m_kota", "key_columns": ["kd_kota"]},
    "m_pegawai": {"capture_instance": "dbo_m_pegawai", "key_columns": ["kd_pegawai"]},
    "m_satuan": {"capture_instance": "dbo_m_satuan", "key_columns": ["kd_satuan"]},
}

# Sync parents before their detail tables, so a detail re-fetch never races
# ahead of its header row (matters for the very first incremental run after
# a backfill).
SYNC_ORDER = [
    "t_penjualan", "t_penjualan_detail",
    "t_penjualan_retur", "t_penjualan_retur_detail",
    "t_pembelian", "t_pembelian_detail",
    "t_pembelian_retur", "t_pembelian_retur_detail",
    "m_barang", "m_barang_satuan", "m_barang_stok_akhir",
    "m_customer", "m_supplier", "m_divisi", "m_kategori", "m_kota", "m_pegawai", "m_satuan",
]


def _dictify(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _insertable_columns(cur, table: str) -> list[str]:
    """Column names of `table` that can be INSERTed into, in column order.

    Excludes computed and identity columns — SQL Server rejects an explicit
    INSERT into either (e.g. t_penjualan_detail's computed `total`). The
    replica schema is hand-provisioned (Phase A) and isn't guaranteed to
    mirror the source's computed/identity flags, so ask the target it's being
    written to, not the source. Returned names always exist as plain columns on
    the source too (same names), so a `SELECT`/`row.get()` by them is safe.

    Raises RuntimeError if `table` doesn't exist on this connection — otherwise
    OBJECT_ID returns NULL, the query yields zero columns, and we'd silently
    build a malformed INSERT. The common cause is the replica not being
    provisioned yet (Phase A), so name that explicitly.
    """
    cur.execute("SELECT OBJECT_ID(?)", [table])
    if cur.fetchone()[0] is None:
        raise RuntimeError(
            f"Tabel '{table}' tidak ada di server tujuan (replica). Buat dulu "
            f"skema tabelnya di replica sebelum backfill/sync — lihat prasyarat "
            f"Phase A di docstring apps/transactions/cdc_sync.py."
        )
    cur.execute(
        "SELECT name FROM sys.columns "
        "WHERE object_id = OBJECT_ID(?) AND is_computed = 0 AND is_identity = 0 "
        "ORDER BY column_id",
        [table],
    )
    return [r[0] for r in cur.fetchall()]


def _has_lob_columns(cur, table: str) -> bool:
    """True if `table` has any large-object column: a MAX type (max_length = -1)
    or the legacy LOB types image/text/ntext/xml (system_type_id 34/35/99/241).

    Matters for fast_executemany: pyodbc pre-allocates a per-cell buffer sized
    to the column's *maximum* width for the whole batch, so a single image /
    varbinary(max) column blows memory up to GBs (e.g. m_pegawai.foto). We keep
    fast_executemany only for LOB-free tables and fall back to the plain (slow
    but bounded) path otherwise.
    """
    cur.execute(
        "SELECT COUNT(*) FROM sys.columns "
        "WHERE object_id = OBJECT_ID(?) "
        "AND (max_length = -1 OR system_type_id IN (34, 35, 99, 241))",
        [table],
    )
    return cur.fetchone()[0] > 0


def _delete_by_key(cur, table: str, key_columns: list[str], row: dict) -> None:
    where = " AND ".join(f"{c} = ?" for c in key_columns)
    cur.execute(f"DELETE FROM {table} WHERE {where}", [row[c] for c in key_columns])


def _insert_row(cur, table: str, columns: list[str], row: dict) -> None:
    cols_sql = ", ".join(columns)
    placeholders = ", ".join("?" * len(columns))
    cur.execute(f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders})", [row.get(c) for c in columns])


def _get_or_create_cursor(profile, table_name: str) -> CdcSyncCursor:
    cursor_row, _ = CdcSyncCursor.objects.get_or_create(profile=profile, table_name=table_name)
    return cursor_row


def backfill_table(profile, table_name: str, target=None, chunk_size: int = 2000) -> int:
    """One-time full copy legacy -> replica. Run once before incremental sync
    starts (and again if the replica ever needs a rebuild). Returns row count.
    """
    target = target or mssql.get_report_source(profile)
    if not target:
        raise RuntimeError(f"{profile.name}: report_source belum diset.")

    # Snapshot the LSN *before* copying, not after: any change that lands on
    # the source while the (potentially slow) copy below is running would
    # otherwise fall in the gap and never be seen by the incremental sync.
    # Starting the cursor here instead means such changes get re-applied by
    # sync_table afterwards — redundant but safe, since applying is idempotent
    # (delete-then-insert / child re-fetch), never lossy.
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT sys.fn_cdc_get_max_lsn()")
        pre_copy_lsn = cur.fetchone()[0]

    n = 0
    with mssql.cursor(profile) as src_cur, mssql.cursor(target, autocommit=False) as tgt_cur:
        # Copy only insertable columns (skip computed/identity), and select the
        # same explicit column set from the source so INSERT positions line up.
        columns = _insertable_columns(tgt_cur, table_name)
        tgt_cur.execute(f"DELETE FROM {table_name}")
        tgt_cur.connection.commit()  # persist the clear even if the table is empty (no batches below)
        cols_sql = ", ".join(columns)
        src_cur.execute(f"SELECT {cols_sql} FROM {table_name}")
        placeholders = ", ".join("?" * len(columns))
        insert_sql = f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders})"
        # fast_executemany batches all params into one round-trip instead of a
        # per-row prepared exec — the difference between minutes and hours on a
        # 3M-row table. But it pre-allocates a per-cell buffer at each column's
        # MAX width, so a LOB column (image/varbinary(max)/...) would blow up
        # memory (MemoryError on m_pegawai.foto). Use it only for LOB-free
        # tables; LOB tables take the plain path with a small batch. Commit per
        # chunk so the replica's transaction log stays bounded.
        has_lob = _has_lob_columns(tgt_cur, table_name)
        tgt_cur.fast_executemany = not has_lob
        batch_size = 50 if has_lob else chunk_size
        while True:
            batch = src_cur.fetchmany(batch_size)
            if not batch:
                break
            tgt_cur.executemany(insert_sql, [list(row) for row in batch])
            tgt_cur.connection.commit()
            n += len(batch)

    cursor_row = _get_or_create_cursor(profile, table_name)
    cursor_row.last_lsn = pre_copy_lsn.hex() if pre_copy_lsn else ""
    cursor_row.last_synced_at = timezone.now()
    cursor_row.last_rows_applied = n
    cursor_row.status = "ok"
    cursor_row.error_message = ""
    cursor_row.save()
    return n


def _sync_keyed_table(tgt_cur, table_name: str, key_columns: list[str], changes: list[dict]) -> int:
    columns = _insertable_columns(tgt_cur, table_name)
    applied = 0
    for row in changes:
        op = row["__$operation"]
        if op == CDC_OP_UPDATE_BEFORE:
            continue  # only need the after-image; before-image is redundant here
        _delete_by_key(tgt_cur, table_name, key_columns, row)
        if op in (CDC_OP_INSERT, CDC_OP_UPDATE_AFTER):
            _insert_row(tgt_cur, table_name, columns, row)
        applied += 1
    return applied


def _sync_child_table(src_cur, tgt_cur, table_name: str, parent_key: str, changes: list[dict]) -> int:
    parent_values = {row[parent_key] for row in changes}
    if not parent_values:
        return 0
    columns = _insertable_columns(tgt_cur, table_name)
    placeholders = ", ".join("?" * len(parent_values))
    for value in parent_values:
        tgt_cur.execute(f"DELETE FROM {table_name} WHERE {parent_key} = ?", [value])
    src_cur.execute(
        f"SELECT * FROM {table_name} WHERE {parent_key} IN ({placeholders})", list(parent_values)
    )
    fresh_rows = _dictify(src_cur)
    for row in fresh_rows:
        _insert_row(tgt_cur, table_name, columns, row)
    return len(parent_values)


def sync_table(profile, table_name: str) -> dict:
    """Apply CDC changes for one table since its last cursor. Returns a
    summary dict; also persists the new cursor position on success.
    """
    spec = CDC_TABLE_SPECS[table_name]
    target = mssql.get_report_source(profile)
    if not target:
        raise RuntimeError(f"{profile.name}: report_source belum diset.")

    cursor_row = _get_or_create_cursor(profile, table_name)
    result = {"table": table_name, "applied": 0, "status": "ok", "error": ""}

    try:
        with mssql.cursor(profile) as src_cur:
            if cursor_row.last_lsn:
                from_lsn = bytes.fromhex(cursor_row.last_lsn)
                src_cur.execute("SELECT sys.fn_cdc_increment_lsn(?)", [from_lsn])
                from_lsn = src_cur.fetchone()[0]
            else:
                src_cur.execute("SELECT sys.fn_cdc_get_min_lsn(?)", [spec["capture_instance"]])
                from_lsn = src_cur.fetchone()[0]
            src_cur.execute("SELECT sys.fn_cdc_get_max_lsn()")
            to_lsn = src_cur.fetchone()[0]

            if not to_lsn or not from_lsn or from_lsn > to_lsn:
                # No LSN yet (CDC just enabled, nothing captured) or already
                # caught up — nothing to do this run.
                result["status"] = "nothing_to_sync"
                return result

            # capture_instance is only ever one of our own CDC_TABLE_SPECS
            # values (never request input) — same whitelist shape as the
            # sort/filter aliases in apps/core/reporting.py.
            src_cur.execute(
                f"SELECT * FROM cdc.fn_cdc_get_all_changes_{spec['capture_instance']}(?, ?, 'all')",
                [from_lsn, to_lsn],
            )
            changes = _dictify(src_cur)

            with mssql.cursor(target, autocommit=False) as tgt_cur:
                if "key_columns" in spec:
                    applied = _sync_keyed_table(tgt_cur, table_name, spec["key_columns"], changes)
                else:
                    applied = _sync_child_table(src_cur, tgt_cur, table_name, spec["parent_key"], changes)
                tgt_cur.connection.commit()

        cursor_row.last_lsn = to_lsn.hex()
        cursor_row.last_synced_at = timezone.now()
        cursor_row.last_rows_applied = applied
        cursor_row.status = "ok"
        cursor_row.error_message = ""
        result["applied"] = applied
    except (pyodbc.Error, RuntimeError) as exc:
        # RuntimeError = missing replica table (see _insertable_columns) — record
        # it as this table's failure so sync_all keeps going for the rest,
        # rather than aborting the whole run on one unprovisioned table.
        msg = str(exc.args[-1] if exc.args else exc)
        cursor_row.status = "failed"
        cursor_row.error_message = msg[:255]
        result["status"] = "failed"
        result["error"] = msg
    cursor_row.save()
    return result


def sync_all(profile) -> list[dict]:
    """Run sync_table for every registered table, in dependency order.

    A single table failing (e.g. CDC not enabled yet for it) doesn't stop the
    rest — each table's cursor/status is independent, and the caller (the
    `sync_cdc` management command) reports failures per table.
    """
    return [sync_table(profile, table_name) for table_name in SYNC_ORDER]

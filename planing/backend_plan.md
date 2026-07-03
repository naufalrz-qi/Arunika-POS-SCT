# Backend Task Playbook — Arunika POS

> **Audience:** an AI coding model executing tasks one by one (Haiku 4.5 / Gemini Flash 3 level).
> **Companion docs:** `planing/prd.md` (product spec), `planing/frontend_plan.md` + `planing/frontend_tasks.md` (frontend side). This file is the backend build list **and** the integration contract the frontend depends on.
> **Instructions are in English. All user-facing strings (error messages, flash, labels) stay in Indonesian.**

---

## SECTION 0 — RULES (read first, follow every task)

1. Only touch **backend files** (`apps/`, `config/`, `core/`, `requirements.txt`, `.env.example`). **Do NOT change anything under `frontend/`** — the frontend is built separately from `planing/frontend_tasks.md`.
2. Do the tasks **in order**. Each task says CREATE or EDIT, gives the exact file path, and gives the **full code**. Paste it as-is. Do not invent prop names, URL paths, or row field names — they are a contract with the frontend (see R2/R3).
3. All MS SQL access is **raw pyodbc** through `core/mssql.py`. **Never** create Django models for `m_*`/`t_*` tables. **Never** use legacy views (`v_*`, `mon_*`), functions (`Get*`), or stored procedures.
4. All SQL must be **parameterized** (`?` placeholders). Never interpolate user input into SQL strings. Sorting uses a whitelist dict (see `reporting.py`); anything outside the whitelist falls back to the default sort.
5. **Never use the `total` column** of `t_penjualan_detail` / `t_pembelian_detail` (computed column backed by a legacy UDF — wrong SET options, can't be indexed, values not trustworthy). Always compute line totals yourself with the tiered-discount formula (R4).
6. Every transaction query **must** have a date predicate. `parse_report_params` defaults the range to the current month and clamps ranges longer than the report's `max_range_days`.
7. When joining SQL result sets **in Python** on `kd_*` keys, normalize **both sides** with `_k()` (upper + strip) — SQL Server collation is case-insensitive and ignores trailing spaces; plain dict lookups silently drop rows. (`_k` lives in `apps/inventory/services.py`.)
8. Follow the **deferred pattern** for every page: heavy data wrapped in `defer(callable)`, `pyodbc.Error` caught into `conn_error` (Indonesian message), `filters` echoed back so the frontend can restore the form. Reference implementation: `barang_histori_index` in `apps/monitoring/views.py`.
9. After finishing a task, run `python manage.py check`. If it fails, fix the file you just wrote before moving on. Tasks that add models also say when to run `makemigrations` / `migrate`.
10. Mark each task done: change `- [ ]` to `- [x]`.

### R1 — Existing helpers you must reuse (do not re-implement)

| Helper | Where | What it does |
|---|---|---|
| `mssql.cursor(profile)` | `core/mssql.py` | Context manager yielding a pyodbc cursor for a `ServerProfile`. `mssql.cursor(profile, autocommit=False)` for writes. |
| `mssql.get_active_profile()` | `core/mssql.py` | The single globally-active `ServerProfile` (also auto-triggers index build). |
| `_active()` | `apps/monitoring/views.py:35` | Shorthand for `mssql.get_active_profile()`. |
| `CONN_ERROR` | `apps/monitoring/views.py:32` | Standard Indonesian "no active connection" message. |
| `_parse_date(s)` / `_eod(d)` | `apps/monitoring/views.py:21/28` | `"YYYY-MM-DD"` → datetime / end-of-day 23:59:59. |
| `defer`, `render` | `from inertia import defer, render` | Deferred Inertia props. |
| `get_data(request)` | `apps/core/http.py` | POST body (JSON or form) as dict-like. |
| `log_activity(request, action, detail)` | `apps/core/models.py` | Writes an `ActivityLog` row. |
| `_k(v)` | `apps/inventory/services.py:65` | Join-key normalization (upper + strip). |
| `inv.list_divisi(profile)` | `apps/inventory/services.py` | `[{"kd_divisi","nama"}]` for filter dropdowns. |
| `inv.stok_akhir_per_tanggal`, `inv.stock_levels`, `inv.barang_histori` | `apps/inventory/services.py` | Movement engine (already `g_tutup_buku`-aware). Reuse — never rewrite stock math. |
| `master.*` | `apps/master_data/services.py` | `list_products`, `list_customers`, `update_harga`, `compare_harga_jual`, `sync_harga_jual`, `_dictify`, `_st`, `_f`, `_active(status)`, `MAX_ROWS=500`. |
| `ensure_indexes(_async)` | `apps/transactions/indexes.py` | Idempotent index builder (extended in B3). |

### R2 — Data contracts (must match `frontend_tasks.md` exactly)

**Server-side report pages** (big tables; PenjualanAll, PenjualanNota, PenjualanCustomer, PenjualanUser, PenjualanPeriode, ReturPenjualan, Pembelian, ReturPembelian, Opname, Kas, Shift). The view sends TWO props:

```
report (DEFERRED) = {
  rows:    [ {...page-specific fields..., _rid: <int>} ],
  total:   <int — total row count across all pages>,
  summary: { jml_baris, total_qty, total_nilai } (numbers; kas uses its own keys, see B17),
  options: { divisi: [{value,label}], customer: [...], supplier: [...], kas: [...] } (only the lists that page's filters need),
  conn_error: <string|null — also carries the date-clamp warning>,
}
filters (NOT deferred) = {
  date_from, date_to, search, sort, sort_dir, page, per_page,  // always
  ...module filter keys (kd_divisi, kd_customer, ...)          // per page
}
```

GET query params the frontend sends: `date_from, date_to, search, sort, sort_dir, page, per_page` + module filters. `per_page` default 50.

**Client-side pages** (small datasets; StokAkhir, StokDivisi, Promo, Voucher, FmiPenjualan, FmiStok, Supplier, SyncHistory). One deferred prop:

```
data (DEFERRED) = { rows: [...], conn_error: <string|null> }
```

**Export:** every server-side report also answers `GET <page-url>/export?<same query>` with an XLSX download (same filters, no pagination, hard cap `EXPORT_CAP`).

**Options item shape:** `{ "value": "<code>", "label": "<name>" }` — both strings, stripped.

### R3 — Page matrix (URL ↔ view ↔ component ↔ contract ↔ tasks)

URLs already exist in `apps/monitoring/urls.py` unless marked **NEW**. "FE task" = the task in `frontend_tasks.md` this unblocks.

| Page | URL (`/admin-panel/` +) | View function | Component | Deferred prop | Backend task | FE task |
|---|---|---|---|---|---|---|
| Penjualan Detail | `laporan/penjualan` (+`/export` NEW) | `penjualan_all` | `Admin/Reports/PenjualanAll` | `report` | B5–B7 | T9 |
| Penjualan per Nota | `laporan/penjualan-nota` (+`/export` NEW) | `penjualan_nota` | `Admin/Reports/PenjualanNota` | `report` | B8 | T10 |
| Penjualan per Customer | `laporan/penjualan-customer` (+`/export` NEW) | `penjualan_customer` | `Admin/Reports/PenjualanCustomer` | `report` | B9 | T11 |
| Penjualan per User | `laporan/penjualan-user` (+`/export` NEW) | `penjualan_user` | `Admin/Reports/PenjualanUser` | `report` | B10 | T12 |
| Penjualan per Periode | `laporan/penjualan-periode` (+`/export` NEW) | `penjualan_periode` | `Admin/Reports/PenjualanPeriode` | `report` | B11 | T13 |
| Retur Penjualan | `laporan/retur-penjualan` (+`/export` NEW) | `retur_penjualan` | `Admin/Reports/ReturPenjualan` | `report` | B12 | T14 |
| Pembelian | `laporan/pembelian` (+`/export` NEW) | `pembelian` | `Admin/Reports/Pembelian` | `report` | B13 | T15 |
| Retur Pembelian | `laporan/retur-pembelian` (+`/export` NEW) | `retur_pembelian` | `Admin/Reports/ReturPembelian` | `report` | B14 | T16 |
| Opname | `inventory/opname` (+`/export` NEW) | `opname` | `Admin/Inventory/Opname` | `report` | B15 | T17 |
| Shift Kasir | `kas/shift` (+`/export` NEW) | `shift` | `Admin/Cash/Shift` | `report` | B16 | T19 |
| Kas Harian | `kas/harian` (+`/export` NEW) | `kas_harian` | `Admin/Cash/Kas` | `report` | B17 | T18 |
| Promo & Diskon | `promo/diskon` | `promo` | `Admin/Promo/Promo` | `data` | B18 | T22 |
| Voucher | `promo/voucher` | `voucher` | `Admin/Promo/Voucher` | `data` | B19 | T23 |
| FMI Penjualan | `analitik/fmi-penjualan` | `fmi_penjualan` | `Admin/Analytics/FmiPenjualan` | `data` | B20 | T24 |
| FMI Stok | `analitik/fmi-stok` | `fmi_stok` | `Admin/Analytics/FmiStok` | `data` | B21 | T25 |
| Master Supplier | `master/suppliers` **NEW** | `suppliers_index` | `Admin/MasterData/Supplier` | `data` | B22 | T28 |
| Riwayat Sync | `master/sync-history` **NEW** | `sync_history_index` | `Admin/MasterData/SyncHistory` | `data` | B23–B25 | T32 |
| Log Aktivitas | `logs` | `logs_index` | `Admin/ActivityLogs` | (plain props) | B27 | T30 |

Already real, untouched by this playbook: dashboard, `inventory/stock`, `inventory/histori`, `inventory/stok-divisi`, `inventory/stok-akhir`, master products/customers, update-barang, sync-harga (read side), users, connections, menus, profile.

### R4 — Business rules (memorize)

1. **Tiered discount formula.** Line net = `qty * harga * (1 - d1/100) * (1 - d2/100) * (1 - d3/100) * (1 - d4/100)`, NULL-safe via `COALESCE(diskonN, 0)`. Header-level (nota) net additionally multiplies the header's four discounts, then subtracts `diskon_uang`, then applies `pajak` percent. This is the whole replacement for the forbidden computed `total` column.
2. **`g_tutup_buku` cutoff.** All opening/closing-stock math must go through the existing movement engine in `apps/inventory/services.py` (already cutoff-aware). Never recompute stock from scratch in a report.
3. **Status enum** on `m_*` tables: tinyint `0` = Non-aktif, `1` = Aktif, `2` = Tidak dijual (barang). `master._active(status)` maps `1/A/Y` → `True`.
4. **Key columns are `char(N)`** — values come back space-padded. Strip in SQL (`RTRIM`) or Python (`.strip()`) before sending to the frontend; use `_k()` for Python-side joins.
5. **`t_penjualan.kd_voucher`, `kd_customer`, `kd_kas` may be empty strings** rather than NULL — treat `LTRIM(RTRIM(col)) <> ''` as "has value".

---

## SECTION 1 — FOUNDATION

Build these first. Every report task depends on them.

### - [ ] B1 — EDIT `requirements.txt` (add openpyxl)

Add this line at the end of the file:

```
openpyxl>=3.1
```

Then install it:

```bash
pip install openpyxl
```

**DoD:** `python -c "import openpyxl"` prints nothing (no error).

### - [ ] B2 — CREATE `apps/core/reporting.py`

Shared plumbing for all server-side report pages: parameter parsing (dates default to current month), COUNT + OFFSET/FETCH pagination over a subquery, XLSX export response, option-list shaping.

```python
"""Shared plumbing for server-side report pages (PRD §6 / §10).

Contract with the frontend (planing/frontend_tasks.md):
- deferred prop `report` = { rows, total, summary, options, conn_error }
- prop `filters` echoes the requested params so the form can be restored
- GET <page-url>/export?<same query> answers with an XLSX file.
"""
import datetime as dt
from decimal import Decimal

from django.http import HttpResponse

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200
MAX_RANGE_DAYS = 92        # ~3 months; longer ranges are clamped (PRD §10)
EXPORT_CAP = 100_000       # hard cap on exported rows (PRD §10)

RANGE_WARNING = (
    "Rentang tanggal dibatasi maksimal {d} hari — tanggal mulai disesuaikan otomatis."
)


def _parse_date(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d") if s else None
    except (ValueError, TypeError):
        return None


def month_start(today=None) -> dt.datetime:
    today = today or dt.date.today()
    return dt.datetime(today.year, today.month, 1)


def parse_report_params(request, sorts, default_sort, max_range_days=MAX_RANGE_DAYS):
    """Read the standard report params from request.GET into a dict `f`.

    `sorts` is the whitelist: {sort_param: output_column_alias}. Anything not in
    it falls back to `default_sort` — this is the SQL-injection guard, since the
    ORDER BY clause is built from the alias, never from raw user input.
    """
    g = request.GET
    today = dt.date.today()
    date_from = _parse_date(g.get("date_from")) or month_start(today)
    date_to = _parse_date(g.get("date_to")) or dt.datetime(today.year, today.month, today.day)
    warning = None
    if (date_to - date_from).days > max_range_days:
        date_from = date_to - dt.timedelta(days=max_range_days)
        warning = RANGE_WARNING.format(d=max_range_days)

    sort = g.get("sort") or default_sort
    if sort not in sorts:
        sort = default_sort
    sort_dir = "asc" if (g.get("sort_dir") or "desc").lower() == "asc" else "desc"

    try:
        page = max(1, int(g.get("page") or 1))
    except ValueError:
        page = 1
    try:
        per_page = min(MAX_PER_PAGE, max(10, int(g.get("per_page") or DEFAULT_PER_PAGE)))
    except ValueError:
        per_page = DEFAULT_PER_PAGE

    return {
        "date_from": date_from,
        "date_to": date_to.replace(hour=23, minute=59, second=59),
        "date_from_s": date_from.strftime("%Y-%m-%d"),
        "date_to_s": date_to.strftime("%Y-%m-%d"),
        "search": (g.get("search") or "").strip(),
        "sort": sort,
        "sort_dir": sort_dir,
        "order_by": f"q.{sorts[sort]} {sort_dir.upper()}",
        "page": page,
        "per_page": per_page,
        "warning": warning,
        "export": False,
    }


def dictify(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str):
        return v.strip()
    return v


def clean_rows(rows: list[dict]) -> list[dict]:
    """Decimal → float, datetime → string, char() padding stripped."""
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


def run_paged(cur, inner_sql, params, f):
    """COUNT + OFFSET/FETCH over `inner_sql` (a full SELECT without ORDER BY).

    ORDER BY references the subquery's output aliases (f["order_by"] was built
    from the whitelist in parse_report_params). Returns (rows, total); every row
    gets a synthetic `_rid` (global row number) usable as a stable row key.
    """
    cur.execute(f"SELECT COUNT(*) FROM ({inner_sql}) AS q", params)
    total = int(cur.fetchone()[0] or 0)
    offset = (f["page"] - 1) * f["per_page"]
    cur.execute(
        f"SELECT * FROM ({inner_sql}) AS q ORDER BY {f['order_by']} "
        "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
        list(params) + [offset, f["per_page"]],
    )
    rows = clean_rows(dictify(cur))
    for i, r in enumerate(rows):
        r["_rid"] = offset + i + 1
    return rows, total


def run_all(cur, inner_sql, params, f):
    """Export path: the same query without pagination, capped at EXPORT_CAP."""
    cur.execute(
        f"SELECT TOP {EXPORT_CAP} * FROM ({inner_sql}) AS q ORDER BY {f['order_by']}",
        params,
    )
    rows = clean_rows(dictify(cur))
    for i, r in enumerate(rows):
        r["_rid"] = i + 1
    return rows


def opt(rows, value_key, label_key):
    """Shape master rows into [{value,label}] for SelectSearch dropdowns."""
    out = []
    for r in rows:
        v = r.get(value_key)
        label = r.get(label_key)
        out.append({
            "value": str(v).strip() if v is not None else "",
            "label": str(label).strip() if label is not None else "",
        })
    return out


def xlsx_response(filename, columns, rows):
    """Stream rows as an XLSX download. `columns` = [{key,label}] like the frontend."""
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Data")
    ws.append([c["label"] for c in columns])
    for r in rows[:EXPORT_CAP]:
        ws.append([r.get(c["key"]) for c in columns])
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    resp["Content-Disposition"] = f'attachment; filename="{filename}-{stamp}.xlsx"'
    wb.save(resp)
    return resp
```

**DoD:** `python manage.py check` passes.

### - [ ] B3 — EDIT `apps/transactions/indexes.py` (expanded registry + kill switch + audit log)

Three changes in this file:

**(a)** REPLACE the whole `INDEXES = { ... }` dict with this expanded registry (PRD §9). Keep the comment block above it.

```python
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
}
```

**(b)** REPLACE the existing `ensure_indexes_async` function with this version (adds the `POS_AUTO_INDEX` kill switch; add `import os` to the imports at the top of the file):

```python
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
```

**(c)** REPLACE the existing `_safe_ensure` function with this version (records the outcome to `ActivityLog`, PRD §9):

```python
def _safe_ensure(profile):
    try:
        failed = ensure_indexes(profile)
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
```

Also EDIT `.env.example`: add these two lines in the config section:

```
# Auto-index MSSQL saat profil aktif/terdaftar (1=aktif, 0=manual via manage.py ensure_indexes)
POS_AUTO_INDEX=1
```

**DoD:** `python manage.py check` passes; `python manage.py ensure_indexes` still runs (prints per-index progress) against the dev connection.

### - [ ] B4 — EDIT `apps/connections/views.py` (auto-index on profile registration)

PRD §9: indexes must also be ensured when a profile is **registered/edited**, not only when activated. In `connections_save`, right after `profile.save()` and before `log_activity(...)`, add the trigger:

```python
    profile.save()
    from apps.transactions.indexes import ensure_indexes_async
    ensure_indexes_async(profile)  # PRD §9 — build registry indexes on registration
    log_activity(request, "konfigurasi", f"Simpan koneksi {profile.name}")
```

(The import is placed inside the function to match how this codebase avoids import cycles — `mssql.get_active_profile` does the same.)

**DoD:** `python manage.py check` passes. Saving a connection profile in the UI creates an `ActivityLog` row with action `index` shortly after (background thread).

<!-- LANJUT -->


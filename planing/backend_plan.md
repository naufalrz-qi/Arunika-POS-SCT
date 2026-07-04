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

## SECTION 2 — PILOT: PENJUALAN DETAIL (the template for every report)

How the report stack fits together (B5–B7 build it once; B8–B16 only add small blocks):

- `apps/transactions/reports.py` (CREATE in B5) holds the **SQL builders**. Each report has: a function `<name>(f) -> (inner_sql, params)` (full SELECT, no ORDER BY), a `SORTS_<NAME>` whitelist dict, and a `SUMMARY_<NAME>` select-list string.
- `apps/monitoring/views.py` (EDIT in B6) gets two **generic view factories** `_report_view(spec)` / `_report_export(spec)` plus option-list helpers. Each report page then is just a `spec` dict + 2 assignments.
- `apps/monitoring/urls.py` gets one `/export` path per report.

### - [ ] B5 — CREATE `apps/transactions/reports.py`

**Unblocks frontend T9.** Full file:

```python
"""Report SQL builders (server-side report pages, PRD §6).

Each report contributes:
- `<name>(f)`      -> (inner_sql, params): full SELECT without ORDER BY, built
                      from the parsed params dict `f` (apps/core/reporting.py).
- `SORTS_<NAME>`   -> whitelist {sort param: output alias} for ORDER BY.
- `SUMMARY_<NAME>` -> select list run as `SELECT {summary} FROM (inner) AS q`
                      with the SAME params (keys: jml_baris, total_qty, total_nilai).

Rules honored here (SECTION 0): raw tables only, parameterized `?` everywhere,
never the computed `total` column — line totals use the tiered-discount
formula (R4.1) via `_line_net`.
"""
import datetime as dt

from apps.core import reporting


def _line_net(price_col: str, alias: str = "d") -> str:
    """R4.1 — qty * price * (1-d1%)(1-d2%)(1-d3%)(1-d4%), NULL-safe."""
    return (
        f"({alias}.qty * {alias}.{price_col}"
        f" * (1 - COALESCE({alias}.diskon1, 0) / 100.0)"
        f" * (1 - COALESCE({alias}.diskon2, 0) / 100.0)"
        f" * (1 - COALESCE({alias}.diskon3, 0) / 100.0)"
        f" * (1 - COALESCE({alias}.diskon4, 0) / 100.0))"
    )


# R4.1 header level — the four header discounts as one multiplier.
HDR_FACTOR = (
    "(1 - COALESCE(h.diskon1, 0) / 100.0)"
    " * (1 - COALESCE(h.diskon2, 0) / 100.0)"
    " * (1 - COALESCE(h.diskon3, 0) / 100.0)"
    " * (1 - COALESCE(h.diskon4, 0) / 100.0)"
)


def _search(where: list, params: list, f: dict, cols: list) -> None:
    """Append a LIKE-on-any-of-`cols` clause when f['search'] is set."""
    if f["search"]:
        like = " OR ".join(f"{c} LIKE ?" for c in cols)
        where.append(f"({like})")
        params.extend([f"%{f['search']}%"] * len(cols))


def _nota_net(where_sql: str) -> str:
    """Per-nota subquery: header net total per R4.1 (line nets * header discounts
    - diskon_uang, then + pajak%). Reused by nota/customer/user/periode/kas."""
    net = f"SUM({_line_net('harga_jual')}) * {HDR_FACTOR} - COALESCE(h.diskon_uang, 0)"
    return (
        "SELECT h.no_transaksi, MIN(h.tanggal) AS tanggal, MIN(h.kd_customer) AS kd_customer, "
        "MIN(h.kd_user) AS kd_user, MIN(h.kd_kas) AS kd_kas, "
        "SUM(d.qty * d.harga_jual) AS total_kotor, "
        f"({net}) * COALESCE(MIN(h.pajak), 0) / 100.0 AS pajak, "
        f"({net}) * (1 + COALESCE(MIN(h.pajak), 0) / 100.0) AS total_bersih "
        "FROM t_penjualan h "
        "INNER JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi "
        f"WHERE {where_sql} "
        "GROUP BY h.no_transaksi, h.diskon1, h.diskon2, h.diskon3, h.diskon4, h.diskon_uang, h.pajak"
    )


def _base_where(f, date_col="h.tanggal", div_col="h.kd_divisi"):
    """Standard date range + optional kd_divisi filter."""
    where = [f"{date_col} >= ?", f"{date_col} <= ?"]
    params = [f["date_from"], f["date_to"]]
    if f.get("kd_divisi"):
        where.append(f"{div_col} = ?")
        params.append(f["kd_divisi"])
    return where, params


# --- Penjualan Detail (B5) ---------------------------------------------------

SORTS_PENJUALAN_DETAIL = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "subtotal": "subtotal"}
SUMMARY_PENJUALAN_DETAIL = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, "
    "COALESCE(SUM(q.subtotal), 0) AS total_nilai"
)


def penjualan_detail(f):
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_transaksi", "b.nama", "c.nama"])
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(c.nama, '') AS customer, "
        "b.nama AS barang, d.qty, d.harga_jual AS harga, "
        f"{_line_net('harga_jual')} AS subtotal "
        "FROM t_penjualan h "
        "INNER JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_customer c ON h.kd_customer = c.kd_customer "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params
```

**DoD:** `python manage.py check` passes.

### - [ ] B6 — EDIT `apps/monitoring/views.py` (generic report views + real Penjualan Detail)

**Unblocks frontend T9.** Three edits in this file.

**(a)** Add two imports below `from apps.transactions import services as tx` (top of file):

```python
from apps.core import reporting
from apps.transactions import reports as rpt
```

**(b)** Insert this whole block directly ABOVE the line `def _mock_page(component):`:

```python
# --- Server-side report plumbing (PRD §6, contract R2) -----------------------
# A report page is a `spec` dict; _report_view/_report_export do the rest.
# spec keys: component, url, inner (rpt.<fn>), sorts, default_sort, summary,
#   filter_keys (module filters, echoed + passed to inner via f), options
#   (callable profile -> dict of [{value,label}] lists), filename + columns (export).

def _opt_divisi(profile):
    return reporting.opt(inv.list_divisi(profile), "kd_divisi", "nama")


def _opt_master(profile, sql):
    with mssql.cursor(profile) as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return reporting.opt(rows, cols[0], cols[1])


def _opt_customer(profile):
    return _opt_master(profile, "SELECT TOP 1000 kd_customer, nama FROM m_customer WHERE status = 1 ORDER BY nama")


def _opt_supplier(profile):
    return _opt_master(profile, "SELECT TOP 1000 kd_supplier, nama FROM m_supplier ORDER BY nama")


def _opt_kas(profile):
    return _opt_master(profile, "SELECT kd_kas, keterangan FROM m_kas WHERE status <> 0 ORDER BY keterangan")


def _spec_params(request, spec):
    f = reporting.parse_report_params(request, spec["sorts"], spec["default_sort"])
    for k in spec.get("filter_keys", []):
        f[k] = (request.GET.get(k) or "").strip()
    return f


def _spec_filters(f, spec):
    filters = {
        "date_from": f["date_from_s"], "date_to": f["date_to_s"],
        "search": f["search"], "sort": f["sort"], "sort_dir": f["sort_dir"],
        "page": f["page"], "per_page": f["per_page"],
    }
    for k in spec.get("filter_keys", []):
        filters[k] = f[k]
    return filters


def _report_view(spec):
    def view(request):
        f = _spec_params(request, spec)

        def load_report():
            rows, total, summary, options, conn_error = [], 0, {}, {}, None
            profile = _active()
            if profile:
                try:
                    inner, params = spec["inner"](f)
                    with mssql.cursor(profile) as cur:
                        rows, total = reporting.run_paged(cur, inner, params, f)
                        cur.execute(f"SELECT {spec['summary']} FROM ({inner}) AS q", params)
                        summary = reporting.clean_rows(reporting.dictify(cur))[0]
                    if spec.get("options"):
                        options = spec["options"](profile)
                except pyodbc.Error as exc:
                    conn_error = f"Gagal membaca laporan: {exc.args[-1] if exc.args else exc}"
            else:
                conn_error = CONN_ERROR
            if f["warning"]:
                conn_error = f["warning"] if not conn_error else f"{conn_error} {f['warning']}"
            return {"rows": rows, "total": total, "summary": summary,
                    "options": options, "conn_error": conn_error}

        return render(request, spec["component"],
                      props={"report": defer(load_report), "filters": _spec_filters(f, spec)})

    return view


def _report_export(spec):
    def view(request):
        f = _spec_params(request, spec)
        profile = _active()
        if not profile:
            request.session["flash_error"] = CONN_ERROR
            return redirect(spec["url"])
        try:
            inner, params = spec["inner"](f)
            with mssql.cursor(profile) as cur:
                rows = reporting.run_all(cur, inner, params, f)
        except pyodbc.Error as exc:
            request.session["flash_error"] = f"Gagal export: {exc.args[-1] if exc.args else exc}"
            return redirect(spec["url"])
        log_activity(request, "export", f"Export {spec['filename']}: {len(rows)} baris")
        return reporting.xlsx_response(spec["filename"], spec["columns"], rows)

    return view
```

**(c)** REPLACE the line `penjualan_all = _mock_page("Admin/Reports/PenjualanAll")` with:

```python
_PENJUALAN_ALL = {
    "component": "Admin/Reports/PenjualanAll",
    "url": "/admin-panel/laporan/penjualan",
    "inner": rpt.penjualan_detail,
    "sorts": rpt.SORTS_PENJUALAN_DETAIL,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PENJUALAN_DETAIL,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-detail",
    "columns": [
        {"key": "no_transaksi", "label": "No. Transaksi"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "customer", "label": "Customer"},
        {"key": "barang", "label": "Barang"},
        {"key": "qty", "label": "Qty"},
        {"key": "harga", "label": "Harga"},
        {"key": "subtotal", "label": "Subtotal"},
    ],
}
penjualan_all = _report_view(_PENJUALAN_ALL)
penjualan_all_export = _report_export(_PENJUALAN_ALL)
```

**DoD:** `python manage.py check` passes. `/admin-panel/laporan/penjualan` renders the shell, then real rows for the current month; filter + sort + pagination round-trip.

### - [ ] B7 — EDIT `apps/monitoring/urls.py` (export URL)

Add directly below the `laporan/penjualan` path:

```python
    path("laporan/penjualan/export", views.penjualan_all_export, name="penjualan_all_export"),
```

**DoD:** `python manage.py check` passes; the Export button on the page downloads an `.xlsx` honoring the active filters.

## SECTION 3 — REMAINING SERVER-SIDE REPORTS

Every task here has the same 3 steps: **(1)** append a block to `apps/transactions/reports.py`, **(2)** in `apps/monitoring/views.py` replace the page's `_mock_page` assignment with a spec + 2 assignments (copy the `_PENJUALAN_ALL` shape), **(3)** add one export path in `apps/monitoring/urls.py`. DoD for each: `python manage.py check` passes, page shows real data, export downloads.

### - [ ] B8 — Penjualan per Nota (unblocks frontend T10)

**(1)** Append to `apps/transactions/reports.py`:

```python
# --- Penjualan per Nota (B8) --------------------------------------------------

SORTS_PENJUALAN_NOTA = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "total_bersih": "total_bersih"}
SUMMARY_PENJUALAN_NOTA = (
    "COUNT(*) AS jml_baris, 0 AS total_qty, COALESCE(SUM(q.total_bersih), 0) AS total_nilai"
)


def penjualan_nota(f):
    where, params = _base_where(f)
    if f.get("kd_customer"):
        where.append("h.kd_customer = ?")
        params.append(f["kd_customer"])
    if f["search"]:
        where.append("h.no_transaksi LIKE ?")
        params.append(f"%{f['search']}%")
    inner = (
        "SELECT n.no_transaksi, n.tanggal, COALESCE(c.nama, '') AS customer, "
        "n.total_kotor, n.total_kotor - (n.total_bersih - n.pajak) AS potongan, "
        "n.pajak, n.total_bersih "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer"
    )
    return inner, params
```

**(2)** REPLACE `penjualan_nota = _mock_page("Admin/Reports/PenjualanNota")` with:

```python
_PENJUALAN_NOTA = {
    "component": "Admin/Reports/PenjualanNota",
    "url": "/admin-panel/laporan/penjualan-nota",
    "inner": rpt.penjualan_nota,
    "sorts": rpt.SORTS_PENJUALAN_NOTA,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PENJUALAN_NOTA,
    "filter_keys": ["kd_divisi", "kd_customer"],
    "options": lambda p: {"divisi": _opt_divisi(p), "customer": _opt_customer(p)},
    "filename": "penjualan-nota",
    "columns": [
        {"key": "no_transaksi", "label": "No. Nota"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "customer", "label": "Customer"},
        {"key": "total_kotor", "label": "Total Kotor"},
        {"key": "potongan", "label": "Potongan"},
        {"key": "pajak", "label": "Pajak"},
        {"key": "total_bersih", "label": "Total Bersih"},
    ],
}
penjualan_nota = _report_view(_PENJUALAN_NOTA)
penjualan_nota_export = _report_export(_PENJUALAN_NOTA)
```

**(3)** urls.py: `path("laporan/penjualan-nota/export", views.penjualan_nota_export, name="penjualan_nota_export"),`

**Verify against legacy:** open one nota in the legacy app and compare `total_bersih` — this is the R4.1 header formula's acid test. If it disagrees, stop and re-check the formula before building the remaining reports.

### - [ ] B9 — Penjualan per Customer (unblocks frontend T11)

**(1)** Append to `reports.py`:

```python
# --- Penjualan per Customer (B9) ----------------------------------------------

SORTS_PENJUALAN_CUSTOMER = {"customer": "customer", "jml_nota": "jml_nota", "total": "total"}
SUMMARY_PENJUALAN_CUSTOMER = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.jml_nota), 0) AS total_qty, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)


def penjualan_customer(f):
    where, params = _base_where(f)
    outer = ""
    if f["search"]:
        outer = "WHERE (c.nama LIKE ? OR n.kd_customer LIKE ?) "
        params = params + [f"%{f['search']}%"] * 2
    inner = (
        "SELECT RTRIM(n.kd_customer) AS kd_customer, COALESCE(MIN(c.nama), '') AS customer, "
        "COALESCE(MIN(k.nama), '') AS kota, COUNT(*) AS jml_nota, SUM(n.total_bersih) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "LEFT JOIN m_kota k ON c.kd_kota = k.kd_kota "
        f"{outer}GROUP BY n.kd_customer"
    )
    return inner, params
```

**(2)** REPLACE the `penjualan_customer = _mock_page(...)` line with a spec (`component "Admin/Reports/PenjualanCustomer"`, `url "/admin-panel/laporan/penjualan-customer"`, `inner rpt.penjualan_customer`, sorts/summary from above, `default_sort "total"`, `filter_keys ["kd_divisi"]`, `options divisi`, `filename "penjualan-customer"`, columns `kd_customer/Kode, customer/Customer, kota/Kota, jml_nota/Jml Nota, total/Total`) + `penjualan_customer = _report_view(...)` + `penjualan_customer_export = _report_export(...)` — same shape as B8.

**(3)** urls.py: `path("laporan/penjualan-customer/export", views.penjualan_customer_export, name="penjualan_customer_export"),`

### - [ ] B10 — Penjualan per User (unblocks frontend T12)

**(1)** Append to `reports.py`. NOTE: `USER` is a reserved word in T-SQL — the alias must stay bracketed `[user]`, and the sort whitelist maps to the bracketed alias.

```python
# --- Penjualan per User (B10) ---------------------------------------------------

SORTS_PENJUALAN_USER = {"user": "[user]", "jml_nota": "jml_nota", "total": "total"}
SUMMARY_PENJUALAN_USER = SUMMARY_PENJUALAN_CUSTOMER


def penjualan_user(f):
    where, params = _base_where(f)
    inner = (
        "SELECT RTRIM(n.kd_user) AS kd_user, "
        "COALESCE(MIN(u.nama), RTRIM(n.kd_user)) AS [user], "
        "COUNT(*) AS jml_nota, SUM(n.total_bersih) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_userx u ON n.kd_user = u.kd_user "
        "GROUP BY n.kd_user"
    )
    return inner, params
```

**(2)** Spec: component `"Admin/Reports/PenjualanUser"`, url `"/admin-panel/laporan/penjualan-user"`, `default_sort "total"`, `filter_keys ["kd_divisi"]`, options divisi, filename `"penjualan-user"`, columns `kd_user/Kode, user/User \/ Kasir, jml_nota/Jml Nota, total/Total`. Assign `penjualan_user` / `penjualan_user_export`.

**(3)** urls.py: `path("laporan/penjualan-user/export", views.penjualan_user_export, name="penjualan_user_export"),`

### - [ ] B11 — Penjualan per Periode (unblocks frontend T13)

Extra module filter `granularitas` (`harian` default | `bulanan`). The period expression is chosen with a Python `if` over two hardcoded strings — never interpolate the raw param.

**(1)** Append to `reports.py`:

```python
# --- Penjualan per Periode (B11) -------------------------------------------------

SORTS_PENJUALAN_PERIODE = {"periode": "periode", "total": "total"}
SUMMARY_PENJUALAN_PERIODE = SUMMARY_PENJUALAN_CUSTOMER


def penjualan_periode(f):
    where, params = _base_where(f)
    if f.get("granularitas") == "bulanan":
        expr = "CONVERT(char(7), n.tanggal, 120)"   # 'YYYY-MM'
    else:
        expr = "CONVERT(char(10), n.tanggal, 120)"  # 'YYYY-MM-DD'
    inner = (
        f"SELECT {expr} AS periode, COUNT(*) AS jml_nota, SUM(n.total_bersih) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        f"GROUP BY {expr}"
    )
    return inner, params
```

**(2)** Spec: component `"Admin/Reports/PenjualanPeriode"`, url `"/admin-panel/laporan/penjualan-periode"`, `default_sort "periode"`, `filter_keys ["kd_divisi", "granularitas"]`, options divisi, filename `"penjualan-periode"`, columns `periode/Periode, jml_nota/Jml Nota, total/Total`. Assign `penjualan_periode` / `penjualan_periode_export`.

**(3)** urls.py: `path("laporan/penjualan-periode/export", views.penjualan_periode_export, name="penjualan_periode_export"),`

### - [ ] B12 — Retur Penjualan (unblocks frontend T14)

**(1)** Append to `reports.py` (detail-level like B5; retur detail price column is `harga_jual`):

```python
# --- Retur Penjualan (B12) ------------------------------------------------------

SORTS_RETUR_PENJUALAN = {"no_retur": "no_retur", "tanggal": "tanggal", "nilai": "nilai"}
SUMMARY_RETUR_PENJUALAN = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, "
    "COALESCE(SUM(q.nilai), 0) AS total_nilai"
)


def retur_penjualan(f):
    where, params = _base_where(f)
    if f.get("kd_customer"):
        where.append("h.kd_customer = ?")
        params.append(f["kd_customer"])
    _search(where, params, f, ["h.no_retur", "b.nama", "c.nama"])
    inner = (
        "SELECT h.no_retur, h.tanggal, COALESCE(c.nama, '') AS customer, "
        "b.nama AS barang, d.qty, "
        f"{_line_net('harga_jual')} AS nilai "
        "FROM t_penjualan_retur h "
        "INNER JOIN t_penjualan_retur_detail d ON h.no_retur = d.no_retur "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_customer c ON h.kd_customer = c.kd_customer "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params
```

**(2)** Spec: component `"Admin/Reports/ReturPenjualan"`, url `"/admin-panel/laporan/retur-penjualan"`, `default_sort "tanggal"`, `filter_keys ["kd_divisi", "kd_customer"]`, options divisi + customer, filename `"retur-penjualan"`, columns `no_retur/No. Retur, tanggal/Tanggal, customer/Customer, barang/Barang, qty/Qty, nilai/Nilai`. Assign `retur_penjualan` / `retur_penjualan_export`.

**(3)** urls.py: `path("laporan/retur-penjualan/export", views.retur_penjualan_export, name="retur_penjualan_export"),`

### - [ ] B13 — Pembelian (unblocks frontend T15)

**(1)** Append to `reports.py` (price column `harga_beli`; keep `status IN (0, 1)` — same filter the movement engine uses):

```python
# --- Pembelian (B13) --------------------------------------------------------------

SORTS_PEMBELIAN = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "subtotal": "subtotal"}
SUMMARY_PEMBELIAN = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, "
    "COALESCE(SUM(q.subtotal), 0) AS total_nilai"
)


def pembelian(f):
    where, params = _base_where(f)
    where.append("h.status IN (0, 1)")
    if f.get("kd_supplier"):
        where.append("h.kd_supplier = ?")
        params.append(f["kd_supplier"])
    _search(where, params, f, ["h.no_transaksi", "b.nama", "s.nama"])
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(s.nama, '') AS supplier, "
        "b.nama AS barang, d.qty, d.harga_beli, "
        f"{_line_net('harga_beli')} AS subtotal "
        "FROM t_pembelian h "
        "INNER JOIN t_pembelian_detail d ON h.no_transaksi = d.no_transaksi "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_supplier s ON h.kd_supplier = s.kd_supplier "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params
```

**(2)** Spec: component `"Admin/Reports/Pembelian"`, url `"/admin-panel/laporan/pembelian"`, `default_sort "tanggal"`, `filter_keys ["kd_divisi", "kd_supplier"]`, options divisi + supplier (`_opt_supplier`), filename `"pembelian"`, columns `no_transaksi/No. Transaksi, tanggal/Tanggal, supplier/Supplier, barang/Barang, qty/Qty, harga_beli/Harga Beli, subtotal/Subtotal`. Assign `pembelian` / `pembelian_export`.

**(3)** urls.py: `path("laporan/pembelian/export", views.pembelian_export, name="pembelian_export"),`

### - [ ] B14 — Retur Pembelian (unblocks frontend T16)

**(1)** Append to `reports.py` — copy of B12 with supplier instead of customer; NOTE the detail price column here is **`harga`** (not `harga_beli`/`harga_jual`):

```python
# --- Retur Pembelian (B14) ---------------------------------------------------------

SORTS_RETUR_PEMBELIAN = SORTS_RETUR_PENJUALAN
SUMMARY_RETUR_PEMBELIAN = SUMMARY_RETUR_PENJUALAN


def retur_pembelian(f):
    where, params = _base_where(f)
    if f.get("kd_supplier"):
        where.append("h.kd_supplier = ?")
        params.append(f["kd_supplier"])
    _search(where, params, f, ["h.no_retur", "b.nama", "s.nama"])
    inner = (
        "SELECT h.no_retur, h.tanggal, COALESCE(s.nama, '') AS supplier, "
        "b.nama AS barang, d.qty, "
        f"{_line_net('harga')} AS nilai "
        "FROM t_pembelian_retur h "
        "INNER JOIN t_pembelian_retur_detail d ON h.no_retur = d.no_retur "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_supplier s ON h.kd_supplier = s.kd_supplier "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params
```

**(2)** Spec: component `"Admin/Reports/ReturPembelian"`, url `"/admin-panel/laporan/retur-pembelian"`, `default_sort "tanggal"`, `filter_keys ["kd_divisi", "kd_supplier"]`, options divisi + supplier, filename `"retur-pembelian"`, columns `no_retur/No. Retur, tanggal/Tanggal, supplier/Supplier, barang/Barang, qty/Qty, nilai/Nilai`. Assign `retur_pembelian` / `retur_pembelian_export`.

**(3)** urls.py: `path("laporan/retur-pembelian/export", views.retur_pembelian_export, name="retur_pembelian_export"),`

### - [ ] B15 — Opname Stok (unblocks frontend T17)

Semantics (matches the movement engine, `apps/inventory/services.py` block [3/4]): a `t_opname_stok` row is an **adjustment** — `status = 2` adds stock, anything else removes it. So `selisih` = signed qty. `qty_fisik` comes from `t_opname_proses` matched by (divisi, barang, satuan, same calendar day) via `OUTER APPLY` — the two tables **cannot** be joined on `no_transaksi` (varchar vs bigint). When no proses row matches, `qty_fisik`/`qty_sistem` are NULL and the frontend shows "-". **This mapping is a best guess from the schema — verify against live data in B28 before trusting the qty_sistem/qty_fisik columns.**

**(1)** Append to `reports.py`:

```python
# --- Opname Stok (B15) ---------------------------------------------------------------

SORTS_OPNAME = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "selisih": "selisih"}
SUMMARY_OPNAME = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.selisih), 0) AS total_qty, 0 AS total_nilai"
)


def opname(f):
    where, params = _base_where(f, date_col="s.tanggal", div_col="s.kd_divisi")
    _search(where, params, f, ["s.no_transaksi", "b.nama"])
    selisih = "CASE WHEN s.status = 2 THEN s.qty ELSE -s.qty END"
    inner = (
        "SELECT s.no_transaksi, s.tanggal, COALESCE(dv.nama, RTRIM(s.kd_divisi)) AS divisi, "
        f"b.nama AS barang, p.qty - ({selisih}) AS qty_sistem, p.qty AS qty_fisik, "
        f"{selisih} AS selisih "
        "FROM t_opname_stok s "
        "INNER JOIN m_barang b ON s.kd_barang = b.kd_barang "
        "LEFT JOIN m_divisi dv ON s.kd_divisi = dv.kd_divisi "
        "OUTER APPLY (SELECT TOP 1 pr.qty FROM t_opname_proses pr "
        "WHERE pr.kd_divisi = s.kd_divisi AND pr.kd_barang = s.kd_barang "
        "AND pr.kd_satuan = s.kd_satuan AND CONVERT(date, pr.tanggal) = CONVERT(date, s.tanggal)) p "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params
```

**(2)** Spec: component `"Admin/Inventory/Opname"`, url `"/admin-panel/inventory/opname"`, `default_sort "tanggal"`, `filter_keys ["kd_divisi"]`, options divisi, filename `"opname-stok"`, columns `no_transaksi/No. Opname, tanggal/Tanggal, divisi/Divisi, barang/Barang, qty_sistem/Qty Sistem, qty_fisik/Qty Fisik, selisih/Selisih`. Assign `opname` / `opname_export` (replaces `opname = _mock_page(...)`).

**(3)** urls.py: `path("inventory/opname/export", views.opname_export, name="opname_export"),`

### - [ ] B16 — Shift Kasir (unblocks frontend T19)

`t_pegawai_ganti_shift` has **no `kd_divisi`** — the Divisi filter goes through `m_pegawai.kd_divisi` (joined via the detail row's `kd_pegawai`). `no_transaksi` is bigint → CAST to varchar so the frontend row-key is a string.

**(1)** Append to `reports.py`:

```python
# --- Shift Kasir (B16) -----------------------------------------------------------------

SORTS_SHIFT = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "pegawai": "pegawai"}
SUMMARY_SHIFT = "COUNT(*) AS jml_baris, 0 AS total_qty, 0 AS total_nilai"


def shift(f):
    where = ["h.tanggal >= ?", "h.tanggal <= ?"]
    params = [f["date_from"], f["date_to"]]
    if f.get("kd_divisi"):  # header has no divisi; filter via pegawai's divisi
        where.append("pg.kd_divisi = ?")
        params.append(f["kd_divisi"])
    _search(where, params, f, ["pg.nama", "h.keterangan"])
    inner = (
        "SELECT CAST(h.no_transaksi AS varchar(20)) AS no_transaksi, h.tanggal, "
        "COALESCE(pg.nama, RTRIM(d.kd_pegawai)) AS pegawai, RTRIM(d.kd_shift) AS shift, "
        "COALESCE(h.keterangan, '') AS keterangan "
        "FROM t_pegawai_ganti_shift h "
        "INNER JOIN t_pegawai_ganti_shift_detail d ON h.no_transaksi = d.no_transaksi "
        "LEFT JOIN m_pegawai pg ON d.kd_pegawai = pg.kd_pegawai "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params
```

**(2)** Spec: component `"Admin/Cash/Shift"`, url `"/admin-panel/kas/shift"`, `default_sort "tanggal"`, `filter_keys ["kd_divisi"]`, options divisi, filename `"shift-kasir"`, columns `no_transaksi/No. Transaksi, tanggal/Tanggal, pegawai/Pegawai, shift/Shift, keterangan/Keterangan`. Assign `shift` / `shift_export` (replaces `shift = _mock_page(...)`).

**(3)** urls.py: `path("kas/shift/export", views.shift_export, name="shift_export"),`

## SECTION 4 — KAS HARIAN (running balance — its own pattern)

Kas Harian cannot use `run_paged`: the `saldo` column is a running balance, so all rows in the (clamped) range are fetched and the saldo computed in Python. Summary uses its own keys: `{saldo_awal, total_masuk, total_keluar, saldo_akhir}`.

### - [ ] B17 — Kas Harian (unblocks frontend T18)

**(1)** EDIT `apps/transactions/reports.py`: add `from core import mssql` to the imports at the top, then append:

```python
# --- Kas Harian (B17) — saldo berjalan, dihitung di Python ------------------------

KAS_SORTS = {"tanggal": "tanggal"}  # only sort supported; saldo needs chronological order


def _kas_union(pred: str) -> str:
    """UNION of every cash-affecting source, uniform columns:
    tanggal, kd_kas, keterangan, masuk, keluar.

    `pred` is a date predicate template like "{col} >= ? AND {col} <= ?" —
    it is applied to each of the 6 arms, so callers pass the SAME param
    tuple once PER ARM (6x). Sales money-in is the per-nota net (R4.1) for
    notas whose kd_kas is filled; NOTE: which sales rows actually hit the
    cash drawer is a best guess — verify one day's saldo in B28."""
    def w(col):
        return pred.format(col=col)

    nota = _nota_net(w("h.tanggal") + " AND LTRIM(RTRIM(COALESCE(h.kd_kas, ''))) <> ''")
    return (
        "SELECT tanggal, kd_kas, COALESCE(keterangan, '') AS keterangan, nominal AS masuk, 0 AS keluar "
        f"FROM t_penambahan_kas WHERE {w('tanggal')}"
        " UNION ALL "
        "SELECT tanggal, kd_kas, 'Pendapatan: ' + COALESCE(keterangan, ''), nominal, 0 "
        f"FROM t_pendapatan WHERE {w('tanggal')}"
        " UNION ALL "
        "SELECT tanggal, kd_kas, 'Biaya: ' + COALESCE(keterangan, ''), 0, nominal "
        f"FROM t_biaya_operasional WHERE {w('tanggal')}"
        " UNION ALL "
        "SELECT tanggal, kd_kas_sumber, 'Mutasi keluar: ' + COALESCE(keterangan, ''), 0, nominal "
        f"FROM t_mutasi_kas WHERE {w('tanggal')}"
        " UNION ALL "
        "SELECT tanggal, kd_kas_tujuan, 'Mutasi masuk: ' + COALESCE(keterangan, ''), nominal, 0 "
        f"FROM t_mutasi_kas WHERE {w('tanggal')}"
        " UNION ALL "
        "SELECT x.tanggal, x.kd_kas, 'Penjualan ' + RTRIM(x.no_transaksi), x.total_bersih, 0 "
        f"FROM ({nota}) x"
    )


def kas_harian_data(profile, f, export=False) -> dict:
    """Rows + running saldo. Pagination is a Python slice — the range is
    already clamped to max_range_days, so the row volume stays sane."""
    from apps.inventory.services import _k

    period_sql = _kas_union("{col} >= ? AND {col} <= ?")
    pre_sql = (
        "SELECT RTRIM(kd_kas) AS kd_kas, SUM(masuk) - SUM(keluar) AS net "
        "FROM (" + _kas_union("{col} < ?") + ") u GROUP BY kd_kas"
    )
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT kd_kas, kd_index, keterangan, saldo_awal FROM m_kas")
        kas_rows = reporting.dictify(cur)
        cur.execute(pre_sql, [f["date_from"]] * 6)
        pre = reporting.dictify(cur)
        cur.execute(period_sql, [f["date_from"], f["date_to"]] * 6)
        moves = reporting.dictify(cur)

    def _fl(v):
        return float(v) if v is not None else 0.0

    kas_name, saldo = {}, {}
    for r in kas_rows:
        kk = _k(r["kd_kas"])
        kas_name[kk] = (r["keterangan"] or r["kd_index"] or r["kd_kas"] or "").strip()
        saldo[kk] = _fl(r["saldo_awal"])
    for r in pre:  # net movement before date_from, on top of m_kas.saldo_awal
        kk = _k(r["kd_kas"])
        saldo[kk] = saldo.get(kk, 0.0) + _fl(r["net"])

    want = _k(f["kd_kas"]) if f.get("kd_kas") else None
    saldo_awal = saldo.get(want, 0.0) if want else sum(saldo.values())

    moves.sort(key=lambda m: m["tanggal"])
    rows, total_masuk, total_keluar = [], 0.0, 0.0
    for m in moves:
        kk = _k(m["kd_kas"])
        masuk, keluar = _fl(m["masuk"]), _fl(m["keluar"])
        saldo[kk] = saldo.get(kk, 0.0) + masuk - keluar
        if want and kk != want:
            continue
        total_masuk += masuk
        total_keluar += keluar
        rows.append({
            "tanggal": m["tanggal"].strftime("%Y-%m-%d %H:%M") if hasattr(m["tanggal"], "strftime") else str(m["tanggal"]),
            "kas": kas_name.get(kk, (m["kd_kas"] or "").strip()),
            "keterangan": (m["keterangan"] or "").strip(),
            "masuk": masuk,
            "keluar": keluar,
            "saldo": round(saldo[kk], 2),
        })
    for i, r in enumerate(rows):
        r["_rid"] = i + 1

    summary = {
        "saldo_awal": round(saldo_awal, 2),
        "total_masuk": round(total_masuk, 2),
        "total_keluar": round(total_keluar, 2),
        "saldo_akhir": round(saldo_awal + total_masuk - total_keluar, 2),
    }
    total = len(rows)
    if f["sort_dir"] == "desc":
        rows = rows[::-1]
    if not export:
        start = (f["page"] - 1) * f["per_page"]
        rows = rows[start:start + f["per_page"]]
    return {"rows": rows, "total": total, "summary": summary}
```

**(2)** EDIT `apps/monitoring/views.py`: REPLACE `kas_harian = _mock_page("Admin/Cash/Kas")` with:

```python
def kas_harian(request):
    f = reporting.parse_report_params(request, rpt.KAS_SORTS, "tanggal")
    f["kd_kas"] = (request.GET.get("kd_kas") or "").strip()

    def load_report():
        profile = _active()
        if not profile:
            return {"rows": [], "total": 0, "summary": {}, "options": {}, "conn_error": CONN_ERROR}
        try:
            data = rpt.kas_harian_data(profile, f)
            data["options"] = {"kas": _opt_kas(profile)}
            data["conn_error"] = f["warning"]
            return data
        except pyodbc.Error as exc:
            return {"rows": [], "total": 0, "summary": {}, "options": {},
                    "conn_error": f"Gagal membaca kas: {exc.args[-1] if exc.args else exc}"}

    filters = {
        "date_from": f["date_from_s"], "date_to": f["date_to_s"], "kd_kas": f["kd_kas"],
        "search": f["search"], "sort": f["sort"], "sort_dir": f["sort_dir"],
        "page": f["page"], "per_page": f["per_page"],
    }
    return render(request, "Admin/Cash/Kas", props={"report": defer(load_report), "filters": filters})


KAS_COLUMNS = [
    {"key": "tanggal", "label": "Tanggal"},
    {"key": "kas", "label": "Kas"},
    {"key": "keterangan", "label": "Keterangan"},
    {"key": "masuk", "label": "Masuk"},
    {"key": "keluar", "label": "Keluar"},
    {"key": "saldo", "label": "Saldo"},
]


def kas_harian_export(request):
    f = reporting.parse_report_params(request, rpt.KAS_SORTS, "tanggal")
    f["kd_kas"] = (request.GET.get("kd_kas") or "").strip()
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/admin-panel/kas/harian")
    try:
        data = rpt.kas_harian_data(profile, f, export=True)
    except pyodbc.Error as exc:
        request.session["flash_error"] = f"Gagal export: {exc.args[-1] if exc.args else exc}"
        return redirect("/admin-panel/kas/harian")
    log_activity(request, "export", f"Export kas-harian: {len(data['rows'])} baris")
    return reporting.xlsx_response("kas-harian", KAS_COLUMNS, data["rows"])
```

**(3)** urls.py: `path("kas/harian/export", views.kas_harian_export, name="kas_export"),`

**DoD:** `python manage.py check` passes; page shows chronological rows with a running `saldo`; the summary strip shows saldo awal/masuk/keluar/akhir. **Verify:** pick one day, compare `saldo_akhir` against the legacy app's cash report — the "sales into cash drawer" arm is unverified; if it disagrees, adjust the nota arm's filter (e.g. add a `status` condition) and note the finding here.

## SECTION 5 — CLIENT-SIDE PAGES (deferred prop `data = {rows, conn_error}`)

Small datasets: the backend sends ALL rows in one deferred prop; the frontend does search/sort/paging client-side. View pattern = the existing `stok_akhir` view in `apps/monitoring/views.py` (copy its shape). DoD for each: `python manage.py check` passes; page loads real rows.

### - [ ] B18 — Promo & Diskon (unblocks frontend T22)

**(1)** EDIT `apps/master_data/services.py`: add `import datetime as dt` below the existing `from decimal import Decimal`, then append at the end of the file:

```python
# --- Promo & Voucher (read) --------------------------------------------------

def list_promo(profile) -> list[dict]:
    """m_barang_promo + detail. Status from the date range (jam_awal/jam_akhir
    ignored — daily granularity is enough for this monitoring page)."""
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT RTRIM(h.kd_promo) AS kd_promo, COALESCE(dv.nama, RTRIM(h.kd_divisi)) AS divisi, "
            "b.nama AS barang, d.harga_bersih AS harga_promo, h.tanggal_awal, h.tanggal_akhir "
            "FROM m_barang_promo h "
            "INNER JOIN m_barang_promo_detail d ON h.kd_promo = d.kd_promo "
            "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
            "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
            "ORDER BY h.tanggal_awal DESC"
        )
        rows = _dictify(cur)

    now = dt.datetime.now()
    out = []
    for r in rows:
        awal, akhir = r["tanggal_awal"], r["tanggal_akhir"]
        if awal and now < awal:
            status = "Terjadwal"
        elif akhir and now > akhir.replace(hour=23, minute=59, second=59):
            status = "Berakhir"
        else:
            status = "Aktif"
        out.append({
            "kd_promo": _st(r["kd_promo"]),
            "divisi": _st(r["divisi"]),
            "barang": _st(r["barang"]),
            "harga_promo": _f(r["harga_promo"]),  # harga_bersih; kolom `harga` bertipe char, jangan dipakai
            "tanggal_awal": awal.strftime("%Y-%m-%d") if awal else "",
            "tanggal_akhir": akhir.strftime("%Y-%m-%d") if akhir else "",
            "status": status,
        })
    return out
```

**(2)** EDIT `apps/monitoring/views.py`: REPLACE `promo = _mock_page("Admin/Promo/Promo")` with:

```python
def promo(request):
    def load():
        profile = _active()
        rows, conn_error = [], None
        if profile:
            try:
                rows = master.list_promo(profile)
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca promo: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "conn_error": conn_error}

    return render(request, "Admin/Promo/Promo", props={"data": defer(load)})
```

### - [ ] B19 — Voucher (unblocks frontend T23)

**(1)** Append to `apps/master_data/services.py`:

```python
def list_voucher(profile) -> list[dict]:
    """m_voucher + usage aggregate from t_penjualan.kd_voucher.

    Exception to rule #6 (no date predicate): usage is an ALL-TIME count by
    design, and IX_tpenjualan_voucher (B3) makes it an index seek/scan."""
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT kd_voucher, nama, nominal, status FROM m_voucher ORDER BY nama")
        vouchers = _dictify(cur)
        cur.execute(
            "SELECT kd_voucher, COUNT(*) AS dipakai FROM t_penjualan "
            "WHERE LTRIM(RTRIM(COALESCE(kd_voucher, ''))) <> '' GROUP BY kd_voucher"
        )
        # rule #7: normalize kd_* before dict lookups (CI collation vs Python dict)
        usage = {_st(r["kd_voucher"]).upper(): int(r["dipakai"]) for r in _dictify(cur)}

    out = []
    for v in vouchers:
        kd = _st(v["kd_voucher"])
        n = usage.get(kd.upper(), 0)
        nominal = _f(v["nominal"])
        out.append({
            "kd_voucher": kd,
            "nama": _st(v["nama"]),
            "nominal": nominal,
            "dipakai": n,
            "nilai_dipakai": n * nominal,
            "status": "Aktif" if _active(v["status"]) else "Non-aktif",
        })
    return out
```

**(2)** REPLACE `voucher = _mock_page("Admin/Promo/Voucher")` with a view identical in shape to B18's `promo` view: name `voucher`, calls `master.list_voucher(profile)`, error text `"Gagal membaca voucher: ..."`, component `"Admin/Promo/Voucher"`.

### - [ ] B20 — FMI Penjualan (unblocks frontend T24)

**(1)** Append to `apps/transactions/reports.py`:

```python
# --- FMI (B20/B21) ------------------------------------------------------------------

FMI_DAYS = 30  # analysis window: last 30 days


def fmi_penjualan(profile) -> list[dict]:
    """Qty sold per product over the last FMI_DAYS + Fast/Medium/Slow class.
    Class rule: sort by qty_terjual desc — top third Fast, middle Medium,
    bottom Slow (simple terciles; adjust here if the business wants fixed
    thresholds later)."""
    since = dt.datetime.now() - dt.timedelta(days=FMI_DAYS)
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT RTRIM(d.kd_barang) AS kd_barang, MIN(b.nama) AS barang, "
            "COALESCE(MIN(k.nama), '') AS kategori, SUM(d.qty) AS qty_terjual, "
            f"SUM({_line_net('harga_jual')}) AS nilai "
            "FROM t_penjualan_detail d "
            "INNER JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
            "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
            "LEFT JOIN m_kategori k ON b.kd_kategori = k.kd_kategori "
            "WHERE h.tanggal >= ? "
            "GROUP BY d.kd_barang",
            [since],
        )
        rows = reporting.clean_rows(reporting.dictify(cur))

    rows.sort(key=lambda r: r["qty_terjual"] or 0, reverse=True)
    n = len(rows)
    for i, r in enumerate(rows):
        r["kelas"] = "Fast" if i < n / 3 else ("Medium" if i < 2 * n / 3 else "Slow")
    return rows
```

**(2)** REPLACE `fmi_penjualan = _mock_page("Admin/Analytics/FmiPenjualan")` with a B18-shaped view: name `fmi_penjualan`, calls `rpt.fmi_penjualan(profile)`, error text `"Gagal membaca FMI: ..."`, component `"Admin/Analytics/FmiPenjualan"`.

### - [ ] B21 — FMI Stok (unblocks frontend T25)

Combines B20's sales with the movement engine's closing stock. **The Python-side join MUST go through `_k()`** (rule #7) — this is exactly the case where unnormalized keys silently drop rows.

**(1)** Append to `apps/transactions/reports.py`:

```python
def fmi_stok(profile) -> list[dict]:
    """Stock health: last-FMI_DAYS sales vs current stock (movement engine).
    cover = days of stock left at the current sales rate.
    Kritis: no stock, or cover < 14 days. Overstock: no sales, or cover > 90
    days. Sehat: everything else."""
    from apps.inventory import services as inv
    from apps.inventory.services import _k

    sales = {_k(r["kd_barang"]): r for r in fmi_penjualan(profile)}
    levels = inv.stock_levels(profile)  # Semua Divisi — stok akhir per barang

    out = []
    for lv in levels:
        kb = _k(lv["kd_barang"])
        terjual = float(sales.get(kb, {}).get("qty_terjual") or 0)
        stok = float(lv["stok_akhir"])
        daily = terjual / FMI_DAYS
        cover = (stok / daily) if daily > 0 else None
        if stok <= 0 or (cover is not None and cover < 14):
            status = "Kritis"
        elif terjual == 0 or (cover is not None and cover > 90):
            status = "Overstock"
        else:
            status = "Sehat"
        out.append({
            "kd_barang": lv["kd_barang"],
            "barang": lv["nama"],
            "stok": stok,
            "terjual": terjual,
            "rasio": round(terjual / stok, 2) if stok > 0 else 0,
            "status": status,
        })
    out.sort(key=lambda r: r["barang"])
    return out
```

**(2)** REPLACE `fmi_stok = _mock_page("Admin/Analytics/FmiStok")` with a B18-shaped view: name `fmi_stok`, calls `rpt.fmi_stok(profile)`, error text `"Gagal membaca FMI stok: ..."`, component `"Admin/Analytics/FmiStok"`. (This page is slow-ish — the deferred wrapper is what keeps first paint instant.)

### - [ ] B22 — Master Supplier (unblocks frontend T28)

**(1)** Append to `apps/master_data/services.py` (same shape as `list_customers`):

```python
def list_suppliers(profile, search: str = "") -> list[dict]:
    where, params = ["1=1"], []
    if search:
        where.append("(s.nama LIKE ? OR s.kd_supplier LIKE ? OR k.nama LIKE ?)")
        params += [f"%{search}%"] * 3
    with mssql.cursor(profile) as cur:
        cur.execute(
            f"SELECT TOP {MAX_ROWS} s.kd_supplier, s.nama, k.nama AS kota, s.kontak, s.hp "
            "FROM m_supplier s LEFT JOIN m_kota k ON s.kd_kota = k.kd_kota "
            f"WHERE {' AND '.join(where)} ORDER BY s.nama",
            params,
        )
        rows = _dictify(cur)
    # m_supplier has NO status column — send "" so the frontend renders "-".
    return [
        {
            "kd_supplier": _st(r["kd_supplier"]),
            "nama": _st(r["nama"]),
            "kota": _st(r["kota"]),
            "kontak": _st(r["kontak"]),
            "hp": _st(r["hp"]),
            "status": "",
        }
        for r in rows
    ]
```

**(2)** EDIT `apps/monitoring/views.py`: add this view near `customers_index`:

```python
def suppliers_index(request):
    search = request.GET.get("search", "")

    def load():
        profile = _active()
        rows, conn_error = [], None
        if profile:
            try:
                rows = master.list_suppliers(profile, search)
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca supplier: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "conn_error": conn_error}

    return render(request, "Admin/MasterData/Supplier",
                  props={"data": defer(load), "filters": {"search": search}})
```

**(3)** EDIT `apps/monitoring/urls.py`, below the customers paths:

```python
    path("master/suppliers", views.suppliers_index, name="suppliers"),
```

**DoD:** `python manage.py check` passes; `/admin-panel/master/suppliers` returns rows (menu entry arrives in B26).

## SECTION 6 — SYNC HISTORY (SQLite models + audit of sync-harga)

The models live in `apps/core/models.py` — NOT `apps/master_data/` (that package is not an installed Django app: no models.py/apps.py/migrations, and it is absent from `INSTALLED_APPS`). `apps.core` is registered, has migrations, and already holds `ActivityLog`.

### - [ ] B23 — EDIT `apps/core/models.py` (SyncRun / SyncRunItem)

Append at the end of the file:

```python
class SyncRun(models.Model):
    """One price-sync run between two servers (PRD §8). SQLite-only audit."""
    created_at = models.DateTimeField(auto_now_add=True)
    username = models.CharField(max_length=150, blank=True)
    src_name = models.CharField(max_length=100)
    dst_name = models.CharField(max_length=100)
    mode = models.CharField(max_length=30, blank=True)
    with_margin = models.BooleanField(default=False)
    total_items = models.IntegerField(default=0)
    # pending -> ok / gagal; a run stuck on 'pending' means the process died mid-sync.
    status = models.CharField(max_length=10, default="pending")
    error = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.src_name}->{self.dst_name} {self.status}"


class SyncRunItem(models.Model):
    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="items")
    kd_barang = models.CharField(max_length=30)
    kd_satuan = models.CharField(max_length=10)
    nama_barang = models.CharField(max_length=120, blank=True)
    harga_lama_dst = models.FloatField(null=True, blank=True)  # None = belum ada di dst
    harga_baru = models.FloatField(default=0)
```

Then run (two separate commands):

```bash
python manage.py makemigrations core
python manage.py migrate
```

**DoD:** `python manage.py check` passes; `migrate` applies a new `core` migration.

### - [ ] B24 — EDIT `apps/monitoring/views.py` — record every sync run

REPLACE the whole `sync_harga_apply` function with:

```python
def sync_harga_apply(request):
    data = get_data(request)
    src = get_object_or_404(ServerProfile, pk=data.get("src"))
    dst = get_object_or_404(ServerProfile, pk=data.get("dst"))
    keys = data.get("keys") or []
    with_margin = bool(data.get("with_margin"))
    mode = data.get("mode", "gudang_grosir")

    # Audit (PRD §8): snapshot old/new prices BEFORE writing, and create the
    # run first — a run left on 'pending' is visible evidence of a dead sync.
    from apps.core.models import SyncRun, SyncRunItem
    run = SyncRun.objects.create(
        username=request.user.username, src_name=src.name, dst_name=dst.name,
        mode=mode, with_margin=with_margin, total_items=len(keys),
    )
    try:
        src_map = master._harga_map(src)
        dst_map = master._harga_map(dst)
        with mssql.cursor(src) as cur:
            cur.execute("SELECT kd_barang, nama FROM m_barang")
            names = {(r[0] or "").strip(): (r[1] or "").strip() for r in cur.fetchall()}
        items = []
        for k in keys:
            kb, ks = (k.get("kd_barang") or "").strip(), (k.get("kd_satuan") or "").strip()
            s = src_map.get((kb, ks))
            if not s:
                continue
            d = dst_map.get((kb, ks))
            items.append(SyncRunItem(
                run=run, kd_barang=kb, kd_satuan=ks, nama_barang=names.get(kb, "")[:120],
                harga_lama_dst=d["harga_jual"] if d else None, harga_baru=s["harga_jual"],
            ))
        SyncRunItem.objects.bulk_create(items)

        n = master.sync_harga_jual(src, dst, keys, with_margin=with_margin)
        run.status, run.total_items = "ok", n
        run.save(update_fields=["status", "total_items"])
        log_activity(request, "sync_harga", f"Sync harga {src.name} -> {dst.name}: {n} baris")
        request.session["flash_success"] = f"Sinkronisasi selesai: {n} baris diperbarui."
    except pyodbc.Error as exc:
        msg = str(exc.args[-1] if exc.args else exc)
        run.status, run.error = "gagal", msg[:255]
        run.save(update_fields=["status", "error"])
        request.session["flash_error"] = f"Gagal sinkron: {msg}"
    return redirect(f"/admin-panel/master/sync-harga?mode={mode}&src={src.id}&dst={dst.id}")
```

(Yes, `_harga_map(src)` is fetched here and again inside `sync_harga_jual` — accepted duplication; do not refactor the service in this task.)

**DoD:** `python manage.py check` passes. Running a sync from the UI creates one `SyncRun` with items; killing the connection mid-sync leaves it `gagal`.

### - [ ] B25 — Riwayat Sync view + URL (unblocks frontend T32)

**(1)** EDIT `apps/monitoring/views.py`, add below `sync_harga_apply`:

```python
def sync_history_index(request):
    def load():
        from apps.core.models import SyncRun
        rows = []
        for run in SyncRun.objects.prefetch_related("items")[:100]:
            rows.append({
                "id": run.id,
                "created_at": run.created_at.strftime("%Y-%m-%d %H:%M"),
                "user": run.username or "—",
                "src": run.src_name,
                "dst": run.dst_name,
                "mode": run.mode,
                "total_items": run.total_items,
                "status": run.status,
                "items": [
                    {"nama_barang": it.nama_barang, "kd_satuan": it.kd_satuan,
                     "harga_lama_dst": it.harga_lama_dst, "harga_baru": it.harga_baru}
                    for it in run.items.all()
                ],
            })
        return {"rows": rows, "conn_error": None}  # SQLite — no MSSQL involved

    return render(request, "Admin/MasterData/SyncHistory", props={"data": defer(load)})
```

**(2)** urls.py, below `master/sync-harga/apply`:

```python
    path("master/sync-history", views.sync_history_index, name="sync_history"),
```

**DoD:** `python manage.py check` passes; the page lists runs with nested items.

## SECTION 7 — MENUS & LOGS

### - [ ] B26 — EDIT `apps/core/menus.py` (2 new menu keys)

Insert below the `sync_harga` entry in `ALL_MENUS`:

```python
    {"key": "supplier", "label": "Master Supplier", "icon": "truck", "href": "/admin-panel/master/suppliers", "section": "master"},
    {"key": "sync_history", "label": "Riwayat Sync", "icon": "clock", "href": "/admin-panel/master/sync-history", "section": "master"},
```

**DoD:** `python manage.py check` passes; both items appear under "Master Data" in the sidebar (admins with no explicit menu config get all assignable menus by default). **Unblocks frontend T28/T32 navigation.**

### - [ ] B27 — Log Aktivitas: filters + export (unblocks frontend T30)

**(1)** EDIT `apps/monitoring/views.py`: REPLACE the whole `logs_index` function with:

```python
def _logs_queryset(request):
    qs = ActivityLog.objects.all()
    aksi = (request.GET.get("aksi") or "").strip()
    user = (request.GET.get("user") or "").strip()
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    if aksi:
        qs = qs.filter(action__icontains=aksi)
    if user:
        qs = qs.filter(username=user)
    if date_from:
        qs = qs.filter(timestamp__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__lte=_eod(date_to))
    return qs


def _log_dict(a):
    return {
        "id": a.id,
        "user": a.username or "—",
        "action": a.action,
        "detail": a.detail,
        "ip_address": a.ip_address or "",
        "timestamp": a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }


def logs_index(request):
    logs = [_log_dict(a) for a in _logs_queryset(request)[:300]]
    action_types = sorted(set(ActivityLog.objects.values_list("action", flat=True)))
    users = sorted({u for u in ActivityLog.objects.values_list("username", flat=True) if u})
    return render(
        request,
        "Admin/ActivityLogs",
        props={
            "logs": logs,
            "action_types": action_types,
            "users": users,
            "filters": {
                "aksi": request.GET.get("aksi", ""),
                "user": request.GET.get("user", ""),
                "date_from": request.GET.get("date_from", ""),
                "date_to": request.GET.get("date_to", ""),
            },
        },
    )


LOG_COLUMNS = [
    {"key": "timestamp", "label": "Waktu"},
    {"key": "user", "label": "User"},
    {"key": "action", "label": "Aksi"},
    {"key": "detail", "label": "Detail"},
    {"key": "ip_address", "label": "IP"},
]


def logs_export(request):
    rows = [_log_dict(a) for a in _logs_queryset(request)[:reporting.EXPORT_CAP]]
    return reporting.xlsx_response("log-aktivitas", LOG_COLUMNS, rows)
```

**(2)** urls.py, below the `logs` path:

```python
    path("logs/export", views.logs_export, name="logs_export"),
```

**DoD:** `python manage.py check` passes; `/admin-panel/logs?aksi=sync` filters; export downloads the filtered set.

## SECTION 8 — FINAL VERIFICATION

### - [ ] B28 — Verification checklist (run everything)

1. `python manage.py check` — clean.
2. `python manage.py migrate` — applied (includes the B23 `core` migration).
3. `python manage.py test` — passes.
4. `python manage.py check_stock_agg` — passes (movement engine untouched).
5. `grep -rn "_mock_page" apps/` — the only hit should be the (now unused) factory in `apps/monitoring/views.py`. **Delete the `_mock_page` function**, then re-run `python manage.py check`; the grep must return 0 hits.
6. Index registry: on the dev connection run `python manage.py ensure_indexes` — every B3 index reports "sudah ada" or "OK" (detail-table failures with error 1935 are expected and logged, not fatal).
7. Smoke test in Mode B (`DJANGO_VITE_DEV=0`, `npm run build`, `runserver 0.0.0.0:8000`) for EVERY page in R3: skeleton first, then data; filter + Tampilkan reloads with query params in the URL; sort + pagination fire new requests; Export downloads an `.xlsx` honoring filters; with the active connection stopped, the page still renders and shows the Indonesian error banner.
8. **Number verification against the legacy app** (these three carry unverified business semantics — record findings in the task blocks above):
   - PenjualanNota: `total_bersih` of one real nota (R4.1 header formula).
   - Kas Harian: `saldo_akhir` for one day (the "sales into cash drawer" arm).
   - Opname: `qty_sistem`/`qty_fisik` of one opname row (the t_opname_proses OUTER APPLY mapping).
9. Mark every finished task `- [x]` in this file.

**Done means:** all mock report pages serve real MS SQL data through the deferred contract, exports work, sync runs are audited, and the three flagged numbers match the legacy application.


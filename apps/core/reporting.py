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

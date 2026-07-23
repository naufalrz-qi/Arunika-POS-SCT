"""Audit: setiap SUMMARY_* laporan == agregasi ulang baris-barisnya di Python.

Menangkap summary yang "belum pas" — angka ringkasan yang tak cocok dengan data
baris yang sebenarnya ditampilkan (mis. beda grain akibat JOIN fan-out, COUNT
DISTINCT beda collation, penanganan NULL, dsb).

Jalan atas koneksi aktif; untuk tiap report spec generik (_report_view) di
apps/monitoring/views.py, materialisasi satu iris (TOP N, jendela uji 1 bulan),
lalu bandingkan:
  (a) SELECT {SUMMARY_*} FROM (iris) q      — jalur produksi
  (b) agregasi ulang baris (a) di Python    — referensi independen
Selisih dilaporkan. Iris (bukan full set) supaya aman di tabel besar; karena (a)
dan (b) dihitung atas iris yang SAMA, cek tetap sahih.

    python manage.py check_report_summaries
    python manage.py check_report_summaries --self-test   # cek parser, tanpa DB
    python manage.py check_report_summaries --days 30 --top 50000

Catatan: mode "100 data terbaru" (first load) memang menghitung summary hanya
atas 100 baris ter-cap (bukan seluruh periode) — itu perilaku by-design di
views.py, bukan yang diaudit di sini. Command ini mengaudit kebenaran agregasi
summary terhadap barisnya, bukan cakupan first-load.
"""
import datetime as dt
import re

from django.core.management.base import BaseCommand, CommandError

REQUIRED_SPEC_KEYS = {"inner", "summary", "sorts", "default_sort"}

# Satu term summary -> (kind, col, alias). kind: "count_all" | "count_distinct" | "sum".
_RE_COUNT_ALL = re.compile(r"COUNT\(\s*\*\s*\)\s+AS\s+(\w+)", re.I)
_RE_COUNT_DISTINCT = re.compile(r"COUNT\(\s*DISTINCT\s+(?:q\.)?(\w+)\s*\)\s+AS\s+(\w+)", re.I)
_RE_SUM = re.compile(r"SUM\(\s*(?:q\.)?(\w+)\s*\).*?AS\s+(\w+)", re.I | re.S)


def _split_terms(summary: str):
    """Pisah select-list summary di koma level-atas (abaikan koma dalam kurung)."""
    terms, depth, start = [], 0, 0
    for i, ch in enumerate(summary):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            terms.append(summary[start:i])
            start = i + 1
    terms.append(summary[start:])
    return [t.strip() for t in terms if t.strip()]


def parse_summary_terms(summary: str):
    """['COUNT(*) AS jml_baris', 'COALESCE(SUM(q.qty),0) AS total_qty', ...]
    -> [('count_all', None, 'jml_baris'), ('sum', 'qty', 'total_qty'), ...]."""
    out = []
    for term in _split_terms(summary):
        m = _RE_COUNT_ALL.search(term)
        if m:
            out.append(("count_all", None, m.group(1)))
            continue
        m = _RE_COUNT_DISTINCT.search(term)
        if m:
            out.append(("count_distinct", m.group(1), m.group(2)))
            continue
        m = _RE_SUM.search(term)
        if m:
            out.append(("sum", m.group(1), m.group(2)))
            continue
        # Term tak dikenal -> lewati (dilaporkan sebagai un-parsed).
        out.append(("unknown", None, term))
    return out


def _norm_key(v):
    """Samakan dgn semantik SQL Server: CI + abaikan spasi ekor untuk string."""
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip().casefold()
    return v


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def py_aggregate(terms, rows):
    """Hitung nilai referensi tiap alias dari daftar baris (dict)."""
    ref = {}
    for kind, col, alias in terms:
        if kind == "count_all":
            ref[alias] = len(rows)
        elif kind == "count_distinct":
            ref[alias] = len({_norm_key(r.get(col)) for r in rows if r.get(col) is not None})
        elif kind == "sum":
            ref[alias] = sum(_num(r.get(col)) for r in rows)
        # unknown -> tak dihitung
    return ref


def _self_test():
    cases = [
        ("COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, "
         "COALESCE(SUM(q.subtotal), 0) AS total_nilai",
         [("count_all", None, "jml_baris"), ("sum", "qty", "total_qty"),
          ("sum", "subtotal", "total_nilai")]),
        ("COUNT(DISTINCT q.kd_customer) AS jml_customer, "
         "COALESCE(SUM(q.jml_nota), 0) AS total_nota, COALESCE(SUM(q.total), 0) AS total_nilai",
         [("count_distinct", "kd_customer", "jml_customer"),
          ("sum", "jml_nota", "total_nota"), ("sum", "total", "total_nilai")]),
        ("COUNT(DISTINCT kd_barang) AS jml_barang, COALESCE(SUM(qty_terjual), 0) AS total_qty, "
         "COALESCE(SUM(nilai), 0) AS total_nilai",
         [("count_distinct", "kd_barang", "jml_barang"), ("sum", "qty_terjual", "total_qty"),
          ("sum", "nilai", "total_nilai")]),
    ]
    for summary, expected in cases:
        got = parse_summary_terms(summary)
        assert got == expected, f"\n  expected {expected}\n  got      {got}"
    # Agregasi
    rows = [{"qty": 2, "subtotal": 10.0}, {"qty": 3, "subtotal": 5.5}]
    terms = parse_summary_terms("COUNT(*) AS n, COALESCE(SUM(q.qty),0) AS tq, SUM(q.subtotal) AS ts")
    ref = py_aggregate(terms, rows)
    assert ref == {"n": 2, "tq": 5.0, "ts": 15.5}, ref
    # CI distinct
    terms2 = parse_summary_terms("COUNT(DISTINCT q.k) AS d")
    ref2 = py_aggregate(terms2, [{"k": "AB "}, {"k": "ab"}, {"k": None}])
    assert ref2 == {"d": 1}, ref2


class Command(BaseCommand):
    help = "Audit tiap SUMMARY_* laporan vs agregasi ulang baris-barisnya (koneksi aktif)."

    def add_arguments(self, parser):
        parser.add_argument("--self-test", action="store_true", help="Cek parser saja, tanpa DB.")
        parser.add_argument("--days", type=int, default=30, help="Lebar jendela uji (hari).")
        parser.add_argument("--top", type=int, default=50000, help="Batas baris materialisasi per report.")

    def handle(self, *args, **options):
        if options["self_test"]:
            _self_test()
            self.stdout.write(self.style.SUCCESS("Self-test parser OK."))
            return

        from core import mssql
        from apps.core import reporting
        import apps.monitoring.views as views
        from django.test import RequestFactory

        specs = {
            name: obj
            for name, obj in vars(views).items()
            if isinstance(obj, dict) and REQUIRED_SPEC_KEYS <= set(obj.keys())
        }
        if not specs:
            raise CommandError("Tidak ada report spec ditemukan di apps.monitoring.views.")

        profile = mssql.get_active_profile()
        if not profile:
            raise CommandError("Tidak ada koneksi aktif.")

        top = options["top"]
        date_to = dt.date.today()
        date_from = date_to - dt.timedelta(days=options["days"])
        rf = RequestFactory()
        req = rf.get("/", {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})

        total_bad, checked, skipped = 0, 0, []
        with mssql.cursor(profile) as cur:
            for name in sorted(specs):
                spec = specs[name]
                terms = parse_summary_terms(spec["summary"])
                unknown = [a for k, _, a in terms if k == "unknown"]
                try:
                    f = reporting.parse_report_params(req, spec["sorts"], spec["default_sort"])
                    inner, params = spec["inner"](f)
                    capped = f"SELECT TOP {top} * FROM ({inner}) AS q ORDER BY {f['order_by']}"
                    cur.execute(f"SELECT * FROM ({capped}) AS q", params)
                    rows = reporting.clean_rows(reporting.dictify(cur))
                    cur.execute(f"SELECT {spec['summary']} FROM ({capped}) AS q", params)
                    sql_sum = reporting.clean_rows(reporting.dictify(cur))[0]
                except Exception as exc:  # noqa: BLE001 — satu report gagal jangan hentikan audit
                    skipped.append((name, str(exc).splitlines()[-1][:120]))
                    continue

                checked += 1
                ref = py_aggregate(terms, rows)
                capped_note = " [iris penuh TOP, mungkin terpotong]" if len(rows) >= top else ""
                diffs = []
                for _, _, alias in terms:
                    if alias not in ref:
                        continue
                    a, b = _num(sql_sum.get(alias)), _num(ref.get(alias))
                    if abs(a - b) > 0.01:
                        diffs.append(f"    {alias}: sql={sql_sum.get(alias)} py={ref.get(alias)}")
                if diffs or unknown:
                    total_bad += len(diffs)
                    self.stderr.write(self.style.WARNING(f"[{name}] {len(rows)} baris{capped_note}"))
                    for d in diffs:
                        self.stderr.write(d)
                    if unknown:
                        self.stderr.write(f"    term tak terparse: {unknown}")
                else:
                    self.stdout.write(f"OK [{name}] {len(rows)} baris{capped_note}")

        for name, err in skipped:
            self.stdout.write(self.style.NOTICE(f"SKIP [{name}]: {err}"))
        msg = f"Audit selesai: {checked} report dicek, {total_bad} selisih, {len(skipped)} dilewati."
        if total_bad:
            raise CommandError(msg)
        self.stdout.write(self.style.SUCCESS(msg))

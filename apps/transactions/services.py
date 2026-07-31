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
from apps.transactions.reports import _line_net


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

        # Fast movers bulan berjalan (top 10 by qty). Barang tanpa harga jual di
        # master (kresek/packaging) dikecualikan — filter EXISTS yang sama dgn
        # FMI Penjualan (apps/transactions/reports.py::fmi_penjualan). Nilai =
        # Nilai pakai _line_net() langsung — dulu formulanya disalin tangan ke
        # sini sbg pengurangan flat, jadi ikut salah utk diskon fraksi.
        month_start = dt.datetime(day.year, day.month, 1)
        cur.execute(
            "SELECT TOP 10 b.kd_barang, b.nama, SUM(d.qty) AS qty_terjual, "
            f"SUM({_line_net('harga_jual')}) AS nilai "
            "FROM t_penjualan_detail d "
            "JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
            "JOIN m_barang b ON d.kd_barang = b.kd_barang "
            "WHERE h.tanggal >= ? AND h.tanggal < ? "
            "AND EXISTS (SELECT 1 FROM m_barang_satuan bs "
            "WHERE bs.kd_barang = b.kd_barang AND bs.harga_jual > 0) "
            "GROUP BY b.kd_barang, b.nama "
            "ORDER BY SUM(d.qty) DESC",
            [month_start, end],
        )
        fast_movers = [
            {
                "kd_barang": (r["kd_barang"] or "").strip(),
                "nama": (r["nama"] or "").strip(),
                "qty": round(_f(r["qty_terjual"])),
                "nilai": round(_f(r["nilai"])),
            }
            for r in _dictify(cur)
        ]

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
        "fast_movers": fast_movers,
    }



# --- Klasifikasi Pelanggan: payload kolumnar -------------------------------

# Kolom & urutannya dinyatakan eksplisit, tidak diturunkan dari rows[0]: saat
# hasil query kosong, bentuk turunan itu menghasilkan payload tanpa kolom sama
# sekali, dan dropdown saringan di klien jadi kosong tanpa gejala lain.
KLASIFIKASI_COLS = [
    "kd_customer", "customer", "hp", "telepon", "kota",
    "segmen", "segmen_urut", "tier_nilai",
    "jml_nota", "total_belanja", "rata_nota",
    "nota_pertama", "nota_terakhir", "jeda_hari", "umur_hari",
]


def klasifikasi_kolumnar(profile, f) -> dict:
    """Seluruh baris klasifikasi pelanggan dalam bentuk kolom-mayor.

    Halaman ini mengirim SATU payload berisi semua pelanggan supaya pencarian
    dan pengurutan terjadi di peramban tanpa bolak-balik ke server. Aman di sini
    karena setelah UMUM/ECERAN/OBRAL dikeluarkan, profil terbesar hanya
    menyisakan ~4.800 pelanggan — dua orde lebih kecil dari katalog Stok Akhir
    (55rb baris) yang melahirkan bentuk kolumnar ini.

    Ambang segmen TIDAK bisa dihitung ulang di klien: ia bagian dari SQL, dan
    menduplikasinya ke JavaScript berarti dua definisi yang bisa menyimpang —
    termasuk menyimpang dari file Excel, yang tetap dibuat server.
    """
    from apps.inventory.services import _kolumnar  # kamus + tipe kolom, satu definisi
    from apps.transactions import reports as rpt

    inner, params = rpt.klasifikasi_pelanggan(f)
    with mssql.report_cursor(profile) as cur:
        cur.execute(f"SELECT * FROM ({inner}) AS q ORDER BY q.segmen_urut, q.customer", params)
        rows = _dictify(cur)

    # Decimal/datetime -> float/str sebelum masuk kamus: keduanya tak bisa
    # di-JSON-kan, dan _kolumnar menilai bentuk kolom dari tipe Python-nya.
    from apps.core.reporting import clean_rows
    return _kolumnar(clean_rows(rows), KLASIFIKASI_COLS)

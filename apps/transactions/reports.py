"""Report SQL builders (server-side report pages, PRD §6).

Each report contributes:
- `<name>(f)`      -> (inner_sql, params): full SELECT without ORDER BY
- `SORTS_<NAME>`   -> whitelist {sort param: output alias} for ORDER BY
- `SUMMARY_<NAME>` -> select list for aggregates (jml_baris, total_qty, total_nilai)
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


HDR_FACTOR = (
    "(1 - COALESCE(h.diskon1, 0) / 100.0)"
    " * (1 - COALESCE(h.diskon2, 0) / 100.0)"
    " * (1 - COALESCE(h.diskon3, 0) / 100.0)"
    " * (1 - COALESCE(h.diskon4, 0) / 100.0)"
)


def _search(where: list, params: list, f: dict, cols: list) -> None:
    """Append LIKE clause when f['search'] is set."""
    if f["search"]:
        like = " OR ".join(f"{c} LIKE ?" for c in cols)
        where.append(f"({like})")
        params.extend([f"%{f['search']}%"] * len(cols))


def _nota_net(where_sql: str) -> str:
    """Per-nota subquery: header net total per R4.1."""
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


# --- Penjualan Detail (B5) ---

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


# --- Penjualan per Nota (B8) --

SORTS_PENJUALAN_NOTA = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "total_bersih": "total_bersih"}
SUMMARY_PENJUALAN_NOTA = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.total_kotor), 0) AS total_kotor, "
    "COALESCE(SUM(q.potongan), 0) AS total_potongan, COALESCE(SUM(q.pajak), 0) AS total_pajak, "
    "COALESCE(SUM(q.total_bersih), 0) AS total_bersih"
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


# --- Penjualan per Customer (B9) --

SORTS_PENJUALAN_CUSTOMER = {"customer": "customer", "jml_nota": "jml_nota", "total": "total"}
SUMMARY_PENJUALAN_CUSTOMER = (
    "COUNT(DISTINCT q.kd_customer) AS jml_customer, COALESCE(SUM(q.jml_nota), 0) AS total_nota, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)

def penjualan_customer(f):
    where, params = _base_where(f)
    if f["search"]:
        where.append("c.nama LIKE ?")
        params.append(f"%{f['search']}%")
    inner = (
        "SELECT n.kd_customer, COALESCE(c.nama, '') AS customer, "
        "COUNT(n.no_transaksi) AS jml_nota, COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "GROUP BY n.kd_customer, c.nama"
    )
    return inner, params


# --- Penjualan per User (B10) --

SORTS_PENJUALAN_USER = {"user": "[user]", "jml_nota": "jml_nota", "total": "total"}
SUMMARY_PENJUALAN_USER = (
    "COUNT(DISTINCT q.kd_user) AS jml_user, COALESCE(SUM(q.jml_nota), 0) AS total_nota, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)

def penjualan_user(f):
    # kd_user is a legacy kasir code (t_penjualan.kd_user); there is no
    # matching master table on the MS SQL side (apps_user is Django/SQLite,
    # a different database — never joinable from this connection).
    where, params = _base_where(f)
    inner = (
        "SELECT RTRIM(n.kd_user) AS [user], n.kd_user, "
        "COUNT(n.no_transaksi) AS jml_nota, COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "GROUP BY n.kd_user"
    )
    return inner, params


# --- Penjualan per Periode (B11) --

SORTS_PENJUALAN_PERIODE = {"periode": "periode", "total": "total"}
SUMMARY_PENJUALAN_PERIODE = (
    "COUNT(DISTINCT q.periode) AS jml_periode, COALESCE(SUM(q.jml_nota), 0) AS total_nota, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)

def penjualan_periode(f):
    where, params = _base_where(f)
    granul = f.get("granularitas", "harian")
    if granul == "bulanan":
        periode = "FORMAT(n.tanggal, 'yyyy-MM')"
    else:
        periode = "FORMAT(n.tanggal, 'yyyy-MM-dd')"
    inner = (
        f"SELECT {periode} AS periode, COUNT(n.no_transaksi) AS jml_nota, "
        "COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        f"GROUP BY {periode}"
    )
    return inner, params


# --- Retur Penjualan (B12) --

SORTS_RETUR_PENJUALAN = {"no_retur": "no_retur", "tanggal": "tanggal", "nilai": "nilai"}
SUMMARY_RETUR_PENJUALAN = (
    "COUNT(*) AS jml_retur, COALESCE(SUM(q.qty), 0) AS total_qty, COALESCE(SUM(q.nilai), 0) AS total_nilai"
)

def retur_penjualan(f):
    where, params = _base_where(f, "h.tanggal", "h.kd_divisi")
    if f.get("kd_customer"):
        where.append("h.kd_customer = ?")
        params.append(f["kd_customer"])
    _search(where, params, f, ["h.no_retur", "b.nama", "c.nama"])
    inner = (
        "SELECT h.no_retur, h.tanggal, COALESCE(c.nama, '') AS customer, "
        "b.nama AS barang, d.qty, "
        f"{_line_net('harga_jual', 'd')} AS nilai "
        "FROM t_penjualan_retur h "
        "INNER JOIN t_penjualan_retur_detail d ON h.no_retur = d.no_retur "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_customer c ON h.kd_customer = c.kd_customer "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Pembelian (B13) --

SORTS_PEMBELIAN = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "subtotal": "subtotal"}
SUMMARY_PEMBELIAN = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, COALESCE(SUM(q.subtotal), 0) AS total_nilai"
)

def pembelian(f):
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_transaksi", "b.nama", "s.nama"])
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(s.nama, '') AS supplier, "
        "b.nama AS barang, d.qty, d.harga_beli AS harga, "
        f"(d.qty * d.harga_beli) AS subtotal "
        "FROM t_pembelian h "
        "INNER JOIN t_pembelian_detail d ON h.no_transaksi = d.no_transaksi "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_supplier s ON h.kd_supplier = s.kd_supplier "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Retur Pembelian (B14) --

SORTS_RETUR_PEMBELIAN = {"no_retur": "no_retur", "tanggal": "tanggal", "nilai": "nilai"}
SUMMARY_RETUR_PEMBELIAN = (
    "COUNT(*) AS jml_retur, COALESCE(SUM(q.qty), 0) AS total_qty, COALESCE(SUM(q.nilai), 0) AS total_nilai"
)

def retur_pembelian(f):
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_retur", "b.nama", "s.nama"])
    inner = (
        "SELECT h.no_retur, h.tanggal, COALESCE(s.nama, '') AS supplier, "
        "b.nama AS barang, d.qty, "
        f"(d.qty * d.harga) AS nilai "
        "FROM t_pembelian_retur h "
        "INNER JOIN t_pembelian_retur_detail d ON h.no_retur = d.no_retur "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_supplier s ON h.kd_supplier = s.kd_supplier "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Opname Stok (B15) --

SORTS_OPNAME = {"kd_barang": "kd_barang", "tanggal": "tanggal", "diferensi": "diferensi"}
SUMMARY_OPNAME = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty_fisik), 0) AS total_fisik, COALESCE(SUM(q.diferensi), 0) AS total_diferensi"
)

def opname(f):
    where, params = _base_where(f)
    _search(where, params, f, ["b.kd_barang", "b.nama"])
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(dv.nama, '') AS divisi, h.kd_barang, b.nama AS barang, "
        "CASE WHEN h.status=2 THEN 0 ELSE h.qty END AS qty_sistem, "
        "CASE WHEN h.status=2 THEN h.qty ELSE 0 END AS qty_fisik, "
        "CASE WHEN h.status=2 THEN h.qty ELSE -h.qty END AS diferensi "
        "FROM t_opname_stok h "
        "INNER JOIN m_barang b ON h.kd_barang = b.kd_barang "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Kas Harian (B16) --
# t_arus_kas doesn't exist. Real cash-affecting sources: t_penambahan_kas
# (top-up), t_pendapatan (revenue), t_biaya_operasional (expense), t_mutasi_kas
# (transfer between two kas accounts — sumber=out, tujuan=in), and cash sales
# (t_penjualan where kd_kas is filled). `saldo` is a running balance across
# the WHOLE selected range, so this can't use the generic run_paged/_report_view
# pagination (SQL OFFSET/FETCH would break the running total across pages) —
# see kas_harian_rows() below, called directly from a bespoke view.

SORTS_KAS = {"tanggal": "tanggal"}  # only sort supported — saldo needs chronological order


def _kas_union(pred: str) -> str:
    """UNION of every cash-affecting source, uniform columns:
    tanggal, kd_kas, keterangan, masuk, keluar.

    `pred` is a date predicate template like "{col} >= ? AND {col} <= ?" —
    applied to each of the 6 arms, so callers pass the SAME param tuple once
    PER ARM (6x)."""
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


def kas_harian_rows(cur, f):
    """Rows (chronological, with running `saldo` per kd_kas) + summary dict.

    Caller (apps/monitoring/views.py) owns pagination: slice the returned
    rows in Python after this, and reverse for sort_dir=desc.
    """
    from apps.inventory.services import _k

    period_sql = _kas_union("{col} >= ? AND {col} <= ?")
    pre_sql = (
        "SELECT RTRIM(kd_kas) AS kd_kas, SUM(masuk) - SUM(keluar) AS net "
        "FROM (" + _kas_union("{col} < ?") + ") u GROUP BY kd_kas"
    )

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

    if f.get("sort_dir") == "desc":
        rows = rows[::-1]
    for i, r in enumerate(rows):
        r["_rid"] = i + 1

    summary = {
        "jml_baris": len(rows),
        "saldo_awal": round(saldo_awal, 2),
        "total_masuk": round(total_masuk, 2),
        "total_keluar": round(total_keluar, 2),
        "saldo_akhir": round(saldo_awal + total_masuk - total_keluar, 2),
    }
    return rows, summary


# --- Shift / Pegawai Ganti Shift (B17) --
# t_pegawai_ganti_shift is header-only (no_transaksi, tanggal, keterangan,
# kd_user) — kd_pegawai/kd_shift live on the separate _detail table, one row
# per employee assigned in that shift change.

SORTS_SHIFT = {"tanggal": "tanggal", "pegawai": "pegawai", "shift": "shift"}
SUMMARY_SHIFT = (
    "COUNT(*) AS jml_baris, COUNT(DISTINCT pegawai) AS jml_pegawai, COUNT(DISTINCT shift) AS jml_shift"
)

def shift(f):
    where, params = _base_where(f)
    _search(where, params, f, ["p.nama"])
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(p.nama, '') AS pegawai, d.kd_shift AS shift, "
        "COALESCE(h.keterangan, '') AS keterangan "
        "FROM t_pegawai_ganti_shift h "
        "INNER JOIN t_pegawai_ganti_shift_detail d ON h.no_transaksi = d.no_transaksi "
        "LEFT JOIN m_pegawai p ON d.kd_pegawai = p.kd_pegawai "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Promo & Diskon (B18) --
# m_promo doesn't exist — real tables are m_barang_promo (header) +
# m_barang_promo_detail (per-barang price); flag_aktif doesn't exist either,
# status is derived from the date range. detail.harga is char — use
# harga_bersih (numeric) instead.

SORTS_PROMO = {"kd_promo": "kd_promo", "barang": "barang", "harga_promo": "harga_promo", "tanggal_awal": "tanggal_awal"}
SUMMARY_PROMO = "COUNT(*) AS jml_baris, COUNT(DISTINCT kd_barang) AS jml_barang"

def promo(f):
    where = ["1=1"]
    params = []
    if f.get("date_from"):
        where.append("h.tanggal_awal >= ?")
        params.append(f["date_from"])
    if f.get("date_to"):
        where.append("h.tanggal_akhir <= ?")
        params.append(f["date_to"])
    _search(where, params, f, ["h.kd_promo", "b.nama"])
    inner = (
        "SELECT h.kd_promo, d.kd_barang, COALESCE(dv.nama, RTRIM(h.kd_divisi)) AS divisi, b.nama AS barang, "
        "d.harga_bersih AS harga_promo, h.tanggal_awal, h.tanggal_akhir, "
        "CASE WHEN GETDATE() < h.tanggal_awal THEN 'Terjadwal' "
        "WHEN GETDATE() > h.tanggal_akhir THEN 'Berakhir' ELSE 'Aktif' END AS status "
        "FROM m_barang_promo h "
        "INNER JOIN m_barang_promo_detail d ON h.kd_promo = d.kd_promo "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Voucher (B19) --
# m_voucher has no validity dates/active flag (just kd_voucher/nama/nominal/
# keterangan/status) — "dipakai"/"nilai_dipakai" are derived from usage on
# t_penjualan.kd_voucher (all-time; this page has no date filter, PRD table).

SORTS_VOUCHER = {"kd_voucher": "kd_voucher", "nama": "nama", "nominal": "nominal", "dipakai": "dipakai"}
SUMMARY_VOUCHER = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(nominal), 0) AS total_nominal, "
    "COALESCE(SUM(dipakai), 0) AS total_dipakai, COALESCE(SUM(nilai_dipakai), 0) AS total_nilai_dipakai"
)

def voucher(f):
    where = ["1=1"]
    params = []
    _search(where, params, f, ["v.kd_voucher", "v.nama"])
    inner = (
        "SELECT RTRIM(v.kd_voucher) AS kd_voucher, v.nama, v.nominal, "
        "COALESCE(u.dipakai, 0) AS dipakai, COALESCE(u.dipakai, 0) * v.nominal AS nilai_dipakai, "
        "CASE WHEN v.status <> 0 THEN 'Aktif' ELSE 'Nonaktif' END AS status "
        "FROM m_voucher v "
        "LEFT JOIN (SELECT kd_voucher, COUNT(*) AS dipakai FROM t_penjualan "
        "WHERE LTRIM(RTRIM(COALESCE(kd_voucher, ''))) <> '' GROUP BY kd_voucher) u "
        "ON RTRIM(v.kd_voucher) = RTRIM(u.kd_voucher) "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- FMI Penjualan (B20) - Fast Moving Items by quantity sold --

SORTS_FMI_PENJUALAN = {"qty_terjual": "qty_terjual", "nilai": "nilai", "kelas": "kelas"}
SUMMARY_FMI_PENJUALAN = (
    "COUNT(DISTINCT kd_barang) AS jml_barang, COALESCE(SUM(qty_terjual), 0) AS total_qty, COALESCE(SUM(nilai), 0) AS total_nilai"
)

def fmi_penjualan(f):
    where, params = _base_where(f)
    inner = (
        "SELECT b.kd_barang, b.nama AS barang, COALESCE(k.nama, '') AS kategori, "
        "COALESCE(SUM(d.qty), 0) AS qty_terjual, COALESCE(SUM(d.qty * d.harga_jual * (1-COALESCE(d.diskon1,0)/100.0)), 0) AS nilai, "
        "CASE WHEN COALESCE(SUM(d.qty), 0) > 100 THEN 'A' WHEN COALESCE(SUM(d.qty), 0) > 50 THEN 'B' ELSE 'C' END AS kelas "
        "FROM m_barang b "
        "LEFT JOIN m_kategori k ON b.kd_kategori = k.kd_kategori "
        "LEFT JOIN t_penjualan_detail d ON b.kd_barang = d.kd_barang "
        "LEFT JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
        f"WHERE 1=1 {' AND ' + ' AND '.join(where) if where else ''} "
        "GROUP BY b.kd_barang, b.nama, k.nama"
    )
    return inner, params


# --- FMI Stok (B21) - Stock velocity analysis --
# t_stok doesn't exist and m_barang has no harga_beli column. Real live stock
# snapshot is m_barang_stok_akhir (kd_divisi, kd_barang, stok_akhir); cost
# price comes from m_barang_divisi.harga_beli_awal (same fallback used by
# apps/inventory/services.py's _purchase_prices). The stock snapshot itself
# is point-in-time (no tanggal column), but "terjual"/"rasio"/"status" are
# computed against how much sold in the requested date_from-date_to window,
# to give an actual velocity read instead of a bare in-stock/out-of-stock flag.

_FMI_STOK_KRITIS_HARI = 7      # < this many days of stock left at current pace -> Kritis
_FMI_STOK_OVERSTOCK_HARI = 90  # > this many days of stock left (or never sold) -> Overstock

SORTS_FMI_STOK = {"qty_stok": "qty_stok", "nilai_stok": "nilai_stok", "terjual": "terjual", "rasio": "rasio"}
SUMMARY_FMI_STOK = (
    "COUNT(DISTINCT kd_barang) AS jml_barang, COALESCE(SUM(qty_stok), 0) AS total_qty, "
    "COALESCE(SUM(nilai_stok), 0) AS total_nilai, COALESCE(SUM(terjual), 0) AS total_terjual"
)

def fmi_stok(f):
    where, params = ["1=1"], []
    if f.get("kd_divisi"):
        where.append("s.kd_divisi = ?")
        params.append(f["kd_divisi"])
    _search(where, params, f, ["b.kd_barang", "b.nama"])

    days = max((f["date_to"].date() - f["date_from"].date()).days + 1, 1)
    sold_params = [f["date_from"], f["date_to"]]

    base = (
        "SELECT b.kd_barang, b.nama AS barang, COALESCE(k.nama, '') AS kategori, "
        "COALESCE(SUM(s.stok_akhir), 0) AS qty_stok, "
        "COALESCE(SUM(s.stok_akhir * bd.harga_beli_awal), 0) AS nilai_stok, "
        "COALESCE(MAX(sold.terjual), 0) AS terjual "
        "FROM m_barang b "
        "LEFT JOIN m_kategori k ON b.kd_kategori = k.kd_kategori "
        "LEFT JOIN m_barang_stok_akhir s ON b.kd_barang = s.kd_barang "
        "LEFT JOIN m_barang_divisi bd ON s.kd_barang = bd.kd_barang AND s.kd_divisi = bd.kd_divisi "
        "LEFT JOIN (SELECT d.kd_barang, SUM(d.qty) AS terjual FROM t_penjualan_detail d "
        "INNER JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
        "WHERE h.tanggal >= ? AND h.tanggal <= ? GROUP BY d.kd_barang) sold ON b.kd_barang = sold.kd_barang "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY b.kd_barang, b.nama, k.nama"
    )
    inner = (
        "SELECT x.*, ROUND(x.terjual / NULLIF(x.qty_stok, 0), 2) AS rasio, "
        "CASE "
        "WHEN x.terjual = 0 AND x.qty_stok > 0 THEN 'Overstock' "
        f"WHEN x.terjual > 0 AND x.qty_stok / (x.terjual / {days}.0) < {_FMI_STOK_KRITIS_HARI} THEN 'Kritis' "
        f"WHEN x.terjual > 0 AND x.qty_stok / (x.terjual / {days}.0) > {_FMI_STOK_OVERSTOCK_HARI} THEN 'Overstock' "
        "ELSE 'Sehat' END AS status "
        f"FROM ({base}) x"
    )
    return inner, sold_params + params

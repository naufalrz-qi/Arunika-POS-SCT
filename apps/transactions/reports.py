"""Report SQL builders (server-side report pages, PRD §6).

Each report contributes:
- `<name>(f)`      -> (inner_sql, params): full SELECT without ORDER BY
- `SORTS_<NAME>`   -> whitelist {sort param: output alias} for ORDER BY
- `SUMMARY_<NAME>` -> select list for aggregates (jml_baris, total_qty, total_nilai)
"""
import datetime as dt
from apps.core import reporting


def _line_net(price_col: str, alias: str = "d") -> str:
    """qty * (price - d1 - d2 - d3 - d4), NULL-safe.

    diskon1-4 are flat Rupiah-per-unit amounts, not percentages — verified
    against t_penjualan_detail.total on the legacy schema (e.g. harga_jual
    39902.85, diskon1 2.85 -> total 39900; harga_jual 168000, diskon1 26250
    -> total 141750). Treating them as a "1 - d/100" percent factor is wrong
    even for small values, and goes catastrophically negative once diskon1
    exceeds 100 (which happens for ~1% of real rows).
    """
    return (
        f"({alias}.qty * ({alias}.{price_col}"
        f" - COALESCE({alias}.diskon1, 0)"
        f" - COALESCE({alias}.diskon2, 0)"
        f" - COALESCE({alias}.diskon3, 0)"
        f" - COALESCE({alias}.diskon4, 0)))"
    )


HDR_DISKON = (
    "(COALESCE(h.diskon1, 0) + COALESCE(h.diskon2, 0)"
    " + COALESCE(h.diskon3, 0) + COALESCE(h.diskon4, 0))"
)


def _search(where: list, params: list, f: dict, cols: list) -> None:
    """Append LIKE clause when f['search'] is set."""
    if f["search"]:
        like = " OR ".join(f"{c} LIKE ?" for c in cols)
        where.append(f"({like})")
        params.extend([f"%{f['search']}%"] * len(cols))


def _nota_net(where_sql: str) -> str:
    """Per-nota subquery: header net total per R4.1."""
    net = f"SUM({_line_net('harga_jual')}) - {HDR_DISKON} - COALESCE(h.diskon_uang, 0)"
    return (
        "SELECT h.no_transaksi, MIN(h.tanggal) AS tanggal, MIN(h.kd_customer) AS kd_customer, "
        "MIN(h.kd_divisi) AS kd_divisi, MIN(h.status) AS status_raw, MIN(h.kd_voucher) AS kd_voucher, "
        "MIN(h.kd_user) AS kd_user, MIN(h.kd_kas) AS kd_kas, MIN(h.tanggal_jatuh_tempo) AS tanggal_jatuh_tempo, "
        "SUM(d.qty * d.harga_jual) AS total_kotor, "
        f"({net}) * COALESCE(MIN(h.pajak), 0) / 100.0 AS pajak, "
        f"({net}) * (1 + COALESCE(MIN(h.pajak), 0) / 100.0) AS total_bersih "
        "FROM t_penjualan h "
        "INNER JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi "
        f"WHERE {where_sql} "
        "GROUP BY h.no_transaksi, h.diskon1, h.diskon2, h.diskon3, h.diskon4, h.diskon_uang, h.pajak"
    )


def _base_where(f, date_col="h.tanggal", div_col="h.kd_divisi"):
    """Standard date range + optional kd_divisi filter.

    Skips the date predicate entirely when f["skip_date_predicate"] (recent-mode
    first load, PRD advanced-filter feature) — not just a wider range, no date
    filter at all, so the "100 terbaru" cap sees the whole history.
    """
    where, params = [], []
    if not f.get("skip_date_predicate"):
        where = [f"{date_col} >= ?", f"{date_col} <= ?"]
        params = [f["date_from"], f["date_to"]]
    if f.get("kd_divisi"):
        where.append(f"{div_col} = ?")
        params.append(f["kd_divisi"])
    if not where:
        where = ["1=1"]
    return where, params


# --- Penjualan Detail (B5) ---

# GetConvertStatus(@status) legacy UDF, reimplemented per project convention
# (definisi diverifikasi di scripts/output/view_function_definitions_testing.json).
STATUS_PENJUALAN_CASE = "CASE h.status WHEN 0 THEN 'Kredit' WHEN 1 THEN 'Tunai' WHEN 2 THEN 'Lunas' ELSE '' END"

SORTS_PENJUALAN_DETAIL = {
    "no_transaksi": "no_transaksi", "tanggal": "tanggal", "subtotal": "subtotal",
    "divisi": "divisi", "kota": "kota", "kategori": "kategori", "sales": "sales",
}
SUMMARY_PENJUALAN_DETAIL = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, "
    "COALESCE(SUM(q.subtotal), 0) AS total_nilai"
)
FILTERS_PENJUALAN_DETAIL = {
    "no_transaksi": ("no_transaksi", "text"),
    "customer": ("customer", "text"),
    "barang": ("barang", "text"),
    "kd_barang": ("kd_barang", "text"),
    "kategori": ("kategori", "text"),
    "sales": ("sales", "text"),
    "status": ("status", "category"),
    "qty": ("qty", "number_range"),
    "harga": ("harga", "number_range"),
    "subtotal": ("subtotal", "number_range"),
    "jth_tempo": ("jth_tempo", "date"),
}


def penjualan_detail(f):
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_transaksi", "b.nama", "c.nama"])
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(dv.nama, '') AS divisi, "
        "COALESCE(c.nama, '') AS customer, COALESCE(mk.nama, '') AS kota, "
        "h.tanggal_jatuh_tempo AS jth_tempo, "
        f"{STATUS_PENJUALAN_CASE} AS status, COALESCE(h.keterangan, '') AS keterangan, "
        "d.kd_barang, b.nama AS barang, COALESCE(kt.nama, '') AS kategori, "
        "COALESCE(p.nama, '') AS sales, d.qty, COALESCE(st.nama, '') AS satuan, "
        "d.harga_jual AS harga, "
        "COALESCE(d.diskon1, 0) AS dd1, COALESCE(d.diskon2, 0) AS dd2, "
        "COALESCE(d.diskon3, 0) AS dd3, COALESCE(d.diskon4, 0) AS dd4, "
        "COALESCE(h.diskon1, 0) AS dt1, COALESCE(h.diskon2, 0) AS dt2, "
        "COALESCE(h.diskon3, 0) AS dt3, COALESCE(h.diskon4, 0) AS dt4, "
        # Harga Bersih: per-unit price net of item-level diskon1-4 only. Header
        # diskon1-4/pajak are a nota-level adjustment applied once on the SUM
        # (see _nota_net), not something that distributes meaningfully back
        # onto a single line — deliberately not replicated here.
        "(d.harga_jual - COALESCE(d.diskon1, 0) - COALESCE(d.diskon2, 0) "
        "- COALESCE(d.diskon3, 0) - COALESCE(d.diskon4, 0)) AS harga_bersih, "
        f"{_line_net('harga_jual')} AS subtotal "
        "FROM t_penjualan h "
        "INNER JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_customer c ON h.kd_customer = c.kd_customer "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        "LEFT JOIN m_kota mk ON c.kd_kota = mk.kd_kota "
        "LEFT JOIN m_kategori kt ON b.kd_kategori = kt.kd_kategori "
        "LEFT JOIN m_pegawai p ON d.kd_pegawai = p.kd_pegawai "
        "LEFT JOIN m_satuan st ON d.kd_satuan = st.kd_satuan "
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
FILTERS_PENJUALAN_NOTA = {
    "no_transaksi": ("no_transaksi", "text"),
    "customer": ("customer", "text"),
    "total_bersih": ("total_bersih", "number_range"),
}

def penjualan_nota(f):
    where, params = _base_where(f)
    if f.get("kd_customer"):
        where.append("h.kd_customer = ?")
        params.append(f["kd_customer"])
    if f["search"]:
        where.append("h.no_transaksi LIKE ?")
        params.append(f"%{f['search']}%")
    inner = (
        "SELECT n.no_transaksi, n.tanggal, COALESCE(dv.nama, '') AS divisi, "
        "COALESCE(c.nama, '') AS customer, COALESCE(mk.nama, '') AS kota, "
        "n.total_kotor, n.total_kotor - (n.total_bersih - n.pajak) AS potongan, "
        "COALESCE(v.nominal, 0) AS voucher, "
        "n.total_bersih - COALESCE(v.nominal, 0) AS total_setelah_voucher, "
        # Total Pajak2: legacy view derives this from a per-line-distributed
        # header-diskon+pajak formula that doesn't reconcile cleanly with this
        # codebase's header-level model (HDR_DISKON applied once on the nota
        # sum, not per line — see _line_net()/_nota_net() docstrings). Exposed
        # as equal to `pajak` (our already-validated tax-only figure) rather
        # than guessing at the legacy per-line math; verify against real
        # invoices before treating as authoritative.
        "n.pajak AS pajak2, "
        "n.pajak, n.total_bersih, COALESCE(u.nama, '') AS petugas "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "LEFT JOIN m_divisi dv ON n.kd_divisi = dv.kd_divisi "
        "LEFT JOIN m_kota mk ON c.kd_kota = mk.kd_kota "
        "LEFT JOIN m_voucher v ON n.kd_voucher = v.kd_voucher "
        "LEFT JOIN m_userx u ON n.kd_user = u.kd_user"
    )
    return inner, params


# --- Penjualan per Customer (B9) --

SORTS_PENJUALAN_CUSTOMER = {"customer": "customer", "jml_nota": "jml_nota", "total": "total", "divisi": "divisi"}
FILTERS_PENJUALAN_CUSTOMER = {
    "customer": ("customer", "text"),
    "jml_nota": ("jml_nota", "number_range"),
    "total": ("total", "number_range"),
}
SUMMARY_PENJUALAN_CUSTOMER = (
    "COUNT(DISTINCT q.kd_customer) AS jml_customer, COALESCE(SUM(q.jml_nota), 0) AS total_nota, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)

def penjualan_customer(f):
    # search filters c.nama, which only exists AFTER the LEFT JOIN below — it
    # must not be embedded into _nota_net()'s where_sql (that subquery's FROM
    # is t_penjualan/t_penjualan_detail only, no m_customer alias in scope;
    # doing so throws "multi-part identifier 'c.nama' could not be bound"
    # every time a search term is given — a pre-existing bug, fixed here).
    # Grouped by (kd_divisi, kd_customer) — matches mon_t_penjualan_per_customer's
    # actual grain (Divisi is a grouping column there, not a flat extra field);
    # a customer trading in two divisions gets one row per divisi.
    where, params = _base_where(f)
    nota_sql = _nota_net(" AND ".join(where))
    where_outer, params_outer = [], []
    if f["search"]:
        where_outer.append("c.nama LIKE ?")
        params_outer.append(f"%{f['search']}%")
    inner = (
        "SELECT n.kd_customer, COALESCE(c.nama, '') AS customer, "
        "n.kd_divisi, COALESCE(dv.nama, '') AS divisi, "
        "COUNT(n.no_transaksi) AS jml_nota, COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({nota_sql}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "LEFT JOIN m_divisi dv ON n.kd_divisi = dv.kd_divisi "
        + (f"WHERE {' AND '.join(where_outer)} " if where_outer else "")
        + "GROUP BY n.kd_customer, c.nama, n.kd_divisi, dv.nama"
    )
    return inner, params + params_outer


# --- Penjualan per User (B10) --

# Detail per-transaksi, sesuai grain view legacy mon_t_penjualan_per_user (satu
# baris per nota, bukan agregat per user) — m_userx memang ada sebagai master
# table utk kd_user (koreksi asumsi lama bahwa tidak ada tabel master utk ini).
SORTS_PENJUALAN_USER = {
    "no_transaksi": "no_transaksi", "tanggal": "tanggal", "nominal": "nominal",
    "user": "user", "customer": "customer", "divisi": "divisi",
}
SUMMARY_PENJUALAN_USER = (
    "COUNT(*) AS jml_nota, COUNT(DISTINCT q.kd_user) AS jml_user, "
    "COALESCE(SUM(q.nominal), 0) AS total_nilai"
)
FILTERS_PENJUALAN_USER = {
    "no_transaksi": ("no_transaksi", "text"),
    "customer": ("customer", "text"),
    "user": ("user", "text"),
    "status": ("status", "category"),
    "nominal": ("nominal", "number_range"),
}

def penjualan_user(f):
    where, params = _base_where(f)
    inner = (
        "SELECT n.no_transaksi, n.tanggal, COALESCE(dv.nama, '') AS divisi, "
        f"{STATUS_PENJUALAN_CASE.replace('h.status', 'n.status_raw')} AS status, "
        "COALESCE(c.nama, '') AS customer, n.total_bersih AS nominal, "
        "COALESCE(u.nama, RTRIM(n.kd_user)) AS [user], n.kd_user "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "LEFT JOIN m_divisi dv ON n.kd_divisi = dv.kd_divisi "
        "LEFT JOIN m_userx u ON n.kd_user = u.kd_user"
    )
    return inner, params


# --- Penjualan per Periode (B11) --

SORTS_PENJUALAN_PERIODE = {"periode": "periode", "total": "total"}
SUMMARY_PENJUALAN_PERIODE = (
    "COUNT(DISTINCT q.periode) AS jml_periode, COALESCE(SUM(q.jml_nota), 0) AS total_nota, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)

def penjualan_periode(f):
    # Breakdown kotor/diskon/pajak, analog mon_t_penjualan_per_hari. total_kotor
    # and pajak both come straight out of _nota_net(); total_diskon is derived
    # algebraically (total_kotor - (total_bersih - pajak) = the item+header
    # discount taken out before tax) rather than tracked separately — verify
    # against a handful of real notas before treating as final (same caveat as
    # the Total Pajak2 column on Penjualan per Nota).
    where, params = _base_where(f)
    granul = f.get("granularitas", "harian")
    if granul == "bulanan":
        periode = "FORMAT(n.tanggal, 'yyyy-MM')"
    else:
        periode = "FORMAT(n.tanggal, 'yyyy-MM-dd')"
    inner = (
        f"SELECT {periode} AS periode, COUNT(n.no_transaksi) AS jml_nota, "
        "COALESCE(SUM(n.total_kotor), 0) AS total_kotor, "
        "COALESCE(SUM(n.total_kotor) - SUM(n.total_bersih) + SUM(n.pajak), 0) AS total_diskon, "
        "COALESCE(SUM(n.pajak), 0) AS total_pajak, "
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
FILTERS_RETUR_PENJUALAN = {
    "no_retur": ("no_retur", "text"),
    "customer": ("customer", "text"),
    "barang": ("barang", "text"),
    "sales": ("sales", "text"),
    "qty": ("qty", "number_range"),
    "nilai": ("nilai", "number_range"),
}

def retur_penjualan(f):
    where, params = _base_where(f, "h.tanggal", "h.kd_divisi")
    if f.get("kd_customer"):
        where.append("h.kd_customer = ?")
        params.append(f["kd_customer"])
    _search(where, params, f, ["h.no_retur", "b.nama", "c.nama"])
    inner = (
        "SELECT h.no_retur, h.tanggal, h.no_bukti, COALESCE(dv.nama, '') AS divisi, "
        "COALESCE(dv.keterangan, '') AS keterangan_divisi, COALESCE(dv.kepala_nota, '') AS kepala_nota, "
        "COALESCE(c.nama, '') AS customer, b.nama AS barang, COALESCE(st.nama, '') AS satuan, "
        "COALESCE(jb.nama, '') AS jenis_bayar, COALESCE(kas.no_rekening, '') AS no_rekening, "
        "COALESCE(bk.nama, '') AS bank, d.harga_jual, COALESCE(p.nama, '') AS sales, d.qty, "
        f"{_line_net('harga_jual', 'd')} AS nilai "
        "FROM t_penjualan_retur h "
        "INNER JOIN t_penjualan_retur_detail d ON h.no_retur = d.no_retur "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_customer c ON h.kd_customer = c.kd_customer "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        "LEFT JOIN m_satuan st ON d.kd_satuan = st.kd_satuan "
        "LEFT JOIN m_jenis_bayar jb ON h.kd_jenis = jb.kd_jenis "
        "LEFT JOIN m_kas kas ON h.kd_kas = kas.kd_kas "
        "LEFT JOIN m_bank bk ON kas.kd_bank = bk.kd_bank "
        "LEFT JOIN m_pegawai p ON d.kd_pegawai = p.kd_pegawai "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Pembelian (B13) --

SORTS_PEMBELIAN = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "subtotal": "subtotal"}
SUMMARY_PEMBELIAN = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, COALESCE(SUM(q.subtotal), 0) AS total_nilai"
)
FILTERS_PEMBELIAN = {
    "no_transaksi": ("no_transaksi", "text"),
    "no_order": ("no_order", "text"),
    "supplier": ("supplier", "text"),
    "barang": ("barang", "text"),
    "qty": ("qty", "number_range"),
    "harga": ("harga", "number_range"),
    "subtotal": ("subtotal", "number_range"),
}

def pembelian(f):
    # subtotal applies diskon1-4 (flat Rupiah, per _line_net()'s docstring) —
    # t_pembelian_detail has the same diskon1-4 shape as t_penjualan_detail
    # (confirmed live); previously computed as a flat qty*harga_beli, silently
    # ignoring any per-line discount.
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_transaksi", "b.nama", "s.nama"])
    inner = (
        "SELECT h.no_transaksi, COALESCE(h.no_order, '') AS no_order, h.tanggal, "
        "COALESCE(s.nama, '') AS supplier, COALESCE(h.keterangan, '') AS note, "
        "b.nama AS barang, d.qty, COALESCE(st.nama, '') AS satuan, d.harga_beli AS harga, "
        "COALESCE(d.diskon1, 0) AS diskon_item1, COALESCE(d.diskon2, 0) AS diskon_item2, "
        "COALESCE(d.diskon3, 0) AS diskon_item3, COALESCE(d.diskon4, 0) AS diskon_item4, "
        "COALESCE(h.diskon1, 0) AS diskon_total1, COALESCE(h.diskon2, 0) AS diskon_total2, "
        "COALESCE(h.diskon3, 0) AS diskon_total3, COALESCE(h.diskon4, 0) AS diskon_total4, "
        "COALESCE(h.pajak, 0) AS pajak, COALESCE(h.ppnbm, 0) AS ppnbm, "
        f"{_line_net('harga_beli')} AS subtotal "
        "FROM t_pembelian h "
        "INNER JOIN t_pembelian_detail d ON h.no_transaksi = d.no_transaksi "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_supplier s ON h.kd_supplier = s.kd_supplier "
        "LEFT JOIN m_satuan st ON d.kd_satuan = st.kd_satuan "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


def _pembelian_nota(where_sql: str) -> str:
    """Per-nota subquery pembelian, mirrors _nota_net(): total bersih setelah
    diskon1-4 per baris (_line_net) + diskon header + pajak/ppnbm (persen,
    sama seperti t_penjualan). Tidak menjumlahkan t_pembelian_biaya_angkut di
    sini — itu tabel header (1 baris/no_transaksi); breakdown ongkos kirim
    per supplier/periode disisihkan sebagai fitur terpisah nanti."""
    net = f"SUM({_line_net('harga_beli')}) - {HDR_DISKON}"
    pajak_amt = f"({net}) * COALESCE(MIN(h.pajak), 0) / 100.0"
    return (
        "SELECT h.no_transaksi, MIN(h.tanggal) AS tanggal, MIN(h.kd_supplier) AS kd_supplier, "
        "MIN(h.kd_divisi) AS kd_divisi, "
        "SUM(d.qty * d.harga_beli) AS total_kotor, "
        f"{pajak_amt} AS pajak, "
        f"({net}) * (1 + COALESCE(MIN(h.pajak), 0) / 100.0 + COALESCE(MIN(h.ppnbm), 0) / 100.0) AS total_bersih "
        "FROM t_pembelian h "
        "INNER JOIN t_pembelian_detail d ON h.no_transaksi = d.no_transaksi "
        f"WHERE {where_sql} "
        "GROUP BY h.no_transaksi, h.diskon1, h.diskon2, h.diskon3, h.diskon4, h.pajak, h.ppnbm"
    )


# --- Pembelian per Supplier --

SORTS_PEMBELIAN_SUPPLIER = {"supplier": "supplier", "jml_nota": "jml_nota", "total": "total", "divisi": "divisi"}
SUMMARY_PEMBELIAN_SUPPLIER = (
    "COUNT(DISTINCT q.kd_supplier) AS jml_supplier, COALESCE(SUM(q.jml_nota), 0) AS total_nota, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)
FILTERS_PEMBELIAN_SUPPLIER = {
    "supplier": ("supplier", "text"),
    "jml_nota": ("jml_nota", "number_range"),
    "total": ("total", "number_range"),
}

def pembelian_supplier(f):
    # Grouped by (kd_divisi, kd_supplier) — a supplier trading with multiple
    # divisions gets one row per divisi, mirroring penjualan_customer's grain.
    where, params = _base_where(f)
    inner = (
        "SELECT n.kd_supplier, COALESCE(s.nama, '') AS supplier, "
        "n.kd_divisi, COALESCE(dv.nama, '') AS divisi, "
        "COUNT(n.no_transaksi) AS jml_nota, COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({_pembelian_nota(' AND '.join(where))}) n "
        "LEFT JOIN m_supplier s ON n.kd_supplier = s.kd_supplier "
        "LEFT JOIN m_divisi dv ON n.kd_divisi = dv.kd_divisi "
        "GROUP BY n.kd_supplier, s.nama, n.kd_divisi, dv.nama"
    )
    return inner, params


# --- Pembelian per Periode --

SORTS_PEMBELIAN_PERIODE = {"periode": "periode", "total": "total"}
SUMMARY_PEMBELIAN_PERIODE = (
    "COUNT(DISTINCT q.periode) AS jml_periode, COALESCE(SUM(q.jml_nota), 0) AS total_nota, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)

def pembelian_periode(f):
    # Breakdown kotor/diskon/pajak, no direct legacy view acuan for pembelian
    # per-periode — added analog to penjualan_periode's breakdown per user's
    # explicit request; same derivation caveat applies (verify vs. real data).
    where, params = _base_where(f)
    granul = f.get("granularitas", "harian")
    periode = "FORMAT(n.tanggal, 'yyyy-MM')" if granul == "bulanan" else "FORMAT(n.tanggal, 'yyyy-MM-dd')"
    inner = (
        f"SELECT {periode} AS periode, COUNT(n.no_transaksi) AS jml_nota, "
        "COALESCE(SUM(n.total_kotor), 0) AS total_kotor, "
        "COALESCE(SUM(n.total_kotor) - SUM(n.total_bersih) + SUM(n.pajak), 0) AS total_diskon, "
        "COALESCE(SUM(n.pajak), 0) AS total_pajak, "
        "COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({_pembelian_nota(' AND '.join(where))}) n "
        f"GROUP BY {periode}"
    )
    return inner, params


# --- Retur Pembelian (B14) --

SORTS_RETUR_PEMBELIAN = {"no_retur": "no_retur", "tanggal": "tanggal", "nilai": "nilai"}
SUMMARY_RETUR_PEMBELIAN = (
    "COUNT(*) AS jml_retur, COALESCE(SUM(q.qty), 0) AS total_qty, COALESCE(SUM(q.nilai), 0) AS total_nilai"
)
FILTERS_RETUR_PEMBELIAN = {
    "no_retur": ("no_retur", "text"),
    "supplier": ("supplier", "text"),
    "barang": ("barang", "text"),
    "qty": ("qty", "number_range"),
    "nilai": ("nilai", "number_range"),
}

def retur_pembelian(f):
    # nilai applies diskon1-4 like pembelian(f) above — t_pembelian_retur_detail
    # has the same diskon1-4 columns (confirmed live), currently all-zero in
    # this dataset's history but not guaranteed to stay that way.
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_retur", "b.nama", "s.nama"])
    inner = (
        "SELECT h.no_retur, h.tanggal, h.no_bukti, COALESCE(dv.nama, '') AS divisi, "
        "COALESCE(s.nama, '') AS supplier, COALESCE(jb.nama, '') AS pembayaran, "
        "COALESCE(bk.nama, '') AS bank, COALESCE(kas.no_rekening, '') AS no_rekening, "
        "COALESCE(u.nama, '') AS petugas, d.kd_barang, b.nama AS barang, d.harga, "
        "COALESCE(st.nama, '') AS satuan, COALESCE(h.keterangan, '') AS keterangan, d.qty, "
        f"{_line_net('harga', 'd')} AS nilai "
        "FROM t_pembelian_retur h "
        "INNER JOIN t_pembelian_retur_detail d ON h.no_retur = d.no_retur "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_supplier s ON h.kd_supplier = s.kd_supplier "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        "LEFT JOIN m_jenis_bayar jb ON h.kd_jenis = jb.kd_jenis "
        "LEFT JOIN m_kas kas ON h.kd_kas = kas.kd_kas "
        "LEFT JOIN m_bank bk ON kas.kd_bank = bk.kd_bank "
        "LEFT JOIN m_userx u ON h.kd_user = u.kd_user "
        "LEFT JOIN m_satuan st ON d.kd_satuan = st.kd_satuan "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Piutang (receivables) --
# Reimplements mon_t_piutang_aktif's logic against base tables (view/UDF not
# called directly, per project convention). t_penjualan.status=0 marks a
# credit-sale nota still open (rare — 7 of ~438k rows live — the reference
# view confirms this filter; most sales are status=1/settled and never touch
# t_piutang_cicilan at all). total_penjualan reuses _nota_net() as-is so this
# report's numbers reconcile with penjualan_nota/penjualan_customer/dst — the
# legacy GetTotalPenjualan() also subtracts voucher nominal, which _nota_net()
# does not; left unchanged here to stay consistent with the already-shipped
# penjualan reports rather than silently diverging just for this one page.

SORTS_PIUTANG = {"customer": "customer", "tanggal": "tanggal", "jatuh_tempo": "jatuh_tempo", "sisa_piutang": "sisa_piutang"}
SUMMARY_PIUTANG = (
    "COUNT(*) AS jml_nota, COALESCE(SUM(q.total_penjualan), 0) AS total_penjualan, "
    "COALESCE(SUM(q.total_cicilan), 0) AS total_cicilan, COALESCE(SUM(q.sisa_piutang), 0) AS total_sisa_piutang"
)
FILTERS_PIUTANG = {
    "no_transaksi": ("no_transaksi", "text"),
    "customer": ("customer", "text"),
    "jatuh_tempo": ("jatuh_tempo", "date"),
    "total_penjualan": ("total_penjualan", "number_range"),
    "sisa_piutang": ("sisa_piutang", "number_range"),
    "hari_terlambat": ("hari_terlambat", "number_range"),
}

def piutang(f):
    """Saldo piutang per nota, as-of f['date_to'] (snapshot: cicilan dihitung
    s.d. date_to, bukan agregasi transaksi dalam rentang seperti laporan lain).
    date_from/date_to tetap memfilter tanggal nota (h.tanggal) seperti laporan
    lain — lebar-kan rentang untuk melihat piutang yang lebih lama."""
    where, params = _base_where(f)
    where.append("h.status = 0")
    if f.get("kd_customer"):
        where.append("h.kd_customer = ?")
        params.append(f["kd_customer"])
    if f["search"]:
        where.append("h.no_transaksi LIKE ?")
        params.append(f"%{f['search']}%")

    nota_sql = _nota_net(" AND ".join(where))
    inner = (
        "SELECT n.no_transaksi, n.tanggal, COALESCE(c.nama, '') AS customer, "
        "n.tanggal_jatuh_tempo AS jatuh_tempo, n.total_bersih AS total_penjualan, "
        "COALESCE(cic.total_cicilan, 0) AS total_cicilan, "
        "n.total_bersih - COALESCE(cic.total_cicilan, 0) AS sisa_piutang, "
        "CASE WHEN DATEDIFF(day, n.tanggal_jatuh_tempo, ?) > 0 "
        "THEN DATEDIFF(day, n.tanggal_jatuh_tempo, ?) ELSE 0 END AS hari_terlambat "
        f"FROM ({nota_sql}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "LEFT JOIN (SELECT no_transaksi, SUM(nominal) AS total_cicilan FROM t_piutang_cicilan "
        "WHERE tanggal <= ? GROUP BY no_transaksi) cic ON cic.no_transaksi = n.no_transaksi "
        "WHERE n.total_bersih - COALESCE(cic.total_cicilan, 0) > 0"
    )
    # Param order must match the ?'s left-to-right position in `inner`, NOT the
    # order they were built in: the two DATEDIFF placeholders sit in the outer
    # SELECT list, which renders BEFORE the FROM (nota_sql) clause that embeds
    # `params` — so date_to/date_to come first, then `params`, then the cic
    # subquery's cutoff.
    return inner, [f["date_to"], f["date_to"]] + params + [f["date_to"]]


# --- Pengeluaran / Biaya Operasional --
# t_biaya_operasional today only feeds kas_harian_rows()'s UNION (Biaya: arm);
# this adds a standalone detail + per-kategori rollup. Label mapping verified
# directly against the mon_m_biaya view definition (not called — reimplemented
# as a CASE, per project convention); live data only has status 1/2 in use
# (retail/toys, no production), 3/4 exist in the mapping but are currently unused.
_BIAYA_KATEGORI_CASE = (
    "CASE b.status WHEN 1 THEN 'Operasional (Penjualan)' WHEN 2 THEN 'Operasional (Adm. dan Umum)' "
    "WHEN 3 THEN 'Produksi (Biaya Langsung)' WHEN 4 THEN 'Produksi (Biaya Tak Langsung)' ELSE '' END"
)

SORTS_BIAYA = {"tanggal": "tanggal", "biaya": "biaya", "nominal": "nominal"}
SUMMARY_BIAYA = "COUNT(*) AS jml_baris, COALESCE(SUM(q.nominal), 0) AS total_nominal"

def biaya_operasional(f):
    where, params = _base_where(f)
    if f.get("kategori"):
        where.append("b.status = ?")
        params.append(f["kategori"])
    _search(where, params, f, ["b.nama", "h.keterangan"])
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(dv.nama, '') AS divisi, "
        "b.nama AS biaya, "
        f"{_BIAYA_KATEGORI_CASE} AS kategori, "
        "h.nominal, COALESCE(h.keterangan, '') AS keterangan "
        "FROM t_biaya_operasional h "
        "INNER JOIN m_biaya b ON h.kd_biaya = b.kd_biaya "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


SORTS_BIAYA_KATEGORI = {"kategori": "kategori", "total": "total"}
SUMMARY_BIAYA_KATEGORI = (
    "COUNT(DISTINCT q.kategori) AS jml_kategori, COALESCE(SUM(q.jml_baris), 0) AS total_baris, "
    "COALESCE(SUM(q.total), 0) AS total_nilai"
)

def biaya_kategori(f):
    """Rollup per kategori (m_biaya.status) — mirrors penjualan_periode's rollup shape."""
    where, params = _base_where(f)
    inner = (
        f"SELECT {_BIAYA_KATEGORI_CASE} AS kategori, COUNT(*) AS jml_baris, SUM(h.nominal) AS total "
        "FROM t_biaya_operasional h "
        "INNER JOIN m_biaya b ON h.kd_biaya = b.kd_biaya "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY b.status"
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
        f"COALESCE(SUM(d.qty), 0) AS qty_terjual, COALESCE(SUM({_line_net('harga_jual')}), 0) AS nilai, "
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

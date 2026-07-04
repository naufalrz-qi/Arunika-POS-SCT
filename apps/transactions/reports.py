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


# --- Penjualan per Customer (B9) --

SORTS_PENJUALAN_CUSTOMER = {"customer": "customer", "jml_nota": "jml_nota", "total": "total"}
SUMMARY_PENJUALAN_CUSTOMER = (
    "COUNT(DISTINCT q.kd_customer) AS jml_baris, 0 AS total_qty, COALESCE(SUM(q.total_bersih), 0) AS total_nilai"
)

def penjualan_customer(f):
    where, params = _base_where(f)
    if f["search"]:
        where.append("c.nama LIKE ?")
        params.append(f"%{f['search']}%")
    inner = (
        "SELECT n.kd_customer, COALESCE(c.nama, '') AS customer, COALESCE(c.kota, '') AS kota, "
        "COUNT(n.no_transaksi) AS jml_nota, COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "GROUP BY n.kd_customer, c.nama, c.kota"
    )
    return inner, params


# --- Penjualan per User (B10) --

SORTS_PENJUALAN_USER = {"user": "user", "jml_nota": "jml_nota", "total": "total"}
SUMMARY_PENJUALAN_USER = (
    "COUNT(DISTINCT q.kd_user) AS jml_baris, 0 AS total_qty, COALESCE(SUM(q.total_bersih), 0) AS total_nilai"
)

def penjualan_user(f):
    where, params = _base_where(f)
    inner = (
        "SELECT COALESCE(u.nama, n.kd_user) AS user, n.kd_user, "
        "COUNT(n.no_transaksi) AS jml_nota, COALESCE(SUM(n.total_bersih), 0) AS total "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN apps_user u ON n.kd_user = u.username "
        "GROUP BY n.kd_user, u.nama"
    )
    return inner, params


# --- Penjualan per Periode (B11) --

SORTS_PENJUALAN_PERIODE = {"periode": "periode", "total": "total"}
SUMMARY_PENJUALAN_PERIODE = (
    "COUNT(DISTINCT q.periode) AS jml_baris, 0 AS total_qty, COALESCE(SUM(q.total_bersih), 0) AS total_nilai"
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
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, COALESCE(SUM(q.nilai), 0) AS total_nilai"
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
        f"{_line_net('harga_beli', 'd')} AS subtotal "
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
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.qty), 0) AS total_qty, COALESCE(SUM(q.nilai), 0) AS total_nilai"
)

def retur_pembelian(f):
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_retur", "b.nama", "s.nama"])
    inner = (
        "SELECT h.no_retur, h.tanggal, COALESCE(s.nama, '') AS supplier, "
        "b.nama AS barang, d.qty, "
        f"{_line_net('harga_beli', 'd')} AS nilai "
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
        "SELECT h.kd_barang, b.nama AS barang, h.qty_sistem, h.qty_fisik, "
        "(h.qty_fisik - h.qty_sistem) AS diferensi, h.tanggal "
        "FROM t_opname_stok h "
        "INNER JOIN m_barang b ON h.kd_barang = b.kd_barang "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Kas Harian (B16) --

SORTS_KAS = {"tanggal": "tanggal", "opening": "opening", "masuk": "masuk", "keluar": "keluar", "penutupan": "penutupan"}
SUMMARY_KAS = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.opening), 0) AS total_opening, "
    "COALESCE(SUM(q.masuk), 0) AS total_masuk, COALESCE(SUM(q.keluar), 0) AS total_keluar"
)

def kas(f):
    where, params = _base_where(f)
    where_str = ' AND '.join(where) if where else "1=1"
    # Simplified: aggregated kas by date (union of all kas-affecting tables)
    inner = (
        "SELECT h.tanggal, "
        "COALESCE(SUM(CASE WHEN k.tipe = 'masuk' THEN k.jumlah ELSE 0 END), 0) AS masuk, "
        "COALESCE(SUM(CASE WHEN k.tipe = 'keluar' THEN k.jumlah ELSE 0 END), 0) AS keluar, "
        "COALESCE(MAX(h.opening), 0) AS opening, "
        "COALESCE(MAX(h.penutupan), 0) AS penutupan "
        "FROM (SELECT DISTINCT CAST(tanggal AS DATE) AS tanggal FROM t_mutasi_kas "
        f"WHERE {where_str}) h "
        "LEFT JOIN (SELECT tanggal, 'masuk' AS tipe, SUM(jumlah) AS jumlah FROM t_mutasi_kas WHERE tipe='masuk' GROUP BY tanggal "
        "UNION ALL SELECT tanggal, 'keluar', SUM(jumlah) FROM t_mutasi_kas WHERE tipe='keluar' GROUP BY tanggal) k "
        "ON h.tanggal = CAST(k.tanggal AS DATE) "
        "GROUP BY h.tanggal"
    )
    return inner, params


# --- Shift / Pegawai Ganti Shift (B17) --

SORTS_SHIFT = {"tanggal": "tanggal", "nama_pegawai": "nama_pegawai", "shift": "shift"}
SUMMARY_SHIFT = (
    "COUNT(*) AS jml_baris, COUNT(DISTINCT nama_pegawai) AS jml_pegawai, COUNT(DISTINCT shift) AS jml_shift"
)

def shift(f):
    where, params = _base_where(f)
    _search(where, params, f, ["p.nama"])
    inner = (
        "SELECT h.tanggal, COALESCE(p.nama, '') AS nama_pegawai, h.shift, h.kd_kas "
        "FROM t_pegawai_ganti_shift h "
        "LEFT JOIN m_pegawai p ON h.kd_pegawai = p.kd_pegawai "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Promo & Diskon (B18) --

SORTS_PROMO = {"kd_promo": "kd_promo", "barang": "barang", "harga_promo": "harga_promo", "tanggal_awal": "tanggal_awal"}
SUMMARY_PROMO = "COUNT(*) AS jml_baris, COUNT(DISTINCT kd_barang) AS jml_barang"

def promo(f):
    where = ["1=1"]
    params = []
    if f.get("date_from"):
        where.append("tanggal_awal >= ?")
        params.append(f["date_from"])
    if f.get("date_to"):
        where.append("tanggal_akhir <= ?")
        params.append(f["date_to"])
    _search(where, params, f, ["kd_promo", "b.nama"])
    inner = (
        "SELECT p.kd_promo, d.kd_divisi AS divisi, b.nama AS barang, p.harga_promo, "
        "p.tanggal_awal, p.tanggal_akhir, CASE WHEN p.flag_aktif=1 THEN 'Aktif' ELSE 'Nonaktif' END AS status "
        "FROM m_promo p "
        "LEFT JOIN m_barang b ON p.kd_barang = b.kd_barang "
        "LEFT JOIN (SELECT DISTINCT kd_barang, kd_divisi FROM t_penjualan_detail d INNER JOIN t_penjualan h ON d.no_transaksi=h.no_transaksi) d ON p.kd_barang=d.kd_barang "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Voucher (B19) --

SORTS_VOUCHER = {"kd_voucher": "kd_voucher", "divisi": "divisi", "nominal": "nominal"}
SUMMARY_VOUCHER = "COUNT(*) AS jml_baris, COALESCE(SUM(nominal), 0) AS total_nominal"

def voucher(f):
    where = ["1=1"]
    params = []
    if f.get("date_from"):
        where.append("tanggal_awal >= ?")
        params.append(f["date_from"])
    if f.get("date_to"):
        where.append("tanggal_akhir <= ?")
        params.append(f["date_to"])
    _search(where, params, f, ["v.kd_voucher"])
    inner = (
        "SELECT v.kd_voucher, COALESCE(d.kd_divisi, '') AS divisi, v.nominal, v.tanggal_awal, v.tanggal_akhir, "
        "CASE WHEN v.flag_aktif=1 THEN 'Aktif' ELSE 'Nonaktif' END AS status "
        "FROM m_voucher v "
        "LEFT JOIN (SELECT DISTINCT kd_voucher, kd_divisi FROM t_penjualan WHERE kd_voucher IS NOT NULL) d ON v.kd_voucher=d.kd_voucher "
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
        "SELECT b.kd_barang, b.nama AS barang, b.kd_kategori AS kategori, "
        "COALESCE(SUM(d.qty), 0) AS qty_terjual, COALESCE(SUM(d.qty * d.harga_jual * (1-COALESCE(d.diskon1,0)/100.0)), 0) AS nilai, "
        "CASE WHEN COALESCE(SUM(d.qty), 0) > 100 THEN 'A' WHEN COALESCE(SUM(d.qty), 0) > 50 THEN 'B' ELSE 'C' END AS kelas "
        "FROM m_barang b "
        "LEFT JOIN t_penjualan_detail d ON b.kd_barang = d.kd_barang "
        "LEFT JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
        f"WHERE 1=1 {' AND ' + ' AND '.join(where) if where else ''} "
        "GROUP BY b.kd_barang, b.nama, b.kd_kategori"
    )
    return inner, params


# --- FMI Stok (B21) - Stock velocity analysis --

SORTS_FMI_STOK = {"qty_stok": "qty_stok", "nilai_stok": "nilai_stok", "turnover_rate": "turnover_rate"}
SUMMARY_FMI_STOK = (
    "COUNT(DISTINCT kd_barang) AS jml_barang, COALESCE(SUM(qty_stok), 0) AS total_qty, COALESCE(SUM(nilai_stok), 0) AS total_nilai"
)

def fmi_stok(f):
    where, params = _base_where(f)
    inner = (
        "SELECT b.kd_barang, b.nama AS barang, b.kd_kategori AS kategori, "
        "COALESCE(SUM(s.qty), 0) AS qty_stok, COALESCE(SUM(s.qty * b.harga_beli), 0) AS nilai_stok, "
        "COALESCE(SUM(CASE WHEN s.qty > 0 THEN 1 ELSE 0 END), 0) AS turnover_rate "
        "FROM m_barang b "
        "LEFT JOIN (SELECT kd_barang, SUM(qty) as qty FROM t_stok GROUP BY kd_barang) s ON b.kd_barang = s.kd_barang "
        f"WHERE 1=1 {' AND ' + ' AND '.join(where) if where else ''} "
        "GROUP BY b.kd_barang, b.nama, b.kd_kategori, b.harga_beli"
    )
    return inner, params

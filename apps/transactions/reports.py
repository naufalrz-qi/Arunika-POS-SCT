"""Report SQL builders (server-side report pages, PRD §6).

Each report contributes:
- `<name>(f)`      -> (inner_sql, params): full SELECT without ORDER BY
- `SORTS_<NAME>`   -> whitelist {sort param: output alias} for ORDER BY
- `SUMMARY_<NAME>` -> select list for aggregates (jml_baris, total_qty, total_nilai)
"""
import datetime as dt
import os


def _ghb(price: str, diskon: list[str], pajak: str = "0", ppnbm: str = "0") -> str:
    """Emulasi UDF dbo.GetHargaBersih sbg satu ekspresi SQL (PRD §5.3: no UDF call).

    Tiap diskon1-4 diterapkan berurutan atas nilai berjalan dgn semantik UDF
    (dual-mode): nilai di (-1,1) = persen (v*(1-d)), |nilai|>=1 = rupiah flat
    (v-d). Lalu pajak & ppnbm ditambah sbg fraksi (v*(1+p)). Guard UDF
    `IF @harga_bersih > 0` direplikasi: nilai dihitung lalu dibuang bila price
    awal <= 0.

    Kunci: tiap langkah ditulis `v*mult(d) - sub(d)` sehingga nilai berjalan `v`
    muncul TEPAT SEKALI per langkah (mult/sub hanya bergantung pd konstanta d,
    bukan v). Bentuk CASE naif (v muncul 3x tiap cabang) membuat SQL Server
    meng-inline-ulang tiap langkah 3x saat optimasi -> ledakan ekspresi 3^4 per
    GHB (error 8632 'expression services limit'). Bentuk once-only ini flat linear."""
    v = f"({price})"
    for d in diskon:
        mult = f"(CASE WHEN {d} > -1 AND {d} < 1 THEN 1 - ({d}) ELSE 1 END)"
        sub = f"(CASE WHEN {d} > -1 AND {d} < 1 THEN 0 ELSE ({d}) END)"
        v = f"({v} * {mult} - {sub})"
    v = f"({v} * (1 + {pajak}) * (1 + {ppnbm}))"
    return f"(CASE WHEN ({price}) > 0 THEN {v} ELSE ({price}) END)"


def _disk4(alias: str) -> list[str]:
    """Keempat kolom diskon1-4 milik `alias`, NULL-safe — satu definisi dipakai
    baik level baris (_unit_net) maupun level header (_nota_net/_pembelian_nota)."""
    return [f"COALESCE({alias}.diskon{i}, 0)" for i in (1, 2, 3, 4)]


def _unit_net(price_col: str, alias: str = "d") -> str:
    """Harga bersih PER UNIT setelah diskon1-4 level baris, semantik GHB.

    Menggantikan aritmetika flat lama (`price - d1 - d2 - d3 - d4`). Klaim lama
    "diskon1-4 selalu rupiah flat" benar untuk 2.990.175 dari 2.990.262 baris
    t_penjualan_detail, tapi salah untuk 87 sisanya: 82 baris menyimpan diskon
    sebagai fraksi (mis. harga_jual 58400 diskon1 0.2 -> kolom `total` 140160
    utk qty 3, bukan 175199.4 ala flat), dan 85 baris harga_jual <= 0 jadi
    subtotal negatif palsu tanpa guard UDF.

    _ghb benar untuk KEDUA mode sekaligus: cabang |d| >= 1 memang identik dgn
    pengurangan flat, jadi 99,997% baris yang sudah benar tetap tidak bergerak."""
    return _ghb(f"{alias}.{price_col}", _disk4(alias))


def _line_net(price_col: str, alias: str = "d") -> str:
    """qty * harga bersih per unit (diskon1-4 level baris, semantik GHB)."""
    return f"({alias}.qty * {_unit_net(price_col, alias)})"


def _search(where: list, params: list, f: dict, cols: list) -> None:
    """Append LIKE clause when f['search'] is set."""
    if f["search"]:
        like = " OR ".join(f"{c} LIKE ?" for c in cols)
        where.append(f"({like})")
        params.extend([f"%{f['search']}%"] * len(cols))


def _nota_net(where_sql: str) -> str:
    """Per-nota subquery: header net total, semantik UDF legacy.

    TIGA UDF legacy (diverifikasi dari sys.sql_modules) saling konsisten dan
    semuanya memakai GetHargaBersih utk diskon header:
        GetTotalPenjualan      = net_pre_tax * (1 + pajak) - voucher - diskon_uang
        GetTotalPajakPenjualan = pajak * net_pre_tax          <- DIKALI LANGSUNG
        GetTotalDiskonPenjualan= total_kotor - net_pre_tax + diskon_uang
    dgn net_pre_tax = SUM(GHB(GHB(harga_jual, d.diskon1-4), h.diskon1-4) * qty).

    Tiga hal yang dulu salah dan diperbaiki di sini:
    1. h.diskon1-4 BUKAN rupiah flat. Di DB live seluruh nota berdiskon header
       bernilai fraksi (0.05/0.1/0.25/...), tak satu pun >= 1 — versi lama
       mengurangi Rp0,05 alih-alih 5%. Tetap dipakai _ghb (dual-mode) bukan
       hardcode fraksi, karena mode rupiah flat masih bisa muncul dari aplikasi
       legacy kapan saja.
    2. h.pajak juga fraksi, bukan angka-persen: `/100.0` membuat pajak 0.05
       dihitung 0,05% alih-alih 5%. GetTotalPajakPenjualan mengalikan `pajak`
       langsung tanpa /100 — konfirmasi independen.
    3. diskon_uang dikurangi PALING AKHIR (setelah pajak), bukan sebelum.
       diskon_uang sendiri memang rupiah flat, itu sudah benar.

    Diskon header diterapkan SEKALI per nota di outer (atas SUM baris), bukan
    per baris seperti UDF. Untuk diskon persen keduanya setara secara aljabar
    (distributif) — dicek atas seluruh nota terdampak, selisih maks 3,6e-12,
    murni noise float. Keduanya baru berbeda pada mode rupiah flat, yang legacy
    kurangi dari TIAP baris; nol kejadian di DB ini (tak ada header diskon
    |d| >= 1), dan bentuk per-baris memakan 2x waktu Kas Harian/Summary. Kalau
    suatu saat muncul header diskon rupiah flat, pindahkan _ghb header ke dalam
    SUM (`SUM(_ghb(_unit_net(...), _disk4('h')) * d.qty)`) — h.diskon1-4 boleh
    dirujuk di dalam SUM() karena semuanya kolom GROUP BY.

    Bentuk dua level disengaja: inner mengagregasi baris, outer menerapkan
    diskon header + pajak sekali per nota. Selain lebih murah, ini menjaga
    jumlah ekspresi GHB per statement tetap kecil (risiko error 8632, lihat
    docstring _ghb) — Kas Harian menanam _nota_net dua kali per statement.

    Voucher sengaja TIDAK dikurangi walau GetTotalPenjualan menguranginya;
    lihat catatan di bagian Piutang."""
    net_pre_tax = _ghb("net_lines", ["hd1", "hd2", "hd3", "hd4"])
    return (
        "SELECT no_transaksi, tanggal, kd_customer, kd_divisi, status_raw, kd_voucher, "
        "kd_user, kd_kas, tanggal_jatuh_tempo, total_kotor, "
        f"({net_pre_tax}) * pajak_rate AS pajak, "
        f"({net_pre_tax}) * (1 + pajak_rate) - diskon_uang AS total_bersih "
        "FROM ("
        "SELECT h.no_transaksi, MIN(h.tanggal) AS tanggal, MIN(h.kd_customer) AS kd_customer, "
        "MIN(h.kd_divisi) AS kd_divisi, MIN(h.status) AS status_raw, MIN(h.kd_voucher) AS kd_voucher, "
        "MIN(h.kd_user) AS kd_user, MIN(h.kd_kas) AS kd_kas, MIN(h.tanggal_jatuh_tempo) AS tanggal_jatuh_tempo, "
        "SUM(d.qty * d.harga_jual) AS total_kotor, "
        "COALESCE(MIN(h.pajak), 0) AS pajak_rate, "
        "COALESCE(MIN(h.diskon_uang), 0) AS diskon_uang, "
        "COALESCE(MIN(h.diskon1), 0) AS hd1, COALESCE(MIN(h.diskon2), 0) AS hd2, "
        "COALESCE(MIN(h.diskon3), 0) AS hd3, COALESCE(MIN(h.diskon4), 0) AS hd4, "
        f"SUM({_unit_net('harga_jual')} * d.qty) AS net_lines "
        "FROM t_penjualan h "
        "INNER JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi "
        f"WHERE {where_sql} "
        "GROUP BY h.no_transaksi, h.diskon1, h.diskon2, h.diskon3, h.diskon4, h.diskon_uang, h.pajak"
        ") nz"
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
        # Harga Bersih: harga per unit net diskon1-4 level baris saja. Diskon
        # header + pajak adalah penyesuaian level nota (lihat _nota_net) —
        # sengaja tidak direplikasi ke satu baris di sini.
        f"{_unit_net('harga_jual')} AS harga_bersih, "
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


# --- Laba per Barang (HPP) — replikasi VIEW mon_t_penjualan_per_barang_harga_pokok --
# VIEW legacy tak boleh dipanggil (PRD §5.3); logikanya ditulis ulang table-level.
# "harga pokok" = harga beli net pembelian TERAKHIR per unit dasar (subquery cost,
# ROW_NUMBER), fallback MAX(harga_beli_awal) m_barang_divisi (opening). UDF
# GetHargaBersih diemulasi _ghb_apply (dual-mode diskon + pajak, semantik fraksi).
# Join master pakai LEFT (konvensi sibling report), beda dari VIEW yg INNER —
# baris dgn customer/divisi hilang tetap tampil, bukan didrop. `opening` INNER
# meniru VIEW `bdiv`: barang tanpa baris m_barang_divisi memang tereksklusi.
SORTS_PENJUALAN_HPP = {
    "tanggal": "tanggal", "no_transaksi": "no_transaksi", "barang": "barang",
    "kategori": "kategori", "harga_pokok": "harga_pokok",
    "total_bersih": "total_bersih", "total_harga_pokok": "total_harga_pokok",
    "laba": "laba", "margin": "margin",
}
SUMMARY_PENJUALAN_HPP = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.total_bersih), 0) AS total_bersih, "
    "COALESCE(SUM(q.total_harga_pokok), 0) AS total_harga_pokok, "
    "COALESCE(SUM(q.laba), 0) AS total_laba, "
    "ROUND(COALESCE(SUM(q.laba), 0) / NULLIF(SUM(q.total_harga_pokok), 0) * 100, 2) AS margin_total"
)
FILTERS_PENJUALAN_HPP = {
    "no_transaksi": ("no_transaksi", "text"),
    "customer": ("customer", "text"),
    "barang": ("barang", "text"),
    "kd_barang": ("kd_barang", "text"),
    "kategori": ("kategori", "text"),
    "laba": ("laba", "number_range"),
    "margin": ("margin", "number_range"),
    "total_bersih": ("total_bersih", "number_range"),
}


def penjualan_hpp(f):
    where, params = _base_where(f)
    _search(where, params, f, ["h.no_transaksi", "b.nama", "c.nama"])

    # Net jual per unit terjual: GHB item (diskon baris, tanpa pajak) -> GHB
    # header (diskon nota + pajak). Dua guard `harga>0` dipertahankan bertingkat.
    item_net = _unit_net("harga_jual")
    harga_net = _ghb(item_net, _disk4("h"), pajak="COALESCE(h.pajak,0)")

    # Cost per unit dasar: pembelian terakhir (net dari diskon+pajak+ppnbm beli).
    cost_net = _ghb("pd.harga_beli", _disk4("pd"),
                    pajak="COALESCE(pb.pajak,0)", ppnbm="COALESCE(pb.ppnbm,0)")
    cost_sub = (
        "SELECT kd_barang, harga_net_cost FROM ("
        "SELECT pd.kd_barang, "
        f"({cost_net}) / NULLIF(brg.jumlah, 0) AS harga_net_cost, "
        "ROW_NUMBER() OVER (PARTITION BY pd.kd_barang ORDER BY pb.tanggal DESC, pb.no_transaksi DESC) AS rn "
        "FROM t_pembelian_detail pd "
        "INNER JOIN t_pembelian pb ON pd.no_transaksi = pb.no_transaksi "
        "INNER JOIN m_barang_satuan brg ON brg.kd_barang = pd.kd_barang AND brg.kd_satuan = pd.kd_satuan "
        "WHERE pd.harga_beli > 0"
        ") z WHERE z.rn = 1"
    )

    # bst = satuan baris terjual: konv (bst.jumlah) melayani /konv (Harga per unit
    # dasar) sekaligus *konv (Total HPP). VIEW menjoin m_barang_satuan dua kali
    # untuk itu; satu join cukup (predikat identik).
    base = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(dv.nama, '') AS divisi, "
        "COALESCE(c.nama, '') AS customer, d.kd_barang, COALESCE(b.nama, '') AS barang, "
        "COALESCE(kt.nama, '') AS kategori, d.qty, COALESCE(st.nama, '') AS satuan, "
        "COALESCE(pg.nama, '') AS petugas, bst.jumlah AS konv, "
        f"({harga_net}) AS harga_net, "
        "ISNULL(cost.harga_net_cost, opening.harga_beli_awal) AS harga_pokok "
        "FROM t_penjualan h "
        "INNER JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "LEFT JOIN m_customer c ON h.kd_customer = c.kd_customer "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        "LEFT JOIN m_kategori kt ON b.kd_kategori = kt.kd_kategori "
        "LEFT JOIN m_userx pg ON h.kd_user = pg.kd_user "
        "LEFT JOIN m_satuan st ON d.kd_satuan = st.kd_satuan "
        "INNER JOIN m_barang_satuan bst ON bst.kd_barang = d.kd_barang AND bst.kd_satuan = d.kd_satuan "
        f"LEFT JOIN ({cost_sub}) cost ON cost.kd_barang = d.kd_barang "
        "INNER JOIN (SELECT kd_barang, MAX(harga_beli_awal) AS harga_beli_awal "
        "FROM m_barang_divisi GROUP BY kd_barang) opening ON opening.kd_barang = d.kd_barang "
        f"WHERE {' AND '.join(where)}"
    )

    inner = (
        "SELECT x.no_transaksi, x.tanggal, x.divisi, x.customer, x.kd_barang, x.barang, "
        "x.kategori, x.qty, x.satuan, x.petugas, "
        "ROUND(x.harga_net / NULLIF(x.konv, 0), 2) AS harga, "
        "ROUND(x.harga_pokok, 2) AS harga_pokok, "
        "ROUND(x.harga_net * x.qty, 2) AS total_bersih, "
        "ROUND(x.harga_pokok * x.qty * x.konv, 2) AS total_harga_pokok, "
        "ROUND(x.harga_net * x.qty - x.harga_pokok * x.qty * x.konv, 2) AS laba, "
        "ROUND((x.harga_net * x.qty - x.harga_pokok * x.qty * x.konv) / "
        "(CASE WHEN x.harga_pokok * x.qty * x.konv = 0 THEN 1 "
        "ELSE x.harga_pokok * x.qty * x.konv END) * 100, 2) AS margin "
        f"FROM ({base}) x"
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
        # codebase's model (diskon header masuk ke net_pre_tax di _nota_net,
        # tak dipecah jadi kolom pajak terpisah). Exposed
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
    # subtotal applies diskon1-4 (semantik GHB, per _line_net()'s docstring) —
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
    """Per-nota subquery pembelian, mengikuti UDF dbo.GetTotalPembelian:
        SUM(GHB(GHB(harga_beli, d.diskon1-4), h.diskon1-4, h.pajak, h.ppnbm) * qty)

    Struktur dua level sama seperti _nota_net(), dan memperbaiki cacat yang sama:
    diskon header dual-mode (bukan rupiah flat), pajak & ppnbm fraksi (bukan
    `/100.0`), dan ppnbm dikalikan berurutan `(1+pajak)*(1+ppnbm)` sesuai UDF,
    bukan dijumlah `(1 + pajak + ppnbm)`. Dampaknya nol pada data sekarang —
    seluruh 11.697 baris t_pembelian punya diskon/pajak/ppnbm = 0 — jadi ini
    perbaikan cacat laten, bukan perubahan angka.

    Diskon header sekali per nota di outer, alasan sama seperti _nota_net().

    Tidak menjumlahkan t_pembelian_biaya_angkut di sini — itu tabel header
    (1 baris/no_transaksi); breakdown ongkos kirim per supplier/periode
    disisihkan sebagai fitur terpisah nanti."""
    net_pre_tax = _ghb("net_lines", ["hd1", "hd2", "hd3", "hd4"])
    return (
        "SELECT no_transaksi, tanggal, kd_supplier, kd_divisi, total_kotor, "
        f"({net_pre_tax}) * pajak_rate AS pajak, "
        f"({net_pre_tax}) * (1 + pajak_rate) * (1 + ppnbm_rate) AS total_bersih "
        "FROM ("
        "SELECT h.no_transaksi, MIN(h.tanggal) AS tanggal, MIN(h.kd_supplier) AS kd_supplier, "
        "MIN(h.kd_divisi) AS kd_divisi, "
        "SUM(d.qty * d.harga_beli) AS total_kotor, "
        "COALESCE(MIN(h.pajak), 0) AS pajak_rate, COALESCE(MIN(h.ppnbm), 0) AS ppnbm_rate, "
        "COALESCE(MIN(h.diskon1), 0) AS hd1, COALESCE(MIN(h.diskon2), 0) AS hd2, "
        "COALESCE(MIN(h.diskon3), 0) AS hd3, COALESCE(MIN(h.diskon4), 0) AS hd4, "
        f"SUM({_unit_net('harga_beli')} * d.qty) AS net_lines "
        "FROM t_pembelian h "
        "INNER JOIN t_pembelian_detail d ON h.no_transaksi = d.no_transaksi "
        f"WHERE {where_sql} "
        "GROUP BY h.no_transaksi, h.diskon1, h.diskon2, h.diskon3, h.diskon4, h.pajak, h.ppnbm"
        ") nz"
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

SORTS_PIUTANG = {
    "no_transaksi": "no_transaksi", "customer": "customer", "tanggal": "tanggal",
    "jatuh_tempo": "jatuh_tempo", "sisa_piutang": "sisa_piutang",
}
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
# t_biaya_operasional today only feeds kas_harian()'s UNION (Biaya: arm);
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

SORTS_OPNAME = {
    "no_transaksi": "no_transaksi", "kd_barang": "kd_barang", "tanggal": "tanggal",
    "diferensi": "diferensi",
}
# Bruto berdiri di sebelah neto dengan sengaja: `total_diferensi` adalah SUM
# bertanda, jadi sesi dengan +500 dan -500 tampil "0" dan terlihat bersih padahal
# 1000 unit salah hitung. total_masuk/total_keluar yang menahannya jujur.
SUMMARY_OPNAME = (
    "COUNT(*) AS jml_baris, "
    "COALESCE(SUM(q.koreksi_masuk), 0) AS total_masuk, "
    "COALESCE(SUM(q.koreksi_keluar), 0) AS total_keluar, "
    "COALESCE(SUM(q.diferensi), 0) AS total_diferensi"
)

def opname(f):
    where, params = _base_where(f)
    # h.no_transaksi ikut dicari: kotak pencarian menjanjikan "no opname", dan
    # tanpa ini mengetik nomor opname mengembalikan nol baris.
    _search(where, params, f, ["b.kd_barang", "b.nama", "h.no_transaksi"])
    # Dulu kolom ini bernama qty_sistem/qty_fisik — nama yang menyesatkan, karena
    # t_opname_stok TIDAK menyimpan saldo stok sama sekali, hanya besar koreksi
    # dan arahnya (status=2 masuk, selain itu keluar). Salah satu dari dua kolom
    # itu selalu 0; tak satu pun pernah menjadi "stok menurut sistem".
    inner = (
        "SELECT h.no_transaksi, h.tanggal, COALESCE(dv.nama, '') AS divisi, h.kd_barang, b.nama AS barang, "
        "CASE WHEN h.status=2 THEN 0 ELSE h.qty END AS koreksi_keluar, "
        "CASE WHEN h.status=2 THEN h.qty ELSE 0 END AS koreksi_masuk, "
        "CASE WHEN h.status=2 THEN h.qty ELSE -h.qty END AS diferensi "
        "FROM t_opname_stok h "
        "INNER JOIN m_barang b ON h.kd_barang = b.kd_barang "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        f"WHERE {' AND '.join(where)}"
    )
    return inner, params


# --- Neraca Opname (B15b) — pembantu balancing selisih --
#
# Opname dihitung PARSIAL (bergilir per divisi/rak) supaya operasi tak berhenti.
# Akibatnya pasangan plus-minus yang jatuh di sesi, divisi, atau tanggal berbeda
# tak pernah bertemu di satu layar — padahal justru itu yang dicari saat
# membalance: "barang A minus 3, barang B plus 3, berarti tertukar". Laporan ini
# menjumlahkan selisih LINTAS sesi/divisi/tanggal lalu mengelompokkan barang
# sejenis, supaya pasangan yang tak terlihat oleh hitungan parsial muncul sendiri.
#
# Yang bisa dan tak bisa dijawab halaman ini: t_opname_stok hanya menyimpan delta
# koreksi (qty, dengan arah di `status`), BUKAN stok sistem vs fisik. Jadi
# jawabannya "berapa banyak koreksi dan ke arah mana", bukan "berapa seharusnya".

# Ekspresi kunci GROUP BY. Diinterpolasi ke SQL — GROUP BY tak bisa
# di-parameterize — jadi WAJIB lewat whitelist ini: f["grup"] datang MENTAH dari
# query string lewat spec["filter_keys"] (views._spec_params menyalin apa adanya).
GRUP_NERACA = {
    "nama": "b.nama",
    "kkm": "COALESCE(b.kd_kategori,'') + '|' + COALESCE(b.kd_merk,'') + '|' + COALESCE(b.kd_model,'')",
}
# Bawaan `nama`, dipilih atas dasar PRESISI, bukan recall — dan itu kebalikan
# dari kesan pertama saat mengukur data nyata:
#
#   kkm  menemukan pasangan di 27-50% keluarga, TAPI satu keluarga bisa berisi
#        139 barang. "4.811 unit saling menutup di antara 139 barang" bukan
#        temuan yang bisa ditindaklanjuti; itu cuma ciri sebuah kategori.
#   nama menemukan pasangan di 0,4-1,6% keluarga saja, tapi yang ditemukannya
#        langsung bisa dikerjakan. Contoh nyata di TANJUNG: GSG102 (+299) dan
#        GSG042 (-221), nama sama persis "GASING LAMPU", diposting pada detik
#        yang sama dengan no_transaksi berurutan — tertukar saat pencatatan.
#
# Tugas halaman ini membantu membalance, jadi sedikit-tapi-tepat mengalahkan
# banyak-tapi-kabur. `kkm` tetap tersedia sebagai jaring yang lebih lebar.
GRUP_NERACA_DEFAULT = "nama"

SORTS_OPNAME_NERACA = {
    "grup": "grup", "contoh": "contoh", "anggota": "anggota",
    "lebih": "lebih", "kurang": "kurang", "terpasang": "terpasang",
    "neto": "neto", "neto_abs": "neto_abs", "status_neraca": "status_neraca",
    "tanpa_catatan": "tanpa_catatan",
    "nilai_lebih": "nilai_lebih", "nilai_kurang": "nilai_kurang",
    "nilai_neto": "nilai_neto",
}
# Kolom rupiah WAJIB terdaftar di money_fields spec-nya, kalau tidak pembatasan
# hidden_data_keys jadi hiasan: _report_view mencocokkan pada NAMA FIELD, bukan
# pada halaman mana yang sedang dibuka.
UANG_OPNAME_NERACA = ("nilai_lebih", "nilai_kurang", "nilai_neto",
                      "total_nilai_kurang", "total_nilai_neto")
SUMMARY_OPNAME_NERACA = (
    "COUNT(*) AS jml_grup, "
    "COALESCE(SUM(q.lebih), 0) AS total_lebih, "
    "COALESCE(SUM(q.kurang), 0) AS total_kurang, "
    "COALESCE(SUM(q.terpasang), 0) AS total_terpasang, "
    "COALESCE(SUM(q.neto), 0) AS total_neto, "
    "COALESCE(SUM(q.tanpa_catatan), 0) AS total_tanpa_catatan, "
    "COALESCE(SUM(q.nilai_kurang), 0) AS total_nilai_kurang, "
    "COALESCE(SUM(q.nilai_neto), 0) AS total_nilai_neto"
)

# Arah koreksi. Sengaja sama persis dengan _movement_sql (inventory/services.py)
# dan laporan opname di atas: status=2 masuk, SELAIN ITU keluar. Data nyata
# memuat status 0/1/3/4 juga (3 = keluar dan dominan; 0/1/4 jarang), dan arti
# 0/1/4 tidak terdokumentasi di mana pun. Memakai aturan berbeda di sini akan
# membuat total halaman ini tak bisa dicocokkan dengan halaman Opname Stok —
# konsistensi lebih berharga daripada tebakan.
#
# qty DINORMALKAN KE SATUAN DASAR sebelum dijumlahkan. t_opname_stok punya
# kd_satuan sendiri, dan opname nyata memakai beberapa satuan (di TANJUNG:
# SAA000 82% baris, sisanya SAA002/005/006/008/009 ratusan baris). Dalam satu
# barang satuannya hampir selalu seragam (16 dari 11.493), tapi ANTAR barang
# dalam satu keluarga tidak — tanpa konversi, `terpasang` bisa mengklaim 3 lusin
# menutup 3 pcs. Halaman Opname Stok tidak mengonversi, jadi totalnya memang
# tidak akan sama persis dengan halaman ini; yang ini yang bisa dijumlahkan.
_ARAH_NERACA = (
    "SUM(CASE WHEN h.status = 2 THEN h.qty ELSE -h.qty END * COALESCE(sat.isi, 1))"
)
# Subquery ber-GROUP BY, bukan join langsung: bentuk ini secara struktural tak
# bisa menggandakan baris walau m_barang_satuan punya (kd_barang, kd_satuan)
# kembar — dan penggandaan diam-diam di sini akan melipatkan setiap selisih.
_JOIN_SATUAN = (
    "LEFT JOIN (SELECT kd_barang, kd_satuan, MIN(jumlah) AS isi "
    "FROM m_barang_satuan GROUP BY kd_barang, kd_satuan) sat "
    "ON h.kd_barang = sat.kd_barang AND h.kd_satuan = sat.kd_satuan"
)
# Harga satuan DASAR (jumlah=1). Hanya 2 barang punya >1 baris ber-jumlah=1,
# dan MIN + GROUP BY menutup kasus itu tanpa menggandakan baris. Cakupannya
# 99,9% barang ber-opname, jadi kolom rupiah praktis selalu terisi.
_JOIN_HARGA = (
    "LEFT JOIN (SELECT kd_barang, MIN(harga_jual) AS harga FROM m_barang_satuan "
    "WHERE jumlah = 1 AND harga_jual > 0 GROUP BY kd_barang) hj "
    "ON v.kd_barang = hj.kd_barang"
)
_ADA_CATATAN = (
    "CASE WHEN h.keterangan IS NULL OR LTRIM(RTRIM(h.keterangan)) = '' THEN 0 ELSE 1 END"
)


def _grup_neraca(f):
    kunci = (f.get("grup") or "").strip() or GRUP_NERACA_DEFAULT
    return GRUP_NERACA.get(kunci, GRUP_NERACA[GRUP_NERACA_DEFAULT])


def _neraca_per_barang(f):
    """Level 1: selisih bersih per barang, digabung lintas sesi/tanggal/divisi.

    HAVING <> 0 membuang barang yang koreksinya sudah saling meniadakan sendiri;
    itu bukan temuan, cuma derau.
    """
    where, params = _base_where(f)
    sql = (
        f"SELECT h.kd_barang, {_ARAH_NERACA} AS selisih, COUNT(*) AS n_baris, "
        f"SUM({_ADA_CATATAN}) AS n_catatan, "
        "MAX(LTRIM(RTRIM(h.keterangan))) AS catatan "
        f"FROM t_opname_stok h {_JOIN_SATUAN} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY h.kd_barang HAVING {_ARAH_NERACA} <> 0"
    )
    return sql, params


def opname_neraca(f):
    per_barang, params = _neraca_per_barang(f)
    grup = _grup_neraca(f)
    rollup = (
        f"SELECT {grup} AS grup, MIN(b.nama) AS contoh, COUNT(*) AS anggota, "
        "SUM(CASE WHEN v.selisih > 0 THEN v.selisih ELSE 0 END) AS lebih, "
        "SUM(CASE WHEN v.selisih < 0 THEN -v.selisih ELSE 0 END) AS kurang, "
        "SUM(v.selisih) AS neto, SUM(v.n_baris) AS n_baris, "
        "SUM(v.n_catatan) AS n_catatan, MAX(v.catatan) AS catatan, "
        # Qty menjawab "berapa unit"; rupiah menjawab "mana yang layak dikejar
        # lebih dulu". 6.000 unit slime bisa jauh lebih murah daripada 50 unit
        # barang mahal, dan mengurutkan pakai qty saja menyembunyikan itu.
        "SUM(CASE WHEN v.selisih > 0 THEN v.selisih * COALESCE(hj.harga, 0) ELSE 0 END) AS nilai_lebih, "
        "SUM(CASE WHEN v.selisih < 0 THEN -v.selisih * COALESCE(hj.harga, 0) ELSE 0 END) AS nilai_kurang, "
        "SUM(v.selisih * COALESCE(hj.harga, 0)) AS nilai_neto "
        f"FROM ({per_barang}) v INNER JOIN m_barang b ON v.kd_barang = b.kd_barang "
        f"{_JOIN_HARGA} "
        f"GROUP BY {grup}"
    )
    # Pencarian dipasang di level TERLUAR, bukan di dalam: kalau ia menyaring
    # anggota sebelum rollup, keluarga yang sebenarnya seimbang akan tampak
    # pincang karena separuh pasangannya tersaring keluar.
    where_luar = ["1=1"]
    _search(where_luar, params, f, ["g.grup", "g.contoh", "g.catatan"])
    # Dua level karena SQL Server tak bisa merujuk alias keluaran di SELECT yang
    # sama tempat alias itu dibuat — bentuk yang sama dipakai klasifikasi_pelanggan.
    inner = (
        "SELECT g.*, "
        "CASE WHEN g.lebih < g.kurang THEN g.lebih ELSE g.kurang END AS terpasang, "
        "ABS(g.neto) AS neto_abs, "
        "g.n_baris - g.n_catatan AS tanpa_catatan, "
        "CASE WHEN g.neto = 0 THEN 'Seimbang' "
        "WHEN g.neto < 0 THEN 'Kurang' ELSE 'Lebih' END AS status_neraca "
        f"FROM ({rollup}) g WHERE {' AND '.join(where_luar)}"
    )
    return inner, params


def opname_neraca_anggota(f, nilai_grup):
    """Barang-barang di dalam satu keluarga, untuk panel detail."""
    per_barang, params = _neraca_per_barang(f)
    grup = _grup_neraca(f)
    sql = (
        "SELECT v.kd_barang, b.nama AS barang, COALESCE(w.nama, '') AS warna, "
        "b.ukuran, v.selisih, v.n_baris, v.catatan, "
        # Dinamai `harga_jual`/`nilai` supaya keduanya sudah tercakup pemetaan
        # _FIELDS_BY_DATA_KEY yang ada — nama field itulah yang dicocokkan
        # saat mencabut izin, bukan halamannya.
        "COALESCE(hj.harga, 0) AS harga_jual, "
        "v.selisih * COALESCE(hj.harga, 0) AS nilai "
        f"FROM ({per_barang}) v INNER JOIN m_barang b ON v.kd_barang = b.kd_barang "
        "LEFT JOIN m_warna w ON b.kd_warna = w.kd_warna "
        f"{_JOIN_HARGA} "
        f"WHERE {grup} = ? ORDER BY v.selisih DESC"
    )
    return sql, params + [nilai_grup]


def opname_neraca_kejadian(f, nilai_grup, batas=300):
    """Baris opname mentah untuk keluarga itu — termasuk `keterangan`, yang di
    data nyata memuat alasan yang ditulis operator sendiri ("tertukar dg 206-2",
    "BALANCE SO GLOBAL", "BASAH", "DIBAWA KE H5"). Itu keterangan paling
    berharga di tabel ini dan tak muncul di laporan mana pun sebelumnya."""
    where, params = _base_where(f)
    grup = _grup_neraca(f)
    sql = (
        f"SELECT TOP {int(batas)} h.no_transaksi, h.tanggal, "
        "COALESCE(dv.nama, '') AS divisi, h.kd_barang, b.nama AS barang, "
        "CASE WHEN h.status = 2 THEN 'Lebih' ELSE 'Kurang' END AS arah, h.qty, "
        "LTRIM(RTRIM(COALESCE(h.keterangan, ''))) AS keterangan "
        "FROM t_opname_stok h "
        "INNER JOIN m_barang b ON h.kd_barang = b.kd_barang "
        "LEFT JOIN m_divisi dv ON h.kd_divisi = dv.kd_divisi "
        f"WHERE {' AND '.join(where)} AND {grup} = ? "
        "ORDER BY h.tanggal DESC"
    )
    return sql, params + [nilai_grup]


# --- Kas Harian (B16) --
# t_arus_kas doesn't exist. Real cash-affecting sources: t_penambahan_kas
# (top-up), t_pendapatan (revenue), t_biaya_operasional (expense), t_mutasi_kas
# (transfer between two kas accounts — sumber=out, tujuan=in), and cash sales
# (t_penjualan where kd_kas is filled). `saldo` = saldo berjalan per kas,
# dihitung DI SQL via window function (SUM OVER PARTITION BY kd_kas ORDER BY
# tanggal) — dulunya loop Python atas seluruh rentang (list-of-dict penuh).
# Karena saldo kini melekat per baris (independen dari urutan tampil), inner
# ini kompatibel run_paged (COUNT + OFFSET/FETCH) dan sort desc aman; Python
# tak pernah memegang rentang penuh lagi.

SORTS_KAS = {"tanggal": "tanggal"}  # only sort supported — kolom lain tak bermakna utk arus kas


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


def kas_harian(f):
    """Inner SQL kas harian (kolom: tanggal, kas, keterangan, masuk, keluar,
    saldo) — saldo berjalan per kas via window function, cocok utk run_paged.

    Perbandingan kd_kas mengandalkan collation SQL Server (CI + abaikan spasi
    ekor) — setara normalisasi _k() versi Python lama."""
    period = _kas_union("{col} >= ? AND {col} <= ?")
    pre = _kas_union("{col} < ?")
    kas_where = " WHERE u.kd_kas = ?" if f.get("kd_kas") else ""
    inner = (
        "SELECT u.tanggal, "
        "COALESCE(NULLIF(LTRIM(RTRIM(mk.keterangan)), ''), NULLIF(LTRIM(RTRIM(mk.kd_index)), ''), RTRIM(u.kd_kas)) AS kas, "
        "u.keterangan, u.masuk, u.keluar, "
        # saldo = saldo_awal master + net pergerakan sebelum date_from + kumulatif
        # dalam rentang. Tiebreaker keterangan di ORDER BY window supaya urutan
        # (dan saldo antar baris se-tanggal) deterministik.
        "ROUND(COALESCE(mk.saldo_awal, 0) + COALESCE(pre.net, 0) + SUM(u.masuk - u.keluar) "
        "OVER (PARTITION BY u.kd_kas ORDER BY u.tanggal, u.keterangan ROWS UNBOUNDED PRECEDING), 2) AS saldo "
        f"FROM ({period}) u "
        "LEFT JOIN m_kas mk ON mk.kd_kas = u.kd_kas "
        f"LEFT JOIN (SELECT kd_kas, SUM(masuk) - SUM(keluar) AS net FROM ({pre}) p GROUP BY kd_kas) pre "
        "ON pre.kd_kas = u.kd_kas"
        + kas_where
    )
    params = [f["date_from"], f["date_to"]] * 6 + [f["date_from"]] * 6
    if f.get("kd_kas"):
        params.append(f["kd_kas"])
    return inner, params


def kas_summary(f):
    """(sql, params) summary kas: jml_baris/total_masuk/total_keluar atas rentang
    (terfilter kd_kas bila ada) + saldo_awal (= m_kas.saldo_awal + net pergerakan
    sebelum date_from) + saldo_akhir. Semua agregasi di SQL."""
    period = _kas_union("{col} >= ? AND {col} <= ?")
    pre = _kas_union("{col} < ?")
    kw_u = " WHERE u.kd_kas = ?" if f.get("kd_kas") else ""
    kw_mk = " WHERE kd_kas = ?" if f.get("kd_kas") else ""
    kw_p = " WHERE p.kd_kas = ?" if f.get("kd_kas") else ""
    sql = (
        "SELECT x.jml_baris, x.total_masuk, x.total_keluar, y.saldo_awal, "
        "ROUND(y.saldo_awal + x.total_masuk - x.total_keluar, 2) AS saldo_akhir "
        "FROM (SELECT COUNT(*) AS jml_baris, ROUND(COALESCE(SUM(u.masuk), 0), 2) AS total_masuk, "
        f"ROUND(COALESCE(SUM(u.keluar), 0), 2) AS total_keluar FROM ({period}) u{kw_u}) x "
        "CROSS JOIN (SELECT ROUND("
        f"COALESCE((SELECT SUM(saldo_awal) FROM m_kas{kw_mk}), 0) + "
        f"COALESCE((SELECT SUM(p.masuk) - SUM(p.keluar) FROM ({pre}) p{kw_p}), 0)"
        ", 2) AS saldo_awal) y"
    )
    # Urutan param HARUS ikut posisi ? kiri-ke-kanan dalam teks SQL:
    # period (12) -> filter kd_kas subquery x -> kd_kas subquery m_kas ->
    # pre (6) -> kd_kas subquery pre.
    params = [f["date_from"], f["date_to"]] * 6
    if f.get("kd_kas"):
        params.append(f["kd_kas"])
        params.append(f["kd_kas"])
    params += [f["date_from"]] * 6
    if f.get("kd_kas"):
        params.append(f["kd_kas"])
    return sql, params


# --- Shift / Pegawai Ganti Shift (B17) --
# t_pegawai_ganti_shift is header-only (no_transaksi, tanggal, keterangan,
# kd_user) — kd_pegawai/kd_shift live on the separate _detail table, one row
# per employee assigned in that shift change.

SORTS_SHIFT = {"no_transaksi": "no_transaksi", "tanggal": "tanggal", "pegawai": "pegawai", "shift": "shift"}
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


# --- FMI Penjualan (B20) - Fast Moving Items, analisis Pareto (ABC) --
# Kelas ditentukan HUKUM PARETO atas kontribusi NILAI (bukan ambang qty keras
# lama qty>100->A/>50->B yang arbitrer): item diurut nilai desc, akumulasi
# kontribusi <=80% -> A, <=95% -> B, sisanya C. kontribusi (share thd total) &
# akumulasi (kumulatif) disediakan utk NILAI dan QTY sekaligus.
#
# Dua penyaringan penting:
# 1. Barang tanpa harga jual di master (mis. kresek/packaging — tak ada baris
#    m_barang_satuan.harga_jual > 0) dibuang: nilainya 0, cuma mengotori ranking.
# 2. Hanya barang yang PUNYA penjualan pada periode (HAVING qty_terjual > 0) —
#    Pareto penjualan tak bermakna utk katalog mati; kalau ingin lihat barang
#    priced-tapi-tak-terjual, itu ranah FMI Stok. Filter tanggal/divisi tetap DI
#    DALAM subquery penjualan (predikat pd sisi nullable LEFT JOIN diam-diam
#    mengubahnya jadi inner join).
SORTS_FMI_PENJUALAN = {
    "qty_terjual": "qty_terjual", "nilai": "nilai", "kelas": "kelas",
    "kontribusi_nilai": "kontribusi_nilai", "akumulasi_nilai": "akumulasi_nilai",
    "kontribusi_qty": "kontribusi_qty", "akumulasi_qty": "akumulasi_qty",
}
SUMMARY_FMI_PENJUALAN = (
    "COUNT(DISTINCT kd_barang) AS jml_barang, COALESCE(SUM(qty_terjual), 0) AS total_qty, COALESCE(SUM(nilai), 0) AS total_nilai"
)

def fmi_penjualan(f):
    where, params = _base_where(f)
    grouped = (
        "SELECT b.kd_barang, b.nama AS barang, COALESCE(k.nama, '') AS kategori, "
        "COALESCE(SUM(s.qty), 0) AS qty_terjual, COALESCE(SUM(s.nilai), 0) AS nilai "
        "FROM m_barang b "
        "LEFT JOIN m_kategori k ON b.kd_kategori = k.kd_kategori "
        "LEFT JOIN ("
        f"SELECT d.kd_barang, d.qty, {_line_net('harga_jual')} AS nilai "
        "FROM t_penjualan_detail d "
        "INNER JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
        f"WHERE {' AND '.join(where)}"
        ") s ON b.kd_barang = s.kd_barang "
        "WHERE EXISTS (SELECT 1 FROM m_barang_satuan bs "
        "WHERE bs.kd_barang = b.kd_barang AND bs.harga_jual > 0) "
        "GROUP BY b.kd_barang, b.nama, k.nama "
        "HAVING COALESCE(SUM(s.qty), 0) > 0"
    )
    # Window functions dihitung atas SELURUH set hasil grouped (bukan per-halaman)
    # — run_paged membungkus dgn SELECT * ... ORDER BY ... OFFSET/FETCH, jadi
    # akumulasi tetap benar & terbaca menaik selama default_sort = nilai desc.
    # Tiebreaker kd_barang membuat kunci ORDER BY unik (RANGE == ROWS, deterministik).
    tot_nilai = "NULLIF(SUM(g.nilai) OVER (), 0)"
    tot_qty = "NULLIF(SUM(g.qty_terjual) OVER (), 0)"
    cum_nilai = "SUM(g.nilai) OVER (ORDER BY g.nilai DESC, g.kd_barang)"
    cum_qty = "SUM(g.qty_terjual) OVER (ORDER BY g.qty_terjual DESC, g.kd_barang)"
    inner = (
        "SELECT g.*, "
        f"ROUND(100.0 * g.nilai / {tot_nilai}, 2) AS kontribusi_nilai, "
        f"ROUND(100.0 * {cum_nilai} / {tot_nilai}, 2) AS akumulasi_nilai, "
        f"ROUND(100.0 * g.qty_terjual / {tot_qty}, 2) AS kontribusi_qty, "
        f"ROUND(100.0 * {cum_qty} / {tot_qty}, 2) AS akumulasi_qty, "
        f"CASE WHEN 100.0 * {cum_nilai} / {tot_nilai} <= 80 THEN 'A' "
        f"WHEN 100.0 * {cum_nilai} / {tot_nilai} <= 95 THEN 'B' ELSE 'C' END AS kelas "
        f"FROM ({grouped}) g"
    )
    return inner, params


# --- FMI Stok (B21) - Stock velocity analysis --
# m_barang_stok_akhir (cache stok legacy) RUSAK — berhenti terisi dan angkanya
# menyimpang jauh dari realita — jadi stok TIDAK lagi dibaca dari sana. Baris
# FMI Stok kini dihitung di apps/monitoring/views.py::_fmi_stok_rows lewat
# engine stok asli (apps/inventory/services.stok_akhir_per_tanggal — movement
# engine + snapshot). Modul ini tinggal menyimpan whitelist sort + ambang
# klasifikasi velocity.

_FMI_STOK_KRITIS_HARI = 7      # < sisa hari stok pada laju jual sekarang -> Kritis
_FMI_STOK_OVERSTOCK_HARI = 90  # > sisa hari stok (atau tak pernah laku) -> Overstock

SORTS_FMI_STOK = {"qty_stok": "qty_stok", "nilai_stok": "nilai_stok", "terjual": "terjual", "rasio": "rasio"}

# Stok Akhir: diurut di Python (barisnya dari mesin pergerakan, bukan SELECT),
# jadi nilai peta ini tak pernah masuk ORDER BY — daftar kuncinya saja yang
# dipakai, sebagai whitelist dan sebagai `sort_keys` untuk header tabel.
SORTS_STOK = {
    "divisi": "divisi", "kd_barang": "kd_barang", "barang": "barang",
    "kategori": "kategori", "stok_akhir": "stok_akhir", "nominal": "nominal",
}


# --- Klasifikasi Pelanggan (untuk follow-up) --------------------------------
#
# Menjawab pertanyaan yang tak bisa dijawab "Penjualan per Customer": siapa yang
# BARU datang, siapa yang SETIA, dan siapa yang SUDAH LAMA tak belanja. Keluaran
# dipakai staf menyusun daftar telepon/WA, jadi kontak (hp/telepon) ikut dibawa.
#
# Dua beda sengaja dari penjualan_customer():
# 1. Agregat per kd_customer SAJA, tanpa dipecah divisi. Follow-up ditujukan ke
#    ORANG; satu orang yang belanja di dua divisi tetap satu orang yang ditelepon
#    sekali. (penjualan_customer memecah per divisi karena meniru grain view
#    legacy mon_t_penjualan_per_customer — itu benar untuk laporan penjualan,
#    salah untuk daftar follow-up.)
# 2. Jendela tanggal bawaan panjang (lihat default_from_days di spec view),
#    bukan awal bulan: "belum belanja lebih dari setahun" mustahil terlihat dari
#    jendela sebulan, dan semua orang akan terklasifikasi 'Baru'.

# Penampung transaksi, bukan orang yang bisa difollow up. Diverifikasi live di
# kelima profil koneksi (RTL PUSAT, grosir pusat, TANJUNG, Testing, testgudang):
# ketiga kode ini ada di semuanya, dan CAA025/CAA000 sendiri menelan 99,3% nota
# di retail serta ~69% di grosir.
_PSEUDO_CUSTOMER_CODES = ("CAA000", "CAA025", "CAA027")  # UMUM, ECERAN, OBRAL
# Kanal jualan, bukan orang. Disaring per NAMA (bukan kode) supaya marketplace
# baru tak perlu didaftarkan kodenya satu per satu — kodenya memang seragam di
# kelima profil hari ini, tapi itu kebetulan yang tak dijamin bertahan.
_PSEUDO_CUSTOMER_NAMES = ("SHOPEE", "TOKOPEDIA", "TIKTOK", "LAZADA", "BLIBLI", "BUKALAPAK")


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Daftar dari .env (CSV, case-insensitive) atau `default` bila tak diset.

    Sengaja bisa ditimpa tanpa deploy: tiap toko/cabang bisa punya penampung
    transaksi sendiri (mis. 'GROSIR BEBAS'), dan menunggu rilis untuk itu berarti
    daftar follow-up tercemar sampai rilis berikutnya. String kosong ("") =
    daftar kosong (tanpa penyaringan), berbeda dari tidak diset sama sekali."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return tuple(v.strip().upper() for v in raw.split(",") if v.strip())


def pseudo_customer_codes() -> tuple[str, ...]:
    return _csv_env("POS_PSEUDO_CUSTOMERS", _PSEUDO_CUSTOMER_CODES)


def pseudo_customer_names() -> tuple[str, ...]:
    return _csv_env("POS_PSEUDO_CUSTOMER_NAMES", _PSEUDO_CUSTOMER_NAMES)


# Ambang bawaan. Semuanya bisa diubah dari panel filter (lihat _amb) — ritme
# belanja grosir dan retail berbeda, dan tiap penyesuaian tak boleh butuh deploy.
AMBANG_KLASIFIKASI = {
    "baru_hari": (90, 7, 1095),          # nota PERTAMA masih dalam N hari -> Baru
    "jarang_hari": (90, 7, 1095),        # jeda > N -> Mulai Jarang
    "hilang_hari": (180, 7, 1095),       # jeda > N -> Hilang
    "setia_min_nota": (5, 2, 1000),      # jeda pendek + >= N nota -> Setia
    "tier_besar": (1_000_000, 0, 10**12),    # rata/nota >= N -> Besar
    "tier_sedang": (250_000, 0, 10**12),     # rata/nota >= N -> Sedang
}

# Urutan periksa = urutan urgensi follow-up. Nilai numerik ikut dikeluarkan
# (segmen_urut) supaya mengurut kolom Segmen memberi urutan urgensi, bukan
# abjad — 'Aktif' sebelum 'Hilang' secara abjad justru menyembunyikan yang
# paling perlu dihubungi di halaman terakhir.
SEGMEN_LABEL = {1: "Hilang", 2: "Mulai Jarang", 3: "Baru", 4: "Setia", 5: "Aktif"}


def _amb(f, key: str) -> int:
    """Ambang `key` dari request (sudah jadi string di f), di-clamp ke rentang wajar.

    Di-clamp, bukan divalidasi-lalu-ditolak: laporan yang membalas 500 karena
    seseorang mengetik "abc" di kotak angka lebih buruk daripada laporan yang
    diam-diam memakai nilai bawaan. Karena hasilnya dijamin int, nilainya boleh
    ditanam langsung ke SQL (bukan lewat placeholder) — itu yang menjaga urutan
    parameter tetap sederhana di query berlapis di bawah."""
    default, lo, hi = AMBANG_KLASIFIKASI[key]
    try:
        v = int(float(f.get(key) or default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


SORTS_KLASIFIKASI_PELANGGAN = {
    "customer": "customer", "kota": "kota", "jml_nota": "jml_nota",
    "total_belanja": "total_belanja", "rata_nota": "rata_nota",
    "nota_pertama": "nota_pertama", "nota_terakhir": "nota_terakhir",
    "jeda_hari": "jeda_hari", "umur_hari": "umur_hari",
    "segmen": "segmen_urut", "tier_nilai": "rata_nota",
}
FILTERS_KLASIFIKASI_PELANGGAN = {
    "customer": ("customer", "text"),
    "kota": ("kota", "text"),
    "segmen": ("segmen", "category"),
    "tier_nilai": ("tier_nilai", "category"),
    "jml_nota": ("jml_nota", "number_range"),
    "total_belanja": ("total_belanja", "number_range"),
    "rata_nota": ("rata_nota", "number_range"),
    "jeda_hari": ("jeda_hari", "number_range"),
}
# Tak ada SUMMARY_ untuk laporan ini: halaman mengirim seluruh baris sekali
# (kolumnar) dan menghitung ringkasannya di peramban atas hasil saringan KLIEN.
# Agregat SQL akan menjawab pertanyaan yang berbeda dari yang sedang tampil —
# menyaring satu kota lalu masih melihat hitungan seluruh dataset.
# SORTS_ dan FILTERS_ di atas tetap dipakai: jalur export tetap server-side, dan
# saringan klien diterjemahkan ke parameter itu supaya file Excel-nya cocok
# dengan apa yang terlihat di layar.


def _pseudo_where(where: list, params: list, cust_col: str, nama_col: str) -> None:
    """Buang penampung transaksi & kanal marketplace dari daftar follow-up.

    Disaring dua arah — kode DAN pola nama; alasannya di _PSEUDO_CUSTOMER_NAMES.
    Pelanggan yang kodenya tak ada di m_customer sengaja TIDAK dibuang: namanya
    memang tampil kosong, tapi menyembunyikannya berarti menyembunyikan penjualan
    yang master-nya bermasalah."""
    codes = pseudo_customer_codes()
    if codes:
        where.append(f"UPPER(RTRIM({cust_col})) NOT IN ({','.join('?' * len(codes))})")
        params.extend(codes)
    for nama in pseudo_customer_names():
        where.append(f"COALESCE({nama_col}, '') NOT LIKE ?")
        params.append(f"%{nama}%")


def _segmen_case(f) -> tuple[str, str]:
    """(ekspresi segmen_urut, ekspresi segmen) atas alias keluaran `g`.

    Recency diperiksa SEBELUM 'Baru' dengan sengaja: pelanggan yang sekali datang
    200 hari lalu bukan pendatang baru yang perlu disambut — ia sudah hilang, dan
    itu follow-up yang berbeda. Urutan sebaliknya terlihat sama masuk akal dari
    luar, jadi jangan ditukar tanpa membaca ini.

    `jarang` di-clamp <= `hilang` supaya urutan cabang tetap koheren: tanpa itu
    ambang 'Mulai Jarang' yang lebih besar dari 'Hilang' membuat cabang kedua
    memeriksa syarat yang lebih longgar daripada cabang di atasnya — pembacaan
    kode jadi menyesatkan tanpa mengubah hasil.

    Efeknya: kalau jarang >= hilang, 'Mulai Jarang' memang jadi kosong. Itu
    jawaban yang BENAR untuk ambang seperti itu — semua yang tadinya "mulai
    jarang" sudah masuk "hilang" — dan sengaja tidak dibereskan dengan menukar
    kedua angka. Menukar berarti mengubah "Hilang: jeda lebih dari 180" yang
    diketik pengguna menjadi 400 di belakang punggungnya; segmen kosong yang
    angkanya terlihat di panel filter lebih jujur daripada ambang yang diam-diam
    diganti.
    """
    hilang = _amb(f, "hilang_hari")
    jarang = min(_amb(f, "jarang_hari"), hilang)
    baru = _amb(f, "baru_hari")
    setia = _amb(f, "setia_min_nota")
    # Satu daftar cabang, dua CASE datar atas cabang yang sama. Menyusun label
    # sebagai `CASE WHEN <urut> = 1 THEN ...` akan menanam seluruh CASE angka
    # lima kali dalam satu statement — kelas ledakan ekspresi yang sama yang
    # pernah memicu error 8632 di _ghb (lihat docstringnya).
    cabang = [
        (f"g.jeda_hari > {hilang}", 1),
        (f"g.jeda_hari > {jarang}", 2),
        (f"g.umur_hari <= {baru}", 3),
        (f"g.jml_nota >= {setia}", 4),
    ]
    urut = "CASE " + " ".join(f"WHEN {c} THEN {n}" for c, n in cabang) + " ELSE 5 END"
    label = ("CASE " + " ".join(f"WHEN {c} THEN '{SEGMEN_LABEL[n]}'" for c, n in cabang)
             + f" ELSE '{SEGMEN_LABEL[5]}' END")
    return urut, label


def _klasifikasi_grouped(f) -> tuple[str, list]:
    """Agregat per pelanggan (belum bersegmen). Dipakai laporan & export.

    Nilai nota diambil dari _nota_net — matematika uang yang sudah diaudit di
    modul ini (semantik UDF legacy: diskon dual-mode baris & header, pajak,
    diskon_uang paling akhir). Jangan diganti SUM(qty * harga_jual).

    URUTAN PARAMETER penting dan tidak intuitif: `?` diikat SQL Server menurut
    urutan kemunculan di teks, dan DATEDIFF di daftar SELECT muncul SEBELUM
    subquery nota di klausa FROM. Jadi kedua tanggal acuan mendahului parameter
    _nota_net, bukan sesudahnya."""
    where, params = _base_where(f)
    nota_sql = _nota_net(" AND ".join(where))

    where_outer, params_outer = [], []
    _pseudo_where(where_outer, params_outer, "n.kd_customer", "c.nama")
    if f["search"]:
        where_outer.append("(c.nama LIKE ? OR n.kd_customer LIKE ?)")
        params_outer.extend([f"%{f['search']}%"] * 2)

    anchor = f["date_to"]
    grouped = (
        "SELECT RTRIM(n.kd_customer) AS kd_customer, COALESCE(c.nama, '') AS customer, "
        "COALESCE(c.hp, '') AS hp, COALESCE(c.telepon, '') AS telepon, "
        "COALESCE(mk.nama, '') AS kota, "
        "COUNT(n.no_transaksi) AS jml_nota, "
        "COALESCE(SUM(n.total_bersih), 0) AS total_belanja, "
        "COALESCE(SUM(n.total_bersih) / NULLIF(COUNT(n.no_transaksi), 0), 0) AS rata_nota, "
        "MIN(n.tanggal) AS nota_pertama, MAX(n.tanggal) AS nota_terakhir, "
        "DATEDIFF(day, MAX(n.tanggal), ?) AS jeda_hari, "
        "DATEDIFF(day, MIN(n.tanggal), ?) AS umur_hari "
        f"FROM ({nota_sql}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "LEFT JOIN m_kota mk ON c.kd_kota = mk.kd_kota "
        + (f"WHERE {' AND '.join(where_outer)} " if where_outer else "")
        + "GROUP BY n.kd_customer, c.nama, c.hp, c.telepon, mk.nama"
    )
    return grouped, [anchor, anchor] + params + params_outer


def klasifikasi_pelanggan(f):
    grouped, params = _klasifikasi_grouped(f)
    urut, label = _segmen_case(f)
    besar, sedang = _amb(f, "tier_besar"), _amb(f, "tier_sedang")
    tier = (
        f"CASE WHEN g.rata_nota >= {besar} THEN 'Besar'"
        f" WHEN g.rata_nota >= {sedang} THEN 'Sedang' ELSE 'Kecil' END"
    )
    # Dua level: agregat dulu, segmen sesudahnya. SQL Server tak bisa merujuk
    # alias keluaran (jeda_hari/jml_nota) di SELECT yang sama tempat ia dibuat —
    # bentuk yang sama dipakai fmi_penjualan.
    inner = f"SELECT g.*, {urut} AS segmen_urut, {label} AS segmen, {tier} AS tier_nilai FROM ({grouped}) g"
    return inner, params


# Barang favorit: "biasanya beli apa" — bahan pembuka percakapan saat follow-up.
# Nilai per baris pakai _line_net (diskon level baris), bukan _nota_net: yang
# ditanya di sini kontribusi tiap BARANG, dan diskon header tak bisa dibagi ke
# barang tanpa mengarang aturan alokasi. Angkanya karena itu bisa sedikit lebih
# tinggi dari total_belanja di tabel utama pada nota berdiskon header — beda yang
# disengaja, bukan selisih yang perlu direkonsiliasi.
_FAVORIT_SELECT = (
    "SELECT RTRIM(h.kd_customer) AS kd_customer, COALESCE(c.nama, '') AS customer, "
    "RTRIM(d.kd_barang) AS kd_barang, COALESCE(b.nama, '') AS barang, "
    "COALESCE(SUM(d.qty), 0) AS qty, "
    f"COALESCE(SUM({_line_net('harga_jual')}), 0) AS nilai, "
    "COUNT(DISTINCT d.no_transaksi) AS jml_nota, MAX(h.tanggal) AS terakhir "
    "FROM t_penjualan_detail d "
    "INNER JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
    "LEFT JOIN m_customer c ON h.kd_customer = c.kd_customer "
    "LEFT JOIN m_barang b ON d.kd_barang = b.kd_barang "
)
# HAVING > 0 membuang bonus & pembungkus (BATERAI FREE, KERTAS KADO FREE, kresek).
# Tanpa ini daftar "sering dibeli" diurut qty didominasi barang gratis — terukur
# di data live: tiga teratas hampir setiap pelanggan adalah bonus bernilai nol,
# yang justru bukan pembelian dan tak berguna sebagai pembuka percakapan. Sejalan
# dgn aturan FMI Penjualan yang juga mengecualikan barang tanpa harga jual.
_FAVORIT_GROUP = (
    " GROUP BY h.kd_customer, c.nama, d.kd_barang, b.nama"
    f" HAVING COALESCE(SUM({_line_net('harga_jual')}), 0) > 0"
)

FAVORIT_COLUMNS = [
    {"key": "kd_customer", "label": "Kode Pelanggan"},
    {"key": "customer", "label": "Pelanggan"},
    {"key": "kd_barang", "label": "Kode Barang"},
    {"key": "barang", "label": "Barang"},
    {"key": "qty", "label": "Total Qty"},
    {"key": "nilai", "label": "Total Nilai"},
    {"key": "jml_nota", "label": "Muncul di Nota"},
    {"key": "terakhir", "label": "Terakhir Dibeli"},
]


def barang_favorit_pelanggan(f, kd_customer: str, top_n: int = 20):
    """Barang terbanyak dibeli SATU pelanggan (panel detail). Menyentuh satu
    kd_customer saja, jadi murah walau dipanggil per klik."""
    where, params = _base_where(f)
    where.append("h.kd_customer = ?")
    params.append(kd_customer)
    sql = (
        f"SELECT TOP {int(top_n)} * FROM ({_FAVORIT_SELECT}WHERE {' AND '.join(where)}{_FAVORIT_GROUP}) x "
        "ORDER BY x.qty DESC, x.kd_barang"
    )
    return sql, params


def barang_favorit_massal(f, top_n: int = 5):
    """Top-N barang untuk SETIAP pelanggan — sheet kedua file export.

    ROW_NUMBER per pelanggan, bukan TOP global: tanpa PARTITION BY, beberapa
    pelanggan besar akan memakan seluruh kuota baris dan sisanya tak kebagian
    satu barang pun.

    Menyaring hanya tanggal/divisi/pencarian — TIDAK saringan kolom (segmen,
    kota, kelas nilai). Itu disengaja: ketiganya kolom TURUNAN yang baru ada
    setelah agregasi laporan utama, dan menyaringnya di sini lewat
    `IN (SELECT ... FROM <laporan utama>)` memaksa SQL Server menjalankan ulang
    seluruh agregasi _nota_net di dalam pemeriksaan IN — diukur: query timeout,
    bukan sekadar lambat.

    Penyaringan itu dikerjakan caller di Python atas himpunan kd_customer yang
    sudah dibaca untuk sheet pertama (lihat klasifikasi_pelanggan_export). Aman
    karena populasinya terbatas — profil terbesar ~4.800 pelanggan, dan sheet ini
    paling banyak `top_n` baris per orang.
    """
    where, params = _base_where(f)
    _pseudo_where(where, params, "h.kd_customer", "c.nama")
    if f["search"]:
        where.append("(c.nama LIKE ? OR h.kd_customer LIKE ?)")
        params.extend([f"%{f['search']}%"] * 2)
    ranked = (
        "SELECT x.*, ROW_NUMBER() OVER (PARTITION BY x.kd_customer "
        "ORDER BY x.qty DESC, x.kd_barang) AS rn "
        f"FROM ({_FAVORIT_SELECT}WHERE {' AND '.join(where)}{_FAVORIT_GROUP}) x"
    )
    sql = (
        f"SELECT {', '.join('y.' + c['key'] for c in FAVORIT_COLUMNS)} "
        f"FROM ({ranked}) y WHERE y.rn <= {int(top_n)} "
        "ORDER BY y.customer, y.rn"
    )
    return sql, params


def nota_pelanggan(f, kd_customer: str, top_n: int = 20):
    """Nota terakhir satu pelanggan (panel detail). Filter kd_customer ditaruh DI
    DALAM _nota_net supaya index (kd_customer, tanggal) terpakai untuk menyaring,
    bukan untuk memindai lalu membuang."""
    where, params = _base_where(f)
    where.append("h.kd_customer = ?")
    params.append(kd_customer)
    sql = (
        f"SELECT TOP {int(top_n)} n.no_transaksi, n.tanggal, "
        f"{STATUS_PENJUALAN_CASE.replace('h.status', 'n.status_raw')} AS status, "
        "COALESCE(dv.nama, '') AS divisi, n.total_bersih AS nilai "
        f"FROM ({_nota_net(' AND '.join(where))}) n "
        "LEFT JOIN m_divisi dv ON n.kd_divisi = dv.kd_divisi "
        "ORDER BY n.tanggal DESC"
    )
    return sql, params


# --- Transaksi Barang (transaksi seluruh barang, semua jenis) --------------
SORTS_TRANSAKSI_BARANG = {
    "tanggal": "tanggal", "no_transaksi": "no_transaksi",
    "kd_barang": "kd_barang", "barang": "barang", "transaksi": "transaksi",
}
SUMMARY_TRANSAKSI_BARANG = (
    "COUNT(*) AS jml_baris, COALESCE(SUM(q.masuk), 0) AS total_masuk, "
    "COALESCE(SUM(q.keluar), 0) AS total_keluar"
)

# key -> potongan SELECT dengan placeholder {dp} (predikat tanggal). Kolom
# seragam: kd_divisi, tanggal, transaksi, no_transaksi, kd_barang, masuk,
# keluar, kd_satuan, harga. Id dibiarkan mentah — join master dilakukan sekali
# di wrapper luar. Mengikuti sumber _movement_sql (inventory/services.py),
# TANPA blok [0] Stok Awal (ini laporan transaksi nyata).
_TX_BLOCKS = {
    "pembelian": (
        "SELECT t.kd_divisi, t.tanggal, 'Pembelian' AS transaksi, d.no_transaksi, "
        "d.kd_barang, d.qty AS masuk, 0 AS keluar, d.kd_satuan, d.harga_beli AS harga "
        "FROM t_pembelian_detail d INNER JOIN t_pembelian t ON d.no_transaksi = t.no_transaksi "
        "WHERE {dp} AND t.status IN (0, 1)"
    ),
    "retur_pembelian": (
        "SELECT t.kd_divisi, t.tanggal, 'Retur Pembelian' AS transaksi, d.no_retur AS no_transaksi, "
        "d.kd_barang, 0 AS masuk, d.qty AS keluar, d.kd_satuan, d.harga AS harga "
        "FROM t_pembelian_retur_detail d INNER JOIN t_pembelian_retur t ON d.no_retur = t.no_retur "
        "WHERE {dp}"
    ),
    "penjualan": (
        "SELECT t.kd_divisi, t.tanggal, 'Penjualan' AS transaksi, d.no_transaksi, "
        "d.kd_barang, 0 AS masuk, d.qty AS keluar, d.kd_satuan, d.harga_jual AS harga "
        "FROM t_penjualan_detail d INNER JOIN t_penjualan t ON d.no_transaksi = t.no_transaksi "
        "WHERE {dp}"
    ),
    "retur_penjualan": (
        "SELECT t.kd_divisi, t.tanggal, 'Retur Penjualan' AS transaksi, d.no_retur AS no_transaksi, "
        "d.kd_barang, d.qty AS masuk, 0 AS keluar, d.kd_satuan, d.harga_jual AS harga "
        "FROM t_penjualan_retur_detail d INNER JOIN t_penjualan_retur t ON d.no_retur = t.no_retur "
        "WHERE {dp}"
    ),
    "opname_masuk": (
        "SELECT kd_divisi, tanggal, 'Opname Masuk' AS transaksi, no_transaksi, "
        "kd_barang, qty AS masuk, 0 AS keluar, kd_satuan, 0 AS harga "
        "FROM t_opname_stok WHERE {dp} AND status = 2"
    ),
    "opname_keluar": (
        "SELECT kd_divisi, tanggal, 'Opname Keluar' AS transaksi, no_transaksi, "
        "kd_barang, 0 AS masuk, qty AS keluar, kd_satuan, 0 AS harga "
        "FROM t_opname_stok WHERE {dp} AND status <> 2"
    ),
    "mutasi_masuk": (
        "SELECT t.kd_divisi_tujuan AS kd_divisi, t.tanggal, 'Mutasi Masuk' AS transaksi, d.no_transaksi, "
        "d.kd_barang, d.qty AS masuk, 0 AS keluar, d.kd_satuan, 0 AS harga "
        "FROM t_mutasi_stok_detail d INNER JOIN t_mutasi_stok t ON d.no_transaksi = t.no_transaksi "
        "WHERE {dp}"
    ),
    "mutasi_keluar": (
        "SELECT t.kd_divisi_asal AS kd_divisi, t.tanggal, 'Mutasi Keluar' AS transaksi, d.no_transaksi, "
        "d.kd_barang, 0 AS masuk, d.qty AS keluar, d.kd_satuan, 0 AS harga "
        "FROM t_mutasi_stok_detail d INNER JOIN t_mutasi_stok t ON d.no_transaksi = t.no_transaksi "
        "WHERE {dp}"
    ),
}
TX_JENIS_ORDER = list(_TX_BLOCKS.keys())


def transaksi_barang(*, jenis=None, date_from=None, date_to=None, kd_divisi=None, search=""):
    """Inner SQL (tanpa ORDER BY) untuk laporan transaksi seluruh barang.

    - Tanpa tanggal  -> transaksi SETELAH tutup buku (tanggal > MAX(g_tutup_buku)).
    - Dengan tanggal -> BETWEEN (boleh menembus sebelum tutup buku).
    `jenis` = list key (subset _TX_BLOCKS); kosong = semua. Join master (barang/
    kategori/divisi/satuan) dilakukan sekali di wrapper luar biar ringan.
    """
    def date_pred(col):
        if date_from or date_to:
            parts, p = [], []
            if date_from:
                parts.append(f"{col} >= ?")
                p.append(date_from)
            if date_to:
                parts.append(f"{col} <= ?")
                p.append(date_to)
            return " AND ".join(parts), p
        return f"{col} > (SELECT COALESCE(MAX(tanggal), '19000101') FROM g_tutup_buku)", []

    keys = [k for k in (jenis or []) if k in _TX_BLOCKS] or TX_JENIS_ORDER
    blocks, params = [], []
    for k in keys:
        col = "tanggal" if k.startswith("opname_") else "t.tanggal"
        dp, p = date_pred(col)
        blocks.append(_TX_BLOCKS[k].format(dp=dp))
        params += p

    union = "\nUNION ALL\n".join(blocks)

    outer_where, outer_params = [], []
    if kd_divisi:
        outer_where.append("mv.kd_divisi = ?")
        outer_params.append(kd_divisi)
    if search:
        outer_where.append("(b.nama LIKE ? OR mv.no_transaksi LIKE ? OR mv.kd_barang LIKE ?)")
        outer_params += [f"%{search}%"] * 3
    where_sql = (" WHERE " + " AND ".join(outer_where)) if outer_where else ""

    inner = (
        "SELECT mv.kd_divisi, COALESCE(dv.nama, '') AS divisi, mv.tanggal, mv.transaksi, "
        "mv.no_transaksi, mv.kd_barang, COALESCE(b.nama, '') AS barang, "
        "COALESCE(k.nama, '') AS kategori, mv.masuk, mv.keluar, "
        "mv.kd_satuan, COALESCE(st.nama, '') AS satuan, mv.harga "
        f"FROM (\n{union}\n) mv "
        "INNER JOIN m_barang b ON mv.kd_barang = b.kd_barang "
        "LEFT JOIN m_kategori k ON b.kd_kategori = k.kd_kategori "
        "LEFT JOIN m_divisi dv ON mv.kd_divisi = dv.kd_divisi "
        "LEFT JOIN m_satuan st ON mv.kd_satuan = st.kd_satuan"
        + where_sql
    )
    return inner, params + outer_params

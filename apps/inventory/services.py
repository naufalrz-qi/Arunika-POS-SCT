"""Stock services — ported from .viewandfucntion logic to RAW TABLE queries.

PRD §5.3 + user constraint: NEVER call MS SQL views/functions/SPs. We rebuild the
"kartu stok" movement set (api_v_barang_histori_detail) from base t_*/m_* tables and
do all joins / unit-conversion / aggregation in Python.

A movement dict has: kd_divisi, tanggal, no_transaksi, transaksi, kd_barang,
debet, kredit, kd_satuan, harga, jenis.
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

from core import mssql
from core.cache import _cached, invalidate_master_cache  # noqa: F401 (re-exported)
from apps.core.reporting import dictify as _dictify

# Rolling stock-balance snapshot: SATU set baris terkini per server (bukan
# harian bertumpuk) di tabel `pos_stok_snapshot` pada DB legacy. Membuat blok
# "Stok Awal" jalur baca berhenti me-re-agregasi SELURUH histori sejak tutup
# buku (bisa bertahun-tahun) — cukup baca saldo snapshot + delta transaksi sejak
# tanggal snapshot. Dibangun ulang PENUH tiap malam (self-correcting; error
# window maks 1 hari untuk transaksi backdate — lihat implementation_plan.md §1.5).
SNAPSHOT_TABLE = "pos_stok_snapshot"          # live: saldo as-of ~sekarang (rebuild harian)
SNAPSHOT_BASE_TABLE = "pos_stok_snapshot_base"  # base beku: saldo as-of ~13 bln lalu (rebuild bulanan)


def _snapshot_max_age_days() -> int:
    try:
        return max(1, int(os.environ.get("STOK_SNAPSHOT_MAX_AGE_DAYS", "7")))
    except ValueError:
        return 7


def _snapshot_base_months() -> int:
    try:
        return max(1, int(os.environ.get("STOK_SNAPSHOT_BASE_MONTHS", "13")))
    except ValueError:
        return 13


def _base_date(today=None) -> dt.datetime:
    """Awal bulan ~N bulan lalu (batas region immutable). Data sebelum ini
    diasumsikan tak pernah diedit → base beku aman dipakai sebagai opening."""
    d = today or dt.datetime.now()
    month0 = d.year * 12 + (d.month - 1) - _snapshot_base_months()
    y, m = divmod(month0, 12)
    return dt.datetime(y, m + 1, 1)


def _f(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _s(v) -> str:
    """Safe strip — DB columns like ukuran may come back as float/int/None."""
    if v is None:
        return ""
    return str(v).strip()



def _k(v):
    """Normalize kd_* join keys the way SQL Server CI collation compares them:
    trailing-space and case insensitive. Python dict lookups on raw values miss
    rows the DB itself considers equal ('LYG005' vs 'lyg005') → empty columns."""
    return v.strip().upper() if isinstance(v, str) else v


def _closing_date(cur) -> dt.datetime:
    cur.execute("SELECT MAX(tanggal) FROM g_tutup_buku")
    row = cur.fetchone()
    return row[0] if row and row[0] else dt.datetime(1900, 1, 1)


def _snapshot_meta(cur, table=SNAPSHOT_TABLE):
    """Tanggal set snapshot terkini (datetime) di `table` atau None bila tabel
    belum ada / kosong. Query ringan (satu baris) — dipanggil per _movement_sums."""
    cur.execute("SELECT OBJECT_ID(?)", [table])
    if cur.fetchone()[0] is None:
        return None
    cur.execute(f"SELECT MAX(tanggal) FROM {table}")
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _snapshot_date_if_usable(cur, date_from, date_to):
    """Kembalikan tanggal snapshot bila boleh dipakai sebagai stok awal untuk
    query ini, else None (→ jalur lama re-agregasi penuh).

    v1 forward-only: snapshot hanya menahan saldo SAMPAI tanggalnya, jadi query
    yang butuh saldo SEBELUM tanggal snapshot (date_to/date_from < snapshot)
    tak bisa dilayani → fallback. Juga fallback bila snapshot basi (> N hari)."""
    snap = _snapshot_meta(cur)
    if snap is None:
        return None
    if (dt.datetime.now() - snap).days > _snapshot_max_age_days():
        return None
    if date_to is not None and date_to < snap:
        return None
    if date_from is not None and date_from < snap:
        return None
    return snap


def _unit_factors(cur) -> dict:
    """(kd_barang, kd_satuan) -> jumlah (qty in smallest unit per 1 of this unit)."""
    cur.execute("SELECT kd_barang, kd_satuan, jumlah FROM m_barang_satuan")
    return {(_k(r["kd_barang"]), _k(r["kd_satuan"])): _f(r["jumlah"]) for r in _dictify(cur)}


# --- Movement set (the 9 UNION ALL sources, table-level) --------------------

def _movement_sql(closing, *, kd_barang=None, kd_divisi=None, date_to=None, date_from=None, snapshot_date=None, snapshot_table=SNAPSHOT_TABLE):
    """Build the UNION ALL movement query + params. Optional filters are applied
    inside every source so the DB can seek instead of scanning.

    `date_from` bounds transaction-based sources ([1]-[8]) only — never block
    [0] Stok Awal (a point-in-time opening balance, not a dated movement).
    Callers that need pre-date_from history for a running balance (stock_card,
    _movement_sums) must not pass it.

    `snapshot_date` (opt): when set, block [0] Stok Awal is read from the rolling
    `pos_stok_snapshot` (saldo base-unit at that date) INSTEAD of re-aggregating
    from m_barang_divisi + full history since closing, and the transaction
    sources are bounded to `tanggal > snapshot_date` instead of `> closing`.
    Net result is identical (snapshot saldo already folds in movement
    closing..snapshot_date) but the delta window shrinks to a few days."""
    params: list = []
    # Transaction sources start just after the opening balance point: snapshot
    # date when using the snapshot, else the book-closing date.
    txn_boundary = snapshot_date if snapshot_date else closing

    def trans_filters(tcol, dcol, divcol):
        """Common WHERE tail for transaction-based sources (closing/date/div/barang)."""
        clause = f" AND {tcol} <= ?" if date_to else ""
        p = [date_to] if date_to else []
        if date_from:
            clause += f" AND {tcol} >= ?"
            p.append(date_from)
        if kd_divisi:
            clause += f" AND {divcol} = ?"
            p.append(kd_divisi)
        if kd_barang:
            clause += f" AND {dcol} = ?"
            p.append(kd_barang)
        return clause, p

    blocks: list[str] = []

    if snapshot_date:
        # [0] Stok Awal dari snapshot. saldo sudah base-unit → kd_satuan NULL agar
        # LEFT JOIN faktor di _movement_sums tak match (COALESCE(jumlah,1)=1, tanpa
        # konversi ganda). Tagged tanggal = snapshot_date supaya jatuh ke bucket
        # stok_awal bila date_from > snapshot_date.
        b0 = (
            "SELECT s.kd_divisi, ? AS tanggal, '0' AS no_transaksi, 'Stok Awal' AS transaksi, "
            "s.kd_barang, s.saldo AS debet, 0 AS kredit, NULL AS kd_satuan, 0 AS harga, 0 AS jenis "
            f"FROM {snapshot_table} s WHERE s.tanggal = ?"
        )
        params.append(snapshot_date)  # tanggal tag
        params.append(snapshot_date)  # WHERE s.tanggal = ?
        if kd_divisi:
            b0 += " AND s.kd_divisi = ?"
            params.append(kd_divisi)
        if kd_barang:
            b0 += " AND s.kd_barang = ?"
            params.append(kd_barang)
        blocks.append(b0)
    else:
        # [0] Stok Awal — no date filter (it is the opening balance at closing date).
        b0 = (
            "SELECT bd.kd_divisi, ? AS tanggal, '0' AS no_transaksi, 'Stok Awal' AS transaksi, "
            "bd.kd_barang, bd.stok_awal AS debet, 0 AS kredit, bs.kd_satuan, bd.harga_beli_awal AS harga, 0 AS jenis "
            "FROM m_barang_divisi bd "
            "INNER JOIN m_barang b ON bd.kd_barang = b.kd_barang "
            "INNER JOIN m_kategori k ON b.kd_kategori = k.kd_kategori AND k.status <> 2 "
            "INNER JOIN m_barang_satuan bs ON bd.kd_barang = bs.kd_barang AND bs.jumlah = 1 "
            "WHERE 1=1"
        )
        params.append(closing)
        if kd_divisi:
            b0 += " AND bd.kd_divisi = ?"
            params.append(kd_divisi)
        if kd_barang:
            b0 += " AND bd.kd_barang = ?"
            params.append(kd_barang)
        blocks.append(b0)

    # [1] Mutasi Keluar (-)
    c, p = trans_filters("t.tanggal", "d.kd_barang", "t.kd_divisi_asal")
    blocks.append(
        "SELECT t.kd_divisi_asal, t.tanggal, d.no_transaksi, 'Mutasi Keluar', d.kd_barang, "
        "0, d.qty, d.kd_satuan, 0, 1 "
        "FROM t_mutasi_stok_detail d INNER JOIN t_mutasi_stok t ON d.no_transaksi = t.no_transaksi "
        "WHERE t.tanggal > ?" + c
    )
    params += [txn_boundary] + p

    # [2] Mutasi Masuk (+)
    c, p = trans_filters("t.tanggal", "d.kd_barang", "t.kd_divisi_tujuan")
    blocks.append(
        "SELECT t.kd_divisi_tujuan, t.tanggal, d.no_transaksi, 'Mutasi Masuk', d.kd_barang, "
        "d.qty, 0, d.kd_satuan, 0, 2 "
        "FROM t_mutasi_stok_detail d INNER JOIN t_mutasi_stok t ON d.no_transaksi = t.no_transaksi "
        "WHERE t.tanggal > ?" + c
    )
    params += [txn_boundary] + p

    # [3/4] Opname (status=2 masuk, else keluar)
    c, p = trans_filters("tanggal", "kd_barang", "kd_divisi")
    blocks.append(
        "SELECT kd_divisi, tanggal, no_transaksi, "
        "CASE WHEN status = 2 THEN 'Opname Masuk' ELSE 'Opname Keluar' END, kd_barang, "
        "CASE WHEN status = 2 THEN qty ELSE 0 END, CASE WHEN status <> 2 THEN qty ELSE 0 END, "
        "kd_satuan, 0, CASE WHEN status = 2 THEN 3 ELSE 4 END "
        "FROM t_opname_stok WHERE tanggal > ?" + c
    )
    params += [txn_boundary] + p

    # [5] Pembelian (+)
    c, p = trans_filters("t.tanggal", "d.kd_barang", "t.kd_divisi")
    blocks.append(
        "SELECT t.kd_divisi, t.tanggal, d.no_transaksi, 'Pembelian', d.kd_barang, "
        "d.qty, 0, d.kd_satuan, d.harga_beli, 5 "
        "FROM t_pembelian_detail d INNER JOIN t_pembelian t ON d.no_transaksi = t.no_transaksi "
        "WHERE t.tanggal > ? AND t.status IN (0, 1)" + c
    )
    params += [txn_boundary] + p

    # [6] Retur Pembelian (-)
    c, p = trans_filters("t.tanggal", "d.kd_barang", "t.kd_divisi")
    blocks.append(
        "SELECT t.kd_divisi, t.tanggal, d.no_retur, 'Retur Pembelian', d.kd_barang, "
        "0, d.qty, d.kd_satuan, d.harga, 6 "
        "FROM t_pembelian_retur_detail d INNER JOIN t_pembelian_retur t ON d.no_retur = t.no_retur "
        "WHERE t.tanggal > ?" + c
    )
    params += [txn_boundary] + p

    # [7] Penjualan (-) — non-service categories only
    c, p = trans_filters("t.tanggal", "d.kd_barang", "t.kd_divisi")
    blocks.append(
        "SELECT t.kd_divisi, t.tanggal, d.no_transaksi, 'Penjualan', d.kd_barang, "
        "0, d.qty, d.kd_satuan, d.harga_jual, 7 "
        "FROM t_penjualan_detail d "
        "INNER JOIN t_penjualan t ON d.no_transaksi = t.no_transaksi "
        "INNER JOIN m_barang b ON d.kd_barang = b.kd_barang "
        "INNER JOIN m_kategori k ON b.kd_kategori = k.kd_kategori AND k.status <> 2 "
        "WHERE t.tanggal > ?" + c
    )
    params += [txn_boundary] + p

    # [8] Retur Penjualan (+)
    c, p = trans_filters("t.tanggal", "d.kd_barang", "t.kd_divisi")
    blocks.append(
        "SELECT t.kd_divisi, t.tanggal, d.no_retur, 'Retur Penjualan', d.kd_barang, "
        "d.qty, 0, d.kd_satuan, d.harga_jual, 8 "
        "FROM t_penjualan_retur_detail d INNER JOIN t_penjualan_retur t ON d.no_retur = t.no_retur "
        "WHERE t.tanggal > ?" + c
    )
    params += [txn_boundary] + p

    return "\nUNION ALL\n".join(blocks), params


def _fetch_movements(cur, *, kd_barang=None, kd_divisi=None, date_to=None, date_from=None) -> list[dict]:
    closing = _closing_date(cur)
    sql, params = _movement_sql(
        closing, kd_barang=kd_barang, kd_divisi=kd_divisi, date_to=date_to, date_from=date_from
    )
    cur.execute(sql, params)
    return _dictify(cur)


def _movement_sums(cur, *, kd_divisi=None, date_from=None, date_to=None, use_snapshot=True,
                   snapshot_date=None, snapshot_table=SNAPSHOT_TABLE) -> list[dict]:
    """Movement UNION aggregated IN SQL per (kd_divisi, kd_barang), in base units.

    Row transfer scales with catalog size instead of transaction count — on real
    stores (millions of detail rows) streaming movements to Python dominates page
    time. Plain SELECT + GROUP BY only (no views/functions/SPs per PRD §5.3).
    Returns: stok_awal (movement before date_from), masuk, keluar (>= date_from);
    with date_from=None everything lands in masuk/keluar.

    `use_snapshot`: when True (default) and a fresh, applicable `pos_stok_snapshot`
    exists, the opening block reads from it and the transaction window shrinks to
    movement since the snapshot date — same total, far less scanned. The snapshot
    BUILDER must pass use_snapshot=False so its nightly rebuild is a full,
    self-correcting recompute (catches backdated rows) rather than snapshot+delta.
    """
    closing = _closing_date(cur)
    # Builder boleh menyuntik opening eksplisit (mis. live rebuild baca dari base);
    # jalur baca biasa auto-resolve dari tabel live.
    snap_date = snapshot_date
    if snap_date is None and use_snapshot:
        snap_date = _snapshot_date_if_usable(cur, date_from, date_to)
    inner, params = _movement_sql(
        closing, kd_divisi=kd_divisi, date_to=date_to,
        snapshot_date=snap_date, snapshot_table=snapshot_table,
    )
    boundary = date_from or dt.datetime(1900, 1, 1)
    # MAX(jumlah) dedupes (kd_barang, kd_satuan); missing factor falls back to 1
    # like factors.get(..., 1.0) in the Python path.
    sql = (
        "SELECT mv.kd_divisi, mv.kd_barang, "
        "SUM(CASE WHEN mv.tanggal < ? THEN CAST((COALESCE(mv.debet, 0) - COALESCE(mv.kredit, 0)) * COALESCE(bs.jumlah, 1) AS FLOAT) ELSE 0 END) AS stok_awal, "
        "SUM(CASE WHEN mv.tanggal >= ? THEN CAST(COALESCE(mv.debet, 0) * COALESCE(bs.jumlah, 1) AS FLOAT) ELSE 0 END) AS masuk, "
        "SUM(CASE WHEN mv.tanggal >= ? THEN CAST(COALESCE(mv.kredit, 0) * COALESCE(bs.jumlah, 1) AS FLOAT) ELSE 0 END) AS keluar "
        f"FROM (\n{inner}\n) mv "
        "LEFT JOIN (SELECT kd_barang, kd_satuan, MAX(jumlah) AS jumlah "
        "FROM m_barang_satuan GROUP BY kd_barang, kd_satuan) bs "
        "ON mv.kd_barang = bs.kd_barang AND mv.kd_satuan = bs.kd_satuan "
        "GROUP BY mv.kd_divisi, mv.kd_barang "
        # Skip all-zero groups (opening stock 0, no movement) — both consumers
        # drop them anyway, and they are ~75% of the catalog on real stores.
        "HAVING SUM(CASE WHEN mv.tanggal < ? THEN CAST((COALESCE(mv.debet, 0) - COALESCE(mv.kredit, 0)) * COALESCE(bs.jumlah, 1) AS FLOAT) ELSE 0 END) <> 0 "
        "OR SUM(CASE WHEN mv.tanggal >= ? THEN CAST(COALESCE(mv.debet, 0) * COALESCE(bs.jumlah, 1) AS FLOAT) ELSE 0 END) <> 0 "
        "OR SUM(CASE WHEN mv.tanggal >= ? THEN CAST(COALESCE(mv.kredit, 0) * COALESCE(bs.jumlah, 1) AS FLOAT) ELSE 0 END) <> 0"
    )
    cur.execute(sql, [boundary, boundary, boundary] + params + [boundary, boundary, boundary])
    return _dictify(cur)


# --- Snapshot builder (dua lapis: base beku + live) ------------------------

def _ensure_snapshot_table(profile, table=SNAPSHOT_TABLE) -> None:
    """Buat tabel snapshot di DB legacy bila belum ada (idempotent). Pola DDL
    sama dengan apps/transactions/indexes.py (SET options + IF OBJECT_ID)."""
    with mssql.cursor(profile) as cur:
        cur.execute("SET ANSI_NULLS ON")
        cur.execute("SET QUOTED_IDENTIFIER ON")
        cur.execute(
            f"IF OBJECT_ID('{table}', 'U') IS NULL "
            f"CREATE TABLE {table} ("
            "kd_divisi varchar(30) NOT NULL, kd_barang varchar(30) NOT NULL, "
            "saldo float NOT NULL, tanggal datetime2 NOT NULL, "
            f"CONSTRAINT PK_{table} PRIMARY KEY CLUSTERED (kd_divisi, kd_barang))"
        )


def _sums_to_rows(sums, tanggal) -> list:
    """(stok_awal+masuk-keluar) per SKU → baris (kd_divisi, kd_barang, saldo, tanggal).
    Lewati saldo 0 (opening 0 tak perlu blok)."""
    rows = []
    for m in sums:
        saldo = _f(m["stok_awal"]) + _f(m["masuk"]) - _f(m["keluar"])
        if round(saldo, 3) == 0:
            continue
        rows.append(((m["kd_divisi"] or "").strip(), (m["kd_barang"] or "").strip(), saldo, tanggal))
    return rows


def _write_snapshot(profile, table, rows) -> None:
    """DELETE+INSERT satu set snapshot dalam satu transaksi (fast_executemany,
    pola cdc_sync.backfill_table)."""
    _ensure_snapshot_table(profile, table)
    with mssql.cursor(profile, autocommit=False) as cur:
        cur.execute(f"DELETE FROM {table}")
        if rows:
            cur.fast_executemany = True
            cur.executemany(
                f"INSERT INTO {table} (kd_divisi, kd_barang, saldo, tanggal) VALUES (?, ?, ?, ?)",
                rows,
            )
        cur.connection.commit()


def snapshot_stok_base(profile) -> dict:
    """Bangun ulang BASE beku: saldo per SKU as-of `base_date` (~13 bln lalu).

    Recompute PENUH sejak tutup buku (`use_snapshot=False`) — berat tapi jarang
    (hanya saat bulan base bergeser). Region ini immutable, jadi hasilnya stabil.
    Return {"rows": n, "base_date": base_dt}."""
    base_dt = _base_date()
    with mssql.report_cursor(profile) as rcur:
        sums = _movement_sums(rcur, date_to=base_dt, use_snapshot=False)
    rows = _sums_to_rows(sums, base_dt)
    _write_snapshot(profile, SNAPSHOT_BASE_TABLE, rows)
    return {"rows": len(rows), "base_date": base_dt}


def snapshot_stok(profile) -> dict:
    """Bangun ulang LIVE: saldo per SKU as-of sekarang (satu set per server).

    Opening dibaca dari BASE beku (bila ada) → hanya scan pergerakan sejak
    base_date (≈13 bln), menangkap edit backdate dalam window. Bila base belum
    ada (first run) → fallback recompute penuh sejak tutup buku (perilaku lama,
    tetap benar). Return {"rows": n, "tanggal": snap_ts}."""
    snap_ts = dt.datetime.now()
    with mssql.report_cursor(profile) as rcur:
        base_dt = _snapshot_meta(rcur, SNAPSHOT_BASE_TABLE)
        if base_dt is not None:
            sums = _movement_sums(
                rcur, date_to=snap_ts, snapshot_date=base_dt, snapshot_table=SNAPSHOT_BASE_TABLE,
            )
        else:
            sums = _movement_sums(rcur, date_to=snap_ts, use_snapshot=False)
    rows = _sums_to_rows(sums, snap_ts)
    _write_snapshot(profile, SNAPSHOT_TABLE, rows)
    return {"rows": len(rows), "tanggal": snap_ts}


# --- Public services -------------------------------------------------------

def list_divisi(profile) -> list[dict]:
    with mssql.report_cursor(profile) as cur:
        cur.execute("SELECT kd_divisi, nama FROM m_divisi WHERE status <> 0 ORDER BY nama")
        return [
            {"kd_divisi": (r["kd_divisi"] or "").strip(), "nama": (r["nama"] or "").strip()}
            for r in _dictify(cur)
        ]


def search_barang(profile, search="", limit=50) -> list[dict]:
    where, params = ["status <> 0"], []
    if search:
        where.append("(nama LIKE ? OR kd_barang LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    with mssql.report_cursor(profile) as cur:
        cur.execute(
            f"SELECT TOP {limit} kd_barang, nama FROM m_barang WHERE {' AND '.join(where)} ORDER BY nama",
            params,
        )
        return [
            {"kd_barang": (r["kd_barang"] or "").strip(), "nama": (r["nama"] or "").strip()}
            for r in _dictify(cur)
        ]


def stock_card(profile, kd_barang, kd_divisi=None, date_from=None, date_to=None) -> dict:
    """Kartu stok for one product: movements + running base-unit saldo."""
    with mssql.report_cursor(profile) as cur:
        factors = _cached(profile, "factors", lambda: _unit_factors(cur))
        moves = _fetch_movements(cur, kd_barang=kd_barang, kd_divisi=kd_divisi or None, date_to=date_to)
        divisi = {_k(r["kd_divisi"]): r["nama"] for r in _div_rows(cur)}
        satuan = {_k(r["kd_satuan"]): r["nama"] for r in _satuan_rows(cur)}
        bname = _barang_name(cur, kd_barang)

    moves.sort(key=lambda m: (m["tanggal"], m["jenis"]))

    rows = []
    saldo = 0.0
    opening = 0.0
    for m in moves:
        factor = factors.get((_k(m["kd_barang"]), _k(m["kd_satuan"])), 1.0)
        delta = factor * (_f(m["debet"]) - _f(m["kredit"]))
        saldo += delta
        if date_from and m["tanggal"] < date_from:
            opening = saldo
            continue  # rolled into "saldo awal", not displayed
        rows.append(
            {
                "tanggal": m["tanggal"].strftime("%Y-%m-%d %H:%M") if hasattr(m["tanggal"], "strftime") else str(m["tanggal"]),
                "transaksi": m["transaksi"],
                "no_transaksi": (m["no_transaksi"] or "").strip(),
                "divisi": divisi.get(_k(m["kd_divisi"]), (m["kd_divisi"] or "").strip()),
                "debet": _f(m["debet"]),
                "kredit": _f(m["kredit"]),
                "satuan": satuan.get(_k(m["kd_satuan"]), (m["kd_satuan"] or "").strip()),
                "harga": _f(m["harga"]),
                "saldo": round(saldo, 3),
            }
        )

    return {
        "kd_barang": kd_barang,
        "nama": bname,
        "saldo_awal": round(opening, 3),
        "saldo_akhir": round(saldo, 3),
        "rows": rows,
    }


def stok_awal_barang(profile, cutoff=None) -> list[dict]:
    """Stok awal per barang, ditotal lintas divisi.

    - cutoff None       -> saldo awal seed tersimpan (m_barang_divisi.stok_awal),
                           yaitu baris 'Stok Awal' [0] di kartu stok.
    - cutoff (datetime) -> saldo berjalan tepat SEBELUM cutoff, identik dengan
                           kolom 'Stok Awal' di Barang Histori (_movement_sums
                           date_from=cutoff).
    """
    with mssql.report_cursor(profile) as cur:
        meta = _cached(profile, "meta", lambda: _barang_meta(cur))
        if cutoff is None:
            # Mirror blok [0] _movement_sql: base-unit (jumlah=1), kategori non-jasa.
            cur.execute(
                "SELECT bd.kd_barang, SUM(bd.stok_awal) AS stok_awal "
                "FROM m_barang_divisi bd "
                "INNER JOIN m_barang b ON bd.kd_barang = b.kd_barang "
                "INNER JOIN m_kategori k ON b.kd_kategori = k.kd_kategori AND k.status <> 2 "
                "INNER JOIN m_barang_satuan bs ON bd.kd_barang = bs.kd_barang AND bs.jumlah = 1 "
                "GROUP BY bd.kd_barang"
            )
            agg = {_k(r["kd_barang"]): _f(r["stok_awal"]) for r in _dictify(cur)}
        else:
            sums = _movement_sums(cur, date_from=cutoff)  # stok_awal = saldo < cutoff
            agg = {}
            for m in sums:
                kb = _k(m["kd_barang"])
                agg[kb] = agg.get(kb, 0.0) + _f(m["stok_awal"])

    out = []
    for kb, stok in agg.items():
        if not stok:  # buang barang stok awal 0 (sama seperti app)
            continue
        info = meta.get(kb, {})
        out.append({
            "kd_barang": kb.strip() if isinstance(kb, str) else kb,
            "barang": info.get("nama", ""),
            "kategori": info.get("kategori", ""),
            "stok_awal": round(stok, 3),
        })
    out.sort(key=lambda r: r["barang"])
    return out


def mutasi_stok(profile, date_from=None, date_to=None, kd_divisi=None) -> list[dict]:
    """Mutasi stok per barang untuk sebuah periode, dengan asumsi stok awal = 0.

    'stok' = masuk - keluar dari transaksi dalam rentang [date_from, date_to];
    saldo/seed sebelum date_from diabaikan (itulah asumsi stok awal 0). Ditotal
    lintas divisi kecuali kd_divisi diberikan. Reuse _movement_sums biar konsisten
    dengan Stok Akhir / Barang Histori.
    """
    date_to = date_to or dt.datetime.now()
    with mssql.report_cursor(profile) as cur:
        sums = _movement_sums(cur, kd_divisi=kd_divisi or None, date_from=date_from, date_to=date_to)
        meta = _cached(profile, "meta", lambda: _barang_meta(cur))
        divisi = {_k(r["kd_divisi"]): r["nama"] for r in _div_rows(cur)}

    per_divisi = bool(kd_divisi)
    agg: dict = {}
    for m in sums:
        key = (_k(m["kd_divisi"]), _k(m["kd_barang"])) if per_divisi else (None, _k(m["kd_barang"]))
        a = agg.setdefault(key, {"masuk": 0.0, "keluar": 0.0})
        a["masuk"] += _f(m["masuk"])
        a["keluar"] += _f(m["keluar"])

    out = []
    for (kdiv, kb), a in agg.items():
        if not (a["masuk"] or a["keluar"]):  # hanya barang yang bergerak dalam periode
            continue
        info = meta.get(kb, {})
        out.append({
            "kd_barang": kb.strip() if isinstance(kb, str) else kb,
            "barang": info.get("nama", ""),
            "kategori": info.get("kategori", ""),
            "divisi": divisi.get(kdiv, "Semua Divisi") if per_divisi else "Semua Divisi",
            "masuk": round(a["masuk"], 3),
            "keluar": round(a["keluar"], 3),
            "stok": round(a["masuk"] - a["keluar"], 3),
        })
    out.sort(key=lambda r: r["barang"])
    return out


def stock_levels(profile, kd_divisi=None, date_from=None, date_to=None, search="", kd_kategori="") -> list[dict]:
    """Stok akhir per barang (and per divisi unless 'all'), computed from movements.

    - kd_divisi None  -> Semua Divisi (aggregate across divisions, per barang)
    - date_from None  -> stok akhir as-of date_to (everything counts as 'masuk/keluar' net)
    - date_from set   -> period: stok_awal (before), masuk/keluar (within), stok_akhir
    """
    date_to = date_to or dt.datetime.now()
    with mssql.report_cursor(profile) as cur:
        sums = _movement_sums(cur, kd_divisi=kd_divisi or None, date_from=date_from, date_to=date_to)
        divisi = {_k(r["kd_divisi"]): r["nama"] for r in _div_rows(cur)}
        # kd_barang -> {nama, kategori, kd_kategori, jenis, supplier, status}
        meta = _cached(profile, "meta", lambda: _barang_meta(cur))
        stok_min = _cached(profile, "stok_min", lambda: _stok_min_map(cur))

    # stok_min is per (divisi, barang) in the legacy schema; when aggregating
    # across all divisions there is no single threshold, so sum it — a
    # combined "org-wide" minimum makes more sense than dropping the badge.
    stok_min_by_kb: dict = {}
    for (_d, _kb), _v in stok_min.items():
        stok_min_by_kb[_kb] = stok_min_by_kb.get(_kb, 0.0) + _v

    # group key: per barang, or per (divisi, barang) when a specific divisi is chosen
    per_divisi = bool(kd_divisi)
    agg: dict = {}
    for m in sums:
        key = (_k(m["kd_divisi"]), _k(m["kd_barang"])) if per_divisi else (None, _k(m["kd_barang"]))
        a = agg.setdefault(key, {"stok_awal": 0.0, "masuk": 0.0, "keluar": 0.0})
        a["stok_awal"] += _f(m["stok_awal"])
        a["masuk"] += _f(m["masuk"])
        a["keluar"] += _f(m["keluar"])

    out = []
    for (kdiv, kb), a in agg.items():
        info = meta.get(kb, {})
        if kd_kategori and info.get("kd_kategori") != kd_kategori:
            continue
        nama = info.get("nama", "")
        if search:
            s = search.lower()
            if s not in nama.lower() and s not in kb.lower():
                continue
        stok_akhir = a["stok_awal"] + a["masuk"] - a["keluar"]
        # Skip products with no stock and no movement in the period (noise).
        if not (a["stok_awal"] or a["masuk"] or a["keluar"] or stok_akhir):
            continue
        out.append(
            {
                "kd_barang": kb.strip() if isinstance(kb, str) else kb,
                "nama": nama,
                "kategori": info.get("kategori", ""),
                "jenis": info.get("jenis", ""),
                "supplier": info.get("supplier", ""),
                "divisi": divisi.get(kdiv, "Semua Divisi") if per_divisi else "Semua Divisi",
                "stok_awal": round(a["stok_awal"], 3),
                "masuk": round(a["masuk"], 3),
                "keluar": round(a["keluar"], 3),
                "stok_akhir": round(stok_akhir, 3),
                "stok_min": round(stok_min.get((kdiv, kb), 0.0) if per_divisi else stok_min_by_kb.get(kb, 0.0), 3),
            }
        )
    # Return ALL items with stock or movement (no cap — client filters/searches).
    out.sort(key=lambda r: r["nama"])
    return out


# --- small lookup helpers --------------------------------------------------

def _div_rows(cur):
    cur.execute("SELECT kd_divisi, nama FROM m_divisi")
    return _dictify(cur)


def _satuan_rows(cur):
    cur.execute("SELECT kd_satuan, nama FROM m_satuan")
    return _dictify(cur)


def _barang_name(cur, kd_barang) -> str:
    cur.execute("SELECT nama FROM m_barang WHERE kd_barang = ?", [kd_barang])
    row = cur.fetchone()
    return (row[0] or "").strip() if row else ""


def _barang_meta(cur) -> dict:
    """kd_barang -> names for kategori/jenis/supplier/merk/model/warna/ukuran (joined in Python)."""
    kat = {_k(r["kd_kategori"]): r["nama"] for r in _q(cur, "SELECT kd_kategori, nama FROM m_kategori")}
    jenis = {_k(r["kd_jenis_bahan"]): r["nama"] for r in _q(cur, "SELECT kd_jenis_bahan, nama FROM m_jenis_bahan")}
    merk = {_k(r["kd_merk"]): r["nama"] for r in _q(cur, "SELECT kd_merk, nama FROM m_merk")}
    model = {_k(r["kd_model"]): r["nama"] for r in _q(cur, "SELECT kd_model, nama FROM m_model")}
    warna = {_k(r["kd_warna"]): r["nama"] for r in _q(cur, "SELECT kd_warna, nama FROM m_warna")}
    # first supplier per barang
    supp_name = {_k(r["kd_supplier"]): r["nama"] for r in _q(cur, "SELECT kd_supplier, nama FROM m_supplier")}
    barang_supp: dict = {}
    for r in _q(cur, "SELECT kd_barang, kd_supplier FROM m_barang_supplier"):
        barang_supp.setdefault(_k(r["kd_barang"]), supp_name.get(_k(r["kd_supplier"]), ""))

    meta = {}
    for r in _q(cur, "SELECT kd_barang, nama, kd_kategori, kd_jenis_bahan, kd_merk, kd_model, kd_warna, ukuran, status FROM m_barang"):
        kb = _k(r["kd_barang"])
        meta[kb] = {
            "nama": (r["nama"] or "").strip(),
            "kd_kategori": (r["kd_kategori"] or "").strip(),
            "kategori": (kat.get(_k(r["kd_kategori"]), "") or "").strip(),
            "jenis": (jenis.get(_k(r["kd_jenis_bahan"]), "") or "").strip(),
            "merk": (merk.get(_k(r["kd_merk"]), "") or "").strip(),
            "model": (model.get(_k(r["kd_model"]), "") or "").strip(),
            "warna": (warna.get(_k(r["kd_warna"]), "") or "").strip(),
            "ukuran": _s(r["ukuran"]),
            "supplier": barang_supp.get(kb, ""),
            "status": str(r["status"]).strip(),
        }
    return meta


def _div_rows_full(cur):
    """Divisi rows including kepala_nota."""
    cur.execute("SELECT kd_divisi, nama, kepala_nota FROM m_divisi")
    return _dictify(cur)


def _harga_jual_map(cur) -> dict:
    """kd_barang -> harga_jual (satuan terkecil, jumlah=1)."""
    cur.execute("SELECT kd_barang, harga_jual FROM m_barang_satuan WHERE jumlah = 1")
    return {_k(r["kd_barang"]): _f(r["harga_jual"]) for r in _dictify(cur)}


def _stok_min_map(cur) -> dict:
    """(kd_divisi, kd_barang) -> stok_min, from m_barang_divisi."""
    cur.execute("SELECT kd_divisi, kd_barang, stok_min FROM m_barang_divisi")
    return {(_k(r["kd_divisi"]), _k(r["kd_barang"])): _f(r["stok_min"]) for r in _dictify(cur)}


def _purchase_prices(cur, tanggal) -> tuple[dict, dict, dict]:
    """(harga_average_map, harga_beli_akhir_map, harga_beli_awal_map) — kd_barang -> float."""
    cur.execute(
        """
        SELECT pd.kd_barang,
            SUM(pd.qty * pd.harga_beli / NULLIF(bs.jumlah, 0))
                / NULLIF(SUM(pd.qty / NULLIF(bs.jumlah, 0)), 0) AS harga_avg
        FROM t_pembelian_detail pd
        INNER JOIN t_pembelian p ON pd.no_transaksi = p.no_transaksi
        INNER JOIN m_barang_satuan bs ON pd.kd_barang = bs.kd_barang AND pd.kd_satuan = bs.kd_satuan
        WHERE CONVERT(DATE, p.tanggal) <= ? AND p.status IN (0, 1)
        GROUP BY pd.kd_barang
        """,
        [tanggal],
    )
    avg_map = {_k(r["kd_barang"]): _f(r["harga_avg"]) for r in _dictify(cur)}

    # Last purchase price per base unit — picked in SQL (ROW_NUMBER, still a plain
    # SELECT) instead of streaming every purchase row to Python.
    cur.execute(
        """
        SELECT x.kd_barang, x.harga_per_unit FROM (
            SELECT pd.kd_barang,
                pd.harga_beli / NULLIF(bs.jumlah, 0) AS harga_per_unit,
                ROW_NUMBER() OVER (PARTITION BY pd.kd_barang ORDER BY p.tanggal DESC, p.no_transaksi DESC) AS rn
            FROM t_pembelian_detail pd
            INNER JOIN t_pembelian p ON pd.no_transaksi = p.no_transaksi
            INNER JOIN m_barang_satuan bs ON pd.kd_barang = bs.kd_barang AND pd.kd_satuan = bs.kd_satuan
            WHERE CONVERT(DATE, p.tanggal) <= ? AND p.status IN (0, 1)
        ) x WHERE x.rn = 1
        """,
        [tanggal],
    )
    last_map = {_k(r["kd_barang"]): _f(r["harga_per_unit"]) for r in _dictify(cur)}

    cur.execute("SELECT kd_barang, harga_beli_awal FROM m_barang_divisi")
    init_map: dict = {}
    for r in _dictify(cur):
        init_map.setdefault(_k(r["kd_barang"]), _f(r["harga_beli_awal"]))

    return avg_map, last_map, init_map


def stok_akhir_per_tanggal(profile, tanggal, kd_divisi=None) -> list[dict]:
    """Stok akhir per (divisi, barang) at tanggal — matches api_GetStokAkhirPerTanggal schema."""
    if isinstance(tanggal, dt.date) and not isinstance(tanggal, dt.datetime):
        tanggal = dt.datetime(tanggal.year, tanggal.month, tanggal.day, 23, 59, 59)

    with mssql.report_cursor(profile) as cur:
        sums = _movement_sums(cur, kd_divisi=kd_divisi or None, date_to=tanggal)
        divisi = {_k(r["kd_divisi"]): r for r in _div_rows_full(cur)}
        meta = _cached(profile, "meta", lambda: _barang_meta(cur))
        harga_jual = _cached(profile, "harga_jual", lambda: _harga_jual_map(cur))
        avg_map, last_map, init_map = _purchase_prices(cur, tanggal)

    agg: dict = {}
    for m in sums:
        key = (_k(m["kd_divisi"]), _k(m["kd_barang"]))
        agg[key] = agg.get(key, 0.0) + _f(m["masuk"]) - _f(m["keluar"]) + _f(m["stok_awal"])

    out = []
    for (kd_div, kb), stok in agg.items():
        if stok == 0:
            continue
        info = meta.get(kb, {})
        harga_avg = avg_map.get(kb) or init_map.get(kb, 0.0)
        harga_beli = last_map.get(kb) or init_map.get(kb, 0.0)
        div_info = divisi.get(kd_div, {})
        out.append({
            "kd_divisi": (kd_div or "").strip(),
            "divisi": (div_info.get("nama", "") or "").strip(),
            "kd_barang": (kb or "").strip(),
            "barang": info.get("nama", ""),
            "kategori": info.get("kategori", ""),
            "merk": info.get("merk", ""),
            "model": info.get("model", ""),
            "warna": info.get("warna", ""),
            "ukuran": info.get("ukuran", ""),
            "stok_akhir": round(stok, 3),
            "harga_average": round(harga_avg, 2),
            "harga_jual": round(harga_jual.get(kb, 0.0), 2),
            "nominal": round(stok * harga_avg, 2),
            "harga_beli_akhir": round(harga_beli, 2),
        })
    out.sort(key=lambda r: (r["divisi"], r["barang"]))
    return out


def barang_histori(profile, kd_barang=None, kd_divisi=None, date_from=None, date_to=None) -> list[dict]:
    """Movements list matching api_v_barang_histori view schema."""
    if not any([kd_barang, kd_divisi, date_from, date_to]):
        return []

    with mssql.report_cursor(profile) as cur:
        moves = _fetch_movements(
            cur,
            kd_barang=kd_barang or None,
            kd_divisi=kd_divisi or None,
            date_to=date_to,
            date_from=date_from,
        )
        factors = _cached(profile, "factors", lambda: _unit_factors(cur))
        divisi = {_k(r["kd_divisi"]): r for r in _div_rows_full(cur)}
        satuan = {_k(r["kd_satuan"]): r["nama"] for r in _satuan_rows(cur)}

        def _names():
            cur.execute("SELECT kd_barang, nama FROM m_barang")
            return {_k(r["kd_barang"]): (r["nama"] or "").strip() for r in _dictify(cur)}

        barang_map = _cached(profile, "barang_names", _names)

    rows = []
    for m in sorted(moves, key=lambda x: (x["tanggal"], x["jenis"])):
        div_info = divisi.get(_k(m["kd_divisi"]), {})
        factor = factors.get((_k(m["kd_barang"]), _k(m["kd_satuan"])), 1.0)
        debet, kredit = _f(m["debet"]), _f(m["kredit"])
        rows.append({
            "kd_divisi": (m["kd_divisi"] or "").strip(),
            "divisi": (div_info.get("nama", "") or "").strip(),
            "kepala_nota": (div_info.get("kepala_nota", "") or "").strip(),
            "tanggal": m["tanggal"].strftime("%Y-%m-%d %H:%M") if hasattr(m["tanggal"], "strftime") else str(m["tanggal"]),
            "transaksi": m["transaksi"],
            "no_transaksi": (m["no_transaksi"] or "").strip(),
            "kd_barang": (m["kd_barang"] or "").strip(),
            "barang": barang_map.get(_k(m["kd_barang"]), ""),
            "debet": debet,
            "kredit": kredit,
            "kd_satuan": (m["kd_satuan"] or "").strip(),
            "satuan": satuan.get(_k(m["kd_satuan"]), (m["kd_satuan"] or "").strip()),
            "harga": _f(m["harga"]),
            # base-unit net for a correct cross-satuan saldo summary
            "qty_base": round(factor * (debet - kredit), 3),
        })
    return rows


def _q(cur, sql):
    cur.execute(sql)
    return _dictify(cur)

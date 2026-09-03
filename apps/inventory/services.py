"""Stock services — ported from .viewandfucntion logic to RAW TABLE queries.

PRD §5.3 + user constraint: NEVER call MS SQL views/functions/SPs. We rebuild the
"kartu stok" movement set (api_v_barang_histori_detail) from base t_*/m_* tables and
do all joins / unit-conversion / aggregation in Python.

A movement dict has: kd_divisi, tanggal, no_transaksi, transaksi, kd_barang,
debet, kredit, kd_satuan, harga, jenis.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from decimal import Decimal

from core import mssql
from core.cache import _cached, invalidate_master_cache  # noqa: F401 (re-exported)

log = logging.getLogger(__name__)
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
        log.info("stok: snapshot belum ada -> jalur lambat")
        return None
    if (dt.datetime.now() - snap).days > _snapshot_max_age_days():
        log.info("stok: snapshot basi (%s) -> jalur lambat", snap)
        return None
    if date_to is not None and date_to < snap:
        log.info("stok: date_to %s < snapshot %s -> jalur lambat", date_to, snap)
        return None
    if date_from is not None and date_from < snap:
        log.info("stok: date_from %s < snapshot %s -> jalur lambat", date_from, snap)
        return None
    return snap


def _unit_factors(cur) -> dict:
    """(kd_barang, kd_satuan) -> jumlah (qty in smallest unit per 1 of this unit)."""
    cur.execute("SELECT kd_barang, kd_satuan, jumlah FROM m_barang_satuan")
    return {(_k(r["kd_barang"]), _k(r["kd_satuan"])): _f(r["jumlah"]) for r in _dictify(cur)}


# --- Movement set (the 9 UNION ALL sources, table-level) --------------------

def _movement_sql(closing, *, kd_barang=None, kd_divisi=None, date_to=None, date_from=None, snapshot_date=None, snapshot_table=SNAPSHOT_TABLE, reverse=False):
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
    closing..snapshot_date) but the delta window shrinks to a few days.

    `reverse` (opt): for `date_to` BEFORE `closing` the forward window
    (closing, date_to] is empty, so the plain query silently returns bare
    stok_awal. With reverse the transaction blocks cover (date_to, closing]
    with debet/kredit swapped, giving stok_awal - movement = saldo at date_to."""
    params: list = []
    # Transaction sources start just after the opening balance point: snapshot
    # date when using the snapshot, else the book-closing date.
    txn_boundary = snapshot_date if snapshot_date else closing
    upper = date_to
    if reverse:
        # Saldo di date_to = stok_awal (jangkar closing) MINUS pergerakan
        # (date_to, closing]. Blok transaksi dibalik arahnya oleh wrapper di
        # bawah, jadi di sini cukup geser jendelanya.
        txn_boundary, upper = date_to, closing

    def trans_filters(tcol, dcol, divcol):
        """Common WHERE tail for transaction-based sources (closing/date/div/barang)."""
        clause = f" AND {tcol} <= ?" if upper else ""
        p = [upper] if upper else []
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
            # Satu baris satuan dasar per barang: sebagian barang punya >1 satuan
            # ber-jumlah 1 (mis. PENAL02 -> SAA000 & SAA006), dan join langsung
            # menggandakan baris stok_awal-nya. Faktornya sama-sama 1, jadi pilih
            # satu saja.
            "INNER JOIN (SELECT kd_barang, MIN(kd_satuan) AS kd_satuan FROM m_barang_satuan "
            "WHERE jumlah = 1 GROUP BY kd_barang) bs ON bd.kd_barang = bs.kd_barang "
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

    if not reverse:
        return "\nUNION ALL\n".join(blocks), params
    # Blok [0] tetap apa adanya (stok_awal berjangkar di closing); blok transaksi
    # [1]-[8] ditukar debet<->kredit oleh satu wrapper, sehingga hasilnya
    # stok_awal - pergerakan(date_to, closing] = saldo di date_to. Derived table
    # butuh daftar kolom eksplisit karena blok-blok itu tak beralias.
    tail = "\nUNION ALL\n".join(blocks[1:])
    rev = (
        "SELECT kd_divisi, tanggal, no_transaksi, transaksi, kd_barang, "
        "kredit AS debet, debet AS kredit, kd_satuan, harga, jenis "
        f"FROM (\n{tail}\n) rev "
        "(kd_divisi, tanggal, no_transaksi, transaksi, kd_barang, debet, kredit, kd_satuan, harga, jenis)"
    )
    return blocks[0] + "\nUNION ALL\n" + rev, params


def _fetch_movements(cur, *, kd_barang=None, kd_divisi=None, date_to=None, date_from=None) -> list[dict]:
    closing = _closing_date(cur)
    sql, params = _movement_sql(
        closing, kd_barang=kd_barang, kd_divisi=kd_divisi, date_to=date_to, date_from=date_from
    )
    cur.execute(sql, params)
    return _dictify(cur)


def _movement_sums(cur, *, kd_barang=None, kd_divisi=None, date_from=None, date_to=None, use_snapshot=True,
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
    # date_to sebelum tutup buku: jendela (closing, date_to] kosong, jadi tanpa
    # ini hasilnya diam-diam cuma stok_awal untuk tanggal historis apa pun.
    # Hanya untuk saldo titik-waktu (date_from None) — jalur periode seperti
    # mutasi_stok butuh pergerakan asli, bukan pembalikannya.
    reverse = date_to is not None and date_from is None and snap_date is None and date_to < closing
    inner, params = _movement_sql(
        closing, kd_barang=kd_barang, kd_divisi=kd_divisi, date_to=date_to,
        snapshot_date=snap_date, snapshot_table=snapshot_table, reverse=reverse,
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
    with mssql.report_cursor(profile, query_timeout=mssql.SNAPSHOT_TIMEOUT) as rcur:
        # Opening block [0] membaca m_barang_divisi.stok_awal, yang berjangkar di
        # tanggal tutup buku — base beku tak boleh mulai sebelum itu. Bila lebih
        # awal, jendela transaksi (closing, base_dt] kosong sehingga base berisi
        # stok_awal mentah tapi bertanggal base_dt, lalu lapisan live menambah
        # ulang pergerakan (base_dt, closing] yang sudah terkandung di stok_awal.
        base_dt = max(_base_date(), _closing_date(rcur))
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
    with mssql.report_cursor(profile, query_timeout=mssql.SNAPSHOT_TIMEOUT) as rcur:
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


def _purchase_prices_key(tanggal) -> str:
    return f"purchase_prices:{tanggal:%Y-%m-%d}"


PURCHASE_PRICES_PREFIX = "purchase_prices:"


def warm_master_cache(profile, ttl=None, include_stok=False) -> int:
    """Isi ulang cache master data untuk `profile` dalam SATU koneksi.

    Ongkos cache dingin bukan biaya query, melainkan biaya menstreaming katalog
    penuh lewat kabel: terukur ~30 detik untuk profil WAN antar-kota (vs <5 detik
    saat cache hangat). Tanpa pemanas, ongkos itu ditanggung pengguna PERTAMA
    yang membuka halaman setelah TTL habis atau setelah server restart — jadi
    "kadang 30 detik" selamanya. Dipanggil terjadwal oleh apps/core/scheduler.py
    dengan `ttl` lebih panjang dari jeda tick-nya, sehingga entri selalu diganti
    sebelum kedaluwarsa dan tak pernah ada celah dingin.

    `force=True`: sengaja membangun ulang walau entri lama masih hidup — itulah
    gunanya, mengganti isi cache di latar sebelum pengguna menemukannya kosong.

    `include_stok`: ikut membangun payload kolumnar Stok Akhir hari ini. Ini
    yang menghapus tunggu ~41 detik di halaman itu — key master di atas TIDAK
    mencakupnya, karena biayanya ada di `_movement_sums`, bukan di tabel m_*.
    Sengaja OPT-IN dan dipakai penjadwal hanya untuk profil AKTIF: payloadnya
    ~5 MB, dan membangunnya untuk 13 profil tiap tick berarti menahan semuanya
    di memori proses Django demi halaman yang cuma bisa menampilkan satu.

    Return jumlah key yang diisi."""
    filled = []

    def put(name, build):
        _cached(profile, name, build, ttl=ttl, force=True)
        filled.append(name)

    # Key berkunci tanggal: buang set hari-hari sebelumnya sebelum mengisi yang
    # baru, kalau tidak tiap hari meninggalkan satu peta puluhan ribu entri.
    invalidate_master_cache(profile.pk, prefix=PURCHASE_PRICES_PREFIX)
    if include_stok:
        invalidate_master_cache(profile.pk, prefix=STOK_KOLUMNAR_PREFIX)
        invalidate_master_cache(profile.pk, prefix=DIVISI_KOLUMNAR_PREFIX)

    with mssql.report_cursor(profile) as cur:
        put("universe", lambda: _barang_universe(cur))
        put("meta", lambda: _barang_meta(cur))
        put("factors", lambda: _unit_factors(cur))
        put("harga_jual", lambda: _harga_jual_map(cur))
        put("divisi_full", lambda: {_k(r["kd_divisi"]): r for r in _div_rows_full(cur)})
        put("satuan", lambda: {_k(r["kd_satuan"]): r["nama"] for r in _satuan_rows(cur)})

        def _names():
            cur.execute("SELECT kd_barang, nama FROM m_barang")
            return {_k(r["kd_barang"]): (r["nama"] or "").strip() for r in _dictify(cur)}

        put("barang_names", _names)

        def _divisi_list():
            cur.execute("SELECT kd_divisi, nama FROM m_divisi WHERE status <> 0 ORDER BY nama")
            return [
                {"kd_divisi": (r["kd_divisi"] or "").strip(), "nama": (r["nama"] or "").strip()}
                for r in _dictify(cur)
            ]

        put("divisi_list", _divisi_list)

        stok_min = _stok_min_map(cur)
        put("stok_min", lambda: stok_min)
        put("stok_min_kb", lambda: _sum_by_barang(stok_min))

        hari_ini = dt.datetime.combine(dt.date.today(), dt.time(23, 59, 59))
        put(_purchase_prices_key(hari_ini), lambda: _purchase_prices(cur, hari_ini))

    # DI LUAR blok cursor di atas: stok_akhir_per_tanggal membuka report_cursor
    # sendiri, dan ia harus membaca key-key yang baru saja diisi — kalau
    # dijalankan di dalam blok itu, ia menahan dua koneksi ke server yang sama
    # sepanjang perhitungan puluhan detik.
    if include_stok:
        put(_stok_kolumnar_key(hari_ini),
            lambda: _kolumnar_dari(stok_akhir_per_tanggal(profile, tanggal=hari_ini)))
        put(_divisi_kolumnar_key(hari_ini),
            lambda: _kolumnar_dari(stock_levels(profile, date_to=hari_ini)))

    return len(filled)


def _kolumnar_dari(rows: list[dict]) -> dict:
    return _kolumnar(rows, list(rows[0].keys()) if rows else [])


# --- Public services -------------------------------------------------------

def list_divisi(profile) -> list[dict]:
    """Daftar divisi aktif untuk dropdown filter.

    Dicache: dipanggil di samping stock_levels, yang membuka koneksi ODBC-nya
    sendiri — tanpa cache tiap load halaman membuka dua koneksi hanya untuk
    membaca m_divisi dua kali. WHERE-nya beda dari _div_rows (status <> 0 vs
    semua) jadi keduanya tetap terpisah, cuma sama-sama dicache.
    """
    def build():
        with mssql.report_cursor(profile) as cur:
            cur.execute("SELECT kd_divisi, nama FROM m_divisi WHERE status <> 0 ORDER BY nama")
            return [
                {"kd_divisi": (r["kd_divisi"] or "").strip(), "nama": (r["nama"] or "").strip()}
                for r in _dictify(cur)
            ]

    return _cached(profile, "divisi_list", build)


def snapshot_status(profile) -> dict:
    """Tanggal ringkasan stok harian + apakah masih segar.

    Dipakai UI untuk memberi tahu pengguna saat perhitungan terpaksa lewat
    jalur lambat (angka tetap benar, hanya lebih lama)."""
    with mssql.report_cursor(profile) as cur:
        snap = _snapshot_meta(cur)
    fresh = bool(snap and (dt.datetime.now() - snap).days <= _snapshot_max_age_days())
    return {"tanggal": snap.strftime("%d-%m-%Y %H:%M") if snap else None, "fresh": fresh}


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

    Menampilkan seluruh kode barang di m_barang tanpa kecuali, termasuk yang
    stok awalnya 0.

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

    # Seluruh kode barang ditampilkan tanpa kecuali — `meta` sudah berisi semua
    # baris m_barang, jadi barang tanpa seed/saldo awal tetap muncul dengan 0.
    out = []
    for kb in sorted(set(meta) | set(agg)):
        stok = agg.get(kb, 0.0)
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


def stock_levels(profile, kd_divisi=None, date_to=None) -> list[dict]:
    """Saldo stok per barang untuk cek cepat — SELURUH barang, saldo as-of date_to.

    Menampilkan setiap baris m_barang tanpa kecuali: termasuk yang stoknya nol,
    yang tak pernah bergerak, dan yang berstatus nonaktif. _movement_sums
    membuang grup serba-nol lewat HAVING-nya, jadi hasilnya di-union dengan
    _barang_universe — pola yang sama dipakai stok_akhir_per_tanggal.

    Bentuk barisnya sengaja RAMPING: hanya kolom yang benar-benar dirender
    StokDivisi.vue. Dengan ~55rb barang, tiap kolom tambahan berarti ~1 MB JSON
    lagi yang harus di-parse browser. Kolom divisi tak ikut dikirim karena
    nilainya konstan — sudah ditentukan oleh filter di halaman.

    Tanpa date_from: halaman ini selalu point-in-time supaya jalur snapshot
    aktif (lihat stok_divisi di apps/monitoring/views.py).
    """
    date_to = date_to or dt.datetime.now()
    per_divisi = bool(kd_divisi)
    with mssql.report_cursor(profile) as cur:
        sums = _movement_sums(cur, kd_divisi=kd_divisi or None, date_to=date_to)
        universe = _universe_for(profile, cur, kd_divisi or None)
        # kd_barang -> {nama, kategori, kd_kategori, jenis, supplier, status}
        meta = _cached(profile, "meta", lambda: _barang_meta(cur))
        stok_min = _cached(profile, "stok_min", lambda: _stok_min_map(cur))
    # stok_min is per (divisi, barang) in the legacy schema; when aggregating
    # across all divisions there is no single threshold, so sum it — a
    # combined "org-wide" minimum makes more sense than dropping the badge.
    # Only built for the aggregate view, and cached: rebuilding it per request
    # walked the whole (divisi, barang) map even when the result was discarded.
    stok_min_by_kb = None if per_divisi else _cached(
        profile, "stok_min_kb", lambda: _sum_by_barang(stok_min)
    )
    agg: dict = {}
    for m in sums:
        key = (_k(m["kd_divisi"]), _k(m["kd_barang"])) if per_divisi else (None, _k(m["kd_barang"]))
        agg[key] = agg.get(key, 0.0) + _f(m["stok_awal"]) + _f(m["masuk"]) - _f(m["keluar"])

    # Union dengan universe supaya barang bersaldo nol / tak pernah bergerak
    # tetap muncul. Di mode agregat kunci divisinya diruntuhkan jadi None.
    keys = set(agg)
    keys |= {(kdiv, kb) if per_divisi else (None, kb) for kdiv, kb in universe}

    out = []
    for kdiv, kb in keys:
        stok = agg.get((kdiv, kb), 0.0)
        out.append({
            "kd_barang": kb.strip() if isinstance(kb, str) else kb,
            "nama": meta.get(kb, {}).get("nama", ""),
            "stok_akhir": round(stok, 3),
            "stok_min": round(
                stok_min.get((kdiv, kb), 0.0) if per_divisi else stok_min_by_kb.get(kb, 0.0), 3
            ),
        })
    # ponytail: tanpa cap dan tanpa paginasi server — filter/cari di klien.
    # Barisnya sudah diramping jadi 4 kolom; kalau payload masih jadi bottleneck,
    # langkah berikutnya paginasi server (pindah ke stack ServerTable), bukan
    # memotong daftar barang secara diam-diam.
    out.sort(key=lambda r: r["nama"])
    return out


# --- small lookup helpers --------------------------------------------------

def _sum_by_barang(stok_min: dict) -> dict:
    """(divisi, barang) -> nilai  =>  barang -> total lintas divisi."""
    out: dict = {}
    for (_d, kb), v in stok_min.items():
        out[kb] = out.get(kb, 0.0) + v
    return out


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


# `jumlah` lewat subquery ber-MAX, bukan join langsung ke m_barang_satuan:
# (kd_barang, kd_satuan) bisa ganda di sana, dan join langsung akan menggandakan
# baris pembelian sehingga bobot rata-ratanya ikut ganda. Pola yang sama dengan
# _movement_sums. LEFT JOIN + COALESCE(...,1) supaya baris yang satuannya tak
# terdaftar tetap ikut dihitung — sisi KUANTITAS sudah menghitungnya, jadi
# menjatuhkannya di sisi harga membuat keduanya bicara tentang barang berbeda.
_JUMLAH_SATUAN = (
    "LEFT JOIN (SELECT kd_barang, kd_satuan, MAX(jumlah) AS jumlah "
    "FROM m_barang_satuan GROUP BY kd_barang, kd_satuan) bs "
    "ON bs.kd_barang = pd.kd_barang AND bs.kd_satuan = pd.kd_satuan"
)


def _purchase_prices(cur, tanggal) -> tuple[dict, dict, dict]:
    """(harga_average_map, harga_beli_akhir_map, harga_beli_awal_map) — kd_barang -> float.

    Ketiganya **per satuan TERKECIL**, karena yang mengalikannya (`stok_akhir` di
    `stok_akhir_per_tanggal`) juga dalam satuan terkecil.

    Satuannya adalah keseluruhan isi fungsi ini, dan pernah salah: rumus lama
    membagi pembilang DAN penyebut dengan `bs.jumlah`, sehingga faktornya saling
    menghilangkan dan yang keluar harga per satuan BELI. Kolom `nominal` di layar
    Stok Akhir karena itu menggelembung sebesar faktor kemasan tiap barang —
    terukur 2,25x (PAGESANGAN) sampai 3,89x (testgudang) atas seluruh katalog,
    dan tepat 10,00x pada `AMP013` yang dibeli per satuan berisi 10.

    Yang membuatnya lolos lama: `harga_beli_akhir` di fungsi yang SAMA membagi
    dengan benar, jadi dua kolom bertetangga memakai satuan berbeda tanpa ada
    yang mencolok di layar. Invarian yang menahannya sekarang ada di
    `manage.py check_stock_agg`: harga_average wajib berada di antara harga beli
    per satuan terkecil terendah dan tertinggi milik barang itu.

    Ini BUKAN rata-rata tertimbang PSAK 14 seperti `_harga_pokok_rata` (dipakai
    Laba Rugi): tak berjangkar tutup buku, harga bruto, retur pembelian tak
    dikurangkan. Sengaja: layar ini mendaftar seluruh katalog, dan versi PSAK
    menilai Rp 0 untuk barang tanpa pembelian sejak tutup buku — 1.602 dari
    12.930 baris di PUSAT. Keduanya diukur berselisih <=3% (PUSAT +2,9%,
    testgudang -1,7%, PAGESANGAN -0,4%), jadi total di layar ini dan persediaan
    di Laba Rugi memang berbeda tipis, dan itu bukan cacat.
    """
    cur.execute(
        f"""
        SELECT pd.kd_barang,
            SUM(pd.qty * pd.harga_beli)
                / NULLIF(SUM(pd.qty * COALESCE(bs.jumlah, 1)), 0) AS harga_avg
        FROM t_pembelian_detail pd
        INNER JOIN t_pembelian p ON pd.no_transaksi = p.no_transaksi
        {_JUMLAH_SATUAN}
        WHERE CONVERT(DATE, p.tanggal) <= ? AND p.status IN (0, 1)
        GROUP BY pd.kd_barang
        """,
        [tanggal],
    )
    avg_map = {_k(r["kd_barang"]): _f(r["harga_avg"]) for r in _dictify(cur)}

    # Last purchase price per base unit — picked in SQL (ROW_NUMBER, still a plain
    # SELECT) instead of streaming every purchase row to Python.
    cur.execute(
        f"""
        SELECT x.kd_barang, x.harga_per_unit FROM (
            SELECT pd.kd_barang,
                pd.harga_beli / NULLIF(COALESCE(bs.jumlah, 1), 0) AS harga_per_unit,
                ROW_NUMBER() OVER (PARTITION BY pd.kd_barang ORDER BY p.tanggal DESC, p.no_transaksi DESC) AS rn
            FROM t_pembelian_detail pd
            INNER JOIN t_pembelian p ON pd.no_transaksi = p.no_transaksi
            {_JUMLAH_SATUAN}
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


def _harga_pokok_rata(cur, tanggal) -> dict:
    """Harga pokok rata-rata tertimbang per barang s.d. `tanggal` — kd_barang -> float.

    Rata-rata tertimbang (PSAK 14 / IAS 2), dihitung HANYA atas arus yang membawa
    biaya perolehan: saldo awal, pembelian, dikurangi retur pembelian.

        harga = (stok_awal*harga_beli_awal + Σ qty_beli*harga_netto - Σ qty_retur*harga_retur)
                / (stok_awal + Σ qty_beli - Σ qty_retur)

    **Opname, mutasi, dan retur penjualan sengaja TIDAK ikut.** Ketiganya menggeser
    kuantitas tanpa menimbulkan biaya, jadi mereka mengubah stok on-hand tapi bukan
    dasar harganya — unitnya otomatis dinilai pada rata-rata yang sama. Ini bedanya
    dengan legacy `GetHargaAverageBarangPerTanggal`, yang menelusuri lapisan secara
    LIFO (dilarang PSAK 14) dan menilai stok hasil opname masuk Rp 0 — di GUDANG itu
    14,3 juta unit, bukan kasus pinggiran.

    Harga beli dipakai NETTO (diskon1-4 baris, diskon1-4 nota, pajak, ppnbm) lewat
    `_ghb` yang sama dengan laporan pembelian, karena biaya perolehan memang termasuk
    pajak yang tak terpulihkan. Semua kuantitas dikonversi ke satuan terkecil.

    Bukan `_purchase_prices()`: fungsi itu membagi pembilang DAN penyebutnya dengan
    `bs.jumlah` sehingga faktornya saling menghilangkan, dan hasilnya harga per satuan
    BELI — sementara kuantitas yang mengalikannya dalam satuan terkecil.
    """
    from apps.transactions.reports import _ghb  # noqa: PLC0415 — hindari impor silang di modul

    beli_netto = _ghb(
        _ghb("d.harga_beli", [f"COALESCE(d.diskon{i}, 0)" for i in (1, 2, 3, 4)]),
        [f"COALESCE(t.diskon{i}, 0)" for i in (1, 2, 3, 4)],
        pajak="COALESCE(t.pajak, 0)", ppnbm="COALESCE(t.ppnbm, 0)",
    )
    closing = _closing_date(cur)
    cur.execute(
        # `jumlah` lewat subquery ber-MAX supaya (kd_barang, kd_satuan) ganda tak
        # menggandakan baris pembelian — pola yang sama dengan _movement_sums.
        f"""
        SELECT kd_barang, SUM(qty) AS qty, SUM(nilai) AS nilai FROM (
            SELECT bd.kd_barang,
                   SUM(COALESCE(bd.stok_awal, 0)) AS qty,
                   SUM(COALESCE(bd.stok_awal, 0) * COALESCE(bd.harga_beli_awal, 0)) AS nilai
            FROM m_barang_divisi bd WHERE bd.stok_awal > 0 GROUP BY bd.kd_barang
            UNION ALL
            SELECT d.kd_barang,
                   SUM(COALESCE(bs.jumlah, 1) * d.qty),
                   SUM(d.qty * ({beli_netto}))
            FROM t_pembelian_detail d
            INNER JOIN t_pembelian t ON d.no_transaksi = t.no_transaksi
            LEFT JOIN (SELECT kd_barang, kd_satuan, MAX(jumlah) AS jumlah
                       FROM m_barang_satuan GROUP BY kd_barang, kd_satuan) bs
              ON bs.kd_barang = d.kd_barang AND bs.kd_satuan = d.kd_satuan
            WHERE t.tanggal > ? AND t.tanggal <= ? AND t.status IN (0, 1)
            GROUP BY d.kd_barang
            UNION ALL
            SELECT d.kd_barang,
                   -SUM(COALESCE(bs.jumlah, 1) * d.qty),
                   -SUM(d.qty * d.harga)
            FROM t_pembelian_retur_detail d
            INNER JOIN t_pembelian_retur t ON d.no_retur = t.no_retur
            LEFT JOIN (SELECT kd_barang, kd_satuan, MAX(jumlah) AS jumlah
                       FROM m_barang_satuan GROUP BY kd_barang, kd_satuan) bs
              ON bs.kd_barang = d.kd_barang AND bs.kd_satuan = d.kd_satuan
            WHERE t.tanggal > ? AND t.tanggal <= ?
            GROUP BY d.kd_barang
        ) perolehan
        GROUP BY kd_barang
        HAVING SUM(qty) > 0
        """,
        [closing, tanggal, closing, tanggal],
    )
    return {_k(r["kd_barang"]): _f(r["nilai"]) / _f(r["qty"])
            for r in _dictify(cur) if _f(r["qty"])}


def nilai_persediaan(profile, tanggal, kd_divisi=None) -> dict:
    """Nilai persediaan per `tanggal`: kuantitas dari mesin pergerakan × harga rata-rata.

    Mengembalikan {"nilai", "unit", "barang", "tanpa_harga", "stok_negatif"}.

    Kuantitas disaring divisi, **harga TIDAK**: satu barang punya satu biaya perolehan
    bagi perusahaan, tak berubah karena disimpan di gudang mana. Efek yang memang
    diinginkan — nilai persediaan tiap divisi menjumlah tepat ke nilai seluruh server.
    Ini kebalikan dari `stock_levels`, yang angkanya memang bergeser saat difilter.

    Saldo negatif (cacat data, bukan keadaan fisik) tetap dinilai supaya identitas
    HPP = awal + beli - akhir tidak diam-diam meleset; jumlahnya dilaporkan di
    `stok_negatif` agar terlihat, bukan tersembunyi.
    """
    with mssql.cursor(profile) as cur:
        sums = _movement_sums(cur, kd_divisi=kd_divisi, date_to=tanggal)
        harga = _harga_pokok_rata(cur, tanggal)

    saldo: dict = {}
    for r in sums:
        kb = _k(r["kd_barang"])
        saldo[kb] = saldo.get(kb, 0.0) + _f(r["stok_awal"]) + _f(r["masuk"]) - _f(r["keluar"])

    nilai = unit = 0.0
    barang = tanpa = negatif = 0
    for kb, s in saldo.items():
        if not s:
            continue
        barang += 1
        unit += s
        if s < 0:
            negatif += 1
        h = harga.get(kb)
        if h is None:
            tanpa += 1
            continue
        nilai += s * h
    return {"nilai": round(nilai, 2), "unit": round(unit, 3), "barang": barang,
            "tanpa_harga": tanpa, "stok_negatif": negatif}


def _barang_universe(cur, kd_divisi=None) -> list[tuple]:
    """All (kd_divisi, kd_barang) pairs for the Stok Akhir listing — every row of
    m_barang without exception, including barang with no m_barang_divisi
    assignment (kd_divisi ''). Needed because _movement_sums drops all-zero rows
    via its HAVING clause, hiding every zero-stock barang.

    SELALU panggil lewat _universe_for: ~55rb baris, dan di server yang diakses
    lewat WAN ini terukur 2,96 detik per pemanggilan (vs 0,13 detik di LAN) —
    63% dari seluruh waktu Stok per Divisi dengan cache hangat."""
    sql = (
        "SELECT COALESCE(bd.kd_divisi, '') AS kd_divisi, b.kd_barang FROM m_barang b "
        "LEFT JOIN m_barang_divisi bd ON b.kd_barang = bd.kd_barang "
        "WHERE 1=1"
    )
    params = []
    if kd_divisi:
        sql += " AND bd.kd_divisi = ?"
        params.append(kd_divisi)
    cur.execute(sql, params)
    return [(_k(r[0]), _k(r[1])) for r in cur.fetchall()]


def _universe_for(profile, cur, kd_divisi=None) -> list[tuple]:
    """Universe penuh dicache SEKALI, lalu disaring di Python per divisi.

    Menyaring hasil penuh setara dengan query berfilter: `LEFT JOIN + WHERE
    bd.kd_divisi = ?` membuang baris tak-cocok DAN baris tanpa penugasan divisi
    (kd_divisi ''), persis seperti membandingkan kolom pertama. Diuji di
    test_universe_filter.py.

    Dulu key cache-nya memuat kd_divisi ("universe:D01"), jadi tiap divisi yang
    dibuka pengguna adalah key dingin sendiri — di WAN itu puluhan detik lagi per
    divisi baru, berulang tiap TTL. Satu key untuk semua divisi menghapus itu."""
    full = _cached(profile, "universe", lambda: _barang_universe(cur))
    if not kd_divisi:
        return full
    kdiv = _k(kd_divisi)
    return [r for r in full if r[0] == kdiv]


def stok_akhir_per_tanggal(profile, tanggal, kd_divisi=None) -> list[dict]:
    """Stok akhir per (divisi, barang) at tanggal — matches api_GetStokAkhirPerTanggal schema.

    Lists every barang in m_barang without exception, zero-stock included."""
    if isinstance(tanggal, dt.date) and not isinstance(tanggal, dt.datetime):
        tanggal = dt.datetime(tanggal.year, tanggal.month, tanggal.day, 23, 59, 59)

    with mssql.report_cursor(profile) as cur:
        sums = _movement_sums(cur, kd_divisi=kd_divisi or None, date_to=tanggal)
        universe = _universe_for(profile, cur, kd_divisi or None)
        divisi = _cached(profile, "divisi_full", lambda: {_k(r["kd_divisi"]): r for r in _div_rows_full(cur)})
        meta = _cached(profile, "meta", lambda: _barang_meta(cur))
        harga_jual = _cached(profile, "harga_jual", lambda: _harga_jual_map(cur))
        # _purchase_prices = 3 query agregat atas t_pembelian_detail, ~0.34s dan
        # dulu jalan di SETIAP request. Dicache hanya untuk tanggal hari ini —
        # itu nilai default dan mayoritas kunjungan. Tanggal lampau tetap
        # dihitung langsung supaya tak menumpuk key per tanggal yang dipilih
        # pengguna (lihat catatan cache di context.md soal query berkunci
        # parameter bebas). Key memuat tanggalnya: lewat tengah malam key hari
        # kemarin tak terpakai lagi, jadi tak mungkin menyajikan harga basi
        # meski TTL pemanas panjang. Set lama dibuang pemanas terjadwal.
        if tanggal.date() == dt.date.today():
            avg_map, last_map, init_map = _cached(
                profile, _purchase_prices_key(tanggal), lambda: _purchase_prices(cur, tanggal)
            )
        else:
            avg_map, last_map, init_map = _purchase_prices(cur, tanggal)

    agg: dict = {}
    for m in sums:
        key = (_k(m["kd_divisi"]), _k(m["kd_barang"]))
        agg[key] = agg.get(key, 0.0) + _f(m["masuk"]) - _f(m["keluar"]) + _f(m["stok_awal"])

    # Union with agg keys: a barang can carry movement under a divisi it was never
    # assigned to in m_barang_divisi — those rows must not vanish either.
    out = []
    for kd_div, kb in sorted(set(universe) | set(agg.keys())):
        stok = agg.get((kd_div, kb), 0.0)
        info = meta.get(kb, {})
        harga_avg = avg_map.get(kb) or init_map.get(kb, 0.0)
        harga_beli = last_map.get(kb) or init_map.get(kb, 0.0)
        div_info = divisi.get(kd_div, {})
        out.append({
            "kd_divisi": (kd_div or "").strip(),
            "divisi": (div_info.get("nama", "") or "").strip() or ("(Tanpa Divisi)" if not kd_div else (kd_div or "").strip()),
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


# --- Payload kolumnar Stok Akhir -------------------------------------------
#
# Halaman Stok Akhir memegang SELURUH katalog di peramban supaya pencarian
# instan lintas 55rb baris, bukan cuma lintas halaman yang tampil. Bentuk
# "list of dict" tak sanggup untuk itu — terukur 15,6 MB JSON dan 123 MB heap,
# dan di Firefox Android tabnya tak pernah selesai memuat.
#
# Yang mahal bukan JSON-nya, tapi bentuknya. Dua sumber pemborosan:
#
#   1. Nama kunci diulang tiap baris (14 kunci × 55rb).
#   2. Nilai diulang tiap baris. Ekstrem di sini: `divisi` cuma 2 nilai unik,
#      `ukuran` 14, `model` 118, `kategori` 215, `merk` 1.409 — dari 54.955
#      baris. String "CROWN TOYS" tertulis 54.754 kali.
#
# Terukur di RTL PUSAT (54.955 baris, 14 kolom):
#
#   list of dict            15,60 MB   gzip 1,33 MB
#   kolumnar (list of list)  7,43 MB   gzip 1,16 MB
#   kolumnar + kamus         5,30 MB   gzip 1,24 MB
#
# Kolom gzip nyaris tak berubah — kabel tak pernah jadi masalah, gzip sudah
# membuang pengulangan itu sendiri. Yang ditolong bentuk ini adalah `JSON.parse`
# (3x lebih sedikit teks) dan heap peramban.
#
# KOLOM-mayor, bukan baris-mayor: `list of list` tetap melahirkan 54.955 objek
# array di JS. Kolom-mayor hanya 14 array, dan tiap kolom angka bisa dijadikan
# satu Float64Array di klien lalu array hasil parse-nya dilepas.

# Kamus hanya menolong bila nilainya benar-benar berulang. `kd_barang` unik
# seluruhnya dan `barang` hampir seluruhnya (52.487 dari 54.955) — memberi
# keduanya kamus justru MENAMBAH byte (satu tabel penuh + satu indeks per baris)
# tanpa membuang apa pun.
_DICT_MAX_RATIO = 4


def _kolumnar(rows: list[dict], cols: list[str]) -> dict:
    """{cols, types, dict, data, n} kolom-mayor dari list of dict.

    `types[kolom]` menyatakan bentuk kolomnya, dan itu WAJIB dikirim: klien
    dulu menebaknya dari `typeof data[c][0]`, yang salah begitu kolom angka
    memuat satu `None` — tebakannya "num", `Float64Array.from` mengubah null
    jadi NaN, dan layar mencetak "NaN" alih-alih "-". Menyatakannya di sini
    menghapus seluruh kelas kesalahan itu.

      dict — teks yang nilainya berulang; dikirim sebagai indeks ke `dict[c]`
      num  — seluruhnya int/float TANPA None; di klien jadi Float64Array
      str  — seluruhnya string
      raw  — sisanya (campur tipe / ada None); dikirim & dipakai apa adanya
    """
    out_dict: dict[str, list] = {}
    data: dict[str, list] = {}
    types: dict[str, str] = {}
    n = len(rows)
    for c in cols:
        vals = [r.get(c) for r in rows]
        data[c] = vals
        if all(isinstance(v, str) for v in vals):
            uniq = sorted(set(vals))
            # Kamus hanya menolong bila nilainya benar-benar berulang; pada
            # kolom yang hampir unik ia justru MENAMBAH byte (satu tabel penuh
            # plus satu indeks per baris) tanpa membuang apa pun.
            if n and len(uniq) < n / _DICT_MAX_RATIO:
                idx = {v: i for i, v in enumerate(uniq)}
                out_dict[c] = uniq
                data[c] = [idx[v] for v in vals]
                types[c] = "dict"
            else:
                types[c] = "str"
        elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            types[c] = "num"
        else:
            types[c] = "raw"
    return {"cols": cols, "types": types, "dict": out_dict, "data": data, "n": n}


def stok_akhir_kolumnar(profile, tanggal, kd_divisi=None) -> dict:
    """Stok akhir dalam bentuk kolumnar siap kirim ke peramban.

    Mesin stoknya tidak disentuh: ini pembungkus atas `stok_akhir_per_tanggal`,
    satu-satunya sumber stok yang boleh dipercaya (lihat catatannya soal
    `m_barang_stok_akhir` yang rusak).

    Hasil untuk HARI INI tanpa filter divisi — tampilan default halaman, dan
    satu-satunya yang layak dicache — disimpan berkunci tanggal dan dihangatkan
    penjadwal (lihat `warm_master_cache`). Tanggal lampau dan tampilan
    berdivisi dihitung langsung: mencachenya berarti menumpuk satu set 5 MB per
    kombinasi yang pernah diklik seseorang.
    """
    if isinstance(tanggal, dt.date) and not isinstance(tanggal, dt.datetime):
        tanggal = dt.datetime(tanggal.year, tanggal.month, tanggal.day, 23, 59, 59)

    def build():
        return _kolumnar_dari(
            stok_akhir_per_tanggal(profile, tanggal=tanggal, kd_divisi=kd_divisi))

    if kd_divisi or tanggal.date() != dt.date.today():
        return build()
    return _cached(profile, _stok_kolumnar_key(tanggal), build)


STOK_KOLUMNAR_PREFIX = "stok_kolumnar:"
DIVISI_KOLUMNAR_PREFIX = "divisi_kolumnar:"


def _stok_kolumnar_key(tanggal) -> str:
    return f"{STOK_KOLUMNAR_PREFIX}{tanggal:%Y-%m-%d}"


def _divisi_kolumnar_key(tanggal) -> str:
    return f"{DIVISI_KOLUMNAR_PREFIX}{tanggal:%Y-%m-%d}"


def stock_levels_kolumnar(profile, kd_divisi=None, date_to=None) -> dict:
    """Bentuk kolumnar `stock_levels` untuk halaman Stok per Divisi.

    Beda dari Stok Akhir, filter divisi di sini TIDAK boleh dipindah ke klien:
    `stock_levels` mengagregasi berbeda tergantung ada-tidaknya `kd_divisi`
    (per (divisi, barang) versus diruntuhkan per barang), jadi memilih divisi
    mengubah angkanya, bukan sekadar menyaring baris.

    Yang dicache hanya tampilan agregat hari ini — itu yang dibuka pertama, dan
    mencache tiap divisi berarti satu payload lagi per divisi di memori proses.
    """
    date_to = date_to or dt.datetime.now()

    def build():
        return _kolumnar_dari(
            stock_levels(profile, kd_divisi=kd_divisi, date_to=date_to))

    if kd_divisi or date_to.date() != dt.date.today():
        return build()
    return _cached(profile, _divisi_kolumnar_key(date_to), build)


def cek_stok(profile, cari: str, kd_divisi=None, limit=50) -> list[dict]:
    """Cari barang, kembalikan barisnya saja — untuk layar Cek Stok kasir.

    Menyaring payload kolumnar yang SUDAH dihitung, dicache, dan dihangatkan
    scheduler, bukan menghitung ulang. Dua jalan lain sama-sama salah:
    mengirim seluruh ~55rb baris ke ponsel kasir yang cuma ingin melihat satu
    barang, atau menjalankan agregasi stok tiap kali seseorang mengetik.

    Tanpa `kd_divisi` angkanya diruntuhkan per barang (stok seluruh divisi);
    dengan `kd_divisi` ia per divisi — lihat catatan di stock_levels_kolumnar,
    memilih divisi mengubah angkanya, bukan cuma menyaring baris.
    """
    cari = (cari or "").strip().upper()
    if not cari:
        return []
    payload = stock_levels_kolumnar(profile, kd_divisi=kd_divisi)
    cols, data, types = payload["cols"], payload["data"], payload["types"]
    kamus = payload.get("dict", {})

    def nilai(c, i):
        v = data[c][i]
        # Kolom "dict" dikirim sebagai indeks ke kamusnya; tanpa dibuka di sini
        # yang tampil di layar adalah angka indeksnya, bukan nama barangnya.
        return kamus[c][v] if types.get(c) == "dict" else v

    kunci = [c for c in ("kd_barang", "barang", "nama") if c in cols]
    hasil = []
    for i in range(payload["n"]):
        if any(cari in str(nilai(c, i) or "").upper() for c in kunci):
            hasil.append({c: nilai(c, i) for c in cols})
            if len(hasil) >= limit:
                break
    return hasil


def barang_histori(profile, kd_barang=None, kd_divisi=None, date_from=None, date_to=None) -> list[dict]:
    """Movements list matching api_v_barang_histori view schema, plus a running
    base-unit `saldo` per (divisi, barang)."""
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
        # Saldo berjalan harus mulai dari saldo SEBELUM date_from. Diambil sebagai
        # agregat SQL (satu baris per SKU, kolom stok_awal) alih-alih ikut menarik
        # tiap baris pergerakan lama ke Python — lihat catatan row-transfer di
        # _movement_sums.
        saldo: dict = {}
        if date_from:
            for m in _movement_sums(
                cur, kd_barang=kd_barang or None, kd_divisi=kd_divisi or None,
                date_from=date_from, date_to=date_to,
            ):
                saldo[(_k(m["kd_divisi"]), _k(m["kd_barang"]))] = _f(m["stok_awal"])
        factors = _cached(profile, "factors", lambda: _unit_factors(cur))
        divisi = _cached(profile, "divisi_full", lambda: {_k(r["kd_divisi"]): r for r in _div_rows_full(cur)})
        satuan = _cached(profile, "satuan", lambda: {_k(r["kd_satuan"]): r["nama"] for r in _satuan_rows(cur)})

        def _names():
            cur.execute("SELECT kd_barang, nama FROM m_barang")
            return {_k(r["kd_barang"]): (r["nama"] or "").strip() for r in _dictify(cur)}

        barang_map = _cached(profile, "barang_names", _names)

    rows = []
    for m in sorted(moves, key=lambda x: (x["tanggal"], x["jenis"])):
        div_info = divisi.get(_k(m["kd_divisi"]), {})
        factor = factors.get((_k(m["kd_barang"]), _k(m["kd_satuan"])), 1.0)
        debet, kredit = _f(m["debet"]), _f(m["kredit"])
        # Saldo berjalan per (divisi, barang) — deret terpisah tiap SKU, bukan
        # satu kumulatif gabungan (listing bisa lintas barang). Blok [0] Stok Awal
        # tak pernah difilter tanggal, jadi saat date_from aktif ia muncul di
        # listing PADAHAL sudah termasuk di agregat saldo awal — jangan dijumlah
        # lagi. Barisnya tetap tampil sebagai penanda saldo awal periode.
        key = (_k(m["kd_divisi"]), _k(m["kd_barang"]))
        saldo.setdefault(key, 0.0)  # agregat membuang grup bersaldo nol
        if not (date_from and m["transaksi"] == "Stok Awal"):
            saldo[key] += factor * (debet - kredit)
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
            # Masuk/keluar per baris DALAM SATUAN TERKECIL. debet/kredit di atas
            # sengaja dibiarkan apa adanya (satuan barisnya) untuk ditampilkan di
            # sebelah kolom Satuan, tapi menjumlahkannya lintas baris tak ada
            # artinya: 1 dus (faktor 250) + 1 pcs bukan 2. Total apa pun harus
            # pakai dua kolom ini.
            "debet_base": round(factor * debet, 3),
            "kredit_base": round(factor * kredit, 3),
            # saldo berjalan per (divisi, barang), satuan terkecil
            "saldo": round(saldo[key], 3),
        })
    return rows


def _q(cur, sql):
    cur.execute(sql)
    return _dictify(cur)

"""Read services for legacy master data (m_*), via raw pyodbc.

PRD §5.3: table-level access only; joins & calculations done here in Python
(batch-fetch each table once, then merge with dict lookups — avoids N+1, §8.3).
"""
from __future__ import annotations

from decimal import Decimal

from core import mssql
from core.cache import _cached, invalidate_master_cache
from apps.core.reporting import dictify as _dictify

MAX_ROWS = 500


def _f(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _active(status) -> bool:
    # JR_STATUS_JENIS is a 1-char flag; '1'/'A'/'Y' are treated as active.
    return str(status).strip().upper() in ("1", "A", "Y")


def _st(value) -> str:
    return str(value).strip() if value is not None else ""


def _is_retail(profile) -> bool:
    return profile.db_type == "retail"


def _margin(harga_jual: float, modal: float) -> float:
    """Markup atas modal, dalam persen. 0 bila modal tak valid."""
    return round((harga_jual - modal) / modal * 100, 4) if modal and modal > 0 else 0.0


def list_products(profile, search: str = "", kd_kategori: str = "") -> list[dict]:
    """Return products shaped exactly like the Products.vue props."""
    where, params = ["1=1"], []
    if search:
        where.append("(nama LIKE ? OR kd_barang LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if kd_kategori:
        where.append("kd_kategori = ?")
        params.append(kd_kategori)
    where_sql = " AND ".join(where)

    with mssql.cursor(profile) as cur:
        cur.execute(
            f"SELECT TOP {MAX_ROWS} kd_barang, kd_kategori, nama, status "
            f"FROM m_barang WHERE {where_sql} ORDER BY nama",
            params,
        )
        barang = _dictify(cur)

        categories = _cached(
            profile, "categories", lambda: _key_map(cur, "SELECT kd_kategori, nama FROM m_kategori", "kd_kategori", "nama")
        )
        satuan_names = _cached(
            profile, "satuan_names", lambda: _key_map(cur, "SELECT kd_satuan, nama FROM m_satuan", "kd_satuan", "nama")
        )

        # First selling unit + price per product.
        def _build_satuan_price():
            cur.execute("SELECT kd_barang, kd_satuan, harga_jual FROM m_barang_satuan")
            by_barang: dict[str, dict] = {}
            for r in _dictify(cur):
                by_barang.setdefault(r["kd_barang"], r)
            return by_barang

        price_by_barang = _cached(profile, "satuan_price", _build_satuan_price)

        # Stock summed across divisions (in Python, not SQL) — NOT cached: this
        # column changes on every POS sale/purchase/opname, must stay live.
        cur.execute("SELECT kd_barang, stok_akhir FROM m_barang_stok_akhir")
        stok_by_barang: dict[str, float] = {}
        for r in _dictify(cur):
            stok_by_barang[r["kd_barang"]] = stok_by_barang.get(r["kd_barang"], 0.0) + _f(r["stok_akhir"])

    products = []
    for b in barang:
        kd = b["kd_barang"]
        price = price_by_barang.get(kd, {})
        products.append(
            {
                "kd_barang": kd.strip() if isinstance(kd, str) else kd,
                "nama": (b["nama"] or "").strip(),
                "kd_kategori": (b["kd_kategori"] or "").strip(),
                "kategori": (categories.get(b["kd_kategori"], "") or "").strip(),
                "satuan": (satuan_names.get(price.get("kd_satuan"), "") or "").strip(),
                "harga_jual": _f(price.get("harga_jual")),
                "stok": _f(stok_by_barang.get(kd, 0)),
                "status": _active(b["status"]),
            }
        )
    return products


def list_categories(profile) -> list[dict]:
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT kd_kategori, nama FROM m_kategori ORDER BY nama")
        return [
            {"kd_kategori": (r["kd_kategori"] or "").strip(), "nama": (r["nama"] or "").strip()}
            for r in _dictify(cur)
        ]


def list_customers(profile, search: str = "") -> list[dict]:
    where, params = ["1=1"], []
    if search:
        where.append("(nama LIKE ? OR kd_customer LIKE ? OR hp LIKE ?)")
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    where_sql = " AND ".join(where)

    with mssql.cursor(profile) as cur:
        cur.execute(
            f"SELECT TOP {MAX_ROWS} kd_customer, nama, alamat, hp, email, point, "
            f"limit_kredit, status FROM m_customer WHERE {where_sql} ORDER BY nama",
            params,
        )
        rows = _dictify(cur)

    return [
        {
            "kd_customer": (r["kd_customer"] or "").strip(),
            "nama": (r["nama"] or "").strip(),
            "alamat": (r["alamat"] or "").strip(),
            "hp": (r["hp"] or "").strip(),
            "email": (r["email"] or "").strip(),
            "point": _f(r["point"]),
            "limit_kredit": _f(r["limit_kredit"]),
            "status": _active(r["status"]),
        }
        for r in rows
    ]


# --- Update Barang (WRITE) -------------------------------------------------

_STATUS_TABLES = {"m_barang", "m_barang_divisi", "m_barang_satuan"}


def list_barang_edit(profile, search: str = "") -> list[dict]:
    """Barang + satuan (harga_jual/margin/status) + status divisi, untuk edit.

    Retail: sisipkan `modal` (harga_jual server sumber-modal) per satuan dan margin
    terhitung terkini. Grosir/gudang: margin apa adanya dari DB.
    """
    where, params = ["1=1"], []
    if search:
        where.append("(nama LIKE ? OR kd_barang LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    where_sql = " AND ".join(where)

    with mssql.cursor(profile) as cur:
        cur.execute(
            f"SELECT TOP {MAX_ROWS} kd_barang, kd_kategori, nama, keterangan, status FROM m_barang "
            f"WHERE {where_sql} ORDER BY nama",
            params,
        )
        barang = _dictify(cur)
        satuan_names = _cached(
            profile, "satuan_names", lambda: _key_map(cur, "SELECT kd_satuan, nama FROM m_satuan", "kd_satuan", "nama")
        )
        categories = _cached(
            profile, "categories", lambda: _key_map(cur, "SELECT kd_kategori, nama FROM m_kategori", "kd_kategori", "nama")
        )
        divisi_names = _cached(
            profile, "divisi_names", lambda: _key_map(cur, "SELECT kd_divisi, nama FROM m_divisi", "kd_divisi", "nama")
        )

        def _build_satuan_edit():
            cur.execute("SELECT kd_barang, kd_satuan, jumlah, harga_jual, margin, status FROM m_barang_satuan")
            by_barang: dict[str, list] = {}
            for r in _dictify(cur):
                by_barang.setdefault(_st(r["kd_barang"]), []).append(r)
            return by_barang

        satuan_by = _cached(profile, "satuan_edit", _build_satuan_edit)

        def _build_divisi_status():
            cur.execute("SELECT kd_barang, kd_divisi, status FROM m_barang_divisi")
            by_barang: dict[str, list] = {}
            for r in _dictify(cur):
                by_barang.setdefault(_st(r["kd_barang"]), []).append(r)
            return by_barang

        divisi_by = _cached(profile, "divisi_status", _build_divisi_status)

    is_retail = _is_retail(profile)
    modal_all: dict[str, dict] = {}
    if is_retail:
        cost = mssql.get_cost_source(profile)
        if cost:
            def _build_cost_satuan_price():
                with mssql.cursor(cost) as cost_cur:
                    cost_cur.execute("SELECT kd_barang, kd_satuan, harga_jual FROM m_barang_satuan")
                    by_barang: dict[str, dict] = {}
                    for r in _dictify(cost_cur):
                        by_barang.setdefault(_st(r["kd_barang"]), {})[_st(r["kd_satuan"])] = _f(r["harga_jual"])
                    return by_barang

            # Keyed by the cost-source profile itself: multiple retail profiles
            # sharing one grosir/gudang source reuse a single cached read.
            modal_all = _cached(cost, "cost_satuan_price", _build_cost_satuan_price)

    out = []
    for b in barang:
        kd = _st(b["kd_barang"])
        modal_map = modal_all.get(kd, {})
        units = []
        for s in satuan_by.get(kd, []):
            ks = _st(s["kd_satuan"])
            harga = _f(s["harga_jual"])
            unit = {
                "kd_satuan": ks,
                "satuan": _st(satuan_names.get(s["kd_satuan"], "")),
                "jumlah": _f(s["jumlah"]),
                "harga_jual": harga,
                "margin": _f(s["margin"]),
                "status": _st(s["status"]),
            }
            if is_retail:
                m = modal_map.get(ks, 0.0)
                unit["modal"] = m
                unit["margin"] = _margin(harga, m)
            units.append(unit)
        divisi = [
            {
                "kd_divisi": _st(d["kd_divisi"]),
                "nama": _st(divisi_names.get(d["kd_divisi"], "")),
                "status": _st(d["status"]),
            }
            for d in divisi_by.get(kd, [])
        ]
        out.append({
            "kd_barang": kd,
            "nama": _st(b["nama"]),
            "keterangan": _st(b.get("keterangan", "")),
            "status": _st(b["status"]),
            "kd_kategori": _st(b.get("kd_kategori", "")),
            "kategori": _st(categories.get(b.get("kd_kategori"), "")),
            "satuan": units,
            "divisi": divisi,
            "is_retail": is_retail,
        })
    return out


def update_harga(profile, kd_barang: str, prices: dict) -> list[dict]:
    """Update harga_jual (dan margin) per satuan. `prices`: {kd_satuan: harga_jual}.

    Retail: margin = markup atas modal (harga_jual server sumber-modal). Lain: margin=0.
    Return daftar perubahan aktual: [{kd_satuan, harga_lama, harga_baru}, ...] (hanya yang
    nilainya benar-benar berubah) — dipakai caller untuk mencatat riwayat (BarangUpdateLog).
    """
    modal: dict = {}
    is_retail = _is_retail(profile)
    if is_retail:
        cost = mssql.get_cost_source(profile)
        if cost:
            with mssql.cursor(cost) as cur:
                cur.execute("SELECT kd_satuan, harga_jual FROM m_barang_satuan WHERE kd_barang = ?", [kd_barang])
                modal = {_st(r["kd_satuan"]): _f(r["harga_jual"]) for r in _dictify(cur)}

    changes: list[dict] = []
    with mssql.cursor(profile, autocommit=False) as cur:
        cur.execute("SELECT kd_satuan, harga_jual FROM m_barang_satuan WHERE kd_barang = ?", [kd_barang])
        harga_lama = {_st(r["kd_satuan"]): _f(r["harga_jual"]) for r in _dictify(cur)}

        for kd_satuan, harga in prices.items():
            ks = _st(kd_satuan)
            harga = _f(harga)
            lama = harga_lama.get(ks, 0.0)
            margin = _margin(harga, modal.get(ks, 0.0)) if is_retail else 0.0
            cur.execute(
                "UPDATE m_barang_satuan SET harga_jual = ?, margin = ? WHERE kd_barang = ? AND kd_satuan = ?",
                [harga, margin, kd_barang, kd_satuan],
            )
            if cur.rowcount and lama != harga:
                changes.append({"kd_satuan": ks, "harga_lama": lama, "harga_baru": harga})
        cur.connection.commit()
    _invalidate_inventory_cache(profile)
    return changes


def update_status(profile, kd_barang: str, table: str, status, kd_divisi: str | None = None) -> dict:
    """Update kolom status di salah satu dari m_barang / m_barang_divisi / m_barang_satuan.

    Return {"n": jumlah baris ter-update, "lama": status sebelumnya (representatif,
    baris pertama yang cocok) untuk keperluan riwayat}.
    """
    if table not in _STATUS_TABLES:
        raise ValueError(f"Tabel status tidak valid: {table}")
    status = _st(status)
    if status not in ("0", "1", "2"):
        raise ValueError(f"Status tidak valid: {status}")

    where_sql = "WHERE kd_barang = ?"
    where_params: list = [kd_barang]
    if table == "m_barang_divisi" and kd_divisi:
        where_sql += " AND kd_divisi = ?"
        where_params.append(kd_divisi)

    with mssql.cursor(profile, autocommit=False) as cur:
        cur.execute(f"SELECT TOP 1 status FROM {table} {where_sql}", where_params)  # nosec: table di-whitelist di atas
        row = cur.fetchone()
        lama = _st(row[0]) if row else ""

        cur.execute(f"UPDATE {table} SET status = ? {where_sql}", [status] + where_params)  # nosec
        n = cur.rowcount
        cur.connection.commit()
    _invalidate_inventory_cache(profile)
    return {"n": n, "lama": lama}


# --- Sinkronisasi harga antar-server (WRITE) -------------------------------

def _harga_map(profile) -> dict:
    """(kd_barang, kd_satuan) -> {harga_jual, margin} untuk satu server."""
    def build():
        with mssql.cursor(profile) as cur:
            cur.execute("SELECT kd_barang, kd_satuan, harga_jual, margin FROM m_barang_satuan")
            return {
                (_st(r["kd_barang"]), _st(r["kd_satuan"])): {"harga_jual": _f(r["harga_jual"]), "margin": _f(r["margin"])}
                for r in _dictify(cur)
            }

    return _cached(profile, "harga_margin_map", build)


def compare_harga_jual(src_profile, dst_profile) -> list[dict]:
    """Baris m_barang_satuan yang harga_jual-nya beda (atau belum ada di dst)."""
    src = _harga_map(src_profile)
    dst = _harga_map(dst_profile)
    with mssql.cursor(src_profile) as cur:
        names = _key_map(cur, "SELECT kd_barang, nama FROM m_barang", "kd_barang", "nama")
    names = {_st(k): _st(v) for k, v in names.items()}

    out = []
    for (kb, ks), s in src.items():
        d = dst.get((kb, ks))
        harga_dst = d["harga_jual"] if d else None
        if d is not None and harga_dst == s["harga_jual"]:
            continue  # sama, lewati
        out.append({
            "kd_barang": kb,
            "kd_satuan": ks,
            "nama": names.get(kb, ""),
            "harga_src": s["harga_jual"],
            "harga_dst": harga_dst,
            "ada_di_dst": d is not None,
        })
    out.sort(key=lambda r: (r["nama"], r["kd_satuan"]))
    return out


def sync_harga_jual(src_profile, dst_profile, keys: list, with_margin: bool = False) -> int:
    """Salin harga_jual (dan margin bila with_margin) dari src ke dst untuk (kd_barang,kd_satuan) terpilih."""
    src = _harga_map(src_profile)
    n = 0
    with mssql.cursor(dst_profile, autocommit=False) as cur:
        for k in keys:
            kb, ks = _st(k.get("kd_barang")), _st(k.get("kd_satuan"))
            s = src.get((kb, ks))
            if not s:
                continue
            if with_margin:
                cur.execute(
                    "UPDATE m_barang_satuan SET harga_jual = ?, margin = ? WHERE kd_barang = ? AND kd_satuan = ?",
                    [s["harga_jual"], s["margin"], kb, ks],
                )
            else:
                cur.execute(
                    "UPDATE m_barang_satuan SET harga_jual = ? WHERE kd_barang = ? AND kd_satuan = ?",
                    [s["harga_jual"], kb, ks],
                )
            n += cur.rowcount
        cur.connection.commit()
    _invalidate_inventory_cache(dst_profile)
    return n


# --- Snapshot harga harian (diff-only) -------------------------------------

def snapshot_harga_changes(profile) -> dict:
    """Deteksi perubahan harga_jual per SKU dibanding baseline tersimpan
    (BarangHargaState di SQLite). Dipakai command `snapshot_harga` (sekali/hari).

    SKU baru → seed state (tanpa log). Harga beda → catat BarangHargaChange +
    update state. Idempotent (run kedua tanpa perubahan di server → 0 perubahan).
    Return {"changes": n, "seeded": m, "total": t}.
    """
    from apps.core.models import BarangHargaChange, BarangHargaState

    current = _harga_map(profile)  # {(kd_barang, kd_satuan): {harga_jual, margin}}
    with mssql.cursor(profile) as cur:
        names = _key_map(cur, "SELECT kd_barang, nama FROM m_barang", "kd_barang", "nama")
    names = {_st(k): _st(v) for k, v in names.items()}

    existing = {
        (s.kd_barang, s.kd_satuan): s
        for s in BarangHargaState.objects.filter(profile=profile)
    }

    new_states, upd_states, changes = [], [], []
    for (kb, ks), val in current.items():
        harga = Decimal(str(round(_f(val["harga_jual"]), 2)))
        margin = Decimal(str(round(_f(val["margin"]), 2)))
        st = existing.get((kb, ks))
        if st is None:
            new_states.append(
                BarangHargaState(profile=profile, kd_barang=kb, kd_satuan=ks, harga_jual=harga, margin=margin)
            )
            continue
        if st.harga_jual != harga:
            changes.append(
                BarangHargaChange(
                    profile=profile, profile_name=profile.name, kd_barang=kb,
                    nama_barang=names.get(kb, ""), kd_satuan=ks,
                    harga_lama=st.harga_jual, harga_baru=harga,
                )
            )
            st.harga_jual = harga
            st.margin = margin
            upd_states.append(st)

    if new_states:
        BarangHargaState.objects.bulk_create(new_states, batch_size=1000)
    if upd_states:
        # auto_now tidak jalan di bulk_update; last_seen tetap update lewat save
        # berikutnya kalau perlu — di sini fokusnya harga/margin.
        BarangHargaState.objects.bulk_update(upd_states, ["harga_jual", "margin"], batch_size=1000)
    if changes:
        BarangHargaChange.objects.bulk_create(changes, batch_size=1000)

    return {"changes": len(changes), "seeded": len(new_states), "total": len(current)}


# --- Sinkronisasi master data antar-server (m_barang/m_customer/m_supplier) -

# Kolom diverifikasi live via INFORMATION_SCHEMA.COLUMNS (bukan dari dump statis
# scripts/output/schema.json — dump itu sempat keliru untuk m_supplier).
# Dikecualikan dari sinkronisasi: m_barang.tanggal_daftar (timestamp lokal
# server, auto-default GETDATE(), tak boleh ditimpa) dan m_customer.point
# (saldo poin loyalitas — data transaksional, bukan identitas master).
_SYNC_ENTITIES = {
    "m_barang": {
        "table": "m_barang",
        "pk_cols": ["kd_barang"],
        "cols": ["kd_kategori", "kd_jenis_bahan", "kd_model", "kd_merk", "kd_warna",
                 "ukuran", "nama", "keterangan", "status", "status_pinjam", "pabrik"],
        "label": "Produk",
    },
    "m_customer": {
        "table": "m_customer",
        "pk_cols": ["kd_customer"],
        "cols": ["kd_kota", "nama", "alamat", "telepon", "fax", "kontak", "hp", "email",
                 "limit_kredit", "disc", "status", "parent", "keterangan",
                 "npwp_no", "nppkp_no", "npwp_nama", "npwp_alamat"],
        "label": "Pelanggan",
    },
    "m_supplier": {
        "table": "m_supplier",
        "pk_cols": ["kd_supplier"],
        "cols": ["kd_kota", "nama", "alamat", "telepon", "fax", "kontak", "hp", "email",
                 "kd_bank", "rekening", "jenis", "keterangan"],
        "label": "Supplier",
    },
}


def _entity_row_map(profile, entity: str) -> dict:
    """pk_tuple -> row dict (kolom pk + cols), untuk satu server. Cache seperti _harga_map."""
    cfg = _SYNC_ENTITIES[entity]
    cols = cfg["pk_cols"] + cfg["cols"]

    def build():
        with mssql.cursor(profile) as cur:
            cur.execute(f"SELECT {', '.join(cols)} FROM {cfg['table']}")
            out = {}
            for r in _dictify(cur):
                pk = tuple(_st(r[c]) for c in cfg["pk_cols"])
                out[pk] = r
            return out

    return _cached(profile, f"sync_entity_{entity}", build)


def compare_entity(entity: str, src_profile, dst_profile) -> list[dict]:
    """Baris m_barang/m_customer/m_supplier yang berbeda (atau belum ada di dst).

    Diff per-baris penuh: kembalikan baris bila ADA kolom yang beda, atau baris
    itu belum ada di dst sama sekali. `fields_changed` hanya untuk tampilan —
    apply tetap whole-row (semua kolom ter-set sekaligus), bukan per-kolom.
    """
    cfg = _SYNC_ENTITIES[entity]
    src = _entity_row_map(src_profile, entity)
    dst = _entity_row_map(dst_profile, entity)

    out = []
    for pk, s in src.items():
        d = dst.get(pk)
        fields_changed = []
        if d is not None:
            for c in cfg["cols"]:
                if _st(s[c]) != _st(d[c]):
                    fields_changed.append(c)
            if not fields_changed:
                continue  # sama persis, lewati
        row = {pk_col: _st(s[pk_col]) for pk_col in cfg["pk_cols"]}
        row["label"] = _st(s.get("nama"))
        row["fields_changed"] = fields_changed
        row["ada_di_dst"] = d is not None
        out.append(row)
    out.sort(key=lambda r: r["label"])
    return out


def sync_entity(entity: str, src_profile, dst_profile, keys: list[dict]) -> int:
    """Terapkan sinkronisasi whole-row untuk kunci (pk) terpilih.

    UPDATE bila baris sudah ada di dst; INSERT bila belum (identitas saja —
    trigger DB di server sudah menyediakan baris turunan seperti
    m_barang_satuan untuk m_barang baru, jangan buat manual di sini).
    """
    cfg = _SYNC_ENTITIES[entity]
    src = _entity_row_map(src_profile, entity)
    dst_existing = _entity_row_map(dst_profile, entity)
    n = 0
    with mssql.cursor(dst_profile, autocommit=False) as cur:
        for k in keys:
            pk = tuple(_st(k.get(c)) for c in cfg["pk_cols"])
            s = src.get(pk)
            if not s:
                continue
            if pk in dst_existing:
                set_clause = ", ".join(f"{c} = ?" for c in cfg["cols"])
                where_clause = " AND ".join(f"{c} = ?" for c in cfg["pk_cols"])
                params = [s[c] for c in cfg["cols"]] + [s[c] for c in cfg["pk_cols"]]
                cur.execute(f"UPDATE {cfg['table']} SET {set_clause} WHERE {where_clause}", params)
            else:
                insert_cols = cfg["pk_cols"] + cfg["cols"]
                placeholders = ", ".join(["?"] * len(insert_cols))
                params = [s[c] for c in insert_cols]
                cur.execute(
                    f"INSERT INTO {cfg['table']} ({', '.join(insert_cols)}) VALUES ({placeholders})", params
                )
            n += cur.rowcount
        cur.connection.commit()
    _invalidate_inventory_cache(dst_profile)
    return n


# --- helpers ---------------------------------------------------------------


def _invalidate_inventory_cache(profile):
    """Master-data writes must bust the shared cache (core/cache.py) — this
    clears both inventory's and master_data's cached lookups for the profile."""
    invalidate_master_cache(profile.pk)


def _key_map(cursor, sql, key, val) -> dict:
    cursor.execute(sql)
    return {r[key]: r[val] for r in _dictify(cursor)}

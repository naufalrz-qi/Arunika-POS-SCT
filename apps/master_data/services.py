"""Read services for legacy master data (m_*), via raw pyodbc.

PRD §5.3: table-level access only; joins & calculations done here in Python
(batch-fetch each table once, then merge with dict lookups — avoids N+1, §8.3).
"""
from __future__ import annotations

import math
import re

import pyodbc
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
    """Markup atas modal, dalam persen. 0 bila modal tak valid.

    JANGAN dibulatkan. Aplikasi POS lama memakai margin sebagai acuan dan
    menurunkan harga darinya (harga = modal * (1 + margin/100)); margin yang
    dipotong ke 4 desimal tidak cukup untuk mengembalikan harga bulat semula,
    sehingga harga tertulis balik jadi berpecahan (mis. 9200 -> 9200,0019).
    Presisi penuh float membuat perhitungan itu mendarat tepat di harga bulat.
    Tampilan yang butuh angka pendek memformat sendiri (toFixed/format).
    """
    return (harga_jual - modal) / modal * 100 if modal and modal > 0 else 0.0


class HargaTidakBulat(ValueError):
    """Harga jual mengandung pecahan rupiah (mis. 3000,001). Ditolak sebelum ditulis."""


def _cek_harga_bulat(prices: dict) -> dict:
    """Validasi {kd_satuan: harga} — harga wajib bilangan bulat rupiah dan >= 0.

    Kolom harga_jual di legacy schema bertipe pecahan, jadi nilai seperti
    3000.001 diterima DB tapi tampil sebagai "Rp3.000,001" dan merusak
    pembulatan di kasir. Ditolak di sini, bukan di view, supaya semua pemanggil
    update_harga ikut terlindungi.

    Return dict harga yang sudah dinormalkan ke float bulat.
    """
    bersih: dict = {}
    salah: list[str] = []
    for kd_satuan, harga in prices.items():
        ks = _st(kd_satuan)
        # None ditolak eksplisit: _f(None) -> 0.0, jadi field `harga` yang hilang
        # dari payload akan lolos sebagai "harga nol" dan menghapus harga barang.
        # bool ditolak juga karena True lolos int-check sebagai 1.
        if harga is None or isinstance(harga, bool):
            salah.append(f"{ks}: harga kosong")
            continue
        try:
            nilai = _f(harga)
        except (TypeError, ValueError):
            salah.append(f"{ks}: '{harga}' bukan angka")
            continue
        if not math.isfinite(nilai):
            # json.loads menerima NaN/Infinity; int(nan) melempar dan jadi 500.
            salah.append(f"{ks}: '{harga}' bukan angka")
        elif nilai < 0:
            salah.append(f"{ks}: {nilai} negatif")
        elif nilai != int(nilai):
            salah.append(f"{ks}: {nilai}")
        else:
            bersih[ks] = float(int(nilai))
    if salah:
        raise HargaTidakBulat(
            "Harga harus bilangan bulat rupiah (tanpa koma) dan tidak negatif — " + "; ".join(salah)
        )
    return bersih


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
            f"SELECT kd_barang, kd_kategori, kd_jenis_bahan, kd_model, kd_merk, kd_warna, "
            f"ukuran, nama, keterangan, pabrik, status, status_pinjam "
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
                "kd_jenis_bahan": _st(b.get("kd_jenis_bahan")),
                "kd_model": _st(b.get("kd_model")),
                "kd_merk": _st(b.get("kd_merk")),
                "kd_warna": _st(b.get("kd_warna")),
                "ukuran": _st(b.get("ukuran")),
                "keterangan": _st(b.get("keterangan")),
                "pabrik": _st(b.get("pabrik")),
                "satuan": (satuan_names.get(price.get("kd_satuan"), "") or "").strip(),
                "harga_jual": _f(price.get("harga_jual")),
                "stok": _f(stok_by_barang.get(kd, 0)),
                "status": _active(b["status"]),
                "status_pinjam": _st(b.get("status_pinjam")),
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
            f"SELECT kd_customer, kd_kota, nama, alamat, telepon, fax, kontak, hp, email, "
            f"point, limit_kredit, disc, status, parent, keterangan, npwp_no, nppkp_no, npwp_nama, npwp_alamat "
            f"FROM m_customer WHERE {where_sql} ORDER BY nama",
            params,
        )
        rows = _dictify(cur)

    return [
        {
            "kd_customer": (r["kd_customer"] or "").strip(),
            "kd_kota": _st(r.get("kd_kota")),
            "nama": (r["nama"] or "").strip(),
            "alamat": (r["alamat"] or "").strip(),
            "telepon": _st(r.get("telepon")),
            "fax": _st(r.get("fax")),
            "kontak": _st(r.get("kontak")),
            "hp": (r["hp"] or "").strip(),
            "email": (r["email"] or "").strip(),
            "point": _f(r["point"]),
            "limit_kredit": _f(r["limit_kredit"]),
            "disc": _f(r.get("disc")),
            "status": _active(r["status"]),
            "parent": _st(r.get("parent")),
            "keterangan": _st(r.get("keterangan")),
            "npwp_no": _st(r.get("npwp_no")),
            "nppkp_no": _st(r.get("nppkp_no")),
            "npwp_nama": _st(r.get("npwp_nama")),
            "npwp_alamat": _st(r.get("npwp_alamat")),
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
    # Modal per satuan = harga_jual server sumber-modal (cost_source): retail →
    # grosir/gudang, grosir → gudang. Diisi kapan pun cost_source diset (grosir
    # "bergantung gudang" = punya cost_source gudang); tanpa cost_source, modal
    # tak diisi.
    cost = mssql.get_cost_source(profile)
    has_modal = bool(cost)
    modal_all: dict[str, dict] = {}
    if cost:
        def _build_cost_satuan_price():
            with mssql.cursor(cost) as cost_cur:
                cost_cur.execute("SELECT kd_barang, kd_satuan, harga_jual FROM m_barang_satuan")
                by_barang: dict[str, dict] = {}
                for r in _dictify(cost_cur):
                    by_barang.setdefault(_st(r["kd_barang"]), {})[_st(r["kd_satuan"])] = _f(r["harga_jual"])
                return by_barang

        # Keyed by the cost-source profile itself: multiple profiles sharing one
        # grosir/gudang source reuse a single cached read.
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
            if has_modal:
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
            "has_modal": has_modal,
        })
    return out


# keterangan ditulis manual, mis. "ECER 3.450.000(50%)" / "ECER 300.000".
# Ambil bagian sebelum "(" (buang "(50%)"), angka pertama (format ribuan
# bertitik atau polos), lalu buang titik pemisah ribuan. Padanan Python dari
# parseKeteranganPrice di frontend (UpdateBarang.vue) — jaga keduanya seragam.
_KETERANGAN_PRICE_RE = re.compile(r"\d{1,3}(?:\.\d{3})+|\d+")


def parse_keterangan_price(ket) -> float | None:
    if not ket:
        return None
    m = _KETERANGAN_PRICE_RE.search(str(ket).split("(")[0])
    if not m:
        return None
    n = int(m.group(0).replace(".", ""))
    return float(n) if n > 0 else None


def list_saran_harga(profile) -> list[dict]:
    """Saran harga dari kolom keterangan untuk SELURUH katalog (tidak dibatasi
    MAX_ROWS seperti list_barang_edit) — dipakai halaman Pergerakan Harga.

    Satuan dasar = satuan dengan jumlah 1 (mis. PCS), fallback satuan pertama.
    Hanya barang yang harga jual satuan dasarnya beda dari nominal keterangan.
    """
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT kd_barang, nama, keterangan FROM m_barang "
            "WHERE keterangan IS NOT NULL AND LTRIM(RTRIM(keterangan)) <> ''"
        )
        barang = _dictify(cur)
        satuan_names = _cached(
            profile, "satuan_names", lambda: _key_map(cur, "SELECT kd_satuan, nama FROM m_satuan", "kd_satuan", "nama")
        )

        def _build_satuan_edit():
            cur.execute("SELECT kd_barang, kd_satuan, jumlah, harga_jual, margin, status FROM m_barang_satuan")
            by_barang: dict[str, list] = {}
            for r in _dictify(cur):
                by_barang.setdefault(_st(r["kd_barang"]), []).append(r)
            return by_barang

        # Cache key sama dengan list_barang_edit — saling berbagi hasil baca.
        satuan_by = _cached(profile, "satuan_edit", _build_satuan_edit)

    out = []
    for b in barang:
        kd = _st(b["kd_barang"])
        units = satuan_by.get(kd, [])
        base = next((u for u in units if _f(u["jumlah"]) == 1), units[0] if units else None)
        if base is None:
            continue
        target = parse_keterangan_price(b.get("keterangan"))
        harga = _f(base["harga_jual"])
        if target is None or target == harga:
            continue
        ks = _st(base["kd_satuan"])
        out.append({
            "kd_barang": kd,
            "nama": _st(b["nama"]),
            "keterangan": _st(b.get("keterangan", "")),
            "kd_satuan": ks,
            "satuan": _st(satuan_names.get(base["kd_satuan"], "")) or ks,
            "harga_lama": harga,
            "harga_baru": target,
            "selisih": target - harga,
        })
    # Prioritaskan barang yang keterangannya eksplisit soal %/margin, mis.
    # "ECER 3.450.000(50%)" — sinyal paling kuat kalau nominal itu memang harga
    # jual yang disengaja, bukan sekadar catatan bebas.
    def _priority(r):
        ket = r["keterangan"].lower()
        return 0 if ("%" in ket or "margin" in ket) else 1

    out.sort(key=lambda r: (_priority(r), r["nama"]))
    return out


def _harga_satuan(p) -> dict:
    """kd_barang -> {kd_satuan: harga_jual} untuk satu server."""
    with mssql.cursor(p) as cur:
        cur.execute("SELECT kd_barang, kd_satuan, harga_jual FROM m_barang_satuan")
        out: dict[str, dict] = {}
        for r in _dictify(cur):
            out.setdefault(_st(r["kd_barang"]), {})[_st(r["kd_satuan"])] = _f(r["harga_jual"])
        return out


def harga_acuan_gudang(gudang) -> dict:
    """Harga per satuan di server gudang, untuk dipakai sebagai acuan saran.

    Dipisah dari list_saran_harga_gudang supaya kegagalannya bisa DIBEDAKAN:
    gudang yang tak bisa dihubungi adalah keadaan yang wajar (lihat saran_harga),
    sementara gagal membaca server AKTIF adalah masalah nyata yang harus muncul.
    Kalau keduanya di dalam satu fungsi, satu `except` tak bisa membedakannya.

    Kunci cache sama dengan yang dipakai list_barang_edit untuk sumber-modal, dan
    di-key pada profil GUDANG-nya: beberapa grosir yang berbagi satu gudang ikut
    memakai satu hasil baca.
    """
    return _cached(gudang, "cost_satuan_price", lambda: _harga_satuan(gudang))


def list_saran_harga_gudang(profile, gudang, harga_gudang) -> list[dict]:
    """Saran harga NON-RETAIL: harga_jual barang di server gudang.

    Retail memakai nominal di kolom keterangan ("ECER 3.450.000") — itu harga
    ecer yang ditulis manual, dan artinya cuma benar untuk toko retail. Untuk
    grosir, nominal ECER itu harga orang lain. Yang jadi acuan mereka adalah
    harga di gudang, jadi saran harganya harga gudang itu sendiri.

    Dibandingkan PER SATUAN, bukan cuma satuan dasar seperti jalur retail: tiap
    satuan punya harga sendiri di kedua server, dan menyamakan hanya satuan dasar
    akan meninggalkan lusinan/dus menyimpang tanpa terlihat.

    Terukur di pasangan Testing -> testgudang: 54.101 baris, 771 (1,4%) berbeda —
    jadi daftarnya sebanding dengan daftar saran retail, tak perlu dipenggal.

    Baris yang TIDAK dikembalikan:
    - barang/satuan yang tak ada di gudang (98 baris di pengukuran itu). Tak ada
      acuan, dan mengarang 0 sebagai "saran" akan menghapus harga.
    - harga gudang <= 0. Itu barang tanpa harga jual (kresek/packaging), bukan
      saran untuk menjual gratis.
    """
    harga_lokal = _cached(profile, "satuan_harga_lokal", lambda: _harga_satuan(profile))

    with mssql.cursor(profile) as cur:
        cur.execute("SELECT kd_barang, nama, keterangan FROM m_barang")
        barang = {_st(r["kd_barang"]): r for r in _dictify(cur)}
        satuan_names_raw = _cached(
            profile, "satuan_names",
            lambda: _key_map(cur, "SELECT kd_satuan, nama FROM m_satuan", "kd_satuan", "nama"),
        )
    # Kunci cache itu MENTAH dari SQL (char() berspasi ekor); kunci di sini sudah
    # lewat _st(). MS SQL mengabaikan spasi ekor saat membandingkan, dict Python
    # tidak — tanpa normalisasi ini nama satuan diam-diam kosong dan kolom Satuan
    # jatuh ke kode satuannya. Aturan yang sama dengan _k() di inventory/services.
    satuan_names = {_st(k): _st(v) for k, v in satuan_names_raw.items()}

    out = []
    for kd, units in harga_lokal.items():
        acuan = harga_gudang.get(kd)
        if not acuan:
            continue
        b = barang.get(kd)
        for ks, harga in units.items():
            target = acuan.get(ks)
            if target is None or target <= 0 or target == harga:
                continue
            out.append({
                "kd_barang": kd,
                "nama": _st(b["nama"]) if b else kd,
                "keterangan": _st(b.get("keterangan", "")) if b else "",
                "kd_satuan": ks,
                "satuan": satuan_names.get(ks, "") or ks,
                "harga_lama": harga,
                "harga_baru": target,
                "selisih": target - harga,
            })
    # Selisih terbesar dulu: yang paling jauh menyimpang dari gudang itu yang
    # paling mendesak diperiksa, dan paling besar dampaknya kalau salah.
    out.sort(key=lambda r: (-abs(r["selisih"]), r["nama"]))
    return out


def saran_harga(profile) -> dict:
    """Saran harga untuk `profile` — satu pintu, dua mekanisme.

    {rows, sumber, gudang, pesan}. `sumber` menentukan kalimat yang ditampilkan
    layar, dan sengaja dibedakan dari "rows kosong": tak ada saran karena semua
    harga sudah sama, dan tak ada saran karena server acuannya belum diatur,
    adalah dua keadaan berbeda yang butuh dua tindakan berbeda.

    - retail        -> nominal di kolom keterangan (mekanisme lama, tak berubah)
    - non-retail    -> harga_jual di server gudang, ditemukan lewat rantai
                       cost_source (lihat mssql.get_gudang_source)
    - gudang sendiri-> tak ada saran; ia YANG jadi acuan
    - rantai buntu  -> tak ada saran; Sumber Modal memang OPSIONAL
    - gudang mati   -> tak ada saran; bukan kegagalan

    SELURUH fitur ini opsional dan tak pernah menghalangi apa pun. Sumber Modal
    tidak wajib diisi, dan gudang yang sedang mati tidak boleh terlihat seperti
    error: satu-satunya akibatnya adalah tak ada barang yang disarankan. Halaman
    Update Barang tetap bisa mengubah harga dan status seperti biasa.

    Karena itu pyodbc.Error dari pembacaan GUDANG ditangkap di sini, dan hanya
    dari pembacaan gudang — kegagalan membaca server AKTIF tetap dilempar, sebab
    itu masalah nyata yang harus terlihat. (ProfileAuthError turunan pyodbc.Error,
    jadi kunci enkripsi yang hilang ikut tertangkap di jalur yang sama.)

    Dipakai halaman Update Barang DAN Pergerakan Harga. Keduanya lewat fungsi ini
    supaya tak ada dua definisi "saran harga" yang bisa menyimpang.
    """
    if _is_retail(profile):
        return {"rows": list_saran_harga(profile), "sumber": "keterangan",
                "gudang": None, "pesan": None}

    gudang = mssql.get_gudang_source(profile)
    if gudang is None:
        return {
            "rows": [], "sumber": "tanpa_acuan", "gudang": None,
            "pesan": ("Server ini belum punya acuan gudang, jadi tidak ada saran "
                      "harga. Itu tidak apa-apa — saran harga sifatnya opsional. "
                      "Kalau ingin memakainya, isi Sumber Modal pada koneksi ini "
                      "di menu Koneksi Server sampai rantainya mencapai server "
                      "bertipe gudang."),
        }
    if gudang.pk == profile.pk:
        return {
            "rows": [], "sumber": "gudang_sendiri", "gudang": profile.name,
            "pesan": ("Server ini bertipe gudang, jadi ia yang menjadi acuan harga "
                      "bagi server lain — tidak ada harga lain untuk diikuti."),
        }

    try:
        harga_gudang = harga_acuan_gudang(gudang)
    except pyodbc.Error:
        return {
            "rows": [], "sumber": "gudang_offline", "gudang": gudang.name,
            "pesan": (f"Server gudang '{gudang.name}' sedang tidak bisa dihubungi, "
                      "jadi tidak ada saran harga untuk sekarang. Ini tidak "
                      "mengganggu apa pun di halaman ini — harga dan status tetap "
                      "bisa diubah seperti biasa. Coba lagi nanti."),
        }
    return {"rows": list_saran_harga_gudang(profile, gudang, harga_gudang),
            "sumber": "gudang", "gudang": gudang.name, "pesan": None}


def list_harga_pecahan(profile) -> list[dict]:
    """Audit: baris m_barang_satuan yang harga_jual-nya mengandung pecahan rupiah.

    Data lama yang masuk sebelum _cek_harga_bulat ada — mis. 3000,001 dari
    pembulatan margin yang meleset. Read-only; `harga_saran` cuma usulan
    (pembulatan ke terdekat), penulisan tetap lewat update_harga per barang.
    """
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT bs.kd_barang, b.nama, bs.kd_satuan, s.nama AS satuan, bs.harga_jual "
            "FROM m_barang_satuan bs "
            "LEFT JOIN m_barang b ON bs.kd_barang = b.kd_barang "
            "LEFT JOIN m_satuan s ON bs.kd_satuan = s.kd_satuan "
            "WHERE bs.harga_jual % 1 <> 0 "
            "ORDER BY bs.kd_barang, bs.kd_satuan"
        )
        rows = _dictify(cur)

    out = []
    for r in rows:
        harga = _f(r["harga_jual"])
        out.append({
            "kd_barang": _st(r["kd_barang"]),
            "nama": _st(r["nama"]),
            "kd_satuan": _st(r["kd_satuan"]),
            "satuan": _st(r["satuan"]) or _st(r["kd_satuan"]),
            "harga_jual": harga,
            # Pembulatan ke terdekat, .5 ke atas (bukan bankers rounding Python).
            "harga_saran": float(math.floor(harga + 0.5)),
        })
    return out


def update_harga(profile, kd_barang: str, prices: dict) -> list[dict]:
    """Update harga_jual (dan margin) per satuan. `prices`: {kd_satuan: harga_jual}.

    Retail: margin = markup atas modal (harga_jual server sumber-modal). Non-retail:
    kolom margin tidak disentuh — tidak ada sumber-modal untuk menghitungnya, dan
    UI menampilkannya read-only sehingga menimpanya dengan 0 = kehilangan data.
    Return daftar perubahan aktual: [{kd_satuan, harga_lama, harga_baru}, ...] (hanya yang
    nilainya benar-benar berubah) — dipakai caller untuk mencatat riwayat (BarangUpdateLog).

    Raise HargaTidakBulat bila ada harga berpecahan; divalidasi lebih dulu supaya
    tidak ada satuan yang terlanjur tertulis saat satuan lain ditolak.
    """
    prices = _cek_harga_bulat(prices)
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
            if is_retail:
                cur.execute(
                    "UPDATE m_barang_satuan SET harga_jual = ?, margin = ? WHERE kd_barang = ? AND kd_satuan = ?",
                    [harga, _margin(harga, modal.get(ks, 0.0)), kd_barang, kd_satuan],
                )
            else:
                # Non-retail tidak punya sumber-modal untuk menghitung margin, jadi
                # kolomnya tidak disentuh sama sekali. Sebelumnya ditulis 0 dan itu
                # menghapus margin tersimpan padahal UI menampilkannya read-only.
                cur.execute(
                    "UPDATE m_barang_satuan SET harga_jual = ? WHERE kd_barang = ? AND kd_satuan = ?",
                    [harga, kd_barang, kd_satuan],
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


# --- Identitas barang: nama & keterangan (WRITE, khusus gudang) ------------

# Panjang kolom m_barang di server legacy — keduanya varchar(50), diverifikasi
# lewat INFORMATION_SCHEMA. Dipotong DI SINI, bukan diserahkan ke MS SQL: driver
# akan menolak string yang lebih panjang dengan galat yang tak berarti apa pun
# bagi staf toko, dan memotongnya diam-diam di SQL akan menyembunyikan bahwa
# namanya tidak tersimpan utuh.
MAX_NAMA = 50
MAX_KETERANGAN = 50


class BukanServerGudang(Exception):
    """Identitas barang hanya boleh diubah dari server bertipe gudang."""


def _is_gudang(profile) -> bool:
    return profile.db_type == "gudang"


def update_nama_keterangan(profile, kd_barang: str, nama: str, keterangan: str) -> list[dict]:
    """Ubah `nama` dan/atau `keterangan` satu barang. HANYA di server gudang.

    Nama dan keterangan adalah identitas barang yang dipakai bersama seluruh
    cabang: ia muncul di nota, di laporan, dan di layar kasir tiap server. Kalau
    setiap server boleh menamai ulang barangnya sendiri, satu kode barang punya
    beberapa nama dan laporan lintas-server berhenti bisa dibaca. Gudang yang
    memegang katalog, jadi gudang yang boleh mengubahnya — cabang lain menerima
    lewat Sinkronisasi Master Data.

    Penjagaan ini WAJIB di sini, bukan hanya me-disable input di Vue: field yang
    disabled tetap bisa dikirim dengan permintaan buatan sendiri, dan yang menahan
    penulisannya cuma pemeriksaan ini.

    Return daftar perubahan NYATA: [{field, lama, baru}, ...] — kosong berarti
    tak ada yang berubah. Caller memakainya untuk riwayat dan ringkasan.

    Raise BukanServerGudang / ValueError (barang tak ada) tanpa menulis apa pun.
    """
    if not _is_gudang(profile):
        raise BukanServerGudang(
            f"Server '{profile.name}' bertipe {profile.db_type}. Nama dan keterangan "
            "barang hanya bisa diubah dari server gudang."
        )
    kd_barang = _st(kd_barang)
    if not kd_barang:
        raise ValueError("Kode barang tidak disebutkan.")

    nama_baru = _st(nama)[:MAX_NAMA]
    # keterangan NOT NULL di m_barang — string kosong, bukan None.
    ket_baru = _st(keterangan)[:MAX_KETERANGAN]
    if not nama_baru:
        raise ValueError("Nama barang tidak boleh kosong.")

    with mssql.cursor(profile) as cur:
        cur.execute("SELECT nama, keterangan FROM m_barang WHERE kd_barang = ?", [kd_barang])
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Barang {kd_barang} tidak ada di server ini.")
        nama_lama, ket_lama = _st(row[0]), _st(row[1])

        ubah = []
        if nama_lama != nama_baru:
            ubah.append({"field": "nama", "lama": nama_lama, "baru": nama_baru})
        if ket_lama != ket_baru:
            ubah.append({"field": "keterangan", "lama": ket_lama, "baru": ket_baru})
        if not ubah:
            return []

        # Satu UPDATE untuk keduanya: dua statement terpisah bisa menyimpan nama
        # baru lalu gagal di keterangan, meninggalkan barang setengah terubah.
        cur.execute(
            "UPDATE m_barang SET nama = ?, keterangan = ? WHERE kd_barang = ?",
            [nama_baru, ket_baru, kd_barang],
        )
        cur.connection.commit()

    _invalidate_inventory_cache(profile)
    return ubah


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


# Nama kolom MS SQL tak boleh muncul di layar operator toko. Satu peta datar
# (kolomnya banyak yang dipakai bersama antar entitas), hidup di sebelah
# _SYNC_ENTITIES supaya kolom baru dan labelnya ditambah di tempat yang sama.
COL_LABELS = {
    "kd_kategori": "Kategori", "kd_jenis_bahan": "Jenis Bahan", "kd_model": "Model",
    "kd_merk": "Merk", "kd_warna": "Warna", "ukuran": "Ukuran", "nama": "Nama",
    "keterangan": "Keterangan", "status": "Status", "status_pinjam": "Status Pinjam",
    "pabrik": "Pabrik", "kd_kota": "Kota", "alamat": "Alamat", "telepon": "Telepon",
    "fax": "Faks", "kontak": "Kontak", "hp": "HP", "email": "Email",
    "limit_kredit": "Limit Kredit", "disc": "Diskon", "parent": "Induk",
    "npwp_no": "No. NPWP", "nppkp_no": "No. NPPKP", "npwp_nama": "Nama NPWP",
    "npwp_alamat": "Alamat NPWP", "kd_bank": "Bank", "rekening": "Rekening",
    "jenis": "Jenis",
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

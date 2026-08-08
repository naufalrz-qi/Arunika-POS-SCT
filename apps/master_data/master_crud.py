"""CRUD master pelanggan & supplier untuk layar kasir/supervisor.

Satu mesin untuk dua entitas, bukan dua salinan. Bentuk keduanya nyaris sama —
kode + identitas + kontak — dan yang berbeda cuma daftar kolom serta cara kode
barunya dibuat, jadi keduanya dijelaskan sebagai DATA di `_MASTER` alih-alih
ditulis dua kali. Nama tabel dan kolom masuk ke SQL sebagai teks, jadi ia hanya
boleh berasal dari peta ini — tak pernah dari input. Pola yang sama dipakai
`_STATUS_TABLES` di services.py.

Dua hal yang gampang menggigit di skema legacy ini:

1. SELURUH kolom `m_customer` dan `m_supplier` NOT NULL — termasuk yang jelas
   opsional seperti fax dan email. INSERT karena itu wajib menyebut semua
   kolom; yang tak diisi pengguna dikirim sebagai string kosong, bukan NULL.

2. Kode baru dibuat dengan mesin penomoran yang sama dengan nomor nota
   (MAX terkunci + ulang saat bentrok). Balapannya persis sama: aplikasi POS
   lama ikut menambah pelanggan, di tabel yang sama, pada saat yang sama.
"""
from __future__ import annotations

import datetime as dt

from apps.transactions.penomoran import simpan_dengan_nomor, urut_berikutnya
from core import mssql

from apps.core.reporting import dictify as _dictify


def _st(value) -> str:
    return str(value).strip() if value is not None else ""


# kode: (awalan, format tanggal atau None, lebar urutan)
#   pelanggan  SCT20260323000017  = SCT + YYYYMMDD + 6 digit
#   supplier   SAA003             = SAA + 3 digit (tanpa tanggal)
# Keduanya dibaca dari data yang ada di server, bukan ditebak: awalannya bagian
# dari kode yang sudah dipakai bertahun-tahun.
_MASTER = {
    "pelanggan": {
        "tabel": "m_customer",
        "kunci": "kd_customer",
        "kode": ("SCT", "%Y%m%d", 6),
        "label": "Pelanggan",
        # Kolom yang boleh diisi dari layar.
        "teks": ["nama", "alamat", "telepon", "fax", "kontak", "hp", "email",
                 "keterangan", "parent", "npwp_no", "nppkp_no",
                 "npwp_nama", "npwp_alamat"],
        "angka": ["point", "limit_kredit", "disc", "status"],
        # Kolom berkunci-asing: nilainya HARUS kode yang sudah ada. String
        # kosong ditolak FK, jadi ia wajib diisi dan wajib berupa pilihan.
        "lookup": {"kd_kota": ("m_kota", "kd_kota")},
        "wajib": ["nama", "kd_kota"],
    },
    "supplier": {
        "tabel": "m_supplier",
        "kunci": "kd_supplier",
        "kode": ("SAA", None, 3),
        "label": "Supplier",
        "teks": ["nama", "alamat", "telepon", "fax", "kontak", "hp", "email",
                 "rekening", "keterangan"],
        "angka": ["jenis"],
        "lookup": {"kd_kota": ("m_kota", "kd_kota"), "kd_bank": ("m_bank", "kd_bank")},
        "wajib": ["nama", "kd_kota", "kd_bank"],
    },
}

# Panjang kolom teks di legacy. Dipangkas di sini supaya isian yang kepanjangan
# jadi pesan yang bisa dibaca, bukan galat ODBC "String or binary data would be
# truncated" yang tak memberi tahu kolom mana yang salah.
_PANJANG = {
    "nama": 35, "alamat": 50, "telepon": 10, "fax": 10, "kontak": 35, "hp": 15,
    "email": 30, "kd_kota": 6, "kd_bank": 6, "rekening": 25, "parent": 50,
    "npwp_no": 50, "nppkp_no": 50, "npwp_nama": 50, "npwp_alamat": 500,
}
_PANJANG_KETERANGAN = {"pelanggan": 200, "supplier": 50}

# Nama kolom legacy bukan bahasa manusia; pesan "Kd_kota wajib diisi" tak
# memberi tahu operator kotak mana yang harus ia isi.
_LABEL_WAJIB = {"nama": "Nama", "kd_kota": "Kota", "kd_bank": "Bank"}


def spec(entitas: str) -> dict:
    return _MASTER[entitas]  # KeyError kalau entitasnya tak dikenal — memang.


def list_master(profile, entitas: str, cari: str = "", limit: int = 200) -> list[dict]:
    """Daftar pelanggan/supplier, disaring di server.

    Dibatasi `limit`: m_customer punya 9.367 baris di server testing, dan
    mengirim semuanya ke layar kasir hanya untuk mencari satu nama itu
    pemborosan yang sama dengan yang dihindari layar Cek Stok.
    """
    s = spec(entitas)
    kolom = [s["kunci"], *_kolom_isi(s)]
    pilih = ", ".join(kolom)
    cari = _st(cari)
    with mssql.cursor(profile) as cur:
        if cari:
            cur.execute(  # nosec B608 — nama tabel/kolom dari _MASTER
                f"SELECT TOP (?) {pilih} FROM {s['tabel']} "
                f"WHERE nama LIKE ? OR {s['kunci']} LIKE ? ORDER BY nama",
                [limit, f"%{cari}%", f"%{cari}%"],
            )
        else:
            cur.execute(  # nosec B608 — nama tabel/kolom dari _MASTER
                f"SELECT TOP (?) {pilih} FROM {s['tabel']} ORDER BY nama", [limit])
        teks = set(s["teks"]) | set(s["lookup"]) | {s["kunci"]}
        return [{k: (_st(v) if k in teks else v) for k, v in r.items()}
                for r in _dictify(cur)]


def _kolom_isi(s) -> list[str]:
    """Kolom yang boleh diisi layar, urutannya tetap agar INSERT/UPDATE sejajar."""
    return [*s["teks"], *s["lookup"], *s["angka"]]


def list_lookups(profile, entitas: str) -> dict:
    """Pilihan untuk kolom berkunci-asing (kota, bank).

    Wajib ada sebelum baris baru bisa dibuat: FK menolak string kosong, jadi
    membiarkan kolomnya sebagai isian bebas berarti setiap penyimpanan pertama
    gagal dengan galat FK yang tak bisa dibaca operator.
    """
    s = spec(entitas)
    keluar: dict[str, list] = {}
    with mssql.cursor(profile) as cur:
        for field, (tabel, kunci) in s["lookup"].items():
            cur.execute(f"SELECT {kunci}, nama FROM {tabel} ORDER BY nama")  # nosec B608 — dari _MASTER
            keluar[field] = [{"value": _st(r[0]), "label": _st(r[1])}
                             for r in cur.fetchall()]
    return keluar


def _bersihkan(entitas: str, data) -> dict:
    """Ambil hanya kolom yang dikenal, dipangkas ke panjang kolomnya."""
    s = spec(entitas)
    keluar: dict = {}
    for k in [*s["teks"], *s["lookup"]]:
        batas = _PANJANG_KETERANGAN[entitas] if k == "keterangan" else _PANJANG.get(k, 50)
        keluar[k] = _st(data.get(k))[:batas]
    for k in s["angka"]:
        nilai = data.get(k)
        try:
            keluar[k] = float(nilai) if nilai not in (None, "") else 0
        except (TypeError, ValueError):
            keluar[k] = 0
    for w in s["wajib"]:
        if not keluar.get(w):
            raise ValueError(f"{_LABEL_WAJIB.get(w, w)} wajib diisi.")
    return keluar


def _kode_baru(cur, entitas: str) -> str:
    s = spec(entitas)
    awalan, fmt, lebar = s["kode"]
    pola = awalan + (dt.datetime.now().strftime(fmt) if fmt else "")
    return urut_berikutnya(cur, s["tabel"], s["kunci"], pola, lebar)


def simpan_master(profile, entitas: str, data) -> dict:
    """Buat atau ubah satu baris master. Mengembalikan kode & apakah baru.

    Kode hanya dibuat untuk baris BARU. Mengubah kode baris yang sudah ada akan
    memutus setiap nota yang menunjuk ke situ, jadi kuncinya tak pernah diikutkan
    sebagai field yang bisa disunting.
    """
    s = spec(entitas)
    nilai = _bersihkan(entitas, data)
    kode = _st(data.get(s["kunci"]))
    kolom = _kolom_isi(s)

    with mssql.cursor(profile, autocommit=False) as cur:
        if kode:
            # SELECT eksplisit, bukan cur.rowcount: trigger legacy membuat
            # rowcount tak bisa dipercaya untuk menyimpulkan sebuah baris ada.
            cur.execute(  # nosec B608 — dari _MASTER
                f"SELECT 1 FROM {s['tabel']} WHERE {s['kunci']} = ?", [kode])
            if not cur.fetchone():
                raise ValueError(f"{s['label']} {kode} tidak ada di server ini.")
            set_sql = ", ".join(f"{k} = ?" for k in kolom)
            cur.execute(  # nosec B608 — dari _MASTER
                f"UPDATE {s['tabel']} SET {set_sql} WHERE {s['kunci']} = ?",
                [nilai[k] for k in kolom] + [kode])
            cur.connection.commit()
            return {"kode": kode, "baru": False}

        # SELURUH kolom NOT NULL di skema ini, jadi semuanya disebut — yang tak
        # diisi pengguna berangkat sebagai string kosong, bukan NULL.
        semua = [s["kunci"], *kolom]
        tanya = ", ".join("?" for _ in semua)

        def tulis(baru):
            cur.execute(  # nosec B608 — dari _MASTER
                f"INSERT INTO {s['tabel']} ({', '.join(semua)}) VALUES ({tanya})",
                [baru] + [nilai[k] for k in kolom])

        kode = simpan_dengan_nomor(cur, lambda: _kode_baru(cur, entitas), tulis)
        cur.connection.commit()
        return {"kode": kode, "baru": True}

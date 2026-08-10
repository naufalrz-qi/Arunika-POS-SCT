"""CRUD master legacy: pelanggan, supplier, dan sepuluh tabel referensi.

Satu mesin untuk semua entitas, bukan satu salinan per tabel. Bentuknya nyaris
sama — kode + nama + beberapa kolom pelengkap — dan yang berbeda cuma daftar
kolom serta cara kode barunya dibuat, jadi semuanya dijelaskan sebagai DATA di
`_MASTER` alih-alih ditulis berulang. Nama tabel dan kolom masuk ke SQL sebagai
teks, jadi ia hanya boleh berasal dari peta ini — tak pernah dari input. Pola
yang sama dipakai `_STATUS_TABLES` di services.py.

Empat hal yang gampang menggigit di skema legacy ini:

1. SELURUH kolom `m_customer` dan `m_supplier` NOT NULL — termasuk yang jelas
   opsional seperti fax dan email. INSERT karena itu wajib menyebut semua
   kolom; yang tak diisi pengguna dikirim sebagai string kosong, bukan NULL.

2. Kode baru dibuat dengan mesin penomoran yang sama dengan nomor nota
   (MAX terkunci + ulang saat bentrok). Balapannya persis sama: aplikasi POS
   lama ikut menambah pelanggan, di tabel yang sama, pada saat yang sama.

3. **TIDAK ADA `DELETE` di sini, dan itu permanen.** `m_merk`, `m_kategori`,
   `m_model`, `m_warna`, dan `m_jenis_bahan` punya FK `ON DELETE CASCADE` ke
   `m_barang`, sedangkan `m_barang` → `m_barang_satuan`/`_divisi` justru
   `NO_ACTION`. Menghapus satu merk karena itu MENGHAPUS barang-barang "kosong"
   di bawahnya lalu gagal di tengah jalan begitu ketemu barang bersatuan —
   penghapusan separuh jadi, bukan galat bersih. Pembatalan memakai kolom
   `status` (lihat `pilihan` di bawah). Aturan menyeluruhnya di context.md
   § "Hak akses".

4. **Arti `status` dibaca dari data, bukan diasumsikan.** 0 memang nonaktif di
   mana-mana, tapi "aktif" tidak selalu 1: seluruh 38 baris `m_biaya` bernilai
   **2**. Menulis 1 di sana akan membuat setiap baris baru berbeda dari semua
   baris yang sudah ada, tanpa gejala apa pun di layar.
"""
from __future__ import annotations

import datetime as dt

from apps.transactions.penomoran import (
    kode_master_berikutnya,
    simpan_dengan_nomor,
    urut_berikutnya,
)
from core import mssql

from apps.core.reporting import clean_rows as _bersih, dictify as _dictify


def _st(value) -> str:
    return str(value).strip() if value is not None else ""


def _aktif_nonaktif(aktif=1) -> list[dict]:
    """Opsi kolom `status`. Yang PERTAMA jadi nilai bawaan baris baru.

    Urutannya karena itu bukan selera: `_bersihkan` memakai opsi pertama saat
    isiannya kosong, dan kalau Nonaktif yang di depan maka setiap baris baru
    lahir dalam keadaan mati. Itu persis yang terjadi di Kelola Pelanggan
    sebelum ini — isian kosong jatuh ke 0, dan 286 baris `m_customer` bernilai 0
    lawan 9.196 bernilai 1.
    """
    return [{"value": aktif, "label": "Aktif"}, {"value": 0, "label": "Nonaktif"}]


def _referensi(tabel: str, kunci: str, huruf: str, label: str, **ubah) -> dict:
    """Spec untuk tabel referensi berbentuk `kd_X + nama + keterangan + status`.

    Tujuh dari sepuluh tabel referensi berbentuk persis begini; sisanya memakai
    fungsi yang sama lalu menimpa bagian yang berbeda lewat `ubah`.
    """
    spec = {
        "tabel": tabel,
        "kunci": kunci,
        "huruf": huruf,
        "label": label,
        "teks": ["nama", "keterangan"],
        "angka": ["status"],
        "lookup": {},
        "wajib": ["nama"],
        "pilihan": {"status": _aktif_nonaktif()},
        "kolom_tabel": ["keterangan"],
    }
    spec.update(ubah)
    return spec


# Dua cara kode baru dibuat, dan sebuah entitas memakai TEPAT SATU dari keduanya:
#
#   "kode": (awalan, format tanggal, lebar)  → pelanggan: SCT20260323000017
#   "huruf": "M"                             → keluarga {huruf}{blok}{NNN}, mis.
#                                              MAA000 … MAA999, MAB000, …
#
# Keduanya dibaca dari data yang ada di server, bukan ditebak: awalannya bagian
# dari kode yang sudah dipakai bertahun-tahun. Supplier pindah dari `kode` ke
# `huruf` karena `("SAA", None, 3)` punya langit-langit `SAA999` yang pasti
# tercapai — 517 baris sudah terpakai, dan m_merk/m_model membuktikan bloknya
# memang bergulir (MAB483 / MAB296). Lihat `penomoran.kode_master_berikutnya`.
#
# Kunci spec opsional, semuanya bernilai bawaan supaya entitas lama tak berubah:
#   "pilihan"     — field → daftar opsi; dirender Select, opsi PERTAMA jadi bawaan
#   "kolom_tabel" — kolom tambahan yang ditampilkan di tabel daftar
#   "kolom_nama"  — kolom nama manusiawi, untuk ORDER BY & kotak cari (bawaan "nama")
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
        "pilihan": {"status": _aktif_nonaktif()},
        "kolom_tabel": ["alamat", "telepon", "hp"],
    },
    "supplier": {
        "tabel": "m_supplier",
        "kunci": "kd_supplier",
        "huruf": "S",
        "label": "Supplier",
        "teks": ["nama", "alamat", "telepon", "fax", "kontak", "hp", "email",
                 "rekening", "keterangan"],
        "angka": ["jenis"],
        "lookup": {"kd_kota": ("m_kota", "kd_kota"), "kd_bank": ("m_bank", "kd_bank")},
        "wajib": ["nama", "kd_kota", "kd_bank"],
        # `m_supplier` SATU-SATUNYA di peta ini yang tak punya kolom `status`
        # (13 kolom, diverifikasi lewat INFORMATION_SCHEMA). Jadi supplier tak
        # bisa dinonaktifkan — dan karena DELETE tak boleh, ia memang tak bisa
        # dibatalkan sama sekali. Jangan "perbaiki" dengan menambah kolom:
        # skema ini dipakai bersama aplikasi POS lama.
        "kolom_tabel": ["alamat", "telepon", "hp"],
    },
    # --- Referensi barang -------------------------------------------------
    "kategori": _referensi("m_kategori", "kd_kategori", "K", "Kategori"),
    "merk": _referensi("m_merk", "kd_merk", "M", "Merk"),
    "model": _referensi("m_model", "kd_model", "M", "Model"),
    "warna": _referensi("m_warna", "kd_warna", "W", "Warna"),
    "jenis-bahan": _referensi("m_jenis_bahan", "kd_jenis_bahan", "J", "Jenis Bahan"),
    "satuan": _referensi("m_satuan", "kd_satuan", "S", "Satuan"),
    # --- Referensi umum ---------------------------------------------------
    "bank": _referensi("m_bank", "kd_bank", "B", "Bank"),
    # `m_kota` tak punya kolom `keterangan`, tapi punya `kd_telp` (kode area) dan
    # `kd_negara` yang berkunci-asing ke `m_negara`.
    "kota": _referensi(
        "m_kota", "kd_kota", "K", "Kota",
        teks=["nama", "kd_telp"],
        lookup={"kd_negara": ("m_negara", "kd_negara")},
        wajib=["nama", "kd_negara"],
        kolom_tabel=["kd_telp"],
    ),
    # Aktif = 2 di sini, bukan 1: seluruh 38 baris yang ada bernilai 2.
    "biaya": _referensi(
        "m_biaya", "kd_biaya", "B", "Jenis Biaya",
        teks=["nama", "keterangan", "kd_index"],
        pilihan={"status": _aktif_nonaktif(aktif=2)},
        kolom_tabel=["keterangan", "kd_index"],
    ),
    "voucher": _referensi(
        "m_voucher", "kd_voucher", "V", "Voucher",
        angka=["nominal", "status"],
        kolom_tabel=["nominal", "keterangan"],
    ),
    # `m_kas` tak punya kolom `nama` sama sekali — yang manusiawi di sana
    # `cabang`. Tanpa `kolom_nama`, ORDER BY dan kotak carinya akan menunjuk
    # kolom yang tidak ada.
    "kas": _referensi(
        "m_kas", "kd_kas", "K", "Kas / Rekening",
        kolom_nama="cabang",
        teks=["cabang", "no_rekening", "kd_index", "telepon", "kontak", "keterangan"],
        angka=["saldo_awal", "status"],
        lookup={"kd_bank": ("m_bank", "kd_bank"), "kd_kota": ("m_kota", "kd_kota")},
        wajib=["cabang", "kd_bank", "kd_kota"],
        kolom_tabel=["no_rekening", "saldo_awal"],
    ),
}

# Entitas yang dilayani layar "Kelola Data Referensi" (satu menu, satu rute).
# Pelanggan & Supplier sengaja di luar daftar: keduanya sudah punya menunya
# sendiri, dan hak aksesnya sudah diberikan per akun lewat key menu masing-masing.
REFERENSI = ["kategori", "merk", "model", "warna", "jenis-bahan", "satuan",
             "bank", "kota", "biaya", "voucher", "kas"]

# Panjang kolom teks di legacy. Dipangkas di sini supaya isian yang kepanjangan
# jadi pesan yang bisa dibaca, bukan galat ODBC "String or binary data would be
# truncated" yang tak memberi tahu kolom mana yang salah.
_PANJANG = {
    "nama": 35, "alamat": 50, "telepon": 10, "fax": 10, "kontak": 35, "hp": 15,
    "email": 30, "kd_kota": 6, "kd_bank": 6, "rekening": 25, "parent": 50,
    "npwp_no": 50, "nppkp_no": 50, "npwp_nama": 50, "npwp_alamat": 500,
    # Referensi & kas — diverifikasi lewat INFORMATION_SCHEMA di testgudang,
    # bukan dibaca dari docs/skema/ (kolomnya bertipe UDT `JR_*` di sana, dan
    # dump itu tidak meresolusi panjang dasarnya).
    "kd_telp": 4, "kd_negara": 3, "kd_index": 10, "no_rekening": 25, "cabang": 50,
}
# `keterangan` panjangnya beda-beda per tabel; 50 bawaan seluruh tabel referensi.
_PANJANG_KETERANGAN = {"pelanggan": 200}
_PANJANG_KETERANGAN_BAWAAN = 50

# Nama kolom legacy bukan bahasa manusia; pesan "Kd_kota wajib diisi" tak
# memberi tahu operator kotak mana yang harus ia isi.
_LABEL_WAJIB = {"nama": "Nama", "kd_kota": "Kota", "kd_bank": "Bank",
                "kd_negara": "Negara", "cabang": "Nama / Cabang"}


def spec(entitas: str) -> dict:
    return _MASTER[entitas]  # KeyError kalau entitasnya tak dikenal — memang.


def _kolom_nama(s) -> str:
    """Kolom nama manusiawi. `m_kas` tak punya `nama`, ia memakai `cabang`."""
    return s.get("kolom_nama", "nama")


def list_master(profile, entitas: str, cari: str = "", limit: int = 200) -> list[dict]:
    """Daftar satu entitas master, disaring di server.

    Dibatasi `limit`: m_customer punya 9.367 baris di server testing, dan
    mengirim semuanya ke layar kasir hanya untuk mencari satu nama itu
    pemborosan yang sama dengan yang dihindari layar Cek Stok. m_kategori (862)
    dan m_merk (1.475) juga lewat batas ini.
    """
    s = spec(entitas)
    kolom = [s["kunci"], *_kolom_isi(s)]
    pilih = ", ".join(kolom)
    nama = _kolom_nama(s)
    cari = _st(cari)
    with mssql.cursor(profile) as cur:
        if cari:
            cur.execute(  # nosec B608 — nama tabel/kolom dari _MASTER
                f"SELECT TOP (?) {pilih} FROM {s['tabel']} "
                f"WHERE {nama} LIKE ? OR {s['kunci']} LIKE ? ORDER BY {nama}",
                [limit, f"%{cari}%", f"%{cari}%"],
            )
        else:
            cur.execute(  # nosec B608 — nama tabel/kolom dari _MASTER
                f"SELECT TOP (?) {pilih} FROM {s['tabel']} ORDER BY {nama}", [limit])
        # `clean_rows`, bukan pemangkasan buatan sendiri: selain membuang padding
        # char() ia mengubah Decimal → float dan datetime → teks. `m_kas.saldo_awal`
        # bertipe money, jadi tanpa ini prop-nya berisi Decimal — dan yang
        # menyerah bukan layar ini melainkan serialisasi Inertia-nya.
        return _bersih(_dictify(cur))


def _kolom_isi(s) -> list[str]:
    """Kolom yang boleh diisi layar, urutannya tetap agar INSERT/UPDATE sejajar."""
    return [*s["teks"], *s["lookup"], *s["angka"]]


def list_lookups(profile, entitas: str) -> dict:
    """Pilihan untuk kolom berkunci-asing (kota, bank, negara).

    Wajib ada sebelum baris baru bisa dibuat: FK menolak string kosong, jadi
    membiarkan kolomnya sebagai isian bebas berarti setiap penyimpanan pertama
    gagal dengan galat FK yang tak bisa dibaca operator.

    Yang nonaktif dibuang — kalau tidak, "nonaktifkan kota" tak berpengaruh apa
    pun dan tombolnya berbohong. Efek sampingnya disengaja dan terlihat: baris
    lama yang menunjuk kota nonaktif akan tampil dengan pilihan kosong saat
    diubah, lalu ditolak "Kota wajib diisi" — keluhan yang jelas, bukan nilai
    yang diam-diam berubah. Ketiga tabel tujuan (m_kota, m_bank, m_negara)
    punya kolom `status`; kalau nanti ada tujuan yang tidak punya, saringan ini
    harus jadi opsional di spec, bukan dibuang.
    """
    s = spec(entitas)
    keluar: dict[str, list] = {}
    with mssql.cursor(profile) as cur:
        for field, (tabel, kunci) in s["lookup"].items():
            cur.execute(  # nosec B608 — dari _MASTER
                f"SELECT {kunci}, nama FROM {tabel} WHERE status <> 0 ORDER BY nama")
            keluar[field] = [{"value": _st(r[0]), "label": _st(r[1])}
                             for r in cur.fetchall()]
    return keluar


def _bawaan(s, k):
    """Nilai bawaan sebuah kolom `pilihan`: opsi PERTAMA. None kalau bukan pilihan."""
    opsi = s.get("pilihan", {}).get(k)
    return opsi[0]["value"] if opsi else None


def _bersihkan(entitas: str, data) -> dict:
    """Ambil hanya kolom yang dikenal, dipangkas ke panjang kolomnya."""
    s = spec(entitas)
    keluar: dict = {}
    for k in [*s["teks"], *s["lookup"]]:
        batas = (_PANJANG_KETERANGAN.get(entitas, _PANJANG_KETERANGAN_BAWAAN)
                 if k == "keterangan" else _PANJANG.get(k, 50))
        keluar[k] = _st(data.get(k))[:batas]
    for k in s["angka"]:
        nilai = data.get(k)
        # Kolom berpilihan (status) jatuh ke opsi PERTAMA saat kosong, bukan ke
        # 0. Nol berarti "nonaktif" di seluruh skema ini, jadi bawaan 0 membuat
        # setiap baris baru lahir mati — dan di m_biaya bahkan "aktif" pun bukan
        # 1 melainkan 2, jadi angkanya memang harus datang dari spec.
        kosong = _bawaan(s, k)
        if kosong is None:
            kosong = 0
        try:
            keluar[k] = float(nilai) if nilai not in (None, "") else kosong
        except (TypeError, ValueError):
            keluar[k] = kosong
    for w in s["wajib"]:
        if not keluar.get(w):
            raise ValueError(f"{_LABEL_WAJIB.get(w, w)} wajib diisi.")
    return keluar


def _kode_baru(cur, entitas: str) -> str:
    """Kode baru menurut skema entitasnya — bertanggal, atau keluarga berblok."""
    s = spec(entitas)
    if "huruf" in s:
        return kode_master_berikutnya(cur, s["tabel"], s["kunci"], s["huruf"])
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

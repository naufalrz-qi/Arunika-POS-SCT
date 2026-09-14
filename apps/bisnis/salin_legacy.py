"""Salinan legacy untuk uji coba: baca server produksi, tulis ke database lokal.

## Kenapa perlu ada

View adapter `arunika_src.*` membaca tabel legacy **di instans SQL Server yang
sama** dengan database Arunika-nya. Itu artinya menguji dengan data PUSAT
menuntut salah satu dari dua hal: membuat database di SERVER-TOYS, atau
membawa datanya ke sini. Keputusannya tegas dan jadi aturan modul ini:

    Server produksi hanya DIBACA. Semua database uji dibuat di lokal.

Jadi yang dibawa ke sini tabel legacy mentah, persis bentuknya, dalam jendela
tanggal yang diminta. Sesudah itu pipeline yang sudah terbukti berjalan tanpa
perubahan: `init_arunika` memasang view di atas salinan ini, `isi_arunika`
mengisi tabel Arunika dari view itu.

## Beban di server produksi

Hanya `SELECT` di bawah READ UNCOMMITTED (`mssql.report_cursor`), jadi tak ada
shared lock yang memblok tulis POS. Pekerjaan berat -- nilai uang tiap nota,
agregasi GHB -- sengaja TIDAK terjadi di sana: ia terjadi di view lokal saat
`isi_arunika` membacanya.

## Tabel mana, dan bagaimana dipotong

Daftarnya DITURUNKAN dari badan adapter (`tabel_dirujuk`), bukan ditulis tangan:
kalau adapter mulai membaca tabel baru, salinan ikut membawanya. Tiap tabel lalu
masuk satu dari tiga kelas, ditentukan kolomnya sendiri:

* master (`m_*`)             -> disalin utuh; sebuah nota 2025 bisa merujuk
                                barang yang dibuat bertahun-tahun sebelumnya
* kepala (punya `tanggal`)   -> dipotong ke jendela
* detail (tanpa `tanggal`)   -> ikut kepalanya lewat satu-satunya kunci yang
                                ia punya: `no_transaksi`, `no_retur`, atau
                                `no_order`

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from __future__ import annotations

import re

# Tabel penanda di database salinan. Ada = database ini boleh ditimpa ulang.
PENANDA = "_salinan_legacy"

KUNCI_DETAIL = ("no_transaksi", "no_retur", "no_order")

_TEKS = {"char", "varchar", "nchar", "nvarchar", "text", "ntext"}
_PANJANG = {"char", "varchar", "nchar", "nvarchar", "binary", "varbinary"}
_LOB = {"text", "ntext", "image", "xml"}


# Tabel yang TIDAK dibaca adapter tapi dibutuhkan layar legacy aplikasi, supaya
# profil salinan bisa dipilih di navbar dan dipakai -- bukan cuma jadi sumber
# `isi_arunika`. Ditulis tangan karena sumbernya kode layar, bukan badan adapter.
#
# Daftarnya dicari dengan mencocokkan nama di `apps/inventory/services.py`
# terhadap tabel yang BENAR-BENAR ada di PUSAT, bukan dari galat satu per satu:
#
# * `g_tutup_buku` -- `_closing_date` mengambil tanggal tutup buku terakhir dari
#   sini. Tanpanya seluruh layar stok gagal "Invalid object name".
# * `m_barang_supplier` -- `_barang_meta` membaca supplier per barang.
#
# Sengaja TIDAK ikut, walau namanya muncul di berkas yang sama:
#
# * `pos_stok_snapshot` / `pos_stok_snapshot_base` -- cache buatan aplikasi ini
#   sendiri, dan mesin stok sudah menangani ketiadaannya ("snapshot belum ada ->
#   jalur lambat"). Isinya saldo SERVER SUMBER per hari ini, termasuk pergerakan
#   di luar jendela salinan; menyalinnya menerapkan saldo itu ke data yang tak
#   memuat pergerakan tersebut, dan stoknya salah tanpa satu galat pun.
# * `m_barang_stok_akhir` -- cuma disebut di docstring; cache legacy yang rusak.
TAMBAHAN_LAYAR = ("g_tutup_buku", "m_barang_supplier")


def tabel_dirujuk() -> list[str]:
    """Tabel legacy yang dibaca adapter mana pun (termasuk `pergerakan_stok`),
    ditambah `TAMBAHAN_LAYAR`."""
    from apps.bisnis import adapter, master_src

    bagian = [master_src.badan_legacy(n, "X") for n in master_src.daftar()]
    bagian.append(adapter.ddl_pergerakan_stok("X"))
    # Dipisah spasi: badan yang digabung tanpa pemisah pernah menghasilkan nama
    # palsu `m_barang_satuanCREATE`.
    teks = "\n".join(bagian)
    return sorted(set(re.findall(r"dbo\.((?:m_|t_|pos_)\w+)\b", teks)) | set(TAMBAHAN_LAYAR))


def tipe_kolom(c: dict) -> str:
    """Satu definisi kolom `CREATE TABLE` dari baris INFORMATION_SCHEMA.COLUMNS.

    Semua kolom NULL-able dan tanpa default/constraint: ini salinan DATA untuk
    dibaca view, bukan tiruan skema vendor. Kolom terhitung (`t_penjualan_detail
    .total`, yang definisinya rusak di legacy) jadi kolom biasa berisi nilainya.
    `timestamp`/`rowversion` tak bisa diisi, jadi disimpan sebagai varbinary(8).
    """
    t = c["DATA_TYPE"].lower()
    if t in ("timestamp", "rowversion"):
        s = "varbinary(8)"
    elif t in _PANJANG:
        n = c["CHARACTER_MAXIMUM_LENGTH"]
        s = f"{t}({'max' if n in (-1, None) else n})"
    elif t in ("decimal", "numeric"):
        s = f"{t}({c['NUMERIC_PRECISION']},{c['NUMERIC_SCALE']})"
    elif t in ("datetime2", "datetimeoffset", "time"):
        s = f"{t}({c['DATETIME_PRECISION']})"
    else:
        s = t
    # Collation ikut, sebab seluruh adapter bertumpu pada perbandingan yang
    # tak peka huruf besar-kecil -- server tujuan belum tentu berdefault sama.
    if t in _TEKS and c.get("COLLATION_NAME"):
        s += f" COLLATE {c['COLLATION_NAME']}"
    return f"[{c['COLUMN_NAME']}] {s} NULL"


def punya_lob(kolom: list[dict]) -> bool:
    """`fast_executemany` mengalokasikan buffer selebar kolom maksimum; untuk
    `image`/`varchar(max)` itu bisa berarti gigabyte per batch."""
    return any(
        c["DATA_TYPE"].lower() in _LOB
        or (c["DATA_TYPE"].lower() in _PANJANG and c["CHARACTER_MAXIMUM_LENGTH"] == -1)
        for c in kolom
    )


def kelas_tabel(nama: str, kolom_per_tabel: dict[str, list[str]]) -> tuple[str, str, str]:
    """(kelas, kepala, kunci). kelas: `utuh`, `kepala`, atau `detail`.

    Detail dikenali dari akhiran `_detail` DAN kepala yang bertanggal; kuncinya
    kolom kunci yang dimiliki detail itu. Tabel `t_*` yang tak cocok pola mana
    pun ditolak, bukan disalin utuh: menyalin utuh tabel transaksi berarti
    diam-diam membawa seluruh riwayat produksi.
    """
    kol = set(kolom_per_tabel.get(nama, []))
    if not nama.startswith("t_"):
        return ("utuh", "", "")
    if "tanggal" in kol:
        return ("kepala", "", "")
    if nama.endswith("_detail"):
        kepala = nama[: -len("_detail")]
        if "tanggal" in set(kolom_per_tabel.get(kepala, [])):
            for k in KUNCI_DETAIL:
                if k in kol:
                    return ("detail", kepala, k)
    raise ValueError(
        f"{nama}: tabel transaksi tanpa `tanggal` dan tanpa kepala bertanggal. "
        "Tentukan cara memotongnya alih-alih menyalin seluruh riwayatnya."
    )


def sql_baca(nama: str, kolom: list[str], kelas: str, kepala: str, kunci: str) -> str:
    daftar = ", ".join(f"x.[{k}]" for k in kolom)
    if kelas == "utuh":
        return f"SELECT {daftar} FROM dbo.[{nama}] x"
    if kelas == "kepala":
        return f"SELECT {daftar} FROM dbo.[{nama}] x WHERE x.tanggal >= ? AND x.tanggal < ?"
    return (
        f"SELECT {daftar} FROM dbo.[{nama}] x WHERE EXISTS ("
        f"SELECT 1 FROM dbo.[{kepala}] h WHERE h.[{kunci}] = x.[{kunci}] "
        "AND h.tanggal >= ? AND h.tanggal < ?)"
    )

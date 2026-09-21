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

import datetime as dt
import re
import time

from apps.bisnis.siapkan import Ditolak, diam, sql_buat_database
from core import mssql
from core.encryption import decrypt_checked

# Tabel penanda di database salinan. Ada = database ini boleh ditimpa ulang.
PENANDA = "_salinan_legacy"

BATCH = 5000

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


# ---------------------------------------------------------------------------
# Menjalankan salinan. Dipakai perintah `salin_legacy` dan layar Transfer ke
# Arunika; keduanya cuma berbeda cara menampilkan `lapor`.
# ---------------------------------------------------------------------------

def _metadata(sumber) -> dict[str, list[dict]]:
    """Kolom seluruh tabel dbo sumber: satu kueri, tanpa membaca isi."""
    with mssql.report_cursor(sumber) as src:
        src.execute(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
            "NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION, COLLATION_NAME "
            "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
        nama_kol = [d[0] for d in src.description]
        meta: dict[str, list[dict]] = {}
        for r in src.fetchall():
            baris = dict(zip(nama_kol, r))
            meta.setdefault(baris["TABLE_NAME"], []).append(baris)
    return meta


def rencana(sumber) -> tuple[list[str], dict, dict]:
    """(tabel, rencana per tabel, metadata). Menolak kalau sumber tak lengkap."""
    tabel = tabel_dirujuk()
    meta = _metadata(sumber)
    hilang = [t for t in tabel if t not in meta]
    if hilang:
        raise Ditolak(
            f"Server '{sumber.name}' tak punya tabel yang dibutuhkan: {', '.join(hilang)}. "
            "Profil ini bukan database POS legacy."
        )
    kolom_per_tabel = {t: [c["COLUMN_NAME"] for c in cs] for t, cs in meta.items()}
    return tabel, {t: kelas_tabel(t, kolom_per_tabel) for t in tabel}, meta


def _siapkan_database(tujuan, lapor) -> None:
    """Buat database kalau belum ada; kalau ada, WAJIB salinan buatan kita.

    Penjaga ini yang mencegah `--tujuan Testing` menghapus salinan grosirPusat:
    profil itu juga ber-lingkungan uji, jadi penanda lingkungan saja tak cukup.
    """
    pw = decrypt_checked(tujuan.password_encrypted)
    db = tujuan.db_name
    sql_buat = sql_buat_database(db)
    conn = mssql._connect(tujuan.host, tujuan.port, "master", tujuan.username, pw)
    try:
        cur = conn.cursor()
        cur.execute("SELECT DB_ID(?)", [db])
        if cur.fetchone()[0] is None:
            cur.execute(sql_buat)
            cur.execute(f"ALTER DATABASE [{db}] SET RECOVERY SIMPLE")
            lapor({"jenis": "info", "pesan": f"database [{db}] dibuat"})
        else:
            cur.execute(
                f"SELECT OBJECT_ID('[{db}].dbo.[{PENANDA}]'), "
                f"(SELECT COUNT(*) FROM [{db}].sys.tables)"
            )
            penanda, n_tabel = cur.fetchone()
            if penanda is None and n_tabel:
                raise Ditolak(
                    f"Database [{db}] sudah berisi {n_tabel} tabel dan BUKAN salinan "
                    "buatan fitur ini. Menolak menimpanya."
                )
            lapor({"jenis": "info", "pesan": f"database [{db}] salinan lama, ditimpa"})
    finally:
        conn.close()

    conn = mssql._connect(tujuan.host, tujuan.port, db, tujuan.username, pw)
    try:
        conn.cursor().execute(
            f"IF OBJECT_ID('dbo.[{PENANDA}]') IS NULL "
            f"CREATE TABLE dbo.[{PENANDA}] (sumber varchar(300), dari datetime, "
            "sampai datetime, jumlah_tabel int, disalin_pada datetime2)"
        )
    finally:
        conn.close()


def _salin_tabel(src, dst, dst_conn, t, kolom, kelas, kepala, kunci, dari, sampai_eksklusif) -> int:
    dst.execute(f"IF OBJECT_ID('dbo.[{t}]') IS NOT NULL DROP TABLE dbo.[{t}]")
    dst.execute(f"CREATE TABLE dbo.[{t}] (" + ", ".join(tipe_kolom(c) for c in kolom) + ")")
    nama = [c["COLUMN_NAME"] for c in kolom]
    src.execute(sql_baca(t, nama, kelas, kepala, kunci),
                *([] if kelas == "utuh" else [dari, sampai_eksklusif]))

    ins = (f"INSERT INTO dbo.[{t}] (" + ", ".join(f"[{k}]" for k in nama)
           + ") VALUES (" + ", ".join("?" * len(nama)) + ")")
    dst.fast_executemany = not punya_lob(kolom)
    n = 0
    while True:
        potong = src.fetchmany(BATCH)
        if not potong:
            break
        dst.executemany(ins, [tuple(r) for r in potong])
        n += len(potong)
    # Indeks secukupnya supaya view di atas salinan tak memindai tiap kali:
    # tanpanya `_nota_net` meng-GROUP BY 800 ribu baris detail tanpa bantuan.
    for k in ("no_transaksi", "no_retur", "no_order", "tanggal", "kd_barang"):
        if k in nama:
            dst.execute(f"CREATE INDEX [ix_{t}_{k}] ON dbo.[{t}] ([{k}])")
    dst_conn.commit()
    return n


def salin(sumber, tujuan, dari: dt.date, sampai: dt.date, lapor=diam) -> dict:
    """Salin tabel legacy `sumber` ke database `tujuan.db_name`. `sampai` inklusif.

    Sumber hanya DIBACA (`report_cursor`, READ UNCOMMITTED). Tujuan wajib
    lingkungan `uji` dan databasenya kosong atau salinan buatan fitur ini.
    """
    from apps.connections.models import Lingkungan
    from apps.transactions.indexes import ensure_indexes

    if tujuan.lingkungan != Lingkungan.UJI:
        raise Ditolak(f"Profil tujuan '{tujuan.name}' bukan lingkungan 'uji'.")
    if (sumber.host.lower(), sumber.db_name.lower()) == (tujuan.host.lower(), tujuan.db_name.lower()):
        raise Ditolak("Sumber dan tujuan menunjuk database yang sama.")
    if dari > sampai:
        raise Ditolak("Tanggal awal lewat dari tanggal akhir.")
    mulai = dt.datetime.combine(dari, dt.time.min)
    akhir = dt.datetime.combine(sampai, dt.time.min) + dt.timedelta(days=1)

    tabel, rencana_tabel, meta = rencana(sumber)
    _siapkan_database(tujuan, lapor)

    total, t0 = 0, time.time()
    pw = decrypt_checked(tujuan.password_encrypted)
    dst_conn = mssql._connect(tujuan.host, tujuan.port, tujuan.db_name,
                              tujuan.username, pw, autocommit=False)
    try:
        dst = dst_conn.cursor()
        with mssql.report_cursor(sumber) as src:
            for t in tabel:
                t1 = time.time()
                kelas, kepala, kunci = rencana_tabel[t]
                n = _salin_tabel(src, dst, dst_conn, t, meta[t], kelas, kepala, kunci, mulai, akhir)
                total += n
                lapor({"jenis": "langkah", "nama": t, "kelas": kelas, "baris": n,
                       "detik": round(time.time() - t1, 1), "dilewati": 0, "alasan": {}})
        dst.execute(f"INSERT INTO dbo.[{PENANDA}] VALUES (?, ?, ?, ?, SYSDATETIME())",
                    f"{sumber.host}/{sumber.db_name}", mulai, akhir - dt.timedelta(days=1),
                    len(tabel))
        dst_conn.commit()
    finally:
        dst_conn.close()

    # Indeks laporan/stok yang sama dengan server aslinya. Menyalin ulang
    # menghapus tabel beserta indeksnya, jadi dipasang di sini, bukan diserahkan
    # ke ingatan. Tanpanya stok 30 Juni 2025 di salinan PUSAT butuh 15,5 dtk;
    # dengannya 1,6 dtk -- dan angkanya identik. Indeks untuk tabel yang tak ikut
    # salinan (mis. t_pegawai_ganti_shift) memang gagal; itu dilaporkan.
    gagal, _ = ensure_indexes(tujuan, out=lambda *_a, **_k: None)
    lapor({"jenis": "info", "pesan": f"indeks laporan/stok dipasang; {len(gagal)} dilewati "
                                     "(tabelnya tak ikut salinan)"})
    return {"tabel": len(tabel), "baris": total, "detik": round(time.time() - t0, 1)}

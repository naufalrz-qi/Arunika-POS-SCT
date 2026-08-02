r"""Skema pusat data AMPHOREUS, dibangkitkan dari katalog server sumber.

## Kenapa dibangkitkan, bukan ditulis tangan

Ada ~20 tabel yang harus ada di pusat. `CREATE TABLE` yang disalin manual akan
menyimpang dari sumbernya dalam hitungan bulan — seseorang menambah kolom di
server cabang, pusat diam-diam berhenti menerimanya, dan tak ada yang tahu sampai
sebuah laporan kosong. Karena itu DDL dibaca dari `sys.columns` server acuan
(GUDANG) tiap kali `init_hub` dijalankan.

## Yang sengaja BERBEDA dari skema legacy

Pusat ini milik kita, jadi tiga cacat skema legacy tidak ikut diwarisi:

1. **Primary key betulan** pada `(kd_sumber, <kunci alami>)`. `t_penjualan_detail`
   di legacy adalah heap tanpa PK sama sekali — itu yang dulu memaksa
   `apps/transactions/cdc_sync.py` memakai CDC alih-alih replikasi biasa.
2. **Computed column tidak dibawa.** `t_penjualan_detail.total` di legacy dibuat
   dengan setelan ANSI_NULLS/QUOTED_IDENTIFIER yang salah (lihat
   `apps/transactions/indexes.py`) sehingga memblokir penambahan indeks. Nilainya
   juga tidak ada di feed. Laporan menghitung sendiri.
3. **Kolom IDENTITY diratakan** jadi kolom biasa. Nilainya datang dari cabang;
   pusat tidak boleh membangkitkan nomornya sendiri.

## kd_sumber

Kolom pertama tiap tabel, diisi dari `ServerProfile.kode_sumber`. Wajib, karena
tidak ada apa pun di data legacy yang menandai server asal (`divisi_id` bernilai
DAA000/DAA004 di semua server) DAN `no_transaksi` bisa sama antar-server — RUMAK
dan RTL RUMAK sama-sama punya `TR2608010005`, transaksi yang berbeda kalau
keduanya cabang berbeda. Tanpa `kd_sumber` di PK, nota dua cabang saling menimpa
dan omzet salah tanpa ada yang error.
"""
from __future__ import annotations

from core import mssql

KOL_SUMBER = "kd_sumber"
KOL_SUMBER_TIPE = "varchar(20)"

# Tipe yang butuh panjang / presisi saat di-render jadi DDL.
_TIPE_BERPANJANG = {"varchar", "nvarchar", "char", "nchar", "varbinary", "binary"}
_TIPE_BERPRESISI = {"decimal", "numeric"}


def _render_tipe(kol: dict) -> str:
    """Satu baris `sys.columns` -> potongan tipe DDL."""
    nama = kol["tipe"]
    if nama in _TIPE_BERPANJANG:
        if kol["max_length"] == -1:
            panjang = "max"
        elif nama in ("nvarchar", "nchar"):
            panjang = str(kol["max_length"] // 2)  # max_length dalam byte
        else:
            panjang = str(kol["max_length"])
        return f"{nama}({panjang})"
    if nama in _TIPE_BERPRESISI:
        return f"{nama}({kol['precision']},{kol['scale']})"
    return nama


def baca_kolom(cur, tabel: str) -> list[dict]:
    """Kolom `tabel` di server acuan, tanpa computed column.

    Computed column dibuang di sini, bukan di pemanggil: satu-satunya yang ada
    (`t_penjualan_detail.total`) tidak dikirim lewat feed dan definisinya di
    legacy rusak. Menyalinnya berarti membawa serta cacat yang sudah diketahui.
    """
    cur.execute("SELECT OBJECT_ID(?)", [tabel])
    if cur.fetchone()[0] is None:
        raise RuntimeError(f"Tabel acuan '{tabel}' tidak ada di server acuan.")
    cur.execute(
        "SELECT name, TYPE_NAME(system_type_id), max_length, precision, scale, is_nullable "
        "FROM sys.columns WHERE object_id = OBJECT_ID(?) AND is_computed = 0 "
        "ORDER BY column_id",
        [tabel],
    )
    return [
        {
            "nama": r[0], "tipe": r[1], "max_length": r[2],
            "precision": r[3], "scale": r[4], "nullable": bool(r[5]),
        }
        for r in cur.fetchall()
    ]


def ddl_tabel(tabel: str, kolom: list[dict], key_columns: list[str]) -> str:
    """`CREATE TABLE` pusat: kd_sumber + kolom sumber + PK komposit.

    Kolom kunci dipaksa NOT NULL walau di sumber nullable — sebuah PK tidak bisa
    dibangun dari kolom yang boleh kosong, dan baris berkunci NULL tidak akan
    pernah bisa dicocokkan ulang saat sync berikutnya.
    """
    kunci = set(key_columns)
    baris = [f"    [{KOL_SUMBER}] {KOL_SUMBER_TIPE} NOT NULL"]
    for k in kolom:
        if k["nama"] == KOL_SUMBER:
            continue  # jangan pernah menggandakan penanda sumber
        null = "NULL" if (k["nullable"] and k["nama"] not in kunci) else "NOT NULL"
        baris.append(f"    [{k['nama']}] {_render_tipe(k)} {null}")
    pk = ", ".join(f"[{c}]" for c in [KOL_SUMBER] + key_columns)
    baris.append(f"    CONSTRAINT [PK_{tabel}] PRIMARY KEY CLUSTERED ({pk})")
    return f"CREATE TABLE [{tabel}] (\n" + ",\n".join(baris) + "\n)"


def ddl_tabel_detail(tabel: str, kolom: list[dict], parent_key: str) -> str:
    """`CREATE TABLE` untuk tabel detail: TANPA primary key.

    Tabel detail tidak punya kunci per baris yang andal — satu nota sah punya dua
    baris untuk `kd_barang` yang sama (dua harga, dua diskon). PK
    `(kd_sumber, no_transaksi, kd_barang)` akan menolak nota yang sah.

    Gantinya clustered index pada `(kd_sumber, <parent_key>)`, karena satu-satunya
    tulisan yang pernah terjadi di tabel ini adalah "hapus semua baris nota X lalu
    masukkan lagi" — dan itu jadi range seek, bukan scan.
    """
    baris = [f"    [{KOL_SUMBER}] {KOL_SUMBER_TIPE} NOT NULL"]
    for k in kolom:
        if k["nama"] == KOL_SUMBER:
            continue
        null = "NULL" if (k["nullable"] and k["nama"] != parent_key) else "NOT NULL"
        baris.append(f"    [{k['nama']}] {_render_tipe(k)} {null}")
    ddl = f"CREATE TABLE [{tabel}] (\n" + ",\n".join(baris) + "\n)"
    idx = (
        f"CREATE CLUSTERED INDEX [CIX_{tabel}] ON [{tabel}] "
        f"([{KOL_SUMBER}], [{parent_key}])"
    )
    return ddl + ";\n" + idx


def ddl_indeks(tabel: str, kolom_ada: set, indeks: list[list[str]]) -> list[str]:
    """Indeks laporan, hanya untuk kolom yang memang ada di tabel ini.

    Selalu diawali `kd_sumber`: hampir setiap kueri pusat menyaring per cabang,
    dan indeks yang tidak memuatnya memaksa scan seluruh cabang untuk menjawab
    pertanyaan tentang satu cabang.
    """
    keluar = []
    for i, kols in enumerate(indeks, start=1):
        if not all(c in kolom_ada for c in kols):
            continue
        nama = f"IX_{tabel}_{i}"
        daftar = ", ".join(f"[{c}]" for c in [KOL_SUMBER] + kols)
        keluar.append(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{nama}' "
            f"AND object_id = OBJECT_ID('{tabel}')) "
            f"CREATE INDEX [{nama}] ON [{tabel}] ({daftar})"
        )
    return keluar


def buat_skema(ref_profile, hub_profile, specs: dict, dry_run: bool = False) -> list[dict]:
    """Buat tabel pusat yang belum ada. Idempoten: yang sudah ada dilewati.

    Sengaja TIDAK menyentuh tabel yang sudah ada — tidak ada ALTER, tidak ada
    DROP. Kalau skema cabang berubah, itu perlu keputusan manusia (dan mungkin
    migrasi data), bukan DDL yang dijalankan diam-diam oleh sebuah command.
    Perbedaannya dilaporkan sebagai `kolom_baru` supaya terlihat.
    """
    hasil = []
    with mssql.cursor(ref_profile) as ref_cur, mssql.cursor(hub_profile, autocommit=False) as hub_cur:
        for tabel, spec in specs.items():
            kolom = baca_kolom(ref_cur, tabel)
            nama_kolom = {k["nama"] for k in kolom}
            kunci = spec.get("key_columns") or [spec["parent_key"]]
            hilang = [c for c in kunci if c not in nama_kolom]
            if hilang:
                raise RuntimeError(
                    f"{tabel}: kolom kunci {hilang} tidak ada di server acuan — "
                    f"perbaiki HUB_TABLE_SPECS, jangan buat tabel tanpa kunci benar."
                )

            hub_cur.execute("SELECT OBJECT_ID(?)", [tabel])
            sudah_ada = hub_cur.fetchone()[0] is not None
            baris = {"tabel": tabel, "dibuat": False, "indeks": 0, "kolom_baru": []}

            if not sudah_ada:
                if not dry_run:
                    if "parent_key" in spec:
                        # DDL + clustered index dipisah: SQL Server tidak menerima
                        # dua pernyataan dalam satu exec lewat pyodbc.
                        for pernyataan in ddl_tabel_detail(
                            tabel, kolom, spec["parent_key"]
                        ).split(";\n"):
                            hub_cur.execute(pernyataan)
                    else:
                        hub_cur.execute(ddl_tabel(tabel, kolom, spec["key_columns"]))
                baris["dibuat"] = True
            else:
                hub_cur.execute(
                    "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?)", [tabel]
                )
                punya = {r[0] for r in hub_cur.fetchall()}
                baris["kolom_baru"] = sorted(nama_kolom - punya)

            if not dry_run:
                for sql in ddl_indeks(tabel, nama_kolom, spec.get("indeks", [])):
                    hub_cur.execute(sql)
                    baris["indeks"] += 1
            hasil.append(baris)

        if dry_run:
            hub_cur.connection.rollback()
        else:
            hub_cur.connection.commit()
    return hasil

"""Koreksi stok — menulis ke `t_opname_stok`.

Bentuknya beda dari setiap jalur tulis lain di aplikasi ini, dan bedanya bukan
gaya melainkan paksaan dari database lama. Empat hal yang dipastikan langsung
dari server nyata (PAGESANGAN, 4.917 baris; PUSAT), masing-masing mengubah kode
di bawah:

1. TABELNYA DATAR. Satu `no_transaksi` = satu baris = satu barang; tak ada
   tabel detail. Koreksi lima barang berarti lima nomor, bukan satu kepala
   dengan lima baris. Karena itu di sini tak ada `SPEC` kepala/detail seperti
   `transaksi.py`.

2. NOMORNYA TETAP BERBENTUK NOTA. `CP2608060001` di PAGESANGAN (kepala_nota
   `CP`), `SC2608080001` di PUSAT (`SC`) — persis `{kepala_nota}{YYMMDD}{NNNN}`
   yang sudah dibuat `penomoran.no_berikutnya`, jadi penomorannya dipakai ulang
   apa adanya.

3. `trig_update_stok_opname_stok` TIDAK AMAN UNTUK MULTI-BARIS. Isinya
   `SELECT @barang = inserted.kd_barang ... FROM inserted` — assignment skalar
   dari sebuah tabel. Satu INSERT berisi banyak baris hanya akan menyesuaikan
   stok untuk SATU baris (yang mana, tak ditentukan), dan sisanya lenyap tanpa
   galat: barisnya tetap tercatat, stoknya saja yang tak pernah bergerak.
   ITULAH sebabnya `_tulis_satu` dipanggil per item, bukan sekali dengan
   executemany. Jangan pernah menggabungkannya "supaya efisien".

4. ARAH KOREKSI ADA DI `status`, DAN TRIGGER-LAH YANG MENDEFINISIKANNYA:
   `IF @status <> 2 SET @jumlah = @jumlah * -1`. Jadi 2 menambah stok, selain
   itu mengurangi. Data nyata memakai 2 (2.678 baris) dan 3 (2.130); 0/1/4
   sisa lama yang langka. Kita menulis 2 dan 3 — cocok dengan trigger, dengan
   data, dan dengan `reports.opname` yang sudah membaca "status=2 masuk, selain
   itu keluar".

Stok dan sync tidak disentuh dari sini. `trig_update_stok_opname_stok`
memanggil `sp_update_stok_akhir`, dan `insert_temp_m_t_opname_stok` yang
mengantar barisnya ke pusat.
"""
from __future__ import annotations

import datetime as dt

from apps.transactions.penomoran import awalan_untuk, no_berikutnya, simpan_dengan_nomor
from core import mssql

# Empat jenis koreksi. Labelnya BUKAN karangan kita — ia terbaca di view
# `mon_t_opname_stok` milik aplikasi legacy:
#
#   status = CASE t_opname_stok.status
#              WHEN 0 THEN 'Hilang'  WHEN 1 THEN 'Rusak'
#              WHEN 2 THEN 'Lain-Lain(+)'  WHEN 3 THEN 'Lain-Lain (-)' END
#
# Arahnya TIDAK dipilih terpisah, melainkan melekat pada jenisnya, karena
# trigger yang memutuskan: `IF @status <> 2 SET @jumlah = @jumlah * -1`. Jadi
# hanya Lain-Lain(+) yang menambah stok; tiga sisanya mengurangi. Menyediakan
# pilihan arah sendiri berarti mengizinkan "Rusak, stok bertambah".
#
# Bahwa jenisnya perlu berlabel jelas bukan dugaan: di gudang ada 30 baris
# ber-status 3 (Lain-Lain −) yang keterangannya diketik "RUSAK" — operator
# memilih jenis yang salah lalu menuliskan maksudnya sebagai teks bebas.
HILANG, RUSAK, LAIN_PLUS, LAIN_MINUS = 0, 1, 2, 3
JENIS = {
    "hilang": HILANG,
    "rusak": RUSAK,
    "lain_plus": LAIN_PLUS,
    "lain_minus": LAIN_MINUS,
}
# Satu-satunya jenis yang menambah stok. Dipakai layar untuk memilih jenis
# bawaan dari tanda selisih, dan di sini untuk menyusun ringkasan.
MENAMBAH = "lain_plus"

# Nilai `status` lain pernah ada di data lama (mis. 4 — satu baris di
# PAGESANGAN) tapi TIDAK punya label di view legacy sama sekali. Ia sampah,
# bukan jenis kelima; jangan ditulis lagi.

# `keterangan` bertipe varchar(50). Menyimpan yang lebih panjang ditolak SQL
# Server dengan galat yang tak berarti apa-apa bagi operator, jadi dipotong di
# sini — potongan lebih baik daripada koreksi yang gagal tersimpan.
PANJANG_KETERANGAN = 50

KOLOM = ["no_transaksi", "kd_divisi", "kd_barang", "kd_satuan", "tanggal",
         "qty", "keterangan", "kd_user", "status", "tanggal_server"]


def _qty(it) -> float:
    """Qty sebuah baris, atau ValueError yang bisa dibaca operator.

    `float()` telanjang melempar "could not convert string to float: '1,5'" —
    kalimat yang tak berarti apa-apa bagi orang yang sedang menghitung rak, dan
    justru '1,5' yang paling mungkin diketik di sini (koma desimal Indonesia).
    """
    mentah = str(it.get("qty", "")).strip().replace(",", ".")
    try:
        return float(mentah)
    except ValueError:
        raise ValueError(
            f"Qty barang {it.get('kd_barang')} bukan angka: \"{it.get('qty')}\". "
            f"Tulis angkanya saja, mis. 3 atau 1.5.") from None


def _periksa(items, kd_user: str) -> None:
    """Tolak yang tak bisa ditulis, dengan alasan yang bisa ditindaklanjuti."""
    if not kd_user:
        raise ValueError(
            "Akun Anda belum ditautkan ke user legacy untuk koneksi ini, jadi "
            "koreksi stok tak bisa dicatat atas nama Anda. Minta pengelola "
            "aplikasi mengisinya di Kelola Tautan User."
        )
    if not items:
        raise ValueError("Belum ada barang — tambahkan minimal satu baris.")
    for it in items:
        if not str(it.get("kd_barang") or "").strip():
            raise ValueError("Ada baris tanpa barang.")
        if not str(it.get("kd_satuan") or "").strip():
            raise ValueError(
                f"Baris {it.get('kd_barang')} belum punya satuan. Satuan menentukan "
                f"berapa unit stok yang bergeser, jadi ia tak boleh ditebak.")
        if _qty(it) <= 0:
            raise ValueError(f"Qty barang {it.get('kd_barang')} harus lebih dari nol.")
        if str(it.get("jenis") or "") not in JENIS:
            raise ValueError(
                f"Jenis koreksi barang {it.get('kd_barang')} belum dipilih "
                f"(Hilang, Rusak, Lain-Lain + atau Lain-Lain −).")


def _periksa_divisi(cur, kd_divisi: str) -> str:
    """Pastikan `kd_divisi` benar-benar divisi aktif DI SERVER INI.

    Divisi di sini datang dari layar — satu-satunya nilai yang begitu — dan ia
    memutuskan dua hal sekaligus: stok divisi mana yang bergeser, dan (lewat
    `awalan_untuk`) awalan nomor koreksinya. Karena itu ia diperiksa, bukan
    dipercaya.

    Ia HARUS dipilih, tidak boleh ditebak. Toko memang berisi satu divisi
    (`DAA000` di RTL PUSAT, PUSAT, PAGESANGAN), tapi gudang berisi lima — dan di
    sana seluruh 6.698 baris opname ada di DAA001 (PERGUDANGAN, awalan `GP`),
    sedangkan DAA000 (UMUM, `UM`) tak punya satu pun. Mengambil "divisi aktif
    pertama" berarti mencatat koreksi gudang ke divisi yang tak pernah dipakai,
    dengan awalan nomor yang salah pula.
    """
    kd = (kd_divisi or "").strip()
    if not kd:
        raise ValueError(
            "Divisi belum dipilih. Divisi menentukan stok mana yang bergeser dan "
            "awalan nomor koreksinya, jadi ia tak boleh ditebak.")
    cur.execute(
        "SELECT COUNT(*) FROM m_divisi WHERE kd_divisi = ? AND status <> 0", [kd])
    if not (cur.fetchone() or [0])[0]:
        raise ValueError(
            f"Divisi {kd} tidak ada atau tidak aktif di server ini.")
    return kd


def buat_koreksi(profile, *, kd_user, kd_divisi, items, keterangan, tanggal=None) -> dict:
    """Tulis koreksi stok, satu baris per barang. Mengembalikan {nomor, baris}.

    Satu transaksi untuk semuanya: koreksi yang separuh jadi berarti stok
    bergeser separuh, dan tak ada yang akan tahu baris mana yang tak sempat
    ditulis.
    """
    _periksa(items, kd_user)
    catatan = (keterangan or "").strip()
    if not catatan:
        raise ValueError(
            "Keterangan wajib diisi — itu satu-satunya tempat sebab koreksi "
            "tercatat, dan yang dibaca orang saat membalance selisih nanti.")
    catatan = catatan[:PANJANG_KETERANGAN]
    tanggal = tanggal or dt.datetime.now()
    tanya = ", ".join("?" for _ in KOLOM)
    nomor = []

    with mssql.cursor(profile, autocommit=False) as cur:
        kd_divisi = _periksa_divisi(cur, kd_divisi)
        # Awalan dari divisi YANG DIPILIH, bukan dari divisi aktif pertama:
        # kepala_nota disimpan per divisi (GP untuk PERGUDANGAN, GO untuk GUDANG
        # OBRAL, UM untuk UMUM), dan itu terbaca di nomor opname gudang.
        awalan = awalan_untuk(cur, kd_divisi)

        for it in items:
            ctx = {
                "kd_divisi": kd_divisi,
                "kd_barang": str(it["kd_barang"]).strip(),
                "kd_satuan": str(it["kd_satuan"]).strip(),
                "tanggal": tanggal,
                "qty": _qty(it),
                "keterangan": catatan,
                "kd_user": kd_user,
                "status": JENIS[it["jenis"]],
                # Tak ada default constraint di kolom ini, tapi 0 dari 4.917
                # baris lama bernilai NULL — aplikasi POS lama menulisnya
                # sendiri. Jebakan yang sama dengan t_penjualan_order.
                "tanggal_server": dt.datetime.now(),
            }

            def tulis(no, ctx=ctx):
                ctx["no_transaksi"] = no
                # Satu baris per execute. Lihat catatan (3) di atas berkas —
                # menggabungkannya membuat stok berhenti bergerak diam-diam.
                cur.execute(
                    f"INSERT INTO t_opname_stok ({', '.join(KOLOM)}) VALUES ({tanya})",
                    [ctx[k] for k in KOLOM],
                )

            nomor.append(simpan_dengan_nomor(
                cur, lambda: no_berikutnya(cur, "opname", awalan, tanggal), tulis))

        cur.connection.commit()

    return {"nomor": nomor, "baris": len(nomor)}

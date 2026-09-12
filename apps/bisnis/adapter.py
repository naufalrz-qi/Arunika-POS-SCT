"""Adapter: membuat server legacy menyajikan bentuk skema Arunika.

Aplikasi hanya mengenal satu nama untuk buku besar stok. Di database milik
Arunika, `pergerakan_stok` adalah tabel nyata (`apps/bisnis/models.py`). Di
server legacy, ia sebuah **inline table-valued function** bernama sama di schema
`arunika`, yang badannya adalah UNION sembilan sumber yang selama ini disusun
ulang tiap kueri oleh `apps.inventory.services._movement_sql`.

## Kenapa dibangkitkan, bukan ditulis tangan

`_movement_sql` adalah ~180 baris SQL yang tiap barisnya dibayar pengukuran:
satu baris satuan dasar per barang supaya `stok_awal` tidak berganda, kategori
jasa dibuang, jendela tanggal yang berbeda untuk blok saldo awal, pembalikan
debet/kredit untuk tanggal sebelum tutup buku. Menyalinnya ke sini berarti dua
salinan logika uang dan stok yang akan menyimpang dalam hitungan bulan, dan
selisihnya tidak akan memunculkan galat apa pun -- hanya angka yang berbeda.

Karena itu badan fungsinya **dibangkitkan dari `_movement_sql` sendiri**:
fungsi itu dipanggil dengan nilai penanda yang khas, lalu tiap `?` di SQL
hasilnya ditukar dengan nama parameter T-SQL yang sesuai. Satu sumber kebenaran,
nol transkripsi.

## Kenapa iTVF, dan kenapa parameternya WAJIB

Terukur 2026-09-07 di server uji lokal (`testgudang`, `t_penjualan_detail`
569.831 baris), UNION tiga sumber difilter satu `kd_barang`:

    UNION tulis-tangan, parameter apa adanya   0,1208 dtk
    UNION tulis-tangan + bind_varchar          0,0187 dtk
    iTVF, parameter WAJIB                      0,0192 dtk
    iTVF, parameter OPSIONAL                   0,0967 dtk

Dua pelajaran, dan keduanya berlawanan dengan dugaan awal:

1. **iTVF tidak lebih lambat -- ia setara.** Kekhawatiran bahwa predikat tak
   akan turun ke dalam blok tidak terbukti; SQL Server men-inline-nya.
2. **Parameter yang bertipe di tanda tangan fungsi memperbaiki jebakan NVARCHAR
   dengan sendirinya.** Nilainya dikonversi sekali di batas fungsi, bukan
   meracuni predikat tiap cabang. Itulah kenapa iTVF menyamai varian
   `bind_varchar` tanpa perlu memanggilnya.

**Parameter opsional (`@p IS NULL OR kol = @p`) 5x lebih lambat** dan tidak
boleh dipakai: satu badan fungsi tidak bisa melayani banyak bentuk filter dengan
rencana yang optimal. Karena itu tiap bentuk filter dapat fungsinya sendiri.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from __future__ import annotations

import datetime as dt
import re

from apps.inventory import services as inv

# Schema yang sama dengan view master (`apps/bisnis/master_src.py`), di dalam
# database ARUNIKA -- bukan di database legacy.
#
# Penempatan ini berubah setelah Fase 4: semula fungsi ini dipasang di dalam
# database legacy. Sekarang tidak ada satu objek pun yang dibuat di sana, dan
# badan fungsinya membaca legacy lintas-database. Konsekuensinya tiap nama
# tabel legacy harus berkualifikasi database -- lihat `_kualifikasi()`.
SKEMA = "arunika_src"

# Awalan nama tabel legacy yang muncul di badan `_movement_sql`. Dipakai untuk
# mengenali mana yang perlu dikualifikasi; sisanya (derived table, alias) tidak.
_AWALAN_LEGACY = ("m_", "t_", "pos_")

_RUJUKAN = re.compile(
    r"\b(FROM|JOIN)\s+((?:" + "|".join(_AWALAN_LEGACY) + r")\w+)", re.IGNORECASE
)


def _kualifikasi(sql: str, db_legacy: str) -> tuple[str, int]:
    """Beri kualifikasi `[db].dbo.` pada tiap rujukan tabel legacy.

    Fungsi ini hidup di database Arunika, jadi `FROM t_penjualan_detail` akan
    dicari di database ITU dan gagal. Yang dikualifikasi hanya nama berawalan
    legacy sesudah FROM/JOIN; `FROM (SELECT ...` tidak cocok karena polanya
    menuntut karakter kata, dan alias tabel tidak pernah didahului FROM/JOIN.

    Pulangkan juga jumlah rujukan yang disentuh, supaya pemanggil bisa menolak
    hasil yang mencurigakan alih-alih memasang fungsi yang separuh benar.
    """
    if "]" in db_legacy:
        raise ValueError(f"Nama database tak bisa dikutip aman: {db_legacy!r}")
    n = 0

    def ganti(m):
        nonlocal n
        n += 1
        return f"{m.group(1)} [{db_legacy}].dbo.{m.group(2)}"

    return _RUJUKAN.sub(ganti, sql), n

# Nilai penanda: khas, mustahil muncul sebagai data, dan bertipe benar supaya
# `_movement_sql` memperlakukannya persis seperti nilai sungguhan (ia memeriksa
# truthiness untuk memutuskan klausa mana yang disusun).
_PENANDA = {
    "closing": dt.datetime(1901, 1, 1),
    "date_from": dt.datetime(1903, 3, 3),
    "date_to": dt.datetime(1902, 2, 2),
    "kd_divisi": "@@PENANDA_DIVISI@@",
    "kd_barang": "@@PENANDA_BARANG@@",
}

# Tanda tangan fungsi. `varchar`, bukan `nvarchar` -- itu yang membuat
# perbandingan dengan kolom legacy tetap seek (lihat docstring).
_TIPE = {
    "closing": "datetime",
    "date_from": "datetime",
    "date_to": "datetime",
    "kd_divisi": "varchar(30)",
    "kd_barang": "varchar(30)",
}


def _peta_parameter(params: list) -> list[str]:
    """params hasil `_movement_sql` -> nama parameter T-SQL, urut posisi.

    Kalau ada satu nilai saja yang bukan penanda, generator ini salah paham
    terhadap `_movement_sql` dan harus BERHENTI. Menebak di sini berarti
    memasang fungsi yang memfilter dengan konstanta tahun 1901.
    """
    balik = {v: k for k, v in _PENANDA.items()}
    keluar = []
    for i, nilai in enumerate(params):
        if nilai not in balik:
            raise RuntimeError(
                f"Parameter ke-{i} ({nilai!r}) bukan penanda yang dikenal. "
                "_movement_sql berubah bentuk; perbarui adapter ini alih-alih menebak."
            )
        keluar.append("@" + balik[nilai])
    return keluar


def badan_fungsi() -> tuple[str, list[str]]:
    """Pulangkan (badan SELECT, urutan nama parameter yang dipakai)."""
    sql, params = inv._movement_sql(
        _PENANDA["closing"],
        kd_barang=_PENANDA["kd_barang"],
        kd_divisi=_PENANDA["kd_divisi"],
        date_to=_PENANDA["date_to"],
        date_from=_PENANDA["date_from"],
    )
    nama = _peta_parameter(params)
    if sql.count("?") != len(nama):
        raise RuntimeError(
            f"Jumlah '?' ({sql.count('?')}) tidak sama dengan jumlah parameter "
            f"({len(nama)}). Ada '?' di dalam literal string, atau _movement_sql berubah."
        )
    potongan = sql.split("?")
    badan = "".join(p + n for p, n in zip(potongan, nama)) + potongan[-1]
    return badan, nama


def ddl_pergerakan_stok(db_legacy: str) -> str:
    """`CREATE FUNCTION arunika_src.pergerakan_stok` lengkap.

    Urutan parameter dibuat TETAP (bukan urutan kemunculan di SQL) supaya
    pemanggil bisa mengandalkannya walau `_movement_sql` menyusun ulang
    klausanya.
    """
    badan, _ = badan_fungsi()
    badan, n = _kualifikasi(badan, db_legacy)
    # Kalau tak ada satu pun rujukan yang dikualifikasi, `_movement_sql` pasti
    # berubah bentuk -- dan fungsinya akan tercipta dengan sukses lalu gagal
    # saat dipanggil, dari dalam laporan, berbulan-bulan kemudian.
    if n == 0:
        raise RuntimeError(
            "Tak satu pun rujukan tabel legacy dikenali di badan fungsi. "
            "_movement_sql berubah bentuk; perbarui _AWALAN_LEGACY alih-alih menebak."
        )
    urut = ["closing", "date_from", "date_to", "kd_divisi", "kd_barang"]
    tanda = ", ".join(f"@{n_} {_TIPE[n_]}" for n_ in urut)
    return (
        f"CREATE FUNCTION [{SKEMA}].[pergerakan_stok] ({tanda})\n"
        f"RETURNS TABLE AS RETURN (\n{badan}\n)"
    )


URUT_PARAMETER = ("closing", "date_from", "date_to", "kd_divisi", "kd_barang")


GAYA_PYODBC = "?"
GAYA_DJANGO = "%s"


def panggil(gaya: str = GAYA_PYODBC) -> str:
    """Potongan `FROM` untuk memanggil fungsi itu.

    **Gaya placeholder-nya WAJIB dipilih, dan salah pilih tidak menghasilkan
    pesan yang menolong.** Ada dua jalur akses data di aplikasi ini dan keduanya
    memakai konvensi berbeda:

        core/mssql.cursor(profile)      -> pyodbc, placeholder `?`
        django.db.connections[alias]    -> mssql-django, placeholder `%s`

    Memanggil lewat koneksi Django dengan `?` gagal jauh dari sebabnya --
    galatnya muncul di pemformat SQL debug Django sebagai
    `TypeError: not all arguments converted during string formatting`, yang
    tidak menyebut placeholder sama sekali.
    """
    if gaya not in (GAYA_PYODBC, GAYA_DJANGO):
        raise ValueError(f"gaya placeholder tak dikenal: {gaya!r}")
    return f"[{SKEMA}].[pergerakan_stok](" + ", ".join([gaya] * len(URUT_PARAMETER)) + ")"


def pasang(cur, db_legacy: str) -> str:
    """Buat schema + fungsi **di database Arunika**. Pulangkan DDL-nya.

    `cur` harus menunjuk database Arunika, bukan legacy. Database legacy tidak
    menerima objek apa pun; ia hanya dibaca lintas-database dari dalam badan
    fungsi ini.
    """
    cur.execute(f"IF SCHEMA_ID('{SKEMA}') IS NULL EXEC('CREATE SCHEMA [{SKEMA}]')")
    cur.execute(
        f"IF OBJECT_ID('{SKEMA}.pergerakan_stok') IS NOT NULL "
        f"DROP FUNCTION [{SKEMA}].[pergerakan_stok]"
    )
    ddl = ddl_pergerakan_stok(db_legacy)
    cur.execute(ddl)
    return ddl


def copot(cur) -> None:
    """Buang seluruh jejak adapter dari server ini."""
    cur.execute(
        f"IF OBJECT_ID('{SKEMA}.pergerakan_stok') IS NOT NULL "
        f"DROP FUNCTION [{SKEMA}].[pergerakan_stok]"
    )
    cur.execute(f"IF SCHEMA_ID('{SKEMA}') IS NOT NULL DROP SCHEMA [{SKEMA}]")


# --- Nota penjualan: dibangkitkan dari `_nota_net()` ------------------------

def _dari_nota(bangun, db_legacy: str, apa: str) -> str:
    """Kualifikasi badan subquery nota, dengan penjaga yang sama untuk keduanya.

    Dipakai `badan_penjualan` dan `badan_pembelian`. Kalau tak satu pun rujukan
    tabel legacy dikenali, bentuk fungsi sumbernya berubah -- dan view-nya akan
    tercipta dengan sukses lalu gagal saat dibaca, dari dalam laporan,
    berbulan-bulan kemudian.
    """
    inti, n = _kualifikasi(bangun("1=1"), db_legacy)
    if n == 0:
        raise RuntimeError(
            f"Tak satu pun rujukan tabel legacy dikenali di {apa}. "
            "Bentuknya berubah; perbarui adapter ini alih-alih menebak."
        )
    return inti


def badan_pembelian(db_legacy: str) -> str:
    """Badan view `pembelian`, dibangkitkan dari `reports._pembelian_nota()`.

    Cermin `badan_penjualan`, dengan teknik dan alasan yang persis sama: satu
    sumber kebenaran untuk formula uang, nol transkripsi, nol panggilan fungsi
    skalar legacy.

    Yang berbeda hanya tiga hal, dan ketiganya bawaan sisi pembelian:

    * **`ppnbm` ikut dihitung.** `_pembelian_nota()` mengalikannya berurutan
      `(1+pajak)*(1+ppnbm)` sesuai UDF `GetTotalPembelian`, bukan menjumlah
      keduanya. Dampaknya nol pada data sekarang -- seluruh baris `t_pembelian`
      di kedua server berpajak dan ber-ppnbm 0 -- jadi ini kebenaran laten, yang
      justru alasan untuk tidak menuliskannya ulang dengan tangan.
    * **`diskon` diturunkan** dengan identitas yang sama:
      `total_kotor - (total_bersih - pajak)`.
    * **`jenis_bayar` dari `status_raw`.** Di legacy `t_pembelian.status` adalah
      cara bayar, bukan penanda batal; view `mon_t_pembelian` menamai
      `GetConvertStatus(beli.status)` sebagai "Pembayaran".
    """
    from apps.transactions import reports  # lokal: hindari lingkaran impor

    inti = _dari_nota(reports._pembelian_nota, db_legacy, "_pembelian_nota()")
    return (
        "SELECT n.no_transaksi, n.tanggal, RTRIM(n.kd_divisi), RTRIM(n.kd_supplier), "
        "n.total_kotor, n.total_kotor - (n.total_bersih - n.pajak), n.pajak, n.total_bersih, "
        # Empat slot diskon persen tingkat nota, kedua TARIF (fraksi, bukan
        # rupiah), plus `no_order` dan `keterangan`. Mode Arunika mengisi slot
        # pertama dari `diskon_ghb` dan sisanya nol.
        "n.hd1, n.hd2, n.hd3, n.hd4, n.pajak_rate, n.ppnbm_rate, "
        "NULLIF(LTRIM(RTRIM(n.no_order)), ''), n.keterangan, "
        "CASE n.status_raw WHEN 0 THEN 'kredit' WHEN 1 THEN 'tunai' "
        "WHEN 2 THEN 'lunas' ELSE '' END, "
        # Sama seperti penjualan: kepala nota legacy tak punya kolom pembatalan.
        "'aktif' "
        f"FROM ({inti}) n"
    )


_RETUR = {
    # sisi: (tabel detail, tabel kepala, harga, kolom sales atau None)
    "penjualan": ("t_penjualan_retur_detail", "t_penjualan_retur", "harga_jual", "kd_pegawai"),
    "pembelian": ("t_pembelian_retur_detail", "t_pembelian_retur", "harga", None),
}


def badan_retur_baris(db_legacy: str, *, sisi: str) -> str:
    """Badan view `{sisi}_retur_baris`, dengan `total` dari `reports._line_net()`.

    Satu fungsi untuk kedua sisi karena bentuknya memang cermin; yang berbeda
    cuma nama tabel, kolom harga, dan ada-tidaknya `kd_pegawai` --
    `t_pembelian_retur_detail` tak punya sales, dan itu benar: yang menjual
    barang adalah orang, yang memasoknya adalah perusahaan.

    `_line_net()` dipanggil, tidak disalin. Kedua tabel detail membawa
    `diskon1-4` sendiri dan SELURUHNYA nol di data hari ini -- yang justru
    alasan untuk tidak menuliskan rumusnya dengan tangan: sebuah salinan yang
    menyimpang tak akan memunculkan galat apa pun sampai ada yang mengisi kolom
    itu, lalu diam-diam memulangkan angka lain.

    Baris membawa `tanggal` + `divisi_kode` kepalanya, sebab yang sama seperti
    `penjualan_baris`: laporan tingkat-baris tak perlu menyentuh kepala untuk
    menyaring rentang tanggal.
    """
    from apps.transactions import reports  # lokal: hindari lingkaran impor

    detail, kepala, harga, sales = _RETUR[sisi]
    net = reports._line_net(harga, "d")
    kol_sales = f"NULLIF(RTRIM(d.{sales}), ''), " if sales else ""
    # Nama tabel ditulis TELANJANG; `_kualifikasi` yang memberi awalan `[db].dbo.`
    # dan sekalian menghitung berapa rujukan yang benar-benar dikenalinya.
    badan = (
        f"SELECT d.no_retur, h.tanggal, RTRIM(h.kd_divisi), d.kd_barang, "
        f"RTRIM(d.kd_satuan), {kol_sales}d.qty, d.{harga}, ({net}) "
        f"FROM {detail} d "
        f"INNER JOIN {kepala} h ON h.no_retur = d.no_retur"
    )
    hasil, n = _kualifikasi(badan, db_legacy)
    if n == 0:
        raise RuntimeError(
            f"Tak satu pun rujukan tabel legacy dikenali di badan_retur_baris({sisi}). "
            "Bentuknya berubah; perbarui adapter ini alih-alih menebak."
        )
    return hasil


def badan_penjualan_order(db_legacy: str) -> str:
    """Badan view `penjualan_order`, dibangkitkan dari `reports._penjualan_order_net()`.

    Teknik dan alasannya sama dengan `badan_penjualan`/`badan_pembelian`: satu
    sumber kebenaran untuk formula uang, nol transkripsi. Rumusnya sendiri
    diangkat keluar dari `_order_inner` supaya bisa dipanggil dari sini.

    Satu hal khas order, dan ia sengaja TIDAK diwarisi bentuknya: legacy menandai
    order terbuka dengan `no_transaksi = no_order`, bukan dengan kolom `status` --
    karena kolom `status`-nya tak bisa dipercaya (16 baris `status=0` berbanding
    38 order terbuka di server yang sama). `_ORDER_TERBUKA` sudah memulihkan
    maksudnya jadi 'Terbuka'/'Jadi Nota', dan di sini ia jadi TOKEN
    (`terbuka`/`jadi_nota`), sehingga bentuk baru punya kolom status yang berarti
    apa adanya -- §5.E. `nomor_nota` tetap dipulangkan supaya talinya tak putus.
    """
    from apps.transactions import reports  # lokal: hindari lingkaran impor

    inti = _dari_nota(reports._penjualan_order_net, db_legacy, "_penjualan_order_net()")
    return (
        "SELECT n.no_order, n.tanggal, n.tanggal_terima, RTRIM(n.kd_divisi), n.kd_mitra, "
        "CASE n.status WHEN 'Terbuka' THEN 'terbuka' ELSE 'jadi_nota' END, "
        "NULLIF(LTRIM(RTRIM(n.no_transaksi)), ''), "
        "n.jml_item, n.total_qty, n.total_bersih "
        f"FROM ({inti}) n"
    )


def badan_penjualan(db_legacy: str) -> str:
    """Badan view `penjualan`, dibangkitkan dari `reports._nota_net()`.

    ## Kenapa dibangkitkan, dan kenapa bukan fungsi skalar legacy

    Versi pertama view ini memanggil `dbo.GetTotalPenjualan` dkk. Itu benar
    secara nilai -- 200/200 nota cocok dengan `t_penjualan_total` -- tapi dua
    hal membatalkannya, dan keduanya terukur:

    **Terlalu lambat untuk agregat.** Fungsi-fungsi itu `is_inlineable` tapi
    compatibility level database legacy 100 (inlining butuh >= 150), jadi ia
    jalan baris-per-baris. Sebuah agregat menyentuh SETIAP baris:

        1 minggu / 1 bulan / 3 bulan   0,01 dtk, identik
        2025 setahun (118.547 nota)    legacy 5,3 dtk  vs  36,2 dtk
        2024-2026    (264.203 nota)    legacy 9,9 dtk  vs  79,6 dtk

    **Angkanya berbeda dari laporan Arunika yang sudah berjalan.** `_nota_net()`
    TIDAK memotong nominal voucher; fungsi legacy memotongnya. Dampaknya
    Rp 73.700.000 pada 1.396 nota di grosirPusat. Bentuk baru yang memihak sisi
    berbeda dari laporan yang sudah dipakai berarti dua angka omzet untuk data
    yang sama -- tanpa ada yang memutuskan bahwa ia boleh berbeda.

    Membangkitkannya dari `_nota_net()` menyelesaikan keduanya sekaligus: ia
    set-based (nol panggilan fungsi skalar) DAN memakai formula yang sama persis
    dengan jalur lama, sehingga angka yang dilihat pengguna tidak bergeser
    sedikit pun.

    **Perbedaan voucher itu sendiri tidak diselesaikan di sini, dan memang
    tidak boleh.** Ia keputusan pemilik data. Yang berubah adalah tempatnya:
    sesudah ini ia satu perubahan di dalam `_nota_net()` yang merambat ke KEDUA
    jalur sekaligus, bukan dua formula yang harus diingat untuk disamakan.

    ## `diskon` diturunkan

    `_nota_net()` tak memulangkan kolom diskon. Nilainya diturunkan dengan
    identitas yang sudah dipakai `penjualan_periode` sejak lama dan terbukti
    50/50 pada nota berdiskon: `total_kotor - (total_bersih - pajak)`.
    """
    from apps.transactions import reports  # lokal: hindari lingkaran impor

    inti = _dari_nota(reports._nota_net, db_legacy, "_nota_net()")
    return (
        "SELECT n.no_transaksi, n.tanggal, RTRIM(n.kd_divisi), n.kd_customer, "
        # Dipulangkan APA ADANYA, penanda "tanpa voucher" sekalipun (`V1`, `V2`,
        # `VAA000`). Memetakannya ke NULL akan terasa lebih rapi dan langsung
        # memecah laporan Voucher: di sana "dipakai" dihitung sebagai
        # `kd_voucher <> ''`, jadi ketiga penanda itu memang ikut terhitung hari
        # ini. Adapter menyajikan bentuk lain dari data yang sama, bukan
        # pendapat lain tentang datanya.
        "RTRIM(n.kd_voucher), "
        # Kas yang menerima uangnya. `char(6)` (JR_KODE_MASTER), jadi di-RTRIM;
        # kosong -> NULL supaya kedua mode menyatakan "tanpa kas" dengan nilai
        # yang sama, dan pembacanya cukup menulis `IS NOT NULL` sekali. Tak ada
        # laporan yang menampilkan kolom ini, jadi NULLIF di sini tidak mengubah
        # satu angka pun -- berbeda dari penanda voucher di atas, yang justru
        # DIHITUNG apa adanya oleh laporan Voucher.
        "NULLIF(RTRIM(n.kd_kas), ''), "
        # Yang MENGETIK nota -- `m_userx`, bukan yang menjualnya. Sales duduk di
        # `penjualan_baris.sales_kode` karena di legacy pun `kd_pegawai` adalah
        # kolom detail. `char(6)`, jadi RTRIM; kosong -> NULL dengan alasan yang
        # sama seperti `kd_kas` di atas.
        "NULLIF(RTRIM(n.kd_user), ''), "
        "n.total_kotor, n.total_kotor - (n.total_bersih - n.pajak), n.pajak, n.total_bersih, "
        # Empat slot diskon PERSEN tingkat nota (DT1-DT4 di layar Penjualan
        # Detail), berbeda dari kolom `diskon` di kiri yang rupiah. Dipaparkan
        # apa adanya di mode legacy; mode Arunika mengisi slot pertama dari
        # `diskon_ghb` dan sisanya nol -- lihat `PenjualanBaris.diskon_ghb`.
        "n.hd1, n.hd2, n.hd3, n.hd4, n.pajak_rate, "
        "n.tanggal_jatuh_tempo, n.keterangan, "
        # `t_penjualan.status` adalah JENIS PEMBAYARAN, bukan penanda batal --
        # ia keluar di kolomnya sendiri. Nilainya token huruf kecil, sebentuk
        # dengan `status` di bawah; label untuk layar dibentuk pembacanya.
        "CASE n.status_raw WHEN 0 THEN 'kredit' WHEN 1 THEN 'tunai' "
        "WHEN 2 THEN 'lunas' ELSE '' END, "
        # Kepala nota legacy tidak punya kolom pembatalan sama sekali, jadi
        # seluruh nota yang terbaca dari sana adalah nota aktif. Memetakan
        # `status` ke sini -- yang sempat terlihat masuk akal -- akan melabeli
        # setiap penjualan kredit sebagai nota batal.
        "'aktif' "
        f"FROM ({inti}) n"
    )

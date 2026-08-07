"""Penomoran nota: `{kepala_nota}{YY}{MM}{DD}{NNNN}` — mis. `SC2608070001`.

Aplikasi POS lama menulis ke tabel yang sama, pada saat yang sama. Modul ini
ada supaya dua penulis itu tidak pernah memakai nomor yang sama, tanpa menyentuh
aplikasi lamanya sedikit pun.

Tiga hal yang gampang salah dan mahal kalau salah:

1. Awalannya diambil dari `m_divisi.kepala_nota`, TIDAK PERNAH ditebak dari data
   yang sudah ada. Satu database memuat beberapa awalan sekaligus karena baris
   kiriman sync ikut tersimpan di situ: di grosirPusat, `SC` miliknya sendiri
   sedangkan `CT` datang dari retail dan `GP` dari gudang. Untuk `t_pembelian`
   justru `GP` yang terbanyak (10.110 baris lawan 1.587) — menebak dari yang
   terbanyak berarti menulis nota atas nama cabang lain.

2. `MAX()` selalu disaring dengan awalan sendiri. Tanpa itu baris kiriman sync
   ikut menggeser urutan.

3. Nomor dibuat DI DALAM transaksi pemanggil, dengan kunci rentang, lalu tetap
   disiapkan untuk gagal. Kuncinya menahan sesama penulis Arunika; yang menahan
   balapan dengan POS lama adalah pengulangannya.
"""
import datetime as dt

import pyodbc

from apps.transactions.hub_sync import bind_varchar

# Nama tabel & kolom masuk ke SQL sebagai teks, jadi ia TIDAK BOLEH berasal dari
# input. Pola yang sama dipakai _STATUS_TABLES di apps/master_data/services.py.
JENIS = {
    "penjualan": ("t_penjualan", "no_transaksi"),
    "penjualan_retur": ("t_penjualan_retur", "no_retur"),
    "pembelian": ("t_pembelian", "no_transaksi"),
    "pembelian_retur": ("t_pembelian_retur", "no_retur"),
}

_PERCOBAAN = 5


def awalan_untuk(cur, kd_divisi=None) -> str:
    """Awalan nota milik server ini. Lihat catatan (1) di atas berkas."""
    if kd_divisi:
        cur.execute("SELECT kepala_nota FROM m_divisi WHERE kd_divisi = ?", [kd_divisi])
    else:
        cur.execute(
            "SELECT kepala_nota FROM m_divisi WHERE status <> 0 ORDER BY kd_divisi")
    baris = cur.fetchone()
    awalan = ((baris[0] if baris else "") or "").strip().upper()
    if not awalan:
        raise ValueError(
            "Kode nota (m_divisi.kepala_nota) belum diisi untuk divisi ini, "
            "jadi nomor nota tak bisa dibuat. Isi dulu lewat Kelola Kode Nota."
        )
    return awalan


def urut_berikutnya(cur, tabel: str, kolom: str, pola: str, lebar: int) -> str:
    """Inti penomoran: MAX TERKUNCI untuk `pola`, lalu +1 dengan lebar tetap.

    `UPDLOCK, HOLDLOCK` mengunci RENTANGNYA, bukan cuma baris yang sudah ada —
    nomor baru justru baris yang BELUM ada, jadi mengunci baris saja tak cukup:
    tanpa HOLDLOCK dua penulis bisa sama-sama membaca MAX yang sama dan
    sama-sama menyimpulkan nomor yang sama.

    Dipakai nomor nota maupun kode master (pelanggan/supplier) — balapannya
    persis sama, jadi penangkalnya tak perlu ditulis dua kali.
    """
    # Kolom kunci legacy bertipe varchar; pyodbc mengikat str sebagai NVARCHAR,
    # dan konversi implisit di sisi kolom membuang index seek-nya.
    bind_varchar(cur, 1, len(pola) + 1)
    try:
        cur.execute(  # nosec B608 — tabel/kolom dari JENIS, bukan dari input
            f"SELECT MAX({kolom}) FROM {tabel} WITH (UPDLOCK, HOLDLOCK) "
            f"WHERE {kolom} LIKE ?",
            [pola + "%"],
        )
        baris = cur.fetchone()
    finally:
        # Ikatannya menempel di cursor; execute berikutnya dengan jumlah
        # parameter berbeda akan salah kalau tidak direset.
        cur.setinputsizes(None)

    terakhir = ((baris[0] if baris else "") or "").strip()
    ekor = terakhir[len(pola):]
    # Nomor yang bentuknya di luar dugaan diperlakukan seperti belum ada, bukan
    # dijadikan galat: satu baris aneh peninggalan lama tak boleh menghentikan
    # kasir yang sedang melayani antrean.
    urut = int(ekor) + 1 if ekor.isdigit() else 1
    if urut > 10 ** lebar - 1:
        raise ValueError(
            f"Nomor sudah habis untuk awalan {pola} (batas {10 ** lebar - 1}). "
            f"Hubungi pengelola aplikasi."
        )
    return f"{pola}{urut:0{lebar}d}"


def no_berikutnya(cur, jenis: str, awalan: str, tanggal=None) -> str:
    """Nomor nota berikutnya. WAJIB dipanggil di dalam transaksi."""
    tabel, kolom = JENIS[jenis]  # KeyError kalau jenisnya tak dikenal — memang.
    tanggal = tanggal or dt.datetime.now()
    return urut_berikutnya(cur, tabel, kolom, f"{awalan}{tanggal:%y%m%d}", 4)


def _duplikat(exc: Exception) -> bool:
    """2627 = pelanggaran PRIMARY KEY/UNIQUE, 2601 = index unik."""
    teks = " ".join(str(a) for a in getattr(exc, "args", ()))
    return "2627" in teks or "2601" in teks


def simpan_dengan_nomor(cur, buat_nomor, tulis, percobaan: int = _PERCOBAAN) -> str:
    """Panggil `tulis(buat_nomor())`; ulangi dengan nomor baru kalau keburu dipakai.

    Kunci rentang di `no_berikutnya` menahan sesama penulis Arunika. Ia TIDAK
    menahan aplikasi POS lama kalau aplikasi itu menyisipkan barisnya lewat
    jalur yang tak kita ketahui — dan kita memang tak bisa memastikannya dari
    sini. Jadi bentroknya tidak dicegah, melainkan ditangani: ambil nomor baru,
    coba lagi, dan kalau tetap gagal katakan apa adanya alih-alih menyimpan
    dengan nomor yang salah.
    """
    galat = None
    for _ in range(percobaan):
        nomor = buat_nomor()
        try:
            tulis(nomor)
            return nomor
        except pyodbc.Error as exc:
            if not _duplikat(exc):
                raise
            galat = exc
    raise RuntimeError(
        f"Gagal membuat nomor setelah {percobaan} percobaan — nomornya selalu "
        f"keburu dipakai aplikasi lain. Coba lagi sebentar lagi."
    ) from galat

"""Menulis nota penjualan ke server toko, berdampingan dengan aplikasi POS lama.

Satu nota = tiga tabel dalam SATU transaksi: `t_penjualan` (kepala),
`t_penjualan_detail` (baris), `t_penjualan_total` (nilai akhir). Ketiganya
wajib: dari 259.247 baris `t_penjualan_total` di server testing, tak satu pun
nota berawalan SC yang tidak punya pasangannya — laporan legacy membacanya.

Yang TIDAK dilakukan di sini, dan itu disengaja:

- **Stok tidak disentuh.** `t_penjualan_detail` punya trigger
  `trig_update_stok_penjualan_detail`; database yang mengurangi stok. Menulis
  stok sendiri berarti menguranginya dua kali.
- **Feed sync tidak disentuh.** Trigger `insert_temp_m_t_penjualan(_detail)`
  yang mengantar nota ke pusat. Ia menyala sendiri.

Karena trigger-trigger itulah kepala dan baris harus berada dalam satu
transaksi: nota yang separuh jadi akan ikut terkirim ke pusat sebagai nota
yang separuh jadi.
"""
from __future__ import annotations

import datetime as dt

from apps.transactions.penomoran import awalan_untuk, no_berikutnya, simpan_dengan_nomor
from core import mssql

# Kolom yang menerima nilai kosong di data legacy — dilihat dari nota yang sudah
# ada, bukan ditebak: no_bukti dan keterangan berisi "-", bukan string kosong.
KOSONG = "-"

_HEADER = [
    "no_transaksi", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas", "kd_voucher",
    "no_bukti", "tanggal", "tanggal_jatuh_tempo", "status", "diskon1", "diskon2",
    "diskon3", "diskon4", "diskon_uang", "pajak", "keterangan", "kd_user",
]
# `total` SENGAJA tidak ada di sini: ia kolom terhitung (computed column) —
# database yang menghitungnya dengan UDF legacy, dan mencoba mengisinya membuat
# INSERT ditolak ("cannot be modified because it is either a computed column").
_DETAIL = [
    "no_transaksi", "kd_barang", "kd_satuan", "kd_pegawai", "jenis",
    "diskon1", "diskon2", "diskon3", "diskon4", "harga_jual", "qty",
    "point1", "point2",
]


def ghb(harga: float, diskon, pajak: float = 0.0, ppnbm: float = 0.0) -> float:
    """Harga bersih ala UDF legacy `GetHargaBersih`, dalam Python.

    Dual-mode dan itu bukan pilihan kita: nilai diskon di (-1, 1) berarti PERSEN
    (v * (1 - d)), selebihnya rupiah flat (v - d). Aplikasi legacy memakai
    keduanya — 82 dari 2.990.262 baris t_penjualan_detail menyimpan diskon
    sebagai fraksi. Guard `harga <= 0` juga direplikasi; tanpanya baris berharga
    nol menghasilkan subtotal negatif palsu.

    Kembaran SQL-nya ada di `_ghb()` apps/transactions/reports.py. Keduanya
    HARUS sepakat: yang satu menghitung nota yang kita tulis, yang lain
    menghitung nota yang sama di laporan.
    """
    if harga <= 0:
        return harga
    v = harga
    for d in diskon:
        d = d or 0.0
        v = v * (1 - d) if -1 < d < 1 else v - d
    return v * (1 + (pajak or 0.0)) * (1 + (ppnbm or 0.0))


def total_nota(items, diskon_header=(0, 0, 0, 0), diskon_uang=0.0, pajak=0.0) -> float:
    """Nilai akhir nota, mengikuti UDF `GetTotalPenjualan`:

        net_pre_tax * (1 + pajak) - diskon_uang

    dengan net_pre_tax = SUM(GHB(GHB(harga_jual, diskon baris), diskon header) * qty).

    `pajak` adalah FRAKSI (0,05 = 5%), bukan angka persen — GetTotalPajakPenjualan
    mengalikannya langsung tanpa /100. Voucher tidak dikurangi, sejalan dengan
    _nota_net di reports.py.
    """
    net = 0.0
    for it in items:
        satuan = ghb(float(it["harga_jual"]), [it.get(f"diskon{i}", 0) for i in (1, 2, 3, 4)])
        net += ghb(satuan, list(diskon_header)) * float(it["qty"])
    return net * (1 + (pajak or 0.0)) - (diskon_uang or 0.0)


def _periksa(items, kd_user: str) -> None:
    if not kd_user:
        raise ValueError(
            "Akun Anda belum ditautkan ke user legacy, jadi nota tak bisa dibuat "
            "atas nama Anda. Minta pengelola aplikasi mengisinya di Manajemen User."
        )
    if not items:
        raise ValueError("Nota kosong — tambahkan minimal satu barang.")
    for it in items:
        if not str(it.get("kd_barang") or "").strip():
            raise ValueError("Ada baris tanpa barang.")
        if float(it.get("qty") or 0) <= 0:
            raise ValueError(f"Qty barang {it.get('kd_barang')} harus lebih dari nol.")


def buat_nota(profile, *, kd_user, kd_divisi, kd_customer, kd_jenis, kd_kas,
              kd_voucher, kd_pegawai, items, keterangan=KOSONG, no_bukti=KOSONG,
              diskon_header=(0, 0, 0, 0), diskon_uang=0.0, pajak=0.0,
              status=1, tanggal=None, jatuh_tempo=None) -> dict:
    """Tulis satu nota penjualan. Mengembalikan {no_transaksi, total, baris}."""
    _periksa(items, kd_user)
    # `tanggal` datang dari PC kasir (jam mesin itu sendiri, seperti aplikasi
    # legacy). `tanggal_server` TIDAK ditulis di sini — kolomnya ber-DEFAULT
    # GETDATE(), jadi ia selalu jam SERVER. Dua jam yang berbeda memang
    # disengaja: yang satu kapan kasir mencatat, yang lain kapan server menerima.
    tanggal = tanggal or dt.datetime.now()
    jatuh_tempo = jatuh_tempo or (tanggal + dt.timedelta(days=BAWAAN["jatuh_tempo_hari"]))
    dh = list(diskon_header) + [0, 0, 0, 0]
    dh = dh[:4]
    total = total_nota(items, dh, diskon_uang, pajak)

    tanya_h = ", ".join("?" for _ in _HEADER)
    tanya_d = ", ".join("?" for _ in _DETAIL)

    with mssql.cursor(profile, autocommit=False) as cur:
        awalan = awalan_untuk(cur, kd_divisi)

        def tulis(no):
            cur.execute(
                f"INSERT INTO t_penjualan ({', '.join(_HEADER)}) VALUES ({tanya_h})",
                [no, kd_customer, kd_divisi, kd_jenis, kd_kas, kd_voucher,
                 no_bukti or KOSONG, tanggal, jatuh_tempo, status,
                 dh[0], dh[1], dh[2], dh[3], diskon_uang, pajak,
                 keterangan or KOSONG, kd_user],
            )
            for it in items:
                cur.execute(
                    f"INSERT INTO t_penjualan_detail ({', '.join(_DETAIL)}) VALUES ({tanya_d})",
                    [no, it["kd_barang"], it["kd_satuan"],
                     it.get("kd_pegawai") or kd_pegawai, int(it.get("jenis") or 0),
                     it.get("diskon1") or 0, it.get("diskon2") or 0,
                     it.get("diskon3") or 0, it.get("diskon4") or 0,
                     float(it["harga_jual"]), float(it["qty"]),
                     it.get("point1") or 0, it.get("point2") or 0],
                )
            cur.execute(
                "INSERT INTO t_penjualan_total (no_transaksi, total) VALUES (?, ?)",
                [no, total])

        no = simpan_dengan_nomor(
            cur, lambda: no_berikutnya(cur, "penjualan", awalan, tanggal), tulis)
        cur.connection.commit()

    return {"no_transaksi": no, "total": total, "baris": len(items)}


def cari_barang(profile, cari: str, limit: int = 20) -> list[dict]:
    """Cari barang beserta satuan & harga jualnya, untuk kotak cari di kasir.

    Satu barang bisa punya beberapa satuan (pcs/lusin/dus); semuanya dikembalikan
    sebagai baris terpisah supaya kasir memilih satuan sekaligus, bukan menebak.
    """
    cari = (cari or "").strip()
    if not cari:
        return []
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP (?) b.kd_barang, b.nama, bs.kd_satuan, s.nama AS satuan, "
            "bs.harga_jual FROM m_barang b "
            "INNER JOIN m_barang_satuan bs ON bs.kd_barang = b.kd_barang "
            "LEFT JOIN m_satuan s ON s.kd_satuan = bs.kd_satuan "
            "WHERE b.kd_barang LIKE ? OR b.nama LIKE ? ORDER BY b.nama, bs.harga_jual",
            [limit, f"%{cari}%", f"%{cari}%"],
        )
        return [
            {
                "kd_barang": (r[0] or "").strip(),
                "nama": (r[1] or "").strip(),
                "kd_satuan": (r[2] or "").strip(),
                "satuan": (r[3] or "").strip(),
                "harga_jual": float(r[4] or 0),
            }
            for r in cur.fetchall()
        ]


def opsi_nota(profile) -> dict:
    """Pilihan berkunci-asing untuk form nota.

    Semuanya WAJIB terisi kode yang nyata: kd_jenis dan kd_voucher punya
    FOREIGN KEY, dan kd_kas/kd_customer/kd_pegawai NOT NULL. Membiarkannya
    sebagai isian bebas membuat setiap simpan pertama gagal dengan galat FK.
    """
    def ambil(cur, sql):
        cur.execute(sql)
        return [{"value": (r[0] or "").strip(), "label": (r[1] or "").strip()}
                for r in cur.fetchall()]

    with mssql.cursor(profile) as cur:
        return {
            "jenis_bayar": ambil(cur, "SELECT kd_jenis, nama FROM m_jenis_bayar ORDER BY nama"),
            "kas": ambil(cur, "SELECT kd_kas, no_rekening FROM m_kas ORDER BY kd_kas"),
            "voucher": ambil(cur, "SELECT kd_voucher, nama FROM m_voucher ORDER BY kd_voucher"),
            "pegawai": ambil(cur, "SELECT kd_pegawai, nama FROM m_pegawai ORDER BY nama"),
            "pelanggan": ambil(
                cur, "SELECT TOP 200 kd_customer, nama FROM m_customer ORDER BY nama"),
        }


# Nilai bawaan form nota, disamakan dengan layar aplikasi legacy.
#
# kd_kas SENGAJA KAA001 ("KAS BANK NON CV") walau KAA000 dipakai 467.019 dari
# 474.585 nota di data lama. Yang benar adalah yang dipakai kasir hari ini, dan
# layar legacy-nya membuka dengan KAA001 — angka historis di sini menyesatkan
# karena memuat bertahun-tahun nota dari pengaturan yang sudah berubah.
BAWAAN = {
    "kd_customer": "CAA000",   # UMUM
    "kd_jenis": "JAA000",      # TUNAI
    "kd_kas": "KAA001",        # KAS BANK NON CV
    "kd_voucher": "VAA000",    # sentinel "tanpa voucher"
    "status": 1,               # Tunai
    "jatuh_tempo_hari": 30,
}


def bawaan_form(profile) -> dict:
    """Nilai bawaan + nomor nota BERIKUTNYA untuk ditampilkan sebelum disimpan.

    Nomornya cuma ancar-ancar: nomor yang benar-benar dipakai dihitung ulang di
    dalam transaksi saat menyimpan, karena kasir lain (atau aplikasi POS lama)
    bisa memakainya lebih dulu. Menampilkannya tetap berguna — begitulah layar
    legacy bekerja, dan kasir memakainya untuk mencocokkan lembar fisik.
    """
    import datetime as _dt

    hasil = dict(BAWAAN)
    hasil["customer_nama"] = "UMUM"
    hasil["tanggal"] = _dt.date.today().isoformat()
    hasil["jatuh_tempo"] = (
        _dt.date.today() + _dt.timedelta(days=BAWAAN["jatuh_tempo_hari"])).isoformat()
    try:
        with mssql.cursor(profile) as cur:
            awalan = awalan_untuk(cur)
            hasil["no_transaksi"] = no_berikutnya(cur, "penjualan", awalan)
    except Exception:
        # Ancar-ancar nomor tak boleh menjatuhkan seluruh layar.
        hasil["no_transaksi"] = ""
    return hasil


def cari_customer(profile, cari: str, limit: int = 20) -> list[dict]:
    """Cari pelanggan untuk kotak isian nota.

    Dicari, BUKAN di-dropdown: m_customer punya 9.367 baris di server testing,
    dan menggulung daftar sepanjang itu tiap nota lebih lambat daripada
    mengetik tiga huruf.
    """
    cari = (cari or "").strip()
    if not cari:
        return []
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP (?) kd_customer, nama, alamat FROM m_customer "
            "WHERE nama LIKE ? OR kd_customer LIKE ? ORDER BY nama",
            [limit, f"%{cari}%", f"%{cari}%"])
        return [{"kd_customer": (r[0] or "").strip(), "nama": (r[1] or "").strip(),
                 "alamat": (r[2] or "").strip()} for r in cur.fetchall()]


def barang_persis(profile, kode: str) -> dict | None:
    """Cari SATU barang dengan kode persis — jalur pemindai barcode.

    Tak ada kolom barcode di skema ini; label barcode memuat `kd_barang`, jadi
    pemindai pada dasarnya mengetik kode itu lalu menekan Enter. Kalau satu
    barang punya beberapa satuan, yang termurah dipilih (satuan terkecil), dan
    kasir masih bisa menggantinya di baris.
    """
    kode = (kode or "").strip()
    if not kode:
        return None
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP 1 b.kd_barang, b.nama, bs.kd_satuan, s.nama, bs.harga_jual "
            "FROM m_barang b INNER JOIN m_barang_satuan bs ON bs.kd_barang = b.kd_barang "
            "LEFT JOIN m_satuan s ON s.kd_satuan = bs.kd_satuan "
            "WHERE b.kd_barang = ? ORDER BY bs.harga_jual",
            [kode])
        r = cur.fetchone()
    if not r:
        return None
    return {"kd_barang": (r[0] or "").strip(), "nama": (r[1] or "").strip(),
            "kd_satuan": (r[2] or "").strip(), "satuan": (r[3] or "").strip(),
            "harga_jual": float(r[4] or 0)}


def baca_nota(profile, no_transaksi: str) -> dict | None:
    """Satu nota lengkap untuk dicetak."""
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT h.no_transaksi, h.tanggal, h.kd_customer, c.nama, h.kd_user, "
            "h.keterangan, h.diskon_uang, h.pajak, t.total "
            "FROM t_penjualan h LEFT JOIN m_customer c ON c.kd_customer = h.kd_customer "
            "LEFT JOIN t_penjualan_total t ON t.no_transaksi = h.no_transaksi "
            "WHERE h.no_transaksi = ?", [no_transaksi])
        h = cur.fetchone()
        if not h:
            return None
        cur.execute(
            "SELECT d.kd_barang, b.nama, d.kd_satuan, d.qty, d.harga_jual, d.total "
            "FROM t_penjualan_detail d LEFT JOIN m_barang b ON b.kd_barang = d.kd_barang "
            "WHERE d.no_transaksi = ?", [no_transaksi])
        baris = [{"kd_barang": (r[0] or "").strip(), "nama": (r[1] or "").strip(),
                  "satuan": (r[2] or "").strip(), "qty": float(r[3] or 0),
                  "harga": float(r[4] or 0), "total": float(r[5] or 0)}
                 for r in cur.fetchall()]
        cur.execute("SELECT nama, kepala_nota FROM m_divisi")
        d = cur.fetchone()
    return {
        "no_transaksi": (h[0] or "").strip(), "tanggal": h[1],
        "kd_customer": (h[2] or "").strip(), "customer": (h[3] or "").strip(),
        "kd_user": (h[4] or "").strip(), "keterangan": (h[5] or "").strip(),
        "diskon_uang": float(h[6] or 0), "pajak": float(h[7] or 0),
        "total": float(h[8] or 0), "baris": baris,
        "toko": (d[0] if d else "") or "",
    }

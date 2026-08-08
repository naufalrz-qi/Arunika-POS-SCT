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

# Baris nota biasa. Aplikasi legacy menulis 1 pada SELURUH 2.990.259 baris
# t_penjualan_detail; 68 baris ber-`jenis` 0 semuanya tulisan Arunika sendiri
# saat pengujian. Artinya tak diketahui dari skema, jadi yang benar adalah
# meniru satu-satunya nilai yang dipakai data sungguhan.
JENIS_BARIS = 1

# --- Order penjualan --------------------------------------------------------
# Awalannya TIDAK diambil dari m_divisi.kepala_nota. Di server testing seluruh
# 7.209 baris t_penjualan_order berawalan `OJ` sementara kepala_nota divisinya
# `SC`: order punya awalan tetap sendiri di aplikasi legacy. Mengambilnya dari
# kepala_nota membuat penomoran order bercabang dua dan urutannya patah.
AWALAN_ORDER = "OJ"

# tanggal_server SENGAJA di luar daftar: ia diisi GETDATE() sebagai ekspresi SQL
# (lihat _tulis_order). Beda dengan t_penjualan, kolomnya di sini TIDAK punya
# DEFAULT — dibiarkan berarti NULL, padahal 7.209 baris legacy semuanya terisi.
_ORDER_HEADER = [
    "no_order", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas", "kd_voucher",
    "no_bukti", "tanggal", "tanggal_terima", "status", "diskon1", "diskon2",
    "diskon3", "diskon4", "diskon_uang", "pajak", "keterangan", "jaminan",
    "kd_user", "no_transaksi",
]
_ORDER_DETAIL = [
    "no_order", "kd_barang", "kd_satuan", "kd_pegawai", "jenis",
    "diskon1", "diskon2", "diskon3", "diskon4", "harga_jual", "qty",
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
            "Akun Anda belum ditautkan ke user legacy untuk koneksi ini, jadi nota "
            "tak bisa dibuat atas nama Anda. Minta pengelola aplikasi mengisinya "
            "di Kelola Tautan User."
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
              status=1, tanggal=None, jatuh_tempo=None, no_order="") -> dict:
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
                     it.get("kd_pegawai") or kd_pegawai,
                     int(it.get("jenis") or JENIS_BARIS),
                     it.get("diskon1") or 0, it.get("diskon2") or 0,
                     it.get("diskon3") or 0, it.get("diskon4") or 0,
                     float(it["harga_jual"]), float(it["qty"]),
                     it.get("point1") or 0, it.get("point2") or 0],
                )
            cur.execute(
                "INSERT INTO t_penjualan_total (no_transaksi, total) VALUES (?, ?)",
                [no, total])
            if no_order:
                # Order ditandai TERPAKAI di transaksi yang sama. Kalau ditulis
                # terpisah, nota bisa jadi sementara ordernya tetap terbuka —
                # dan order yang sama lalu diambil dua kali.
                cur.execute(
                    "UPDATE t_penjualan_order SET no_transaksi = ?, status = 1 "
                    "WHERE no_order = ? AND (no_transaksi = no_order OR no_transaksi IS NULL)",
                    [no, no_order])
                cur.execute(
                    "SELECT no_transaksi FROM t_penjualan_order WHERE no_order = ?",
                    [no_order])
                cek = cur.fetchone()
                # SELECT eksplisit, bukan rowcount: trigger legacy membuatnya
                # tak bisa dipercaya (lihat context.md).
                if not cek or (cek[0] or "").strip() != no:
                    raise ValueError(
                        f"Order {no_order} sudah diambil transaksi lain. "
                        f"Muat ulang daftar order.")

        no = simpan_dengan_nomor(
            cur, lambda: no_berikutnya(cur, "penjualan", awalan, tanggal), tulis)
        cur.connection.commit()

    return {"no_transaksi": no, "total": total, "baris": len(items),
            "no_order": no_order}


def buat_order(profile, *, kd_user, kd_divisi, kd_customer, kd_jenis, kd_kas,
               kd_voucher, kd_pegawai, items, keterangan=KOSONG, no_bukti=KOSONG,
               diskon_header=(0, 0, 0, 0), diskon_uang=0.0, pajak=0.0,
               tanggal=None, jaminan=0.0) -> dict:
    """Tulis satu order penjualan (pesanan yang belum jadi nota).

    Bentuknya kepala + baris seperti nota, tapi TIGA hal berbeda dan ketiganya
    menentukan apakah ordernya bisa diambil nanti:

    - `no_transaksi` diisi `no_order` SENDIRI, dan `status` 0. Itulah penanda
      "belum diambil" yang dibaca `daftar_order`/`buat_nota` — bukan `status`
      saja, sebab 25 baris legacy berstatus 1 padahal belum diambil.
    - Tak ada tabel total: `t_penjualan_order_total` memang tidak ada. Nilai
      order dihitung ulang saat dibaca.
    - Tak ada trigger di kedua tabelnya (sudah diperiksa di server testing),
      jadi order TIDAK mengurangi stok dan tidak ikut terkirim ke pusat lewat
      trigger — memang begitu seharusnya: barangnya belum keluar.
    """
    _periksa(items, kd_user)
    tanggal = tanggal or dt.datetime.now()
    dh = (list(diskon_header) + [0, 0, 0, 0])[:4]
    total = total_nota(items, dh, diskon_uang, pajak)

    kolom = ", ".join(_ORDER_HEADER)
    tanya_h = ", ".join("?" for _ in _ORDER_HEADER)
    tanya_d = ", ".join("?" for _ in _ORDER_DETAIL)

    with mssql.cursor(profile, autocommit=False) as cur:
        def tulis(no):
            cur.execute(
                f"INSERT INTO t_penjualan_order ({kolom}, tanggal_server) "
                f"VALUES ({tanya_h}, GETDATE())",
                # tanggal_terima disamakan dengan tanggal: di 7.209 baris legacy
                # keduanya jam yang sama (selisih 0 hari pada 5.838 baris, dan
                # yang lain justru MUNDUR) — kolomnya mencatat kapan order
                # diterima, bukan kapan barang dijanjikan.
                [no, kd_customer, kd_divisi, kd_jenis, kd_kas, kd_voucher,
                 no_bukti or KOSONG, tanggal, tanggal, 0,
                 dh[0], dh[1], dh[2], dh[3], diskon_uang, pajak,
                 keterangan or KOSONG, jaminan, kd_user, no],
            )
            for it in items:
                cur.execute(
                    f"INSERT INTO t_penjualan_order_detail ({', '.join(_ORDER_DETAIL)}) "
                    f"VALUES ({tanya_d})",
                    [no, it["kd_barang"], it["kd_satuan"],
                     it.get("kd_pegawai") or kd_pegawai,
                     int(it.get("jenis") or JENIS_BARIS),
                     it.get("diskon1") or 0, it.get("diskon2") or 0,
                     it.get("diskon3") or 0, it.get("diskon4") or 0,
                     float(it["harga_jual"]), float(it["qty"])],
                )

        no = simpan_dengan_nomor(
            cur,
            lambda: no_berikutnya(cur, "penjualan_order", AWALAN_ORDER, tanggal),
            tulis)
        cur.connection.commit()

    return {"no_order": no, "total": total, "baris": len(items)}


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


def satuan_barang(profile, kd_barang: str) -> list[dict]:
    """Semua satuan sebuah barang beserta harganya — untuk mengganti satuan
    pada baris yang sudah masuk keranjang.

    541 barang di server aktif punya lebih dari satu satuan, dan harganya beda
    per satuan (mis. 1001: PCS 4.800, LUSIN 57.600). Karena itu mengganti
    satuan HARUS ikut mengganti harga; membiarkan harga lama berarti menjual
    selusin seharga satu.

    `jumlah` (isi per satuan) ikut dikirim supaya kasir melihat "LUSIN (isi 12)"
    dan bukan kode satuan yang tak berarti apa-apa. Baris ber-`status` 0 tetap
    disertakan: kotak cari pun menampilkannya, dan arti status di tabel ini tak
    terdokumentasi — menyaringnya diam-diam bisa menghilangkan satuan yang
    sebenarnya masih dipakai.
    """
    kd_barang = (kd_barang or "").strip()
    if not kd_barang:
        return []
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT bs.kd_satuan, s.nama, bs.jumlah, bs.harga_jual, bs.status "
            "FROM m_barang_satuan bs LEFT JOIN m_satuan s ON s.kd_satuan = bs.kd_satuan "
            "WHERE bs.kd_barang = ? ORDER BY bs.jumlah, bs.harga_jual",
            [kd_barang])
        return [{"kd_satuan": (r[0] or "").strip(), "satuan": (r[1] or "").strip(),
                 "jumlah": float(r[2] or 0), "harga_jual": float(r[3] or 0),
                 "status": int(r[4] or 0)} for r in cur.fetchall()]


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


def bawaan_form(profile, jenis: str = "penjualan") -> dict:
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
            # Order punya awalan tetap sendiri; kepala_nota tak dilihat sama
            # sekali, jadi layar order tetap jalan walau kolomnya belum diisi.
            awalan = AWALAN_ORDER if jenis == "penjualan_order" else awalan_untuk(cur)
            hasil["nomor"] = no_berikutnya(cur, jenis, awalan)
    except Exception:
        # Ancar-ancar nomor tak boleh menjatuhkan seluruh layar.
        hasil["nomor"] = ""
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


def daftar_order(profile, limit: int = 50) -> list[dict]:
    """Order penjualan yang BELUM jadi nota.

    Alur legacy: order dibuat lebih dulu (awalan OJ, penomoran sendiri), lalu
    saat pembeli datang order itu diambil dan menjadi nota. Yang menandai sudah
    diambil adalah `no_transaksi` — pada order terbuka isinya masih no_order
    sendiri, dan berganti jadi nomor nota begitu ditransaksikan.
    Karena itu saringannya `no_transaksi = no_order`, bukan `status`.
    """
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP (?) o.no_order, o.tanggal, o.kd_customer, c.nama, o.keterangan "
            "FROM t_penjualan_order o "
            "LEFT JOIN m_customer c ON c.kd_customer = o.kd_customer "
            "WHERE o.no_transaksi = o.no_order OR o.no_transaksi IS NULL "
            "ORDER BY o.no_order DESC", [limit])
        return [{"no_order": (r[0] or "").strip(), "tanggal": r[1],
                 "kd_customer": (r[2] or "").strip(), "customer": (r[3] or "").strip(),
                 "keterangan": (r[4] or "").strip()} for r in cur.fetchall()]


def baca_order(profile, no_order: str) -> dict | None:
    """Isi satu order, siap dituang ke nota baru."""
    no_order = (no_order or "").strip()
    if not no_order:
        return None
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT o.no_order, o.kd_customer, c.nama, o.kd_jenis, o.kd_kas, "
            "o.kd_voucher, o.keterangan, o.diskon_uang, o.pajak "
            "FROM t_penjualan_order o "
            "LEFT JOIN m_customer c ON c.kd_customer = o.kd_customer "
            "WHERE o.no_order = ?", [no_order])
        h = cur.fetchone()
        if not h:
            return None
        cur.execute(
            "SELECT d.kd_barang, b.nama, d.kd_satuan, s.nama, d.qty, d.harga_jual, "
            "d.diskon1, d.diskon2, d.diskon3, d.diskon4 "
            "FROM t_penjualan_order_detail d "
            "LEFT JOIN m_barang b ON b.kd_barang = d.kd_barang "
            "LEFT JOIN m_satuan s ON s.kd_satuan = d.kd_satuan "
            "WHERE d.no_order = ?", [no_order])
        items = [{"kd_barang": (r[0] or "").strip(), "nama": (r[1] or "").strip(),
                  "kd_satuan": (r[2] or "").strip(), "satuan": (r[3] or "").strip(),
                  "qty": float(r[4] or 0), "harga_jual": float(r[5] or 0),
                  "diskon1": float(r[6] or 0), "diskon2": float(r[7] or 0),
                  "diskon3": float(r[8] or 0), "diskon4": float(r[9] or 0)}
                 for r in cur.fetchall()]
    return {
        "no_order": (h[0] or "").strip(), "kd_customer": (h[1] or "").strip(),
        "customer_nama": (h[2] or "").strip(), "kd_jenis": (h[3] or "").strip(),
        "kd_kas": (h[4] or "").strip(), "kd_voucher": (h[5] or "").strip(),
        "keterangan": (h[6] or "").strip(), "diskon_uang": float(h[7] or 0),
        "pajak": float(h[8] or 0), "items": items,
    }

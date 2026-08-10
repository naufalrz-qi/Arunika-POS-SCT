"""Retur penjualan, pembelian, dan retur pembelian — satu mesin, tiga bentuk.

`penjualan.py` berdiri sendiri karena ia satu-satunya yang juga menulis
`t_penjualan_total`. Ketiga yang di sini bentuknya sama: kepala + baris, satu
transaksi, nomor dari `penomoran`. Perbedaannya dijelaskan sebagai DATA di
`SPEC` alih-alih ditulis tiga kali — dan perbedaan itu nyata, bukan kosmetik:

- retur tak punya `status`, `diskon_uang`, maupun `kd_voucher`;
- pembelian punya `no_order`, `ppnbm`, dan `tanggal_jatuh_tempo`;
- kolom harganya bernama beda di tiap tabel: `harga_jual`, `harga_beli`, `harga`;
- `t_pembelian_detail.total` KOLOM TERHITUNG — menyebutnya membuat INSERT
  ditolak, sama seperti di t_penjualan_detail.

Nama tabel & kolom masuk ke SQL sebagai teks, jadi ia hanya boleh dari `SPEC`.

Stok dan sync tidak disentuh. Kedua tabel detail retur punya trigger
`trig_update_stok_*_retur_detail`, dan keenam tabel punya trigger
`insert_temp_m_*` yang mengantar barisnya ke pusat. Karena itulah kepala dan
baris wajib satu transaksi: yang separuh jadi ikut terkirim separuh jadi.
"""
from __future__ import annotations

import datetime as dt

from apps.transactions.penjualan import ghb
from apps.transactions.penomoran import awalan_untuk, no_berikutnya, simpan_dengan_nomor
from core import mssql

KOSONG = "-"

SPEC = {
    "penjualan_retur": {
        "label": "Retur Penjualan",
        "tabel": "t_penjualan_retur",
        "tabel_detail": "t_penjualan_retur_detail",
        "kunci": "no_retur",
        "pihak": "kd_customer",
        "harga": "harga_jual",
        "header": ["no_retur", "kd_divisi", "kd_customer", "kd_jenis", "kd_kas",
                   "tanggal", "no_bukti", "diskon1", "diskon2", "diskon3",
                   "diskon4", "pajak", "keterangan", "kd_user"],
        "detail": ["no_retur", "kd_barang", "kd_satuan", "kd_pegawai",
                   "harga_jual", "qty", "diskon1", "diskon2", "diskon3", "diskon4"],
    },
    "pembelian": {
        "label": "Pembelian",
        "tabel": "t_pembelian",
        "tabel_detail": "t_pembelian_detail",
        "kunci": "no_transaksi",
        "pihak": "kd_supplier",
        "harga": "harga_beli",
        "header": ["no_transaksi", "kd_supplier", "kd_divisi", "kd_jenis", "kd_kas",
                   "no_order", "tanggal", "tanggal_jatuh_tempo", "status",
                   "diskon1", "diskon2", "diskon3", "diskon4", "pajak", "ppnbm",
                   "keterangan", "kd_user"],
        # `total` sengaja tak ada: kolom terhitung.
        "detail": ["no_transaksi", "kd_barang", "kd_satuan", "jenis", "qty",
                   "harga_beli", "diskon1", "diskon2", "diskon3", "diskon4", "point1"],
    },
    # Order pembelian. Kembarannya `t_penjualan_order`, tapi TIGA hal berbeda dan
    # ketiganya diverifikasi langsung dari skema server (INFORMATION_SCHEMA):
    #
    # 1. **Kolom pembayarannya `kd_jenis_bayar`, bukan `kd_jenis`** — satu-satunya
    #    tabel di sini yang begitu. Ia tetap menunjuk `m_jenis_bayar.kd_jenis`
    #    (dibuktikan view `mon_t_pembelian_order_edit`), jadi pilihannya sama;
    #    yang beda cuma nama kolomnya. `buat()` mengisi ctx dengan kedua nama.
    # 2. **Ada `no_pp_order`, `jaminan`, dan `tanggal_terima`** yang tak punya
    #    padanan di tabel lain. Label manusianya dari view legacy yang sama:
    #    "No. PP Order", "Jaminan / U.M.", dan "Penerimaan".
    # 3. **`t_pembelian_order` PUNYA trigger `insert_temp_m_*`**, sedangkan
    #    `t_penjualan_order` tak punya satu pun. Artinya order pembelian IKUT
    #    TERKIRIM KE PUSAT begitu disimpan — order penjualan tidak. Jangan
    #    menyamakan keduanya hanya karena namanya bersaudara.
    #
    # Yang TIDAK bisa ditiru dari data: tabelnya KOSONG di setiap server yang
    # terjangkau (testgudang 0 baris, PUSAT 0 baris padahal `t_pembelian` 12.605).
    # Jadi awalan nomor dan penanda order terbuka mengikuti konvensi
    # `t_penjualan_order` yang sudah terbukti di 7.209 baris, bukan tebakan baru.
    "pembelian_order": {
        "label": "Order Pembelian",
        "tabel": "t_pembelian_order",
        "tabel_detail": "t_pembelian_order_detail",
        "kunci": "no_order",
        "pihak": "kd_supplier",
        "harga": "harga_beli",
        # Awalan TETAP, tidak dari m_divisi.kepala_nota — alasan yang sama dengan
        # AWALAN_ORDER ("OJ") di penjualan.py: penomoran order tak boleh bercabang
        # mengikuti divisi, dan layarnya tetap jalan walau kepala_nota belum diisi.
        "awalan": "OB",
        "header": ["no_order", "no_pp_order", "kd_divisi", "kd_supplier", "kd_kas",
                   "kd_jenis_bayar", "tanggal", "tanggal_terima", "status",
                   "diskon1", "diskon2", "diskon3", "diskon4", "pajak", "ppnbm",
                   "no_bukti", "keterangan", "jaminan", "kd_user", "no_transaksi"],
        "detail": ["no_order", "kd_barang", "kd_satuan", "jenis", "qty",
                   "harga_beli", "diskon1", "diskon2", "diskon3", "diskon4"],
    },
    "pembelian_retur": {
        "label": "Retur Pembelian",
        "tabel": "t_pembelian_retur",
        "tabel_detail": "t_pembelian_retur_detail",
        "kunci": "no_retur",
        "pihak": "kd_supplier",
        "harga": "harga",
        "header": ["no_retur", "kd_divisi", "kd_supplier", "kd_jenis", "kd_kas",
                   "tanggal", "no_bukti", "diskon1", "diskon2", "diskon3",
                   "diskon4", "pajak", "ppnbm", "keterangan", "kd_user"],
        "detail": ["no_retur", "kd_barang", "kd_satuan", "qty", "harga",
                   "diskon1", "diskon2", "diskon3", "diskon4"],
    },
}

_HARGA = {"harga_jual", "harga_beli", "harga"}


def spec(jenis: str) -> dict:
    return SPEC[jenis]  # KeyError kalau jenisnya tak dikenal — memang.


def total(items, diskon_header=(0, 0, 0, 0), pajak=0.0, ppnbm=0.0) -> float:
    """Nilai transaksi, semantik GHB yang sama dengan nota penjualan.

    Tak ada `diskon_uang` di ketiga tabel ini — kolomnya memang tidak ada.
    """
    net = 0.0
    for it in items:
        satuan = ghb(float(it["harga"]), [it.get(f"diskon{i}", 0) for i in (1, 2, 3, 4)])
        net += ghb(satuan, list(diskon_header)) * float(it["qty"])
    return net * (1 + (pajak or 0.0)) * (1 + (ppnbm or 0.0))


def _periksa(items, kd_user: str, kd_divisi: str) -> None:
    if not kd_user or not kd_divisi:
        raise ValueError(
            "Akun Anda belum ditautkan ke user legacy dan divisi untuk koneksi "
            "ini, jadi transaksi tak bisa dicatat atas nama Anda. Minta pengelola "
            "aplikasi mengisinya di Kelola Tautan User."
        )
    if not items:
        raise ValueError("Belum ada barang — tambahkan minimal satu baris.")
    for it in items:
        if not str(it.get("kd_barang") or "").strip():
            raise ValueError("Ada baris tanpa barang.")
        if float(it.get("qty") or 0) <= 0:
            raise ValueError(f"Qty barang {it.get('kd_barang')} harus lebih dari nol.")


def _nilai(kolom: str, it: dict, ctx: dict):
    """Satu kolom detail, dari item generik + konteks kepala."""
    if kolom in _HARGA:
        return float(it["harga"])
    if kolom == "qty":
        return float(it["qty"])
    if kolom in ("kd_barang", "kd_satuan"):
        return it[kolom]
    if kolom == "kd_pegawai":
        return it.get("kd_pegawai") or ctx.get("kd_pegawai") or ""
    if kolom == "jenis":
        return int(it.get("jenis") or 0)
    if kolom.startswith("diskon") or kolom.startswith("point"):
        return it.get(kolom) or 0
    return ctx.get(kolom, "")


def buat(profile, jenis: str, *, kd_user, kd_divisi, kd_pihak, kd_jenis, kd_kas,
         items, kd_pegawai="", keterangan=KOSONG, no_bukti=KOSONG, no_order=KOSONG,
         diskon_header=(0, 0, 0, 0), pajak=0.0, ppnbm=0.0, status=1,
         tanggal=None, jatuh_tempo=None,
         no_pp_order=KOSONG, jaminan=0.0, tanggal_terima=None) -> dict:
    """Tulis satu transaksi. Mengembalikan {nomor, total, baris}.

    Tiga argumen terakhir hanya dirujuk `pembelian_order`; jenis lain tak punya
    kolomnya, jadi nilainya tak pernah sampai ke SQL.
    """
    s = spec(jenis)
    _periksa(items, kd_user, kd_divisi)
    tanggal = tanggal or dt.datetime.now()
    dh = (list(diskon_header) + [0, 0, 0, 0])[:4]
    nilai_total = total(items, dh, pajak, ppnbm)

    ctx = {
        "kd_divisi": kd_divisi, s["pihak"]: kd_pihak, "kd_jenis": kd_jenis,
        # `t_pembelian_order` menamai kolom yang sama `kd_jenis_bayar`. Diisi di
        # sini dengan nilai yang sama alih-alih menambah kunci SPEC: keduanya
        # menunjuk `m_jenis_bayar.kd_jenis`, jadi memang satu nilai — cuma satu
        # tabel yang mengejanya berbeda.
        "kd_jenis_bayar": kd_jenis,
        "kd_kas": kd_kas, "kd_user": kd_user, "kd_pegawai": kd_pegawai,
        "tanggal": tanggal, "tanggal_jatuh_tempo": jatuh_tempo or tanggal,
        "tanggal_terima": tanggal_terima or jatuh_tempo or tanggal,
        "no_bukti": no_bukti or KOSONG, "no_order": no_order or KOSONG,
        "no_pp_order": no_pp_order or KOSONG, "jaminan": float(jaminan or 0),
        "keterangan": keterangan or KOSONG, "status": int(status),
        "pajak": pajak, "ppnbm": ppnbm,
        "diskon1": dh[0], "diskon2": dh[1], "diskon3": dh[2], "diskon4": dh[3],
    }
    tanya_h = ", ".join("?" for _ in s["header"])
    tanya_d = ", ".join("?" for _ in s["detail"])
    # Tabel yang kuncinya BUKAN no_transaksi tapi tetap punya kolom itu = order:
    # kolomnya menampung nomor transaksi yang kelak menutup order ini, dan
    # selama masih terbuka ia diisi nomor ordernya sendiri. Konvensi yang sama
    # dipakai `t_penjualan_order` dan terbukti di 7.209 baris; menandainya lewat
    # `status` justru yang gagal di sana (25 baris berstatus 1 padahal belum
    # diambil, lenyap dari daftar tanpa galat apa pun). Disimpulkan dari header
    # supaya tak ada kunci SPEC ketiga yang bisa lupa diisi.
    order_terbuka = "no_transaksi" in s["header"] and s["kunci"] != "no_transaksi"

    with mssql.cursor(profile, autocommit=False) as cur:
        awalan = s.get("awalan") or awalan_untuk(cur, kd_divisi)

        def tulis(no):
            ctx[s["kunci"]] = no
            if order_terbuka:
                ctx["no_transaksi"] = no
            cur.execute(  # nosec B608 — nama tabel/kolom dari SPEC
                f"INSERT INTO {s['tabel']} ({', '.join(s['header'])}) VALUES ({tanya_h})",
                [ctx.get(k, "") for k in s["header"]],
            )
            for it in items:
                cur.execute(  # nosec B608 — dari SPEC
                    f"INSERT INTO {s['tabel_detail']} ({', '.join(s['detail'])}) "
                    f"VALUES ({tanya_d})",
                    [no if k == s["kunci"] else _nilai(k, it, ctx) for k in s["detail"]],
                )

        no = simpan_dengan_nomor(
            cur, lambda: no_berikutnya(cur, jenis, awalan, tanggal), tulis)
        cur.connection.commit()

    return {"nomor": no, "total": nilai_total, "baris": len(items)}

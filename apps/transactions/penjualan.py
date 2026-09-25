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
from contextlib import nullcontext

from django.utils import timezone

from apps.transactions.hub_sync import bind_varchar
from apps.transactions.penomoran import awalan_untuk, no_berikutnya, simpan_dengan_nomor
from core import mssql
from core.cache import _cached

# Kolom yang menerima nilai kosong di data legacy — dilihat dari nota yang sudah
# ada, bukan ditebak: no_bukti dan keterangan berisi "-", bukan string kosong.
KOSONG = "-"

# Panjang minimal kotak cari barang/pelanggan. Dua, bukan tiga: potongan kode
# seperti "TY" masuk akal diketik, sedangkan satu huruf tak pernah menghasilkan
# daftar yang berguna — ia cuma memaksa scan penuh per ketukan tombol.
MIN_CARI = 2

_HEADER = [
    "no_transaksi", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas", "kd_voucher",
    "no_bukti", "tanggal", "tanggal_jatuh_tempo", "status", "diskon1", "diskon2",
    "diskon3", "diskon4", "diskon_uang", "pajak", "keterangan", "kd_user",
    "tanggal_setor",
]
# Kolom yang diisi EKSPRESI SQL, bukan parameter: jamnya harus jam SERVER.
#
# `tanggal_server` dulu tak disebut sama sekali, dengan anggapan kolomnya
# ber-DEFAULT GETDATE(). Dump skema tak menunjukkan DEFAULT itu (ia hanya membaca
# `sys.default_constraints`; bound default gaya lama tak terlihat), jadi
# anggapan itu tak bisa dibuktikan dari repo. Ditulis eksplisit: kalau DEFAULT-
# nya ada, hasilnya sama; kalau tidak, trigger feed merangkai NULL dan seluruh
# payload sync nota ini NULL (lihat apps/transactions/payload_sync.py).
EKSPRESI_NOTA = {"tanggal_server": "GETDATE()"}
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

# Order pembelian mengikuti pola yang sama, dengan satu perbedaan penting: di
# sana TIDAK ada data lama untuk ditiru — `t_pembelian_order` kosong di setiap
# server yang terjangkau (testgudang 0, PUSAT 0 padahal `t_pembelian` 12.605
# baris). Jadi `OB` adalah keputusan, bukan temuan, dan nomor yang sudah terbit
# tak bisa ditarik. Lihat SPEC["pembelian_order"] di transaksi.py.
AWALAN_TETAP = {"penjualan_order": AWALAN_ORDER, "pembelian_order": "OB"}

# tanggal_server SENGAJA di luar daftar: ia diisi GETDATE() sebagai ekspresi SQL
# (`EKSPRESI_ORDER`). Kolomnya di sini TIDAK punya DEFAULT — dibiarkan berarti
# NULL, padahal 7.209 baris legacy semuanya terisi.
EKSPRESI_ORDER = {"tanggal_server": "GETDATE()"}
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


def tanggal_setor(tanggal: dt.datetime) -> dt.datetime:
    """`t_penjualan.tanggal_setor` seperti yang ditulis aplikasi POS lama:
    tanggal nota dikurangi satu hari, jam nota.

    Terbaca dari log legacy: aplikasi lama mengisi ulang kolom ini setiap nota
    disimpan (227 dari 314 edit di grosirPusat 2025+ menggesernya; lihat
    `riwayat_log._BUKAN_PERUBAHAN`). Arunika tak memakai nilainya sama sekali —
    ia ditulis karena trigger `insert_temp_m_t_penjualan` merangkainya ke
    payload sync dengan `+`, dan NULL di sana membuat nota tak terkirim ke
    pusat maupun terbaca Nota Tanggal Mundur.

    Kembaran SQL-nya ada di `edit_nota.ubah_nota`:
    `COALESCE(tanggal_setor, DATEADD(day, -1, tanggal))`. Keduanya harus sepakat.
    """
    return tanggal - dt.timedelta(days=1)


def _kolom_ekspresi(kolom: list[str], ekspresi: dict[str, str]) -> tuple[str, str]:
    """(daftar kolom, daftar nilai) untuk INSERT: parameter lalu ekspresi SQL."""
    return (", ".join(list(kolom) + list(ekspresi)),
            ", ".join(["?"] * len(kolom) + list(ekspresi.values())))


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
    # legacy). `tanggal_server` diisi GETDATE() di server (`EKSPRESI_NOTA`), jadi
    # ia selalu jam SERVER. Dua jam yang berbeda memang disengaja: yang satu
    # kapan kasir mencatat, yang lain kapan server menerima.
    tanggal = tanggal or dt.datetime.now()
    jatuh_tempo = jatuh_tempo or (tanggal + dt.timedelta(days=BAWAAN["jatuh_tempo_hari"]))
    dh = list(diskon_header) + [0, 0, 0, 0]
    dh = dh[:4]
    total = total_nota(items, dh, diskon_uang, pajak)

    kolom_h, nilai_h = _kolom_ekspresi(_HEADER, EKSPRESI_NOTA)
    tanya_d = ", ".join("?" for _ in _DETAIL)

    with mssql.cursor(profile, autocommit=False) as cur:
        awalan = awalan_untuk(cur, kd_divisi)

        def tulis(no):
            cur.execute(
                f"INSERT INTO t_penjualan ({kolom_h}) VALUES ({nilai_h})",
                [no, kd_customer, kd_divisi, kd_jenis, kd_kas, kd_voucher,
                 no_bukti or KOSONG, tanggal, jatuh_tempo, status,
                 dh[0], dh[1], dh[2], dh[3], diskon_uang, pajak,
                 keterangan or KOSONG, kd_user, tanggal_setor(tanggal)],
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

    kolom_h, nilai_h = _kolom_ekspresi(_ORDER_HEADER, EKSPRESI_ORDER)
    tanya_d = ", ".join("?" for _ in _ORDER_DETAIL)

    with mssql.cursor(profile, autocommit=False) as cur:
        def tulis(no):
            cur.execute(
                f"INSERT INTO t_penjualan_order ({kolom_h}) VALUES ({nilai_h})",
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

    Minimal `MIN_CARI` huruf. `LIKE '%x%'` tak pernah bisa seek, jadi satu huruf
    berarti memindai join m_barang x m_barang_satuan (55rb baris) lalu menyortir
    SELURUH hasil cocok sebelum TOP 20 memotongnya — untuk daftar yang tak
    berguna bagi siapa pun. Jalur pemindai tak lewat sini: ia memanggil
    `barang_persis` dengan kode utuh.
    """
    cari = (cari or "").strip()
    if len(cari) < MIN_CARI:
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
        # kd_barang varchar; tanpa execute_varchar pyodbc mengikatnya NVARCHAR
        # dan konversi implisitnya mematikan seek index.
        mssql.execute_varchar(
            cur,
            "SELECT bs.kd_satuan, s.nama, bs.jumlah, bs.harga_jual, bs.status "
            "FROM m_barang_satuan bs LEFT JOIN m_satuan s ON s.kd_satuan = bs.kd_satuan "
            "WHERE bs.kd_barang = ? ORDER BY bs.jumlah, bs.harga_jual",
            [kd_barang])
        return [{"kd_satuan": (r[0] or "").strip(), "satuan": (r[1] or "").strip(),
                 "jumlah": float(r[2] or 0), "harga_jual": float(r[3] or 0),
                 "status": int(r[4] or 0)} for r in cur.fetchall()]


def satuan_banyak(profile, kd_barang: list[str]) -> dict[str, list[dict]]:
    """Satuan untuk BANYAK barang sekaligus: {kd_barang: [satuan, …]}.

    Ada karena layar Koreksi Stok memuat sampai 300 baris sekali tarik, dan di
    sana satuan bukan pelengkap: `kd_satuan` wajib terisi sebelum baris bisa
    disimpan, dan ia yang menentukan besar pergeseran stoknya. Mengambilnya
    per baris berarti 300 round-trip sebelum operator bisa menekan Simpan
    sekali pun — lewat Tailscale itu hitungan menit.

    Harga tidak diambil: layar koreksi tak pernah menampilkannya, dan kolom yang
    tak dikirim tak bisa bocor.
    """
    kode = [k for k in {(k or "").strip() for k in kd_barang} if k]
    if not kode:
        return {}
    out: dict[str, list[dict]] = {}
    with mssql.cursor(profile) as cur:
        # Kolom kunci legacy bertipe varchar; tanpa ikatan ini pyodbc mengirim
        # NVARCHAR dan SQL Server memindai tabel sekali untuk TIAP nilai `IN`
        # (terukur 6,23 dtk → 0,01 dtk untuk 50 nilai). Lihat bind_varchar.
        bind_varchar(cur, len(kode), max(len(k) for k in kode))
        try:
            tanya = ", ".join("?" for _ in kode)
            cur.execute(  # nosec B608 — hanya placeholder yang diinterpolasi
                "SELECT bs.kd_barang, bs.kd_satuan, s.nama, bs.jumlah "
                "FROM m_barang_satuan bs "
                "LEFT JOIN m_satuan s ON s.kd_satuan = bs.kd_satuan "
                f"WHERE bs.kd_barang IN ({tanya}) ORDER BY bs.kd_barang, bs.jumlah",
                kode,
            )
            baris = cur.fetchall()
        finally:
            cur.setinputsizes(None)
    for r in baris:
        out.setdefault((r[0] or "").strip(), []).append({
            "kd_satuan": (r[1] or "").strip(),
            "satuan": (r[2] or "").strip(),
            "jumlah": float(r[3] or 0),
        })
    return out


def opsi_nota(profile) -> dict:
    """Pilihan berkunci-asing untuk form nota.

    Semuanya WAJIB terisi kode yang nyata: kd_jenis dan kd_voucher punya
    FOREIGN KEY, dan kd_kas/kd_customer/kd_pegawai NOT NULL. Membiarkannya
    sebagai isian bebas membuat setiap simpan pertama gagal dengan galat FK.

    Dicache seperti `inv.list_divisi`, dan alasannya sama: kelima daftarnya
    tabel `m_*` yang jarang berubah, sementara ia dibaca di SETIAP muat layar
    kasir — lima query tabel penuh untuk data yang identik sepanjang hari.
    Tulis master membuang cache profil ini lewat `invalidate_master_cache`
    (master_crud.simpan_master dan master_data.services), jadi voucher atau
    pegawai baru tetap langsung terlihat.

    `bawaan_form` sengaja TIDAK ikut dicache: ia memulangkan ancar-ancar nomor
    nota berikutnya, dan nomor basi sepuluh menit lebih buruk daripada satu
    koneksi.
    """
    def ambil(cur, sql):
        cur.execute(sql)
        return [{"value": (r[0] or "").strip(), "label": (r[1] or "").strip()}
                for r in cur.fetchall()]

    def bangun():
        with mssql.cursor(profile) as cur:
            return {
                "jenis_bayar": ambil(cur, "SELECT kd_jenis, nama FROM m_jenis_bayar ORDER BY nama"),
                "kas": ambil(cur, "SELECT kd_kas, no_rekening FROM m_kas ORDER BY kd_kas"),
                "voucher": ambil(cur, "SELECT kd_voucher, nama FROM m_voucher ORDER BY kd_voucher"),
                "pegawai": ambil(cur, "SELECT kd_pegawai, nama FROM m_pegawai ORDER BY nama"),
                "pelanggan": ambil(
                    cur, "SELECT TOP 200 kd_customer, nama FROM m_customer ORDER BY nama"),
            }

    return _cached(profile, "opsi_nota", bangun)


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
    hasil["tanggal"] = _dt.date.today().isoformat()
    hasil["jatuh_tempo"] = (
        _dt.date.today() + _dt.timedelta(days=BAWAAN["jatuh_tempo_hari"])).isoformat()
    if jenis.startswith("penjualan"):
        hasil["customer_nama"] = "UMUM"
    else:
        # Sisi beli tak punya pelanggan maupun voucher, dan tak ada "supplier
        # umum": memilih pemasoknya memang keputusan, bukan sesuatu yang boleh
        # ditebak. Kuncinya dibuang, bukan dikosongkan — kunci kosong di layar
        # supplier terbaca seperti pilihan yang gagal dimuat.
        for k in ("kd_customer", "kd_voucher"):
            hasil.pop(k, None)
    try:
        with mssql.cursor(profile) as cur:
            # Kedua order punya awalan tetap sendiri; kepala_nota tak dilihat
            # sama sekali, jadi layarnya tetap jalan walau kolomnya belum diisi.
            awalan = AWALAN_TETAP.get(jenis) or awalan_untuk(cur)
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

    Batas `MIN_CARI` huruf, alasannya sama dengan `cari_barang`.
    """
    cari = (cari or "").strip()
    if len(cari) < MIN_CARI:
        return []
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP (?) kd_customer, nama, alamat FROM m_customer "
            "WHERE nama LIKE ? OR kd_customer LIKE ? ORDER BY nama",
            [limit, f"%{cari}%", f"%{cari}%"])
        return [{"kd_customer": (r[0] or "").strip(), "nama": (r[1] or "").strip(),
                 "alamat": (r[2] or "").strip()} for r in cur.fetchall()]


# --- Panel info di layar kasir --------------------------------------------
#
# Tiga potong keterangan yang selama ini hanya ada di /admin-panel: siapa yang
# sedang dilayani, berapa piutangnya yang belum lunas, dan apa yang barusan
# dijual oleh kasir ini sendiri. Panel admin tertutup penjaga Tailscale, jadi
# dari jaringan toko ketiganya memang tak terjangkau — kasir menanyakannya lewat
# telepon, atau tidak menanyakannya sama sekali.
#
# Rumus uangnya TIDAK ditulis ulang di sini: keduanya memanggil `_nota_net` yang
# sama dengan seluruh laporan penjualan. Menyalin rumusnya berarti dua definisi
# "total nota" yang akan berbeda diam-diam pada nota berdiskon header.

# Pelanggan lewat. Tak ada member info yang berarti untuknya, dan memanggil
# panel untuk setiap nota tunai berarti satu round-trip WAN di awal tiap nota.
CUSTOMER_UMUM = "CAA000"


def _kursor(profile, cur=None):
    """Kursor yang dioper pemanggil, atau satu yang dibuka sendiri.

    Panel info memanggil TIGA fungsi di bawah dalam satu permintaan HTTP, dan
    masing-masing dulu membuka koneksi pyodbc sendiri — tiga handshake ODBC
    untuk satu klik pelanggan. Di profil jauh, handshake-lah ongkosnya, bukan
    querynya.

    Tetap `cur=None` dan bukan kursor wajib di argumen pertama (pola
    `penomoran.awalan_untuk`): `histori_nota` punya pemanggil kedua
    (`histori_user_json`) yang tak punya alasan mengurus koneksi sendiri.
    """
    return nullcontext(cur) if cur is not None else mssql.cursor(profile)


def info_customer(profile, kd_customer: str, cur=None) -> dict | None:
    """Identitas pelanggan untuk panel info. None kalau kodenya tak ada.

    `point`, `limit_kredit`, dan `disc` ikut dibawa: ketiganya sudah lama ada di
    m_customer dan sudah diisi lewat layar master, tapi tak satu pun layar kasir
    pernah membacanya — jadi diskon langganan dan batas kreditnya cuma diketahui
    orang yang kebetulan hafal.
    """
    kd = (kd_customer or "").strip()
    if not kd:
        return None
    with _kursor(profile, cur) as c:
        # execute_varchar: kd_customer varchar, dan pyodbc mengikat str sebagai
        # NVARCHAR — konversi implisitnya jatuh di KOLOM dan mematikan seek PK.
        mssql.execute_varchar(
            c,
            "SELECT kd_customer, nama, alamat, hp, telepon, point, limit_kredit, "
            "disc, status FROM m_customer WHERE kd_customer = ?", [kd])
        r = c.fetchone()
    if not r:
        return None
    teks = lambda v: (v or "").strip() if isinstance(v, str) else (v or "")  # noqa: E731
    return {
        "kd_customer": teks(r[0]), "nama": teks(r[1]), "alamat": teks(r[2]),
        "hp": teks(r[3]), "telepon": teks(r[4]),
        "point": float(r[5] or 0), "limit_kredit": float(r[6] or 0),
        "disc": float(r[7] or 0), "status": int(r[8] or 0),
    }


def _tanpa_rentang_tanggal(where_extra, params):
    """WHERE untuk `_nota_net` tanpa penyaring tanggal sama sekali.

    Piutang dan histori di panel ini memang bertanya tentang RIWAYAT, bukan satu
    periode: piutang yang jatuh tempo delapan bulan lalu justru yang paling
    perlu terlihat saat orangnya berdiri di depan kasir, dan ia akan hilang dari
    rentang bawaan mana pun.
    """
    from apps.transactions.reports import _base_where

    where, p = _base_where({"skip_date_predicate": True})
    return " AND ".join(where + where_extra), p + params


def piutang_customer(profile, kd_customer: str, limit: int = 10, cur=None) -> list[dict]:
    """Nota yang belum lunas milik satu pelanggan, terlama dulu.

    Bentuk hitungannya sama dengan laporan Piutang Pelanggan (`reports.piutang`):
    `status = 0`, dikurangi cicilan, sisa > 0. Voucher sengaja tidak dikurangi —
    konsisten dengan seluruh laporan penjualan, lihat catatan di reports.py.
    """
    from apps.transactions.reports import _nota_net

    kd = (kd_customer or "").strip()
    if not kd:
        return []
    where, params = _tanpa_rentang_tanggal(
        ["h.status = 0", "h.kd_customer = ?"], [kd])
    sql = (
        f"SELECT TOP {int(limit)} n.no_transaksi, n.tanggal, n.tanggal_jatuh_tempo, "
        "n.total_bersih, COALESCE(cic.total_cicilan, 0) AS total_cicilan, "
        "n.total_bersih - COALESCE(cic.total_cicilan, 0) AS sisa_piutang, "
        "CASE WHEN DATEDIFF(day, n.tanggal_jatuh_tempo, GETDATE()) > 0 "
        "THEN DATEDIFF(day, n.tanggal_jatuh_tempo, GETDATE()) ELSE 0 END AS hari_terlambat "
        f"FROM ({_nota_net(where)}) n "
        "LEFT JOIN (SELECT no_transaksi, SUM(nominal) AS total_cicilan "
        "FROM t_piutang_cicilan GROUP BY no_transaksi) cic "
        "ON cic.no_transaksi = n.no_transaksi "
        "WHERE n.total_bersih - COALESCE(cic.total_cicilan, 0) > 0 "
        # Terlama dulu, bukan terbaru: yang menunggak paling lama itu yang perlu
        # ditagih, dan daftar ini dipotong di baris ke-10.
        "ORDER BY n.tanggal"
    )
    with _kursor(profile, cur) as c:
        # kd_customer varchar; execute_varchar (bukan bind_varchar) karena
        # `_base_where` bisa menyisipkan parameter bertipe lain di depannya.
        mssql.execute_varchar(c, sql, params)
        return [{
            "no_transaksi": (r[0] or "").strip(),
            "tanggal": r[1].strftime("%Y-%m-%d") if r[1] else "",
            "jatuh_tempo": r[2].strftime("%Y-%m-%d") if r[2] else "",
            "total_penjualan": float(r[3] or 0),
            "total_cicilan": float(r[4] or 0),
            "sisa_piutang": float(r[5] or 0),
            "hari_terlambat": int(r[6] or 0),
        } for r in c.fetchall()]


def histori_nota(profile, kd_customer: str = "", kd_user: str = "",
                 limit: int = 10, cur=None) -> list[dict]:
    """Nota terakhir milik satu pelanggan ATAU satu user legacy.

    Satu fungsi untuk dua panel karena bedanya cuma satu kolom di WHERE, dan
    keduanya punya index penampung sendiri: `(kd_customer, tanggal)` dan
    `IX_tpenjualan_user_tanggal (kd_user, tanggal)`. Penyaringnya didorong ke
    DALAM `_nota_net` supaya index dipakai untuk MENYARING, bukan untuk memindai
    seluruh tabel lalu membuang hasilnya.
    """
    from apps.transactions.reports import _nota_net

    extra, params = [], []
    if (kd := (kd_customer or "").strip()):
        extra.append("h.kd_customer = ?")
        params.append(kd)
    if (ku := (kd_user or "").strip()):
        extra.append("h.kd_user = ?")
        params.append(ku)
    if not extra:  # tanpa penyaring ini akan memindai seluruh t_penjualan
        return []
    where, params = _tanpa_rentang_tanggal(extra, params)
    sql = (
        f"SELECT TOP {int(limit)} n.no_transaksi, n.tanggal, n.status_raw, "
        "n.total_bersih, COALESCE(c.nama, '') AS customer "
        f"FROM ({_nota_net(where)}) n "
        "LEFT JOIN m_customer c ON n.kd_customer = c.kd_customer "
        "ORDER BY n.tanggal DESC"
    )
    status = {0: "Kredit", 1: "Tunai", 2: "Lunas"}
    with _kursor(profile, cur) as c:
        # kd_customer/kd_user varchar — lihat catatan di `piutang_customer`.
        mssql.execute_varchar(c, sql, params)
        return [{
            "no_transaksi": (r[0] or "").strip(),
            "tanggal": r[1].strftime("%Y-%m-%d %H:%M") if r[1] else "",
            "status": status.get(int(r[2] or 0), ""),
            "nominal": float(r[3] or 0),
            "customer": (r[4] or "").strip(),
        } for r in c.fetchall()]


def rekap_hari_ini(profile, kd_user: str, tanggal=None, cur=None) -> dict:
    """Penjualan HARI INI milik satu user legacy: jumlah nota + rupiah,
    dipecah tunai/kredit.

    Kasir bertanya "sudah berapa saya hari ini" — terutama saat menutup laci —
    dan jawabannya selama ini cuma ada di /admin-panel, yang tertutup penjaga
    Tailscale dari jaringan toko. Tab "Nota Saya" menampilkan 10 nota terakhir
    SEPANJANG MASA; ia tak menjawab pertanyaan itu, dan menjumlahkan sepuluh
    baris di kepala jelas bukan jawabannya juga.

    Rumus uangnya `_nota_net()` yang sama dengan seluruh laporan penjualan —
    tak ada definisi "total nota" kedua di berkas ini. Tunai/kredit dipecah dari
    `status_raw` yang sudah dipulangkannya (0 Kredit / 1 Tunai / 2 Lunas), jadi
    tanpa join dan tanpa kolom tambahan. `Lunas` ikut kolom kredit: ia nota
    kredit yang sudah dibayar, bukan uang yang masuk laci hari ini.

    Penyaringnya didorong ke DALAM `_nota_net` supaya
    IX_tpenjualan_user_tanggal (kd_user, tanggal) dipakai untuk MENYARING,
    bukan memindai seluruh t_penjualan lalu membuang hasilnya — alasan yang
    sama dengan `histori_nota`.

    Batas atasnya `< besok 00:00`, bukan `<= hari ini 23:59:59`: `tanggal` di
    t_penjualan menyimpan jam, dan detik terakhir hari itu nota yang nyata.
    """
    from apps.transactions.reports import _nota_net

    kosong = {"jml_nota": 0, "total": 0.0, "total_tunai": 0.0, "total_kredit": 0.0}
    ku = (kd_user or "").strip()
    if not ku:
        return kosong
    # localdate(), bukan date.today(): batas harinya mengikuti TIME_ZONE
    # aplikasi, bukan zona jam sistem mesin yang kebetulan menjalankannya.
    hari = tanggal or timezone.localdate()
    params = [ku,
              dt.datetime.combine(hari, dt.time.min),
              dt.datetime.combine(hari + dt.timedelta(days=1), dt.time.min)]
    sql = (
        "SELECT COUNT(n.no_transaksi) AS jml_nota, "
        "COALESCE(SUM(n.total_bersih), 0) AS total, "
        "COALESCE(SUM(CASE WHEN n.status_raw = 1 THEN n.total_bersih ELSE 0 END), 0) AS total_tunai, "
        "COALESCE(SUM(CASE WHEN n.status_raw <> 1 THEN n.total_bersih ELSE 0 END), 0) AS total_kredit "
        f"FROM ({_nota_net('h.kd_user = ? AND h.tanggal >= ? AND h.tanggal < ?')}) n"
    )
    with _kursor(profile, cur) as c:
        # Daftar parameter CAMPURAN (satu str + dua datetime) — execute_varchar,
        # TAK PERNAH bind_varchar: memaksa datetime lewat VARCHAR menyerahkan
        # penafsiran tanggal ke setelan bahasa server (lolos di `us_english`,
        # DataError 22007 di `british`/`deutsch`).
        mssql.execute_varchar(c, sql, params)
        r = c.fetchone()
    if not r:
        return kosong
    return {"jml_nota": int(r[0] or 0), "total": float(r[1] or 0),
            "total_tunai": float(r[2] or 0), "total_kredit": float(r[3] or 0)}


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
        # Jalur pemindai menyala sekali PER BARANG yang dipindai, jadi seek di
        # sini yang paling sering ditagih. kd_barang varchar — execute_varchar.
        mssql.execute_varchar(
            cur,
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


# Teks contoh bawaan installer legacy, bukan identitas siapa pun. `g_info_profile`
# di SERVER-TOYS (18.927 baris) dan SERVER-GUDANG (15.698) masih berisi ini apa
# adanya — nama toko yang sebenarnya justru ada di `m_divisi.nama`. Mencetak
# "PERUSAHAAN ANDA / ALAMAT PERUSAHAAN / Telp : 0" di kop struk pelanggan lebih
# buruk daripada tidak mencetak apa-apa, jadi nilai-nilai ini diperlakukan sama
# dengan kosong. Perbaikan sesungguhnya tetap mengisi layar Informasi Perusahaan.
_PROFIL_CONTOH = {
    "", "-", "0", "PERUSAHAAN ANDA", "NAMA PERUSAHAAN", "ALAMAT PERUSAHAAN",
    "ALAMAT", "TELEPON", "NO TELEPON",
}


def _terisi(nilai) -> str:
    """Nilai profil perusahaan, atau string kosong bila ia cuma teks contoh."""
    v = (nilai or "").strip()
    return "" if v.upper() in _PROFIL_CONTOH else v


def _label_diskon(nilai, satuan: str = "") -> str:
    """Diskon baris jadi teks pendek untuk struk: "10%", "500/PCS", "10%+500/PCS".

    Dua mode, sama seperti `ghb()`: nilai di (-1, 1) itu PERSEN, selebihnya
    rupiah flat. Struk harus menyebut yang mana — "Disc 0,1" tak berarti apa-apa
    di tangan pelanggan, dan "Disc 10%" untuk potongan Rp10 itu bohong.

    Rupiah selalu diberi "/satuan" karena ia potongan PER UNIT, sementara angka
    di kanannya potongan SELURUH BARIS. Tanpa itu baris "Disc 3.000 = 9.000"
    terbaca sebagai hitungan yang salah, padahal 3.000 x 3 pcs memang 9.000.
    """
    bagian = []
    for d in nilai:
        d = float(d or 0)
        if d == 0:
            continue
        if -1 < d < 1:
            bagian.append(f"{d * 100:g}%")
        else:
            bagian.append(f"{d:,.0f}".replace(",", ".") + (f"/{satuan}" if satuan else ""))
    return "+".join(bagian)


def baca_nota(profile, no_transaksi: str) -> dict | None:
    """Satu nota lengkap untuk dicetak: identitas toko, kasir, pegawai, member, uang.

    Uangnya TIDAK dihitung dengan rumus baru. `bruto` dan `net` memakai `ghb()`
    yang sama dengan jalur tulis dan dengan `_nota_net()` di reports.py; rumus
    uang kedua akan menyimpang diam-diam pada nota berdiskon header (lihat
    docstring `total_nota`).

    `diskon` sengaja DITURUNKAN dari total, bukan dijumlahkan sendiri:

        diskon = bruto + pajak_rp - total

    sehingga `Sub Total - Diskon + Pajak = Total` selalu benar di kertas, berapa
    pun yang tersimpan di `t_penjualan_total.total`. Kalau diskon dijumlah
    sendiri dan ternyata meleset serupiah dari total legacy, yang terlihat
    pelanggan adalah struk yang tidak menjumlah — dan itu jauh lebih buruk
    daripada angka diskon yang meleset seorang diri.

    `bayar`/`kembali` TIDAK ada di sini: `t_penjualan` tak punya kolomnya (lihat
    `_HEADER`). Nilainya dioper dari layar kasir lewat query string ke
    `views_kasir.nota_cetak`.
    """
    no_transaksi = (no_transaksi or "").strip()
    if not no_transaksi:
        return None

    with mssql.cursor(profile) as cur:
        # Kasir lewat m_userx, BUKAN m_pegawai: `kd_user` dan `kd_pegawai` dua
        # ruang kode berbeda — orang yang sama `UAA034`/"ADMIN6" di m_userx tak
        # punya padanan di m_pegawai (terukur: join lewat kd_user memulangkan
        # NULL di SETIAP nota server Testing). Versi sebelumnya menambal NULL itu
        # dengan pegawai di baris detail pertama, jadi struk mencetak nama SPG
        # di bawah label "Kasir". Lihat apps/auth_app/models.TautanUser.
        # no_transaksi varchar di kedua tabel — execute_varchar, supaya kedua
        # predikat di bawah tetap seek dan bukan scan.
        mssql.execute_varchar(
            cur,
            "SELECT h.no_transaksi, h.tanggal, h.kd_customer, c.nama, "
            "h.kd_user, u.nama, h.kd_jenis, jb.nama, "
            "h.kd_divisi, dv.nama, h.no_bukti, h.keterangan, h.tanggal_jatuh_tempo, "
            "h.diskon1, h.diskon2, h.diskon3, h.diskon4, h.diskon_uang, h.pajak, "
            "t.total, jb.status, vc.nominal "
            "FROM t_penjualan h "
            "LEFT JOIN m_customer c ON c.kd_customer = h.kd_customer "
            "LEFT JOIN m_userx u ON u.kd_user = h.kd_user "
            "LEFT JOIN m_jenis_bayar jb ON jb.kd_jenis = h.kd_jenis "
            "LEFT JOIN m_divisi dv ON dv.kd_divisi = h.kd_divisi "
            "LEFT JOIN m_voucher vc ON vc.kd_voucher = h.kd_voucher "
            "LEFT JOIN t_penjualan_total t ON t.no_transaksi = h.no_transaksi "
            "WHERE h.no_transaksi = ?",
            [no_transaksi],
        )
        h = cur.fetchone()
        if not h:
            return None

        mssql.execute_varchar(
            cur,
            "SELECT d.kd_barang, b.nama, d.kd_satuan, s.nama, d.qty, d.harga_jual, "
            "d.diskon1, d.diskon2, d.diskon3, d.diskon4, d.total, p.nama "
            "FROM t_penjualan_detail d "
            "LEFT JOIN m_barang b ON b.kd_barang = d.kd_barang "
            "LEFT JOIN m_satuan s ON s.kd_satuan = d.kd_satuan "
            "LEFT JOIN m_pegawai p ON p.kd_pegawai = d.kd_pegawai "
            "WHERE d.no_transaksi = ?",
            [no_transaksi],
        )
        detail = cur.fetchall()

        # Kop toko. Query-nya kembar dengan master_data.services.baca_info_perusahaan
        # — disalin, bukan dipanggil, supaya cetak nota tetap SATU koneksi:
        # mssql.cursor() membuka sambungan baru tiap kali, dan di profil jauh
        # ongkosnya perjalanan bolak-balik, bukan barisnya. ORDER BY-nya wajib,
        # alasannya ada di fungsi itu (tabelnya heap tanpa kunci).
        cur.execute(
            "SELECT TOP 1 perusahaan, alamat, telp FROM g_info_profile "
            "ORDER BY perusahaan, alamat, kota, telp"
        )
        prof = cur.fetchone()

    dh = [float(h[13] or 0), float(h[14] or 0), float(h[15] or 0), float(h[16] or 0)]
    diskon_uang = float(h[17] or 0)
    pajak = float(h[18] or 0)

    baris, items, bruto, net = [], [], 0.0, 0.0
    for r in detail:
        qty = float(r[4] or 0)
        harga = float(r[5] or 0)
        db = [float(r[6] or 0), float(r[7] or 0), float(r[8] or 0), float(r[9] or 0)]
        bruto_baris = harga * qty
        net_baris = ghb(ghb(harga, db), dh) * qty
        bruto += bruto_baris
        net += net_baris
        baris.append({
            "kd_barang": (r[0] or "").strip(),
            "nama": (r[1] or "").strip() or (r[0] or "").strip(),
            "kd_satuan": (r[2] or "").strip(),
            "satuan": (r[3] or "").strip() or (r[2] or "").strip(),
            "qty": qty,
            "harga": harga,
            "bruto": bruto_baris,
            # Potongan baris SAJA (diskon header sengaja tak masuk sini — ia
            # milik nota, bukan barangnya, dan mencantumkannya per baris membuat
            # angkanya terhitung dua kali di mata pembaca struk).
            "diskon": bruto_baris - ghb(harga, db) * qty,
            "diskon_label": _label_diskon(db, (r[3] or "").strip() or (r[2] or "").strip()),
            "total": float(r[10] or 0),
            "pegawai": (r[11] or "").strip(),
        })
        items.append({"harga_jual": harga, "qty": qty, "diskon1": db[0],
                      "diskon2": db[1], "diskon3": db[2], "diskon4": db[3]})

    pajak_rp = net * pajak
    total = float(h[19]) if h[19] is not None else total_nota(items, dh, diskon_uang, pajak)

    # Voucher dipisahkan dari Diskon, dan itu bukan kosmetik. `t_penjualan_total.total`
    # SUDAH memotong nominal voucher (terukur di SERVER-TOYS: pada tiga nota
    # bervoucher, `bruto - total` persis sama dengan nominalnya). Tanpa dipisah,
    # potongan voucher tercetak sebagai "Diskon" — pelanggan yang menyerahkan
    # voucher Rp50.000 melihat "Diskon 50.000" dan tak ada bukti vouchernya
    # dipakai. `total_nota()` sendiri TIDAK mengurangkan voucher, jadi angka ini
    # hanya benar selama `total` datang dari database.
    voucher = float(h[21] or 0) if h[19] is not None else 0.0

    ket = (h[11] or "").strip()
    no_bukti = (h[10] or "").strip()
    # Identitas Arunika (SQLite) menang atas `g_info_profile`; yang legacy cuma
    # cadangan untuk server yang sudah terlanjur mengisinya. Lihat
    # `core.models.InfoPerusahaan` untuk alasan tabelnya dipindah.
    from apps.core.models import InfoPerusahaan

    milik = InfoPerusahaan.objects.filter(profile=profile).first()
    p_nama = (milik.perusahaan if milik else "") or (prof[0] if prof else "")
    p_alamat = (milik.alamat if milik else "") or (prof[1] if prof else "")
    p_telp = (milik.telp if milik else "") or (prof[2] if prof else "")

    # Urutannya: identitas perusahaan -> nama divisi notanya -> menyerah. Di
    # server yang profilnya belum diisi, nama divisi adalah satu-satunya nama
    # toko yang benar-benar ada di sana.
    nama_toko = _terisi(p_nama) or (h[9] or "").strip() or "NOTA PENJUALAN"

    # Uang yang diterima kasir. Tak ada di legacy — ia dicatat di pangkal saat
    # nota disimpan (`core.models.BayarNota`). Kembaliannya DIHITUNG di sini
    # dari total versi server, tak pernah disimpan: itu yang membuat angka di
    # struk tak bisa dikarang. Nota yang tak punya catatan bayar (nota lama,
    # atau yang bayarnya tak diisi) tetap mencetak tanpa kedua baris itu —
    # lebih baik kosong daripada "Kembali: 0" yang tidak benar.
    bayar, kembali = None, None
    if (b := _bayar_tercatat(profile, no_transaksi)) is not None:
        bayar = b
        kembali = max(0.0, b - total)

    return {
        "no_transaksi": (h[0] or "").strip(),
        "tanggal": h[1],
        "kd_customer": (h[2] or "").strip(),
        "customer": (h[3] or "").strip(),
        "kd_user": (h[4] or "").strip(),
        # Dua orang berbeda, dua kolom berbeda: `kasir` menulis notanya,
        # `pegawai` melayani penjualannya.
        "kasir": (h[5] or "").strip() or (h[4] or "").strip(),
        "pegawai": next((b["pegawai"] for b in baris if b["pegawai"]), ""),
        "kd_jenis": (h[6] or "").strip(),
        "jenis_bayar": (h[7] or "").strip() or (h[6] or "").strip(),
        "kd_divisi": (h[8] or "").strip(),
        "divisi": (h[9] or "").strip(),
        "no_bukti": "" if no_bukti == KOSONG else no_bukti,
        "keterangan": "" if ket == KOSONG else ket,
        "jatuh_tempo": h[12],
        "bruto": bruto,
        "diskon": bruto + pajak_rp - total - voucher,
        "voucher": voucher,
        # `m_jenis_bayar.status`: 1 = tunai/langsung lunas (TUNAI, BON, DEBIT),
        # 2 = belum lunas (BG, CEK, KREDIT). BUKAN `t_penjualan.status`, yang
        # praktis selalu 1 (523.878 baris berbanding 7) dan tak membedakan apa pun.
        "status_bayar": "LUNAS" if int(h[20] or 1) == 1 else "KREDIT",
        "pajak": pajak,
        "pajak_rp": pajak_rp,
        "total": total,
        "bayar": bayar,
        "kembali": kembali,
        "baris": baris,
        "toko": nama_toko,
        "alamat": _terisi(p_alamat),
        "telepon": _terisi(p_telp),
    }


def _bayar_tercatat(profile, no_transaksi: str) -> float | None:
    """Uang diterima untuk nota ini, dari pangkal. None kalau tak tercatat.

    Kegagalan baca ditelan, bukan dilempar: pangkal yang bermasalah tak boleh
    membuat struk gagal dicetak — ia cuma kehilangan dua baris.
    """
    from apps.core.models import BayarNota

    try:
        baris = BayarNota.objects.filter(
            profile=profile, no_transaksi=no_transaksi).first()
    except Exception:   # noqa: BLE001 — lihat docstring
        return None
    return float(baris.dibayar) if baris else None


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
        # no_order varchar di kedua tabel — execute_varchar supaya predikatnya
        # tetap bisa seek.
        mssql.execute_varchar(
            cur,
            "SELECT o.no_order, o.kd_customer, c.nama, o.kd_jenis, o.kd_kas, "
            "o.kd_voucher, o.keterangan, o.diskon_uang, o.pajak "
            "FROM t_penjualan_order o "
            "LEFT JOIN m_customer c ON c.kd_customer = o.kd_customer "
            "WHERE o.no_order = ?", [no_order])
        h = cur.fetchone()
        if not h:
            return None
        mssql.execute_varchar(
            cur,
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

"""Audit harga beli toko terhadap pembelian gudang.

Masalahnya: sinkronisasi antar-server menerbitkan pembelian di toko dengan
`harga_beli` diisi HARGA JUAL gudang, bukan harga beli gudang ke supplier.
Selama ini admin mengoreksinya manual satu per satu. Modul ini menemukan yang
terlewat dan menghitung penggantinya.

Kenapa deteksinya bisa pasti: baris yang sudah dikoreksi admin TIDAK lagi sama
dengan harga jual gudang, jadi uji kesamaan menyaringnya keluar dengan
sendirinya. Yang tersisa memang baris yang belum tersentuh. Itu sebabnya
"terapkan semua yang terpilih" aman di sini — himpunannya sudah tersaring, bukan
hasil terkaan.

Aturan pengganti diuji, bukan ditebak: enam kandidat diadu lawan ribuan koreksi
manual admin sebagai kunci jawaban (lihat
apps/core/management/commands/audit_harga_beli_diag.py). Pemenangnya harga beli
NET gudang dari pembelian terakhir bertanggal <= tanggal nota toko — 87,5% tepat,
jauh di atas "harga terakhir kapan pun" yang cuma 60,5%.
"""
from __future__ import annotations

import bisect
import datetime as dt

from apps.core.reporting import dictify as _dictify
from apps.transactions.reports import _ghb
from core import mssql
from core.cache import _cached

# Batas baris yang dikirim ke peramban. Temuan nyata jauh di bawah ini (ratusan),
# jadi menyentuh plafon berarti ada yang tak beres — dan itu dilaporkan ke UI,
# bukan dipotong diam-diam.
MAX_ROWS = 1000

# Profil yang BOLEH ditulis. Deteksi read-only boleh jalan di koneksi mana pun;
# penulisan tidak. Daftar-putih, bukan daftar-hitam: profil baru yang belum
# dikenal ditolak, bukan diizinkan diam-diam. Bentuk yang sama sudah terbukti
# menolak ANDARIA di perintah diagnostik.
_TULIS_DIIZINKAN = {("localhost", "grosirpusat")}

TOLERANSI = 0.01


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _k(v) -> str:
    """Normalisasi key join: collation MS SQL abai huruf besar/kecil dan spasi
    ekor, dict Python tidak. Tanpa ini baris hilang diam-diam saat join."""
    return (v or "").strip().upper()


def boleh_tulis(profile) -> bool:
    return (profile.host.strip().lower(), profile.db_name.strip().lower()) in _TULIS_DIIZINKAN


# --- riwayat gudang --------------------------------------------------------

def _harga_jual_gudang(cur) -> dict:
    """(barang, satuan) -> [(tanggal_pertama, harga_jual)] terurut.

    Diagregasi di SQL per harga, bukan per baris: t_penjualan_detail berisi
    ~570rb baris dan menstreamingnya utuh tiap muat halaman mahal, sementara
    untuk mendeteksi "nilai ini harga jual gudang" yang dibutuhkan hanya
    daftar harga yang pernah berlaku beserta kapan mulai berlaku.
    """
    cur.execute(
        "SELECT d.kd_barang, d.kd_satuan, d.harga_jual, MIN(h.tanggal) AS dari "
        "FROM t_penjualan_detail d "
        "INNER JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
        "GROUP BY d.kd_barang, d.kd_satuan, d.harga_jual"
    )
    out: dict = {}
    for r in _dictify(cur):
        out.setdefault((_k(r["kd_barang"]), _k(r["kd_satuan"])), []).append(
            (r["dari"], _f(r["harga_jual"]))
        )
    return out


def _riwayat_beli_gudang(cur) -> dict:
    """(barang, satuan) -> (tanggal[], harga_net[], no_transaksi[]) terurut waktu.

    Harga net memakai _ghb — emulasi UDF diskon/pajak legacy yang sudah
    diverifikasi lawan UDF aslinya oleh scripts/verify_ghb_semantics.py. Jangan
    tulis ulang rumusnya di sini.
    """
    net = _ghb(
        "d.harga_beli",
        ["COALESCE(d.diskon1,0)", "COALESCE(d.diskon2,0)",
         "COALESCE(d.diskon3,0)", "COALESCE(d.diskon4,0)"],
        pajak="COALESCE(h.pajak,0)", ppnbm="COALESCE(h.ppnbm,0)",
    )
    cur.execute(
        f"SELECT d.kd_barang, d.kd_satuan, h.tanggal, h.no_transaksi, ({net}) AS harga_net "
        "FROM t_pembelian_detail d "
        "INNER JOIN t_pembelian h ON d.no_transaksi = h.no_transaksi "
        "WHERE COALESCE(d.harga_beli, 0) > 0 "
        "ORDER BY h.tanggal"
    )
    kumpul: dict = {}
    for r in _dictify(cur):
        kumpul.setdefault((_k(r["kd_barang"]), _k(r["kd_satuan"])), []).append(
            (r["tanggal"], _f(r["harga_net"]), (r["no_transaksi"] or "").strip())
        )
    return {k: ([x[0] for x in v], [x[1] for x in v], [x[2] for x in v])
            for k, v in kumpul.items()}


def _usulan(riwayat, key, tanggal):
    """Aturan pemenang: pembelian gudang terakhir bertanggal <= tanggal nota.

    Fallback ke pembelian pertama sesudahnya bila nota toko mendahului semua
    pembelian gudang — terjadi saat riwayat gudang lebih pendek dari riwayat
    toko. Mengembalikan (harga, no_transaksi, tanggal) atau (None, "", None).
    """
    v = riwayat.get(key)
    if not v:
        return None, "", None
    i = bisect.bisect_right(v[0], tanggal)
    j = i - 1 if i > 0 else 0
    return v[1][j], v[2][j], v[0][j]


# --- audit -----------------------------------------------------------------

def audit_harga_beli(profile, date_from=None, date_to=None) -> dict:
    """Baris pembelian toko yang harga belinya masih harga jual gudang / nol.

    Hanya baris bermasalah yang dikembalikan — halaman ini gunanya menampilkan
    daftar kerja, bukan seluruh 150rb baris pembelian.
    """
    gudang = mssql.get_cost_source(profile)
    if gudang is None:
        return {
            "rows": [], "gudang": None, "boleh_tulis": False, "terpotong": False,
            "ringkas": {"harga_jual": 0, "nol": 0},
            "conn_error": None,
            "perlu_cost_source": True,
        }

    with mssql.report_cursor(gudang) as gcur:
        jual = _cached(gudang, "audit_harga_jual_gudang", lambda: _harga_jual_gudang(gcur))
        riwayat = _cached(gudang, "audit_riwayat_beli_gudang", lambda: _riwayat_beli_gudang(gcur))

    where, params = ["1=1"], []
    if date_from:
        where.append("h.tanggal >= ?")
        params.append(date_from)
    if date_to:
        where.append("h.tanggal < DATEADD(day, 1, ?)")
        params.append(date_to)

    with mssql.report_cursor(profile) as tcur:
        tcur.execute(
            "SELECT h.no_transaksi, h.tanggal, d.kd_barang, d.kd_satuan, d.jenis, "
            "       d.qty, d.harga_beli, COALESCE(b.nama, '') AS barang "
            "FROM t_pembelian_detail d "
            "INNER JOIN t_pembelian h ON d.no_transaksi = h.no_transaksi "
            "LEFT JOIN m_barang b ON d.kd_barang = b.kd_barang "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY h.tanggal DESC",
            params,
        )
        baris = _dictify(tcur)

    rows, n_jual, n_nol = [], 0, 0
    # Baris terdeteksi bermasalah tapi tak bisa ditindak. Dihitung, bukan dibuang
    # diam-diam: `tanpa_pembanding` sebagian besar baris berharga nol yang barangnya
    # tak pernah dibeli gudang — data rusak yang tetap perlu diketahui walau
    # halaman ini tak bisa mengusulkan penggantinya.
    n_tanpa_pembanding = n_sudah_sama = 0
    for r in baris:
        key = (_k(r["kd_barang"]), _k(r["kd_satuan"]))
        hb = _f(r["harga_beli"])
        tgl = r["tanggal"]

        if hb == 0:
            status = "nol"
        elif any(abs(hb - hrg) < TOLERANSI and (mulai is None or mulai <= tgl)
                 for mulai, hrg in jual.get(key, ())):
            status = "harga_jual"
        else:
            continue  # sudah benar / sudah dikoreksi admin — bukan urusan halaman ini

        usul, nota_gudang, tgl_gudang = _usulan(riwayat, key, tgl)
        if usul is None:
            n_tanpa_pembanding += 1
            continue
        if abs(usul - hb) < TOLERANSI:
            # Nilainya kebetulan sama dengan harga jual gudang yang pernah berlaku,
            # tapi usulannya sama dengan yang sudah tercatat — tak ada yang perlu
            # diubah. Ini penyaring positif-palsu terpenting: 857 dari 1238 baris
            # terdeteksi ternyata sudah benar.
            n_sudah_sama += 1
            continue

        n_jual += status == "harga_jual"
        n_nol += status == "nol"
        rows.append({
            "no_transaksi": (r["no_transaksi"] or "").strip(),
            "tanggal": tgl.strftime("%Y-%m-%d") if hasattr(tgl, "strftime") else str(tgl),
            "kd_barang": (r["kd_barang"] or "").strip(),
            "barang": (r["barang"] or "").strip(),
            "kd_satuan": (r["kd_satuan"] or "").strip(),
            "jenis": (str(r["jenis"]) or "").strip(),
            "qty": _f(r["qty"]),
            "harga_tercatat": round(hb, 2),
            "harga_usulan": round(usul, 2),
            "selisih": round(usul - hb, 2),
            "dasar_nota": nota_gudang,
            "dasar_tanggal": tgl_gudang.strftime("%Y-%m-%d") if hasattr(tgl_gudang, "strftime") else "",
            "status": status,
        })

    terpotong = len(rows) > MAX_ROWS
    return {
        "rows": rows[:MAX_ROWS],
        "gudang": gudang.name,
        "boleh_tulis": boleh_tulis(profile),
        "terpotong": terpotong,
        "ringkas": {
            "harga_jual": n_jual,
            "nol": n_nol,
            "tanpa_pembanding": n_tanpa_pembanding,
            "sudah_sama": n_sudah_sama,
        },
        "conn_error": None,
        "perlu_cost_source": False,
    }


# --- terapkan --------------------------------------------------------------

def terapkan_koreksi(profile, items) -> tuple[int, list]:
    """Tulis harga usulan ke t_pembelian_detail toko. Return (jumlah, rincian).

    `rincian` memuat nilai sebelum & sesudah tiap baris supaya pemanggil bisa
    mencatatnya ke ActivityLog — itu satu-satunya jalan pulang kalau ada yang
    keliru, karena tabel legacy ini tak punya riwayat sendiri.
    """
    if not boleh_tulis(profile):
        raise PermissionError(
            f"Menulis ke {profile.name} ({profile.host}/{profile.db_name}) ditolak. "
            f"Koreksi harga beli hanya boleh ditulis ke database uji."
        )
    if not items:
        return 0, []

    rincian, n = [], 0
    with mssql.cursor(profile, autocommit=False) as cur:
        for it in items:
            no = (it.get("no_transaksi") or "").strip()
            kb = (it.get("kd_barang") or "").strip()
            ks = (it.get("kd_satuan") or "").strip()
            jenis = (it.get("jenis") or "").strip()
            try:
                baru = float(it.get("harga_usulan"))
            except (TypeError, ValueError):
                continue
            if not (no and kb and baru > 0):
                continue

            # Baca nilai lama DI DALAM transaksi yang sama: kalau dibaca dari
            # payload halaman, ia bisa sudah basi dan catatan auditnya berbohong.
            cur.execute(
                "SELECT harga_beli FROM t_pembelian_detail "
                "WHERE no_transaksi = ? AND kd_barang = ? AND kd_satuan = ? AND jenis = ?",
                [no, kb, ks, jenis],
            )
            row = cur.fetchone()
            if row is None:
                continue
            lama = _f(row[0])

            cur.execute(
                "UPDATE t_pembelian_detail SET harga_beli = ? "
                "WHERE no_transaksi = ? AND kd_barang = ? AND kd_satuan = ? AND jenis = ?",
                [baru, no, kb, ks, jenis],
            )
            n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            rincian.append({
                "label": kb, "kode": no,
                "changes": [{"field": "harga_beli", "before": lama, "after": round(baru, 2)}],
            })
        cur.connection.commit()
    return n, rincian

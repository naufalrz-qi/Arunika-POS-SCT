"""Edit nota penjualan yang sudah tersimpan — dengan cara yang SAMA seperti POS lama.

Legacy mengedit nota begini: UPDATE kepala `t_penjualan`, lalu hapus SEMUA baris
`t_penjualan_detail` milik nota itu dan insert ulang isi yang baru (terbaca dari
`tbl_log_transaksi`, lihat `riwayat_log`). Modul ini meniru urutan itu persis,
bukan menciptakan cara sendiri, karena tiga pembaca lain sudah memahaminya:

- sink pusat menerima `delete_temp_*` + `insert_temp_*` dari trigger, sama
  seperti edit dari aplikasi lama;
- `riwayat_log.riwayat()` memutar ulang log detail dengan asumsi baris barang
  tercatat SESUDAH baris kepala peristiwa yang sama — jadi kepala di-UPDATE
  lebih dulu;
- Nota Tanggal Mundur mengenali "diedit" dari baris `t_penjualan__update`.

**Ini satu-satunya DELETE yang Arunika kirim ke server toko** di luar tabel
snapshot miliknya sendiri, dan itu keputusan sadar (context.md § Edit Nota):
`t_penjualan_detail` tabel DAUN — tak ada FK yang menunjuk ke sana, jadi tak ada
cascade — dan cakupannya dikunci ke satu nomor nota, dalam satu transaksi,
sesudah isi lamanya direkam utuh di jejak audit. Kepala nota TIDAK PERNAH
dihapus: `t_penjualan` merambat ke `_total`, `t_piutang_cicilan`, dan
`t_tagihan_detail`. Karena itu "batal nota" belum ada.

Yang TIDAK bisa diubah, dan alasannya:

- `tanggal` — nomor nota menyimpan YYMMDD tanggal pembuatannya, dan legacy
  yang memindah tanggal ikut MENOMORI ULANG notanya (lihat `riwayat_log`).
  Justru itu yang dibongkar layar Nota Tanggal Mundur.
- `kd_divisi` — menentukan awalan nomor dan milik cabang mana nota tercatat.
- `status` — di legacy kolom ini mencampur cara bayar dan pelunasan (0 Kredit,
  1 Tunai, 2 Lunas); jalur buat nota Arunika selalu menulis 1, dan mengubahnya
  di sini berarti menebak arti yang tak pernah dipakai layar mana pun.
- `diskon1..4` kepala — tak ada di layar nota Arunika; dibawa apa adanya dan
  tetap ikut dihitung di total.

Stok tidak disentuh: trigger database dan mesin stok (yang membaca detail
langsung) mengurusnya, sama seperti saat nota dibuat.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

import pyodbc

from apps.inventory.services import _closing_date, _k, _snapshot_meta, SNAPSHOT_BASE_TABLE
from apps.transactions import penjualan as pj
from apps.transactions.hub_sync import bind_varchar
from core import mssql

# Kolom kepala yang boleh diubah. Nama kolom legacy apa adanya — dipakai juga
# sebagai kunci snapshot audit, jadi auditor membaca nama yang sama dengan yang
# ada di database.
KEPALA_UBAH = (
    "kd_customer", "kd_jenis", "kd_kas", "kd_voucher", "no_bukti", "keterangan",
    "tanggal_jatuh_tempo", "diskon_uang", "pajak",
)
_KEPALA = (
    "no_transaksi", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas", "kd_voucher",
    "no_bukti", "tanggal", "tanggal_jatuh_tempo", "status", "diskon1", "diskon2",
    "diskon3", "diskon4", "diskon_uang", "pajak", "keterangan", "kd_user",
    "tanggal_server",
)
_BARIS = (
    "kd_barang", "kd_satuan", "kd_pegawai", "jenis", "diskon1", "diskon2",
    "diskon3", "diskon4", "harga_jual", "qty", "point1", "point2",
)
_TEKS = {"no_transaksi", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas", "kd_voucher",
         "no_bukti", "keterangan", "kd_user", "kd_barang", "kd_satuan", "kd_pegawai"}
_WAKTU = {"tanggal", "tanggal_jatuh_tempo", "tanggal_server"}

# Kode yang wajib ada di tabel masternya — dicek di APLIKASI, bukan diserahkan
# ke FK: FK-nya beda antar server dan 116 di antaranya `not_trusted`
# (context.md § Database legacy). Hanya kode yang BERUBAH yang diperiksa: data
# lama boleh melanggar, dan nota yang tak disentuh bagian itu tak boleh jadi
# tak bisa disimpan karenanya.
_MASTER = {
    "kd_customer": ("m_customer", "kd_customer", "Pelanggan"),
    "kd_jenis": ("m_jenis_bayar", "kd_jenis", "Jenis bayar"),
    "kd_kas": ("m_kas", "kd_kas", "Kas"),
    "kd_voucher": ("m_voucher", "kd_voucher", "Voucher"),
}

MIN_ALASAN = 10

# Ada index yang kolom KUNCI PERTAMA-nya `no_transaksi`? Namanya tak dipatok:
# server bisa punya index serupa buatan orang lain, dan itu sama bergunanya.
_SQL_INDEX_DETAIL = (
    "SELECT COUNT(*) FROM sys.index_columns ic "
    "JOIN sys.indexes i ON i.object_id = ic.object_id AND i.index_id = ic.index_id "
    "WHERE ic.object_id = OBJECT_ID('t_penjualan_detail') AND ic.key_ordinal = 1 "
    "AND COL_NAME(ic.object_id, ic.column_id) = 'no_transaksi'"
)


class NotaDitolak(ValueError):
    """Nota tak boleh diedit, atau isian editnya salah. Pesannya untuk manusia."""


class VersiBerubah(NotaDitolak):
    """Nota diubah orang/aplikasi lain sejak layar edit dibuka."""


def _teks(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v))


def _angka(v) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, str):
        v = v.replace(",", ".")
    return float(v)


def _waktu_iso(v) -> str:
    return v.isoformat(sep=" ", timespec="seconds") if isinstance(v, dt.datetime) else _teks(v)


def _norm_kepala(row: dict) -> dict:
    out = {}
    for k in _KEPALA:
        v = row.get(k)
        if k in _TEKS:
            out[k] = _teks(v)
        elif k in _WAKTU:
            out[k] = v
        elif k == "status":
            out[k] = int(v or 0)
        else:
            out[k] = _angka(v)
    return out


def _norm_baris(row: dict) -> dict:
    out = {}
    for k in _BARIS:
        v = row.get(k)
        if k in _TEKS:
            out[k] = _teks(v)
        elif k == "jenis":
            out[k] = int(v if v not in (None, "") else pj.JENIS_BARIS)
        else:
            out[k] = _angka(v)
    return out


def versi(kepala: dict, baris: list[dict]) -> str:
    """Sidik isi nota: berubah kalau SIAPA PUN menyimpan nota ini lagi.

    `tanggal_server` saja tidak cukup: edit legacy yang disimpan dalam detik yang
    sama tak menggesernya. Baris diurutkan di PYTHON atas seluruh tuple — urutan
    heap SQL tak dijamin, dan `ORDER BY` di bawah collation CI tak total
    (`'X'` dan `'X '` seri), jadi dua bacaan nota yang sama bisa berbeda urutan.
    """
    k = [(c, _waktu_iso(kepala[c]) if c in _WAKTU else kepala[c]) for c in _KEPALA]
    b = sorted(tuple(r[c] for c in _BARIS) for r in baris)
    teks = json.dumps([k, b], default=str, separators=(",", ":"))
    return hashlib.sha256(teks.encode()).hexdigest()[:32]


def _baca(cur, no: str, kunci: bool = False) -> tuple[dict | None, list[dict]]:
    """Kepala + baris nota apa adanya.

    `kunci=True` di dalam transaksi edit mengunci BARIS KEPALA saja (PK, satu
    baris). Itu cukup untuk menyerialkan edit: aplikasi lama pun meng-UPDATE
    kepala lebih dulu, jadi ia menunggu kunci ini dan kita menunggu miliknya.
    Petunjuk kunci di `t_penjualan_detail` sengaja TIDAK dipasang — HOLDLOCK di
    sana mengunci rentang, dan di server yang belum punya index `no_transaksi`
    rentang itu seluruh tabel: setiap kasir yang menyimpan nota ikut tertahan.
    """
    hint = " WITH (UPDLOCK, HOLDLOCK)" if kunci else ""
    mssql.execute_varchar(
        cur,
        f"SELECT {', '.join(_KEPALA)} FROM t_penjualan{hint} WHERE no_transaksi = ?",
        [no])
    r = cur.fetchone()
    if not r:
        return None, []
    kepala = _norm_kepala(dict(zip(_KEPALA, r)))
    mssql.execute_varchar(
        cur,
        f"SELECT {', '.join(_BARIS)} FROM t_penjualan_detail WHERE no_transaksi = ?",
        [no])
    baris = [_norm_baris(dict(zip(_BARIS, x))) for x in cur.fetchall()]
    return kepala, baris


def _satu(cur, sql: str, params) -> object:
    mssql.execute_varchar(cur, sql, params)
    r = cur.fetchone()
    return r[0] if r else None


def penghalang(cur, kepala: dict) -> list[str]:
    """Alasan nota ini TIDAK boleh diedit. Kosong = boleh.

    Semua dikumpulkan, bukan berhenti di yang pertama: admin yang diberi tahu
    satu per satu akan mencoba, gagal, dan mencoba lagi untuk alasan kedua.
    """
    no = kepala["no_transaksi"]
    alasan = []

    # Tanpa index ber-kolom-depan `no_transaksi`, setiap `DELETE TOP (1)` di
    # bawah memindai seluruh `t_penjualan_detail` (3 juta baris di grosirPusat)
    # SAMBIL memegang kunci transaksi edit — kasir lain tertahan sepanjang itu.
    # Index-nya dibuat manual (`indexes.py`, IX_tpenjualan_detail_nota), jadi
    # di sini diperiksa, bukan diasumsikan. Pola yang sama dengan Nota Tanggal
    # Mundur, yang menunggu index log alih-alih men-scan.
    if not _satu(cur, _SQL_INDEX_DETAIL, []):
        alasan.append(
            "Server ini belum punya index nomor nota di t_penjualan_detail, jadi edit "
            "akan memindai jutaan baris sambil menahan kasir lain. Minta admin "
            "menjalankan Cek Index di Koneksi Server (di luar jam toko).")

    tutup = _closing_date(cur)
    if kepala["tanggal"] and kepala["tanggal"] <= tutup:
        alasan.append(
            f"Nota bertanggal {kepala['tanggal']:%d/%m/%Y}, tidak sesudah tutup buku "
            f"terakhir ({tutup:%d/%m/%Y}). Stok periode yang sudah ditutup berjangkar "
            f"di tanggal itu, jadi mengubah notanya membuat stok awal salah.")

    # Snapshot stok DASAR dianggap beku (inventory.services._base_date): data
    # sebelum tanggalnya diasumsikan tak pernah diedit, dan baru dihitung ulang
    # saat bulannya bergeser. Nota di wilayah itu diedit = stok salah sampai
    # sebulan.
    base = _snapshot_meta(cur, SNAPSHOT_BASE_TABLE)
    if base and kepala["tanggal"] and kepala["tanggal"] <= base:
        alasan.append(
            f"Nota bertanggal {kepala['tanggal']:%d/%m/%Y}, sebelum batas snapshot stok "
            f"dasar ({base:%d/%m/%Y}). Wilayah itu dianggap tak pernah diedit; stoknya "
            f"baru benar lagi saat snapshot dasar dibangun ulang bulan depan.")

    if _satu(cur, "SELECT COUNT(*) FROM t_piutang_cicilan WHERE no_transaksi = ?", [no]):
        alasan.append(
            "Nota ini sudah punya cicilan piutang. Mengubah totalnya membuat sisa "
            "piutang tak cocok dengan cicilan yang sudah diterima.")
    if _satu(cur, "SELECT COUNT(*) FROM t_tagihan_detail WHERE no_transaksi = ?", [no]):
        alasan.append(
            "Nota ini sudah masuk tagihan. Mengubah totalnya membuat tagihan yang "
            "sudah dikirim ke pelanggan tak cocok lagi.")

    # Salinan sinkronisasi (nota `CT` retail di database PUSAT, dsb.): nomornya
    # bukan buatan server ini, dan edit di sini tertimpa/menyimpang dari aslinya.
    kepala_nota = _teks(_satu(
        cur, "SELECT kepala_nota FROM m_divisi WHERE kd_divisi = ?", [kepala["kd_divisi"]])).upper()
    if not kepala_nota or not no.upper().startswith(kepala_nota):
        alasan.append(
            f"Nomor {no} bukan buatan divisi {kepala['kd_divisi']} di server ini "
            f"(kode notanya {kepala_nota or 'tidak ada'}) — kemungkinan salinan "
            f"sinkronisasi dari server lain. Edit di server asalnya.")
    return alasan


def _nama(cur, sql: str, kode: list[str]) -> dict:
    """{kode ternormalisasi: nama} untuk daftar kode — satu query, IN homogen."""
    kode = sorted({k for k in kode if k})
    if not kode:
        return {}
    bind_varchar(cur, len(kode), max(len(k) for k in kode))
    try:
        cur.execute(sql.format(tanya=", ".join("?" for _ in kode)), kode)  # nosec B608
        return {_k(r[0]): _teks(r[1]) for r in cur.fetchall()}
    finally:
        cur.setinputsizes(None)


def _lengkapi_nama(cur, kepala: dict, baris: list[dict]) -> None:
    """Nama untuk layar dan jejak audit — kode legacy tak berarti bagi auditor."""
    barang = _nama(cur, "SELECT kd_barang, nama FROM m_barang WHERE kd_barang IN ({tanya})",
                   [b["kd_barang"] for b in baris])
    satuan = _nama(cur, "SELECT kd_satuan, nama FROM m_satuan WHERE kd_satuan IN ({tanya})",
                   [b["kd_satuan"] for b in baris])
    pegawai = _nama(cur, "SELECT kd_pegawai, nama FROM m_pegawai WHERE kd_pegawai IN ({tanya})",
                    [b["kd_pegawai"] for b in baris])
    for b in baris:
        b["nama"] = barang.get(_k(b["kd_barang"]), "")
        b["satuan"] = satuan.get(_k(b["kd_satuan"]), "")
        b["pegawai"] = pegawai.get(_k(b["kd_pegawai"]), "")
    kepala["customer_nama"] = _teks(_satu(
        cur, "SELECT nama FROM m_customer WHERE kd_customer = ?", [kepala["kd_customer"]]))
    kepala["user_nama"] = _teks(_satu(
        cur, "SELECT nama FROM m_userx WHERE kd_user = ?", [kepala["kd_user"]]))


def total(kepala: dict, baris: list[dict]) -> float:
    """Nilai nota — `pj.total_nota`, rumus yang sama dengan saat nota dibuat.
    Rumus kedua akan menyimpang diam-diam pada nota berdiskon kepala."""
    dh = [kepala[f"diskon{i}"] for i in (1, 2, 3, 4)]
    return pj.total_nota(baris, dh, kepala["diskon_uang"], kepala["pajak"])


def baca_untuk_edit(profile, no: str) -> dict | None:
    """Isi nota untuk layar edit: kepala, baris, total, `versi`, `penghalang`."""
    no = (no or "").strip()
    if not no:
        return None
    with mssql.cursor(profile) as cur:
        kepala, baris = _baca(cur, no)
        if kepala is None:
            return None
        tersimpan = _satu(cur, "SELECT total FROM t_penjualan_total WHERE no_transaksi = ?", [no])
        halangan = penghalang(cur, kepala)
        v = versi(kepala, baris)
        _lengkapi_nama(cur, kepala, baris)
    return {
        "kepala": _untuk_json(kepala),
        "baris": baris,
        "total": total(kepala, baris),
        "total_tersimpan": None if tersimpan is None else float(tersimpan),
        "versi": v,
        "penghalang": halangan,
    }


def _untuk_json(kepala: dict) -> dict:
    return {k: (_waktu_iso(v) if k in _WAKTU else v) for k, v in kepala.items()}


# --- Menerapkan perubahan ---------------------------------------------------

def _kepala_baru(lama: dict, perubahan: dict) -> dict:
    baru = dict(lama)
    for k in KEPALA_UBAH:
        if k not in perubahan:
            continue
        v = perubahan[k]
        if k == "tanggal_jatuh_tempo":
            baru[k] = _jatuh_tempo(v, lama[k])
        elif k in ("diskon_uang", "pajak"):
            baru[k] = _angka(v)
        else:
            baru[k] = _teks(v) or (pj.KOSONG if k in ("no_bukti", "keterangan") else "")
    return baru


def _jatuh_tempo(v, lama):
    """Tanggal dari layar (`YYYY-MM-DD`, tanpa jam) → datetime kolom.

    Tanggal yang SAMA dengan yang tersimpan mempertahankan jam lamanya: legacy
    menyimpan jam di kolom ini, layar tidak menampilkannya, dan tanpa ini setiap
    edit akan tercatat "mengubah jatuh tempo" dari 10.33 ke 00.00 padahal tak ada
    yang menyentuhnya.
    """
    if isinstance(v, dt.datetime):
        return v
    s = _teks(v)
    if not s:
        return lama
    try:
        baru = dt.datetime.fromisoformat(s.replace("T", " ").rstrip("Z"))
    except ValueError:
        raise NotaDitolak(f"Tanggal jatuh tempo tidak terbaca: {s}.") from None
    if lama and len(s) <= 10 and baru.date() == lama.date():
        return lama
    return baru


def _baris_baru(lama: list[dict], masuk: list[dict], pegawai_bawaan: str) -> list[dict]:
    """Baris dari layar → baris siap tulis.

    `jenis`/`point1`/`point2` tak ada di layar; nilainya DIBAWA dari baris lama
    yang barang+satuannya sama (dipakai berurutan kalau ada duplikat), dan baris
    yang benar-benar baru memakai nilai jalur buat nota.
    """
    sisa: dict[tuple, list[dict]] = {}
    for b in lama:
        sisa.setdefault((_k(b["kd_barang"]), _k(b["kd_satuan"])), []).append(b)
    out = []
    for i, it in enumerate(masuk, 1):
        kd_barang, kd_satuan = _teks(it.get("kd_barang")), _teks(it.get("kd_satuan"))
        if not kd_barang or not kd_satuan:
            raise NotaDitolak(f"Baris {i}: barang dan satuan wajib diisi.")
        try:
            qty, harga = _angka(it.get("qty")), _angka(it.get("harga_jual"))
            diskon = [_angka(it.get(f"diskon{j}")) for j in (1, 2, 3, 4)]
        except (TypeError, ValueError):
            raise NotaDitolak(f"Baris {i} ({kd_barang}): angka tidak terbaca.") from None
        if qty <= 0:
            raise NotaDitolak(f"Baris {i} ({kd_barang}): qty harus lebih dari nol.")
        if harga < 0 or any(d < 0 for d in diskon):
            raise NotaDitolak(f"Baris {i} ({kd_barang}): harga dan diskon tak boleh negatif.")
        antre = sisa.get((_k(kd_barang), _k(kd_satuan)))
        asal = antre.pop(0) if antre else None
        kd_pegawai = _teks(it.get("kd_pegawai")) or (asal or {}).get("kd_pegawai") or pegawai_bawaan
        if not kd_pegawai:
            raise NotaDitolak(f"Baris {i} ({kd_barang}): pegawai wajib diisi.")
        out.append({
            "kd_barang": kd_barang, "kd_satuan": kd_satuan, "kd_pegawai": kd_pegawai,
            "jenis": asal["jenis"] if asal else pj.JENIS_BARIS,
            "diskon1": diskon[0], "diskon2": diskon[1], "diskon3": diskon[2], "diskon4": diskon[3],
            "harga_jual": harga, "qty": qty,
            "point1": asal["point1"] if asal else 0.0, "point2": asal["point2"] if asal else 0.0,
        })
    if not out:
        raise NotaDitolak(
            "Nota tak boleh dikosongkan. Menghapus seluruh barang sama dengan membatalkan "
            "nota, dan pembatalan belum tersedia.")
    return out


def _periksa_referensi(cur, lama_k: dict, baru_k: dict, lama_b: list[dict], baru_b: list[dict]) -> None:
    for kol, (tabel, pk, label) in _MASTER.items():
        if _k(baru_k[kol]) == _k(lama_k[kol]):
            continue
        if not baru_k[kol] or not _satu(cur, f"SELECT COUNT(*) FROM {tabel} WHERE {pk} = ?",  # nosec B608
                                        [baru_k[kol]]):
            raise NotaDitolak(f"{label} {baru_k[kol] or '(kosong)'} tidak ada di server ini.")

    pasangan_lama = {(_k(b["kd_barang"]), _k(b["kd_satuan"])) for b in lama_b}
    perlu = [b for b in baru_b if (_k(b["kd_barang"]), _k(b["kd_satuan"])) not in pasangan_lama]
    if perlu:
        kode = sorted({b["kd_barang"] for b in perlu})
        bind_varchar(cur, len(kode), max(len(k) for k in kode))
        try:
            cur.execute(  # nosec B608 — hanya placeholder yang diinterpolasi
                "SELECT kd_barang, kd_satuan FROM m_barang_satuan "
                f"WHERE kd_barang IN ({', '.join('?' for _ in kode)})", kode)
            ada = {(_k(r[0]), _k(r[1])) for r in cur.fetchall()}
        finally:
            cur.setinputsizes(None)
        for b in perlu:
            if (_k(b["kd_barang"]), _k(b["kd_satuan"])) not in ada:
                raise NotaDitolak(
                    f"Barang {b['kd_barang']} tidak punya satuan {b['kd_satuan']} di server ini.")

    pegawai_lama = {_k(b["kd_pegawai"]) for b in lama_b}
    pegawai_baru = sorted({b["kd_pegawai"] for b in baru_b if _k(b["kd_pegawai"]) not in pegawai_lama})
    if pegawai_baru:
        ada = _nama(cur, "SELECT kd_pegawai, nama FROM m_pegawai WHERE kd_pegawai IN ({tanya})",
                    pegawai_baru)
        hilang = [p for p in pegawai_baru if _k(p) not in ada]
        if hilang:
            raise NotaDitolak(f"Pegawai {', '.join(hilang)} tidak ada di server ini.")


_NILAI_BARIS = ("qty", "harga_jual", "diskon1", "diskon2", "diskon3", "diskon4")


def selisih(lama_k: dict, baru_k: dict, lama_b: list[dict], baru_b: list[dict]) -> dict:
    """Apa yang berubah, dalam bentuk yang dibaca auditor.

    Barang dipasangkan per (barang, satuan, pegawai) dan urutan kemunculannya,
    sehingga dua baris kembar tak saling menutupi.
    """
    def nilai(d, k):
        return _waktu_iso(d[k]) if k in _WAKTU else d[k]

    kepala = [{"kolom": k, "dari": nilai(lama_k, k), "ke": nilai(baru_k, k)}
              for k in KEPALA_UBAH if nilai(lama_k, k) != nilai(baru_k, k)]

    def kunci(daftar):
        hitung, out = {}, {}
        for b in daftar:
            dasar = (_k(b["kd_barang"]), _k(b["kd_satuan"]), _k(b["kd_pegawai"]))
            hitung[dasar] = hitung.get(dasar, 0) + 1
            out[dasar + (hitung[dasar],)] = b
        return out

    def ringkas(r):
        out = {c: r[c] for c in ("kd_barang", "kd_satuan", "kd_pegawai") + _NILAI_BARIS}
        if r.get("nama"):
            out["nama"] = r["nama"]
        return out

    a, b = kunci(lama_b), kunci(baru_b)
    diubah = []
    for k in [k for k in a if k in b]:
        x, y = a[k], b[k]
        beda = {c: {"dari": x[c], "ke": y[c]} for c in _NILAI_BARIS if x[c] != y[c]}
        if beda:
            diubah.append(ringkas(y) | {"beda": beda})
    return {
        "kepala": kepala,
        "barang": {
            "ditambah": [ringkas(b[k]) for k in b if k not in a],
            "dihapus": [ringkas(a[k]) for k in a if k not in b],
            "diubah": diubah,
        },
    }


def ada_perubahan(s: dict) -> bool:
    return bool(s["kepala"] or any(s["barang"].values()))


def _max_log(cur):
    """Id log legacy terakhir — penanda rentang baris log milik edit ini, supaya
    Jejak Audit tak menampilkan satu edit dua kali (sekali dari audit Arunika,
    sekali dari log trigger). Server tanpa tabel log: tak ada rentang."""
    try:
        cur.execute("SELECT MAX(id) FROM tbl_log_transaksi")
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    except pyodbc.Error:
        return None


def ubah_nota(profile, no: str, *, kd_user: str, kd_pegawai_bawaan: str = "",
              perubahan: dict, items: list[dict], versi_layar: str) -> dict:
    """Terapkan edit dalam SATU transaksi, urutan persis legacy.

    Mengembalikan data audit: `sebelum`, `sesudah`, `selisih`, `log_id`, dll.
    Semua penolakan berupa `NotaDitolak` (pesan untuk manusia) dan terjadi
    SEBELUM satu baris pun ditulis.
    """
    no = (no or "").strip()
    if not kd_user:
        raise NotaDitolak(
            "Akun Anda belum ditautkan ke user legacy untuk koneksi ini, jadi edit tak "
            "bisa dicatat atas nama Anda. Minta pengelola aplikasi mengisinya di Kelola "
            "Tautan User.")

    with mssql.cursor(profile, autocommit=False) as cur:
        lama_k, lama_b = _baca(cur, no, kunci=True)
        if lama_k is None:
            raise NotaDitolak(f"Nota {no} tidak ada di server ini.")
        if versi(lama_k, lama_b) != versi_layar:
            raise VersiBerubah(
                f"Nota {no} sudah diubah sejak Anda membukanya (oleh Arunika atau aplikasi "
                f"lama). Muat ulang notanya, periksa isinya, lalu ulangi edit Anda.")
        halangan = penghalang(cur, lama_k)
        if halangan:
            raise NotaDitolak(" ".join(halangan))

        baru_k = _kepala_baru(lama_k, perubahan)
        pegawai_bawaan = kd_pegawai_bawaan or (lama_b[0]["kd_pegawai"] if lama_b else "")
        baru_b = _baris_baru(lama_b, items, pegawai_bawaan)
        _lengkapi_nama(cur, lama_k, lama_b)
        _lengkapi_nama(cur, baru_k, baru_b)
        beda = selisih(lama_k, baru_k, lama_b, baru_b)
        if not ada_perubahan(beda):
            raise NotaDitolak("Tidak ada yang berubah — nota tidak disimpan ulang.")
        _periksa_referensi(cur, lama_k, baru_k, lama_b, baru_b)

        total_lama = _satu(cur, "SELECT total FROM t_penjualan_total WHERE no_transaksi = ?", [no])
        total_baru = total(baru_k, baru_b)
        log_dari = _max_log(cur)

        # 1. Kepala DULU — riwayat_log memasangkan baris barang ke peristiwa
        #    kepala terakhir sebelum mereka. `kd_user` = pengedit dan
        #    `tanggal_server` = sekarang: begitulah legacy menyimpan edit, dan
        #    Nota Tanggal Mundur membaca tanda itu. Pembuat asli tetap ada di
        #    log legacy dan di `sebelum` jejak audit.
        #
        #    `tanggal_setor` diisi HANYA bila masih NULL, dengan rumus aplikasi
        #    lama (tanggal nota − 1 hari, jam nota; lihat riwayat_log). Trigger
        #    `update_temp_m_t_penjualan` merangkai kolom ini ke `query` dan
        #    `formatted_data` dengan `+`, jadi SATU kolom NULL membuat seluruh
        #    payload NULL: editnya tak terkirim ke pusat dan tak terbaca di log.
        #    Terbukti di tiruan legacy dengan trigger asli dari docs/skema/.
        mssql.execute_varchar(
            cur,
            "UPDATE t_penjualan SET kd_customer = ?, kd_jenis = ?, kd_kas = ?, kd_voucher = ?, "
            "no_bukti = ?, keterangan = ?, tanggal_jatuh_tempo = ?, diskon_uang = ?, pajak = ?, "
            "kd_user = ?, tanggal_server = GETDATE(), "
            "tanggal_setor = COALESCE(tanggal_setor, DATEADD(day, -1, tanggal)) "
            "WHERE no_transaksi = ?",
            [baru_k["kd_customer"], baru_k["kd_jenis"], baru_k["kd_kas"], baru_k["kd_voucher"],
             baru_k["no_bukti"] or pj.KOSONG, baru_k["keterangan"] or pj.KOSONG,
             baru_k["tanggal_jatuh_tempo"], baru_k["diskon_uang"], baru_k["pajak"],
             kd_user, no])
        # Dibaca balik, bukan dikarang dari jam aplikasi: jejak audit harus
        # memuat cap yang benar-benar tersimpan (jam SERVER, bukan jam kita).
        baru_k["kd_user"] = kd_user
        baru_k["tanggal_server"] = _satu(
            cur, "SELECT tanggal_server FROM t_penjualan WHERE no_transaksi = ?", [no])

        # 2. Hapus baris barang lama SATU PER EXECUTE: trigger stok di tabel ini
        #    skalar (hanya memproses satu baris per statement). Diverifikasi
        #    dengan SELECT, bukan rowcount — trigger legacy membuat rowcount
        #    tak bisa dipercaya.
        for _ in lama_b:
            mssql.execute_varchar(
                cur, "DELETE TOP (1) FROM t_penjualan_detail WHERE no_transaksi = ?", [no])
        if _satu(cur, "SELECT COUNT(*) FROM t_penjualan_detail WHERE no_transaksi = ?", [no]):
            raise NotaDitolak(
                f"Baris barang nota {no} bertambah saat sedang diedit. Tidak ada yang "
                f"disimpan; muat ulang lalu ulangi.")

        # 3. Insert ulang, satu per execute, kolom yang sama dengan jalur buat nota.
        tanya = ", ".join("?" for _ in pj._DETAIL)
        for b in baru_b:
            cur.execute(
                f"INSERT INTO t_penjualan_detail ({', '.join(pj._DETAIL)}) VALUES ({tanya})",
                [no, b["kd_barang"], b["kd_satuan"], b["kd_pegawai"], b["jenis"],
                 b["diskon1"], b["diskon2"], b["diskon3"], b["diskon4"],
                 b["harga_jual"], b["qty"], b["point1"], b["point2"]])

        # 4. Total. Nota lama tanpa baris total (45% di grosirPusat) DIBUATKAN
        #    satu, seperti setiap nota yang ditulis Arunika.
        if total_lama is None:
            cur.execute("INSERT INTO t_penjualan_total (no_transaksi, total) VALUES (?, ?)",
                        [no, total_baru])
        else:
            mssql.execute_varchar(
                cur, "UPDATE t_penjualan_total SET total = ? WHERE no_transaksi = ?",
                [total_baru, no])

        cur.connection.commit()
        log_sampai = _max_log(cur)
        cur.connection.commit()

    return {
        "no_transaksi": no,
        "skema": "legacy",
        "sebelum": {"kepala": _untuk_json(lama_k), "baris": lama_b,
                    "total": None if total_lama is None else float(total_lama),
                    "total_hitung": total(lama_k, lama_b)},
        "sesudah": {"kepala": _untuk_json(baru_k), "baris": baru_b, "total": total_baru},
        "selisih": beda,
        "total_dibuat": total_lama is None,
        "log_id": [log_dari, log_sampai] if log_dari is not None else None,
        "baris": len(baru_b),
    }

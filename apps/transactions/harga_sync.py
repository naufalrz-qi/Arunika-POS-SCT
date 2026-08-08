r"""Harga GUDANG -> toko grosir, mendekati realtime, TANPA `tbl_log_transaksi`.

`feed_sync` sudah menyebarkan `m_barang_satuan` ke toko, tapi dua hal membuatnya
tidak cukup untuk harga:

1. **Jadwalnya 30 menit.** Ia menumpang tick scheduler bersama
   (`HARGA_SNAPSHOT_INTERVAL_SECONDS`, default 1800).
2. **Ia hanya melihat apa yang ditulis trigger.** Perubahan harga yang dibuat
   lewat SQL langsung, atau di cabang yang cakupan triggernya berbeda, tidak
   pernah muncul di feed dan karena itu tidak pernah menyeberang.

Modul ini tidak membaca feed sama sekali. Ia membandingkan harga apa adanya.

## Kenapa membandingkan seluruh tabel itu murah

Terukur: `SELECT kd_barang, kd_satuan, harga_jual FROM m_barang_satuan` di GUDANG
mengembalikan **55.365 baris dalam 1,90 detik**; dari ANDARIA lewat Tailscale
(783 ms) 1,78 detik. Jadi menyapu tiap 60 detik menghabiskan ~2 detik satu
koneksi — dan volume perubahannya kecil (GUDANG 1-125 harga per hari, terbaca
dari `BarangHargaChange`), sehingga hampir semua sapuan tidak menulis apa pun.

## Dua mode, dan kenapa dua

- **cepat** (tiap tick) — bandingkan GUDANG dengan salinan hasil sapuan
  SEBELUMNYA yang disimpan di memori proses. Satu pembacaan, ~1,9 detik, dan yang
  ditulis hanya SKU yang benar-benar berubah.
- **penuh** (berkala, dan WAJIB pada sapuan pertama) — bandingkan GUDANG dengan
  keadaan NYATA tiap toko. ~1,8 detik per toko.

Mode cepat sendirian tidak cukup, dan bukan karena teori: salinan di memori
hilang tiap kali proses restart, dan ia juga menganggap "sudah didorong" sama
dengan "sudah sampai". Satu toko yang mati saat perubahan lewat akan melewatkan
harga itu SELAMANYA, karena tick berikutnya melihat GUDANG sama dengan salinan
memori dan menyimpulkan tidak ada yang perlu dikerjakan. Mode penuh yang
menambalnya, dan karena itu ia tidak boleh dimatikan.

Sapuan pertama sesudah restart SELALU penuh — tanpa itu, salinan memori yang
kosong akan terbaca sebagai "55.365 harga baru saja berubah".

## Yang perlu diketahui sebelum mengubah

- **Jangan pakai `master._harga_map()`.** Ia di-cache ~10 menit; poller 60 detik
  yang membaca cache 10 menit adalah poller 10 menit yang berpura-pura cepat.
  Modul ini selalu membuka kursor sendiri.
- **`bind_varchar` wajib** sebelum mengambil baris untuk daftar SKU yang berubah.
  Kolom kuncinya `varchar`/`char`; tanpa ikatan itu daftar `IN` berubah jadi satu
  scan tabel per nilai (terukur 6,23 dtk untuk 50 nilai, vs 0,01 dtk sesudahnya).
- **Menulis ke toko MENYALAKAN trigger legacy di toko itu**, yang mengisi
  `tbl_tmp_post` toko dan diteruskan job legacy ke sink PHP/MySQL. Itu sudah
  terjadi dengan `feed_sync` hari ini, jadi bukan hal baru — tapi artinya jumlah
  tulisan harus sekecil mungkin, dan itulah sebabnya yang didorong hanya SKU yang
  berubah, bukan seluruh tabel.
"""
from __future__ import annotations

import logging
import os

import pyodbc

from apps.transactions.feed_sync import FEED_TABLE_SPECS, _kolom_tujuan, _terapkan_baris
from apps.transactions.hub_sync import bind_varchar
from core import mssql

log = logging.getLogger(__name__)

TABEL = "m_barang_satuan"
KUNCI = ("kd_barang", "kd_satuan")
# Sama dengan `_ambil_ulang_detail`: ruang lebar di bawah batas 2.100 parameter
# SQL Server, dan tetap satu seek per batch berkat `bind_varchar`.
BATCH_SKU = 500

# Salinan harga sumber dari sapuan sebelumnya, per profil sumber. Sengaja di
# memori proses, bukan tabel: ia hanya pintasan agar mode cepat tidak perlu
# membaca 8 toko, dan kebenarannya dijamin mode penuh. Menyimpannya ke SQLite
# akan membuat 55.365 baris ditulis ulang tiap menit demi data yang boleh hilang.
_terakhir: dict[int, dict] = {}


def _norm(v):
    """Samakan dengan cara SQL Server membandingkan: abaikan spasi ekor dan
    huruf besar-kecil. Tanpa ini, 'LYG005 ' dan 'lyg005' terbaca dua SKU berbeda
    dan harganya didorong ulang tiap sapuan, selamanya."""
    return v.strip().upper() if isinstance(v, str) else v


def baca_harga(profile) -> dict:
    """`{(kd_barang, kd_satuan): harga_jual}` untuk satu server, dibaca SEGAR.

    Bukan lewat `master._harga_map()` — itu di-cache ~10 menit dan akan membuat
    poller ini melaporkan harga basi sebagai "tidak berubah".
    """
    with mssql.cursor(profile) as cur:
        cur.execute(f"SELECT kd_barang, kd_satuan, harga_jual FROM [{TABEL}]")
        return {(_norm(r[0]), _norm(r[1])): r[2] for r in cur.fetchall()}


def _ambil_baris(src_cur, kunci: list[tuple], kolom: list[str]) -> list[dict]:
    """Baris `m_barang_satuan` lengkap untuk SKU yang berubah.

    Disaring per `kd_barang` saja (bukan pasangan `(kd_barang, kd_satuan)`):
    daftar `IN` berpasangan butuh `OR` bertumpuk yang mematikan seek, sementara
    satu barang paling banyak punya beberapa satuan — kelebihan barisnya
    sedikit, dan yang didorong tetap disaring di pemanggil.
    """
    barang = sorted({k[0] for k in kunci})
    keluar = []
    for i in range(0, len(barang), BATCH_SKU):
        potong = barang[i:i + BATCH_SKU]
        bind_varchar(src_cur, len(potong))
        try:
            src_cur.execute(
                f"SELECT {', '.join(f'[{k}]' for k in kolom)} FROM [{TABEL}] "
                f"WHERE kd_barang IN ({', '.join('?' * len(potong))})",
                potong,
            )
            keluar += [dict(zip(kolom, r)) for r in src_cur.fetchall()]
        finally:
            src_cur.setinputsizes(None)
    return keluar


def dorong(source, targets, kunci: set, harga_src: dict | None = None) -> dict:
    """Dorong SKU `kunci` dari `source` ke tiap toko. Best-effort per toko.

    Satu toko mati tidak menahan yang lain — pola yang sama dipakai `feed_sync`
    dan `hub_pull`. Toko yang gagal akan tertangkap sapuan penuh berikutnya,
    yang justru alasan sapuan penuh ada.
    """
    hasil = {"sku": len(kunci), "per_toko": {}, "gagal": {}}
    if not kunci:
        return hasil

    spec = FEED_TABLE_SPECS[TABEL]
    try:
        with mssql.cursor(source) as src_cur:
            kolom_src = _kolom_tujuan(src_cur, TABEL)
            baris = _ambil_baris(src_cur, sorted(kunci), kolom_src)
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["gagal"][source.name] = str(exc.args[-1] if exc.args else exc)[:255]
        return hasil

    # Saring balik ke SKU yang memang diminta: `_ambil_baris` menyaring per
    # kd_barang, jadi ia ikut membawa satuan lain dari barang yang sama.
    pilih = [b for b in baris if (_norm(b["kd_barang"]), _norm(b["kd_satuan"])) in kunci]

    for t in targets:
        try:
            with mssql.cursor(t, autocommit=False) as cur:
                kolom = _kolom_tujuan(cur, TABEL)
                for b in pilih:
                    _terapkan_baris(
                        cur, TABEL, spec,
                        {k: b[k] for k in KUNCI},
                        {k: v for k, v in b.items() if k not in KUNCI},
                        kolom,
                    )
                cur.connection.commit()
            hasil["per_toko"][t.name] = len(pilih)
        except (pyodbc.Error, RuntimeError) as exc:
            hasil["gagal"][t.name] = str(exc.args[-1] if exc.args else exc)[:255]
    return hasil


def sapu(source, targets, penuh: bool = False, dry_run: bool = False) -> dict:
    """Satu sapuan harga. `penuh=True` membandingkan dengan keadaan nyata toko.

    Mode cepat membandingkan GUDANG dengan salinan sapuan sebelumnya di memori;
    mode penuh membaca tiap toko. Sapuan pertama (salinan belum ada) DIPAKSA
    penuh: salinan kosong akan terbaca sebagai "semua harga baru saja berubah"
    dan mendorong 55.365 baris ke delapan toko sekaligus.
    """
    hasil = {"mode": "penuh" if penuh else "cepat", "sku": 0, "per_toko": {},
             "gagal": {}, "error": ""}
    try:
        harga_src = baca_harga(source)
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["error"] = str(exc.args[-1] if exc.args else exc)[:255]
        return hasil

    sebelum = _terakhir.get(source.pk)
    if penuh or sebelum is None:
        hasil["mode"] = "penuh"
        beda: set = set()
        for t in targets:
            try:
                harga_t = baca_harga(t)
            except (pyodbc.Error, RuntimeError) as exc:
                hasil["gagal"][t.name] = str(exc.args[-1] if exc.args else exc)[:255]
                continue
            beda |= {k for k, v in harga_src.items() if harga_t.get(k) != v}
    else:
        beda = {k for k, v in harga_src.items() if sebelum.get(k) != v}

    hasil["sku"] = len(beda)
    hasil["contoh"] = sorted(beda)[:10]
    if dry_run:
        # Salinan TIDAK disegarkan: dry run yang diam-diam menandai perubahan
        # sebagai "sudah beres" akan membuat sapuan sungguhan berikutnya
        # melewatinya. Pratinjau tidak boleh mengubah keadaan apa pun.
        hasil["mode"] += "/dry_run"
        return hasil

    if beda:
        d = dorong(source, targets, beda)
        hasil["per_toko"] = d["per_toko"]
        hasil["gagal"].update(d["gagal"])

    # Salinan diperbarui walau ada toko yang gagal: mode cepat memang tidak
    # menjamin sampai, dan sapuan penuh berikutnya yang menambal. Menahan
    # salinan supaya "coba lagi" justru membuat tiap tick mendorong ulang SKU
    # yang sama ke tujuh toko sehat, dan tiap dorongan itu menyalakan trigger
    # legacy di sana.
    _terakhir[source.pk] = harga_src
    return hasil


def dorong_perubahan(source, targets, changes: list[dict]) -> dict:
    """Dorong SEKETIKA hasil `master.update_harga` — dipanggil dari jalur tulis.

    `changes` sudah berisi HANYA satuan yang nilainya benar-benar berubah, jadi
    tidak ada penyaringan tambahan di sini. Bentuknya
    `[{kd_barang, kd_satuan, harga_lama, harga_baru}, ...]`.

    Pemanggil harus memperlakukan ini best-effort: harga sudah tersimpan di
    server sumber sebelum fungsi ini dipanggil, jadi kegagalan mendorong tidak
    boleh menggagalkan penyimpanan. Sapuan berkala menambalnya dalam hitungan
    menit.
    """
    kunci = {
        (_norm(c["kd_barang"]), _norm(c["kd_satuan"]))
        for c in changes
        if c.get("kd_barang") and c.get("kd_satuan")
    }
    hasil = dorong(source, targets, kunci)
    # Salinan memori ikut disegarkan supaya sapuan cepat berikutnya tidak
    # melihat perubahan ini sebagai baru dan mendorongnya untuk kedua kali.
    salinan = _terakhir.get(source.pk)
    if salinan is not None:
        for c in changes:
            k = (_norm(c.get("kd_barang")), _norm(c.get("kd_satuan")))
            if k in kunci:
                salinan[k] = c.get("harga_baru")
    return hasil


def profil_fanout():
    """(sumber, [toko]) menurut env — sama persis dengan yang dipakai `feed_sync`.

    Satu sumber kebenaran untuk "siapa menerima master": daftar kedua akan
    menyimpang, dan menyimpangnya berupa toko yang harganya diam-diam tak pernah
    diperbarui.
    """
    from apps.connections.models import ServerProfile

    nama_sumber = os.environ.get("FEED_SYNC_SOURCE", "GUDANG")
    source = ServerProfile.objects.filter(name=nama_sumber).first()
    if not source:
        return None, []
    csv = os.environ.get("FEED_SYNC_TARGETS", "").strip()
    qs = ServerProfile.objects.exclude(pk=source.pk)
    if csv:
        qs = qs.filter(name__in=[n.strip() for n in csv.split(",") if n.strip()])
    return source, list(qs.order_by("name"))

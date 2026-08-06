r"""AMPHOREUS diisi dengan MENARIK LANGSUNG dari tabel asli tiap cabang.

Pengganti `hub_sync.py`, yang membaca `tbl_log_transaksi`. Modul ini tidak
menyentuh `tbl_log`, `tbl_log_transaksi`, maupun `tbl_tmp_post` sama sekali —
ketiganya tetap dipantau `apps/monitoring/services_sync.py` dan itu urusan
terpisah.

## Kenapa tidak lewat feed

Tiga hal terukur di lapangan, dan ketiganya cacat bawaan pendekatan feed:

- **Lambat secara struktural.** Cursor ANDARIA ada di id 253.528 sementara ujung
  feed 1.962.612 — tertinggal 1,7 juta baris. Dengan 2.000 baris per tick, butuh
  18 sampai 100 hari untuk satu cabang saja.
- **Bisa kehilangan data permanen.** Feed bukan append-only: PUSAT kehilangan
  1.471.184 id (Mei 2024), PRAYA dipotong dari depan sampai baris tertuanya id
  2.658.002. Baris yang lenyap di depan cursor tidak bisa dipulihkan dari feed —
  feed tak bisa menceritakan apa yang sudah terhapus darinya.
- **Datanya terpotong.** Header ditulis dari `formatted_data`, dan trigger legacy
  memotong kolom: `m_barang` ber-`kd_sumber=PRAYA` di AMPHOREUS mentok 30 karakter
  padahal kolomnya `varchar(50)` dan baris GUDANG mencapai 47.

## Yang menggantikannya

Legacy tidak punya penanda perubahan — **tidak ada satu pun kolom `rowversion`
di seluruh database** (dicek lewat `sys.columns` di GUDANG dan RTL PUSAT).
Modul ini tidak membutuhkannya: ia tidak mendeteksi perubahan, ia menyalin ulang
satu rentang tanggal apa adanya. Idempoten, jadi menyalin ulang yang tak berubah
tidak berbahaya — hanya perlu murah. Yang membuatnya murah adalah membagi
rentangnya jadi tiga, dengan `g_tutup_buku` sebagai sekat:

1. **Arsip** (`tanggal <= tutup_buku`) — disalin SEKALI, lalu tidak pernah
   disentuh lagi. Tutup buku adalah lantai keras; di bawahnya data tidak berubah.
2. **Cocokkan** (tutup_buku .. H-N) — sekali sehari. Agregat per hari dibandingkan
   antara cabang dan AMPHOREUS; hanya hari yang berbeda yang disalin ulang.
3. **Segar** (N hari terakhir) — tiap tick, disalin ulang penuh tanpa dibandingkan.

Terukur, dan inilah yang membuat tingkat 2 terjangkau untuk 9 cabang: agregat
harian adalah SATU kueri yang mengembalikan satu baris per hari, bukan satu kueri
per hari. GUDANG 2.019 hari / 55.430 nota = **0,15 detik**; ANDARIA 933 hari /
109.095 nota lewat Tailscale 783 ms = **0,13 detik**.

## Empat aturan, tiap satu dibayar pengukuran

1. **Rentang memakai `tanggal` OR `tanggal_server`, bukan salah satu.** Terukur 13
   dari 927 baris GUDANG dan 13 dari 8.742 baris PUSAT punya `tanggal_server`
   beda HARI dari `tanggal` — nota bertanggal mundur yang diinput belakangan.
   Menyaring `tanggal` saja melewatkannya tanpa suara.
2. **Batas selalu dari jam server, tidak pernah dari `MAX(tanggal)`.** ANDARIA
   punya nota bertanggal **7252-01-09**. Satu typo tahun akan mendorong jendela ke
   abad ke-73 dan memecah agregat harian jadi ribuan hari kosong.
3. **Tanggal di luar akal dikecualikan, tapi DIHITUNG.** `TANGGAL_MAKS` memagari
   setiap kueri rentang, dan jumlah baris yang terpagari dilaporkan sebagai
   `anomali_tanggal`. Menyalinnya diam-diam akan meracuni tiap laporan berbasis
   tanggal di AMPHOREUS; membuangnya diam-diam menyembunyikan data entry yang salah.
   Yang benar adalah tidak menyalin DAN memberi tahu.
4. **Nota yang hilang di cabang ikut dihapus di AMPHOREUS.** Ini yang tidak pernah
   bisa dilakukan feed: feed hanya memuat `__insert`/`__update`, jadi nota yang
   dibatalkan tertinggal jadi hantu — jumlah nota benar, omzetnya salah.

## Yang TIDAK dilihat modul ini

Agregat pencocokan memakai `COUNT(*)` header plus jumlah kolom numerik header
(diskon/pajak). **Tidak ada satu pun kolom nilai di tabel header** — uangnya ada
di tabel detail. Jadi nota lama yang qty/harga DETAILNYA diubah tanpa headernya
tersentuh tidak akan terdeteksi tingkat 2.
# ponytail: agregat header saja. Kalau edit detail pada nota lama ternyata nyata,
# tambahkan agregat detail (JOIN ke header untuk tanggalnya) ke `agregat_harian`.
Jendela segar tidak terpengaruh — ia menyalin ulang tanpa membandingkan.
"""
from __future__ import annotations

import datetime as dt
import time

import pyodbc
from django.utils import timezone

from apps.core.models import HubPullState
from apps.inventory.services import _closing_date, _k
from apps.transactions.feed_sync import _kolom_tujuan
from apps.transactions.hub_schema import KOL_SUMBER
from apps.transactions.hub_sync import (
    HUB_TABLE_SPECS,
    _ambil_ulang_detail,
    _terapkan_header,
    bind_varchar,
    sumber_profiles,
)
from core import mssql

# Pagar atas untuk SETIAP kueri rentang. Bukan kehati-hatian teoretis: ANDARIA
# punya baris `t_penjualan` bertanggal 7252-01-09.
TANGGAL_MAKS = dt.datetime(2100, 1, 1)
# Lantai bawah saat cabang belum pernah tutup buku (`_closing_date` mengembalikan
# 1900-01-01), supaya rentang arsip tidak jadi tak terbatas ke belakang.
TANGGAL_MIN = dt.datetime(1900, 1, 1)
# Lantai untuk MENCARI awal data arsip. Bukan batas penyalinan — potongan pertama
# tetap menyapu dari TANGGAL_MIN. Ini hanya mencegah `MIN(tanggal)` yang berisi
# salah ketik tahun kuno mekar jadi ribuan potongan bulanan kosong.
ARSIP_LANTAI = dt.datetime(2000, 1, 1)

JENDELA_SEGAR_HARI = 7
# `IN (...)` punya batas parameter di SQL Server (2.100); 500 nota per batch
# menyisakan ruang lebar dan tetap satu range seek per batch.
BATCH_PARENT = 500
# Percobaan ulang per cabang saat gagal, dan jedanya. Bukan kehati-hatian
# teoretis: PRAYA gagal `[08001] wait operation timed out` lalu konek 0,7 detik
# kemudian tanpa ada yang berubah, dan blip sesaat itu membuang seluruh cabang.
COBA_ULANG = 2
JEDA_ULANG = 5  # detik

_KOLOM_WAKTU = ("tanggal", "tanggal_server")

# Tabel yang disapu modul ini. Diturunkan dari HUB_TABLE_SPECS, tidak ditulis
# ulang — daftar kedua adalah cara paling pasti agar AMPHOREUS dan sync berbeda isi.
_DETAIL_MILIK_HEADER = {d for s in HUB_TABLE_SPECS.values() for d in s.get("details", ())}
TABEL_HEADER = [
    t for t, s in HUB_TABLE_SPECS.items() if t.startswith("t_") and "key_columns" in s
]
# Tabel transaksi berbentuk detail yang TIDAK dimiliki header mana pun
# (`t_opname_stok`): tidak ada header yang menyeretnya, jadi ia disapu sendiri
# sebagai ganti-seluruh-rentang.
TABEL_RENTANG = [
    t for t, s in HUB_TABLE_SPECS.items()
    if t.startswith("t_") and "parent_key" in s and t not in _DETAIL_MILIK_HEADER
]


def _hasil_kosong(source) -> dict:
    return {
        "source": source.name,
        "kd_sumber": (source.kode_sumber or "").strip(),
        "status": "ok",
        "header": 0,
        "nota": 0,
        "detail": 0,
        "dihapus": 0,
        "hari_beda": 0,
        "anomali_tanggal": 0,
        "dilewati_potongan": 0,
        "tabel": {},
        "error": "",
    }


def batas_arsip(cur) -> dt.datetime:
    """Tanggal tutup buku cabang — sekat antara arsip dan yang masih hidup.

    `g_tutup_buku` berbentuk `(periode, tanggal)` dengan MAYORITAS baris bernilai
    sentinel 2001-01-01, dan periode terbesar belum tentu yang berisi tanggal
    asli (TANJUNG: periode 7325 = 2001-01-01 sementara periode 7324 = 2024-02-16).
    Karena itu `MAX(tanggal)`, bukan `TOP 1 ... ORDER BY periode DESC`.

    Selalu dibaca ulang, tidak pernah di-cache: kalau klien menjalankan tutup buku
    lagi, batasnya maju, dan batas basi akan diam-diam menyapu ulang rentang yang
    sudah jadi arsip.
    """
    return _closing_date(cur)


def _kolom_waktu(cur, tabel: str) -> list[str]:
    """Kolom waktu yang benar-benar ada di `tabel`, bukan yang diasumsikan ada."""
    cur.execute(
        "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?) "
        "AND name IN ('tanggal', 'tanggal_server')",
        [tabel],
    )
    ada = {r[0] for r in cur.fetchall()}
    return [k for k in _KOLOM_WAKTU if k in ada]


def _where_rentang(kolom: list[str], dari, sampai) -> tuple[str, list]:
    """Potongan WHERE untuk rentang tanggal, memakai SEMUA kolom waktu dengan OR.

    OR, bukan AND, dan bukan `tanggal` saja: nota bisa bertanggal tiga minggu lalu
    tapi baru diinput hari ini. Terukur 13 dari 927 baris GUDANG seperti itu.
    Menyaring satu kolom saja membuat nota semacam itu tak pernah sampai ke AMPHOREUS,
    tanpa error, tanpa jejak.
    """
    if not kolom:
        raise RuntimeError("tabel tanpa kolom tanggal tidak bisa disapu per rentang")
    atas = min(sampai, TANGGAL_MAKS)
    potong, params = [], []
    for k in kolom:
        potong.append(f"([{k}] >= ? AND [{k}] < ?)")
        params += [dari, atas]
    return "(" + " OR ".join(potong) + ")", params


def hitung_anomali(cur, tabel: str) -> int:
    """Baris yang tanggalnya di luar akal — dikecualikan semua rentang di atas.

    Dilaporkan, bukan ditelan: baris seperti ini adalah salah ketik yang harus
    diperbaiki manusia di cabang, dan AMPHOREUS yang diam soal itu sama buruknya
    dengan AMPHOREUS yang menyalinnya.

    Hanya `tanggal` yang diperiksa, bukan juga `tanggal_server`. `tanggal`
    terindeks di semua cabang (`IX_tpenjualan_tanggal` dkk, dibuat
    `apps/transactions/indexes.py`) sehingga ini seek; `tanggal_server` tidak
    terindeks sama sekali, dan memeriksanya berarti scan tabel penuh 500rb baris
    setiap tick — pemeriksaan kesehatan yang lebih mahal daripada pekerjaannya
    sendiri. `tanggal_server` diisi GETDATE() jadi tak mungkin bernilai 7252.
    """
    cur.execute("SELECT COUNT(*) FROM [%s] WHERE [tanggal] >= ?" % tabel, [TANGGAL_MAKS])
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _kunci_baris(spec: dict, baris: dict) -> dict:
    return {k: baris[k] for k in spec["key_columns"] if k in baris}


def _salin_header(src_cur, hub_cur, tabel: str, kd_sumber: str, dari, sampai) -> dict:
    """Satu tabel header + detailnya, untuk satu rentang. Ganti-total per rentang.

    Urutannya: tulis apa yang ada di cabang, lalu hapus apa yang tidak ada lagi.
    Terbalik akan membuat AMPHOREUS kosong sesaat di tengah transaksi — tidak fatal
    karena semuanya satu transaksi, tapi urutan ini juga yang membuat hitungan
    `dihapus` berarti "benar-benar lenyap di cabang", bukan "belum sempat ditulis".
    """
    spec = HUB_TABLE_SPECS[tabel]
    kol_hub = _kolom_tujuan(hub_cur, tabel)
    kol_src = set(_kolom_tujuan(src_cur, tabel))
    boleh = [k for k in kol_hub if k != KOL_SUMBER and k in kol_src]
    kunci_kol = spec["key_columns"]

    kol_waktu = _kolom_waktu(src_cur, tabel)
    where, params = _where_rentang(kol_waktu, dari, sampai)

    src_cur.execute(
        f"SELECT {', '.join(f'[{k}]' for k in boleh)} FROM [{tabel}] WHERE {where}", params
    )
    baris_src = src_cur.fetchall()

    # GANTI-SELURUH-RENTANG, bukan cek-lalu-UPDATE/INSERT per baris.
    #
    # `_terapkan_header` mengirim DUA round-trip per baris (SELECT lalu
    # UPDATE/INSERT). Bentuk itu WAJIB di `feed_sync`/`hub_sync` karena di sana
    # nilainya datang dari `formatted_data` yang cuma memuat kolom yang ditulis
    # trigger — DELETE-lalu-INSERT akan mengosongkan kolom yang tak disebut.
    #
    # Di sini tidak: modul ini membaca BARIS PENUH dari tabel asli. Jadi hapus
    # rentangnya sekali, sisipkan semuanya sekali, dan 1.000 round-trip per 500
    # nota jadi 2. Itu bagian terbesar dari ongkos menyalin riwayat lewat
    # Tailscale yang me-relay ke Singapura.
    #
    # Kunci hub dibaca DULU (satu round-trip) — dibutuhkan untuk membersihkan
    # detail milik nota yang lenyap, yang tidak ikut terhapus oleh DELETE ini.
    kol_kunci = kunci_kol[0] if len(kunci_kol) == 1 else None
    where_hub, params_hub = _where_rentang(_kolom_waktu(hub_cur, tabel), dari, sampai)
    kunci_hub = []
    if kol_kunci:
        hub_cur.execute(
            f"SELECT [{kol_kunci}] FROM [{tabel}] WHERE [{KOL_SUMBER}] = ? AND {where_hub}",
            [kd_sumber] + params_hub,
        )
        kunci_hub = [r[0] for r in hub_cur.fetchall()]

    hub_cur.execute(
        f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] = ? AND {where_hub}",
        [kd_sumber] + params_hub,
    )

    parents = set()
    if kol_kunci:
        idx = boleh.index(kol_kunci)
        parents = {r[idx] for r in baris_src}
        # Hapus juga BERDASARKAN KUNCI, bukan cuma rentang.
        #
        # Tanggal di sisi AMPHOREUS bisa BASI. Terukur: nota PAGESANGAN
        # CP2607130001 punya `tanggal_server` 2026-08-06 di cabang (diedit ulang
        # hari itu) tapi 2026-07-23 di AMPHOREUS — salinan lama. Jendela 7 hari
        # memilihnya di sumber lewat tanggal baru, sementara DELETE rentang di
        # AMPHOREUS memakai tanggal lama yang di luar jendela, jadi barisnya
        # bertahan dan INSERT-nya bertabrakan: "Violation of PRIMARY KEY".
        #
        # Bentuk cek-lalu-UPDATE yang lama kebal karena berkunci pada kunci
        # alami. Kekebalan itu dikembalikan di sini tanpa mengembalikan
        # ongkosnya: satu DELETE per 500 kunci, bukan dua round-trip per baris.
        daftar_kunci = sorted(parents, key=lambda v: str(v))
        for i in range(0, len(daftar_kunci), BATCH_PARENT):
            potong = daftar_kunci[i:i + BATCH_PARENT]
            bind_varchar(hub_cur, len(potong) + 1)
            try:
                hub_cur.execute(
                    f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] = ? AND [{kol_kunci}] IN "
                    f"({', '.join('?' * len(potong))})",
                    [kd_sumber] + potong,
                )
            finally:
                hub_cur.setinputsizes(None)

    if baris_src:
        hub_cur.executemany(
            f"INSERT INTO [{tabel}] ([{KOL_SUMBER}], "
            + ", ".join(f"[{k}]" for k in boleh)
            + ") VALUES (" + ", ".join("?" * (len(boleh) + 1)) + ")",
            [[kd_sumber] + list(r) for r in baris_src],
        )

    # Detail SELALU ikut header, tidak menunggu apa pun. Cakupan trigger berbeda
    # tiap cabang (PRAYA: 285 header t_penjualan, NOL feed detail), dan nota tanpa
    # baris adalah kerusakan yang tidak memunculkan satu pun error — laporan jalan,
    # jumlah nota benar, omzetnya nol.
    # `_ambil_ulang_detail` mengembalikan jumlah NOTA yang diambil ulang, bukan
    # jumlah baris. Dihitung terpisah dari `detail` supaya ringkasan di layar
    # tidak menjumlahkan dua satuan yang berbeda jadi satu angka tanpa arti.
    n_nota = 0
    daftar_parent = sorted(parents, key=lambda v: str(v))
    for tdet in spec.get("details", ()):
        kol_det = _kolom_tujuan(hub_cur, tdet)
        for i in range(0, len(daftar_parent), BATCH_PARENT):
            n_nota += _ambil_ulang_detail(
                src_cur, hub_cur, tdet, HUB_TABLE_SPECS[tdet]["parent_key"],
                kd_sumber, daftar_parent[i:i + BATCH_PARENT], kol_det,
            )

    # Nota yang lenyap di cabang. HEADER-nya sudah ikut terhapus oleh DELETE
    # rentang di atas, tapi DETAIL-nya tidak — tidak ada yang menyeretnya, dan
    # baris detail yatim tetap terhitung di laporan omzet AMPHOREUS tanpa nota
    # induk yang bisa ditelusuri.
    #
    # Dibandingkan lewat `_k()`, bukan `==` mentah: collation SQL Server
    # mengabaikan huruf besar-kecil dan spasi ekor, set Python tidak.
    n_hapus = 0
    if kol_kunci:
        punya_src = {_k(v) for v in parents}
        lenyap = [k for k in kunci_hub if _k(k) not in punya_src]
        for i in range(0, len(lenyap), BATCH_PARENT):
            potongan = lenyap[i:i + BATCH_PARENT]
            for tdet in spec.get("details", ()):
                # Ambil-ulang dengan nol baris di sumber = hapus bersih. Bentuk
                # kodenya sengaja sama dengan jalur normal supaya tidak ada dua
                # cara menghapus detail yang bisa menyimpang satu sama lain.
                _ambil_ulang_detail(
                    src_cur, hub_cur, tdet, HUB_TABLE_SPECS[tdet]["parent_key"],
                    kd_sumber, potongan, _kolom_tujuan(hub_cur, tdet),
                )
            n_hapus += len(potongan)

    return {"header": len(baris_src), "nota": n_nota, "detail": 0, "dihapus": n_hapus}


def _salin_rentang_datar(src_cur, hub_cur, tabel: str, kd_sumber: str, dari, sampai) -> dict:
    """Tabel transaksi datar tanpa header pemilik (`t_opname_stok`).

    Tidak ada yang menyeretnya, dan tidak ada kunci per baris yang andal (satu
    opname punya banyak barang, `(no_transaksi, kd_barang)` tidak dijamin unik).
    Jadi bentuk tulisannya paling sederhana yang benar: hapus seluruh rentang di
    AMPHOREUS, salin ulang seluruh rentang dari cabang. Nota opname yang dibatalkan
    ikut hilang dengan sendirinya.
    """
    kol_hub = _kolom_tujuan(hub_cur, tabel)
    kol_src = set(_kolom_tujuan(src_cur, tabel))
    boleh = [k for k in kol_hub if k != KOL_SUMBER and k in kol_src]

    where_hub, params_hub = _where_rentang(_kolom_waktu(hub_cur, tabel), dari, sampai)
    hub_cur.execute(
        f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] = ? AND {where_hub}",
        [kd_sumber] + params_hub,
    )
    dihapus = hub_cur.rowcount if hub_cur.rowcount and hub_cur.rowcount > 0 else 0

    where_src, params_src = _where_rentang(_kolom_waktu(src_cur, tabel), dari, sampai)
    src_cur.execute(
        f"SELECT {', '.join(f'[{k}]' for k in boleh)} FROM [{tabel}] WHERE {where_src}",
        params_src,
    )
    baris = src_cur.fetchall()

    # Hapus juga berdasarkan nota, bukan cuma rentang — alasan yang sama dengan
    # `_salin_header`: tanggal di sisi AMPHOREUS bisa basi sehingga DELETE
    # rentang melewatkan barisnya. Bedanya tabel ini TIDAK punya primary key,
    # jadi akibatnya bukan error melainkan baris berganda yang diam-diam
    # menggelembungkan hasil opname.
    induk = HUB_TABLE_SPECS[tabel]["parent_key"]
    if baris and induk in boleh:
        idx = boleh.index(induk)
        daftar = sorted({r[idx] for r in baris}, key=lambda v: str(v))
        for i in range(0, len(daftar), BATCH_PARENT):
            potong = daftar[i:i + BATCH_PARENT]
            bind_varchar(hub_cur, len(potong) + 1)
            try:
                hub_cur.execute(
                    f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] = ? AND [{induk}] IN "
                    f"({', '.join('?' * len(potong))})",
                    [kd_sumber] + potong,
                )
            finally:
                hub_cur.setinputsizes(None)

    if baris:
        hub_cur.executemany(
            f"INSERT INTO [{tabel}] ([{KOL_SUMBER}], {', '.join(f'[{k}]' for k in boleh)}) "
            f"VALUES ({', '.join('?' * (len(boleh) + 1))})",
            [[kd_sumber] + list(r) for r in baris],
        )
    return {"header": 0, "nota": 0, "detail": len(baris), "dihapus": dihapus}


def salin_rentang(source, hub, dari, sampai, dry_run: bool = False, tabel_saja=None) -> dict:
    """Salin seluruh transaksi cabang dalam `[dari, sampai)` ke AMPHOREUS.

    Satu transaksi untuk seluruh rentang: AMPHOREUS tidak boleh terlihat setengah
    tersalin oleh laporan yang kebetulan dibuka bersamaan.
    """
    hasil = _hasil_kosong(source)
    kd_sumber = hasil["kd_sumber"]
    if not kd_sumber:
        hasil["status"] = "tanpa_kode"
        return hasil

    daftar_header = [t for t in TABEL_HEADER if not tabel_saja or t in tabel_saja]
    daftar_datar = [t for t in TABEL_RENTANG if not tabel_saja or t in tabel_saja]
    try:
        with mssql.cursor(source) as src_cur, mssql.cursor(hub, autocommit=False) as hub_cur:
            for tabel in daftar_header:
                n = _salin_header(src_cur, hub_cur, tabel, kd_sumber, dari, sampai)
                hasil["anomali_tanggal"] += hitung_anomali(src_cur, tabel)
                hasil["tabel"][tabel] = n
                for k in ("header", "nota", "detail", "dihapus"):
                    hasil[k] += n[k]
            for tabel in daftar_datar:
                n = _salin_rentang_datar(src_cur, hub_cur, tabel, kd_sumber, dari, sampai)
                hasil["tabel"][tabel] = n
                for k in ("header", "nota", "detail", "dihapus"):
                    hasil[k] += n[k]

            if dry_run:
                hub_cur.connection.rollback()
                hasil["status"] = "dry_run"
            else:
                hub_cur.connection.commit()
    except (pyodbc.Error, RuntimeError, ValueError) as exc:
        hasil["status"] = "failed"
        hasil["error"] = str(exc.args[-1] if exc.args else exc)
    return hasil


def agregat_harian(cur, tabel: str, kolom_waktu: list[str], dari, sampai,
                   kd_sumber: str | None = None) -> dict:
    """`{tanggal: (jumlah, jumlah_nilai)}` — SATU kueri, satu baris per hari.

    Inilah yang membuat pencocokan 900-2.000 hari x 9 cabang terjangkau: bukan
    satu kueri per hari, melainkan satu `GROUP BY` yang mengembalikan semuanya.
    Terukur 0,15 dtk (GUDANG, 2.019 hari) dan 0,13 dtk (ANDARIA lewat WAN 783 ms,
    933 hari).

    Dikelompokkan menurut `tanggal` (tanggal transaksi), bukan `tanggal_server` —
    itulah sumbu yang dipakai semua laporan, jadi itu pula yang harus cocok.
    """
    where, params = _where_rentang(kolom_waktu, dari, sampai)
    if kd_sumber is not None:
        where = f"[{KOL_SUMBER}] = ? AND {where}"
        params = [kd_sumber] + params

    numerik = _kolom_numerik(cur, tabel)
    nilai = (
        "SUM(" + " + ".join(f"CAST(ISNULL([{k}], 0) AS decimal(18,4))" for k in numerik) + ")"
        if numerik else "CAST(0 AS decimal(18,4))"
    )
    cur.execute(
        f"SELECT CAST([tanggal] AS date) d, COUNT(*), {nilai} FROM [{tabel}] "
        f"WHERE {where} GROUP BY CAST([tanggal] AS date)",
        params,
    )
    return {r[0]: (int(r[1]), r[2]) for r in cur.fetchall()}


def _kolom_numerik(cur, tabel: str) -> list[str]:
    """Kolom float/decimal/money header, urut nama — bahan agregat pencocokan.

    Diurutkan supaya penjumlahannya deterministik di kedua sisi, dan di-CAST ke
    decimal supaya penjumlahan float tidak menghasilkan selisih ujung yang
    membuat hari yang sebenarnya identik terbaca berbeda tiap run.
    """
    cur.execute(
        "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?) "
        "AND TYPE_NAME(system_type_id) IN ('float','real','decimal','numeric','money','smallmoney') "
        "AND is_computed = 0 ORDER BY name",
        [tabel],
    )
    return [r[0] for r in cur.fetchall()]


def cocokkan_harian(source, hub, sampai=None, dry_run: bool = False, lapor=None) -> dict:
    """Tingkat 2: bandingkan agregat per hari, salin ulang HANYA hari yang beda.

    Rentangnya tutup_buku .. jendela segar. Di bawah tutup buku tidak dicocokkan
    (itu arsip, tidak berubah lagi); di atasnya tidak perlu dicocokkan (jendela
    segar sudah menyalin ulang tanpa syarat).
    """
    hasil = _hasil_kosong(source)
    kd_sumber = hasil["kd_sumber"]
    if not kd_sumber:
        hasil["status"] = "tanpa_kode"
        return hasil

    beda_semua: set[dt.date] = set()
    try:
        with mssql.cursor(source) as src_cur, mssql.cursor(hub) as hub_cur:
            tutup = batas_arsip(src_cur)
            atas = sampai or _awal_jendela(src_cur, JENDELA_SEGAR_HARI)
            dari = max(tutup, TANGGAL_MIN)
            if dari >= atas:
                hasil["status"] = "rentang_kosong"
                return hasil
            for tabel in TABEL_HEADER + TABEL_RENTANG:
                kol_src = _kolom_waktu(src_cur, tabel)
                a = agregat_harian(src_cur, tabel, kol_src, dari, atas)
                b = agregat_harian(
                    hub_cur, tabel, _kolom_waktu(hub_cur, tabel), dari, atas, kd_sumber
                )
                beda_semua |= {d for d in set(a) | set(b) if a.get(d) != b.get(d)}
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["status"] = "failed"
        hasil["error"] = str(exc.args[-1] if exc.args else exc)
        return hasil

    hasil["hari_beda"] = len(beda_semua)
    if dry_run:
        # Dry run dari sebuah PERBANDINGAN berhenti di perbandingannya. Meneruskan
        # ke penyalinan lalu me-rollback berarti mengerjakan seluruh ongkos untuk
        # membuang hasilnya — dan pada sapuan pertama, ketika hampir semua hari
        # memang belum ada di AMPHOREUS, itu berjam-jam kerja demi satu angka yang
        # sudah didapat di baris ini.
        hasil["status"] = "dry_run"
        return hasil

    # Hari yang berdekatan digabung jadi satu rentang: 30 hari berurutan lebih
    # murah disalin sebagai satu range seek daripada 30 sapuan terpisah.
    #
    # TAPI hasil gabungan itu DIPOTONG PER BULAN lagi. Pada sapuan pertama
    # hampir semua hari berbeda — terukur 210 sampai 2.101 hari per cabang —
    # sehingga penggabungan menghasilkan SATU rentang 5,7 tahun dan satu
    # transaksi raksasa lewat WAN. Itu persis kegagalan yang sudah dibayar
    # `pull_arsip`: putus di tengah, seluruhnya hangus.
    potongan = [
        p
        for d0, d1 in _gabung_hari(sorted(beda_semua))
        for p in _per_bulan(
            dt.datetime.combine(d0, dt.time.min),
            dt.datetime.combine(d1 + dt.timedelta(days=1), dt.time.min),
        )
    ]
    total = len(potongan)
    for i, (a, b) in enumerate(potongan, start=1):
        satu = salin_rentang(source, hub, a, b, dry_run=dry_run)
        if satu["status"] == "failed":
            if lapor:
                lapor(f"  {source.name:<12} cocok [{i}/{total}] {a:%Y-%m} GAGAL: {satu['error'][:110]}")
            return {**hasil, "status": "failed", "error": satu["error"]}
        for k in ("header", "nota", "detail", "dihapus", "anomali_tanggal"):
            hasil[k] += satu[k]
        if lapor and satu["header"]:
            lapor(
                f"  {source.name:<12} cocok [{i}/{total}] {a:%Y-%m}  "
                f"header={satu['header']} nota={satu['nota']}"
            )
    return hasil


def _gabung_hari(hari: list[dt.date]) -> list[tuple[dt.date, dt.date]]:
    """[1,2,3,7] -> [(1,3), (7,7)]. Rentang bersambung, bukan hari satuan."""
    keluar: list[list[dt.date]] = []
    for d in hari:
        if keluar and d - keluar[-1][1] == dt.timedelta(days=1):
            keluar[-1][1] = d
        else:
            keluar.append([d, d])
    return [(a, b) for a, b in keluar]


def _awal_jendela(cur, hari: int) -> dt.datetime:
    """Awal jendela segar menurut JAM SERVER CABANG, bukan jam mesin ini.

    Bukan dari `MAX(tanggal)`: ANDARIA punya nota bertanggal 7252-01-09, dan
    jendela yang dihitung dari situ akan berhenti menyapu apa pun selamanya.
    Bukan pula dari jam Python: server cabang tersebar di beberapa lokasi dan
    file `d:\\utc.txt` di job legacy ada persis karena seseorang pernah mencoba
    mengoreksi zona waktu di jalur ini dan hasilnya watermark yang meleset.
    """
    cur.execute("SELECT DATEADD(day, ?, CAST(GETDATE() AS date))", [-int(hari)])
    nilai = cur.fetchone()[0]
    # `CAST(... AS date)` kembali sebagai `datetime.date`, sementara seluruh
    # perbandingan rentang di modul ini memakai `datetime`. Mencampur keduanya
    # melempar TypeError di `min()` — di jalur yang hanya jalan saat scheduler
    # menyala, jadi tak akan terlihat sampai produksi.
    if isinstance(nilai, dt.date) and not isinstance(nilai, dt.datetime):
        return dt.datetime.combine(nilai, dt.time.min)
    return nilai


def pull_segar(source, hub, hari: int = JENDELA_SEGAR_HARI, dry_run: bool = False) -> dict:
    """Tingkat 3: N hari terakhir, disalin ulang tanpa dibandingkan."""
    try:
        with mssql.cursor(source) as cur:
            dari = _awal_jendela(cur, hari)
    except (pyodbc.Error, RuntimeError) as exc:
        hasil = _hasil_kosong(source)
        hasil["status"] = "failed"
        hasil["error"] = str(exc.args[-1] if exc.args else exc)
        return hasil
    return salin_rentang(source, hub, dari, TANGGAL_MAKS, dry_run=dry_run)


def pull_arsip(source, hub, potong_tahun: bool = False, dry_run: bool = False,
               lapor=None) -> dict:
    """Tingkat 1: seluruh `tanggal <= tutup_buku`, sekali seumur hidup.

    **Dipotong per BULAN, bukan per tahun.** PUSAT punya 445.167 nota di bawah
    tutup bukunya; satu tahun PUSAT berarti ~90.000 header plus ~600.000 baris
    detail dalam SATU transaksi di AMPHOREUS, lewat WAN, selama puluhan menit —
    dan satu error di menit ke-40 membuang seluruhnya. Per bulan potongannya
    ~7.400 nota: tetap satu range seek (`tanggal` terindeks), tapi yang hilang
    saat gagal cuma sebulan.

    `potong_tahun=True` masih ada untuk cabang kecil yang ingin lebih sedikit
    transaksi, tapi jangan dipakai untuk cabang besar.

    `lapor(teks)` dipanggil tiap potongan selesai. Wajib ada isinya untuk run
    berjam-jam: perintah yang diam sampai akhir tidak bisa dibedakan dari
    perintah yang menggantung.
    """
    hasil = _hasil_kosong(source)
    if not hasil["kd_sumber"]:
        hasil["status"] = "tanpa_kode"
        return hasil
    try:
        with mssql.cursor(source) as cur:
            tutup = batas_arsip(cur)
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["status"] = "failed"
        hasil["error"] = str(exc.args[-1] if exc.args else exc)
        return hasil

    if tutup <= TANGGAL_MIN:
        hasil["status"] = "tanpa_tutup_buku"
        return hasil
    if not dry_run:
        # `HubPullState.tutup_buku` ditampilkan di kolom Kesehatan Sync. Tanpa
        # ditulis di sini kolomnya selamanya "—" — field yang ada tapi tak pernah
        # diisi lebih buruk daripada tidak ada, karena terbaca "belum tutup buku".
        HubPullState.objects.update_or_create(
            source_profile=source, target_profile=hub,
            defaults={"tutup_buku": timezone.make_aware(tutup)},
        )

    batas_atas = tutup + dt.timedelta(seconds=1)
    try:
        with mssql.cursor(source) as cur:
            awal = _awal_data(cur)
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["status"] = "failed"
        hasil["error"] = str(exc.args[-1] if exc.args else exc)
        return hasil

    potong = _per_tahun if potong_tahun else _per_bulan
    # Potongan PERTAMA menyapu dari 1900 sampai data tertua supaya baris yang
    # lebih tua dari perkiraan tetap ikut. Tanpa ini, memulai potongan di
    # `awal` berarti apa pun di bawahnya lolos tanpa suara.
    potongan = [(TANGGAL_MIN, awal)] + potong(awal, batas_atas)
    total = len(potongan)

    # Lanjut dari potongan terakhir yang berhasil, bukan dari nol.
    lanjut = _titik_lanjut(source, hub) if not dry_run else None
    for i, (dari, sampai) in enumerate(potongan, start=1):
        if lanjut is not None and sampai <= lanjut:
            hasil["dilewati_potongan"] += 1
            continue
        satu = salin_rentang(source, hub, dari, sampai, dry_run=dry_run)
        if satu["status"] == "failed":
            if lapor:
                # Nama cabang WAJIB ikut: `pull_all` menjalankan semua cabang
                # sebelum satu pun ringkasan tercetak, jadi baris tanpa nama
                # tidak bisa ditelusuri ke cabang mana pun.
                lapor(f"  {source.name:<12} [{i}/{total}] {dari:%Y-%m} GAGAL: {satu['error'][:110]}")
            return {**hasil, "status": "failed", "error": satu["error"]}
        for k in ("header", "nota", "detail", "dihapus", "anomali_tanggal"):
            hasil[k] += satu[k]
        if not dry_run:
            _catat_lanjut(source, hub, sampai)
        if lapor and (satu["header"] or satu["detail"]):
            lapor(
                f"  {source.name:<12} [{i}/{total}] {dari:%Y-%m}  header={satu['header']} "
                f"nota={satu['nota']} detail={satu['detail']}"
            )
    if dry_run:
        hasil["status"] = "dry_run"
    return hasil


def _titik_lanjut(source, hub):
    """Titik lanjut arsip sebagai datetime NAIF jam lokal.

    `USE_TZ=True`, jadi nilainya tersimpan UTC — sementara batas potongan di
    modul ini naif jam lokal (jam dinding server MS SQL). `.replace(tzinfo=None)`
    langsung akan memberi jam UTC dan menggeser titik lanjut 8 jam: potongan yang
    sudah selesai bisa terbaca belum, atau lebih buruk, yang belum terbaca sudah
    dan dilewati diam-diam. Konversi ke lokal DULU, baru dibuat naif — pola yang
    sama dipakai `services_sync._aware` di batas penyimpanan.
    """
    row = HubPullState.objects.filter(source_profile=source, target_profile=hub).first()
    if not (row and row.arsip_sampai):
        return None
    return timezone.localtime(row.arsip_sampai).replace(tzinfo=None)


def _catat_lanjut(source, hub, sampai) -> None:
    """Tandai satu potongan arsip selesai, SESUDAH commit-nya.

    Ditulis per potongan, bukan per cabang: `arsip_selesai_at` baru terisi di
    akhir cabang, dan run pertama membuktikan apa artinya — PUSAT putus di
    potongan 32 dari 48 dan 285.809 header harus disalin ulang dari nol.
    """
    HubPullState.objects.update_or_create(
        source_profile=source, target_profile=hub,
        defaults={"arsip_sampai": timezone.make_aware(sampai) if timezone.is_naive(sampai) else sampai},
    )


def _awal_data(cur, tabel: str = "t_penjualan") -> dt.datetime:
    """Awal bulan dari transaksi tertua yang masuk akal.

    Memotong dari 1900 akan menghasilkan 1.500 potongan bulanan yang hampir
    semuanya kosong — tiap potongan tetap menjalankan delapan kueri, jadi itu
    menit-menit kerja untuk nol baris. Dipagari `ARSIP_LANTAI` di bawah dan
    `TANGGAL_MAKS` di atas karena `MIN(tanggal)` di data legacy bisa berisi
    tahun ngawur dari salah ketik, persis seperti `MAX(tanggal)`.
    """
    cur.execute(
        f"SELECT MIN([tanggal]) FROM [{tabel}] WHERE [tanggal] >= ? AND [tanggal] < ?",
        [ARSIP_LANTAI, TANGGAL_MAKS],
    )
    row = cur.fetchone()
    nilai = row[0] if row and row[0] else ARSIP_LANTAI
    return dt.datetime(nilai.year, nilai.month, 1)


def _per_bulan(dari: dt.datetime, sampai: dt.datetime) -> list[tuple]:
    """Potongan bulanan `[awal, akhir)`. Satu bulan PUSAT ~7.400 nota."""
    keluar = []
    tahun, bulan = dari.year, dari.month
    while dt.datetime(tahun, bulan, 1) < sampai:
        a = dt.datetime(tahun, bulan, 1)
        tahun_b, bulan_b = (tahun + 1, 1) if bulan == 12 else (tahun, bulan + 1)
        keluar.append((max(dari, a), min(sampai, dt.datetime(tahun_b, bulan_b, 1))))
        tahun, bulan = tahun_b, bulan_b
    return keluar


def _per_tahun(dari: dt.datetime, sampai: dt.datetime) -> list[tuple]:
    keluar = []
    tahun = dari.year
    while dt.datetime(tahun, 1, 1) < sampai:
        a = max(dari, dt.datetime(tahun, 1, 1))
        b = min(sampai, dt.datetime(tahun + 1, 1, 1))
        keluar.append((a, b))
        tahun += 1
    return keluar


def _simpan_state(source, hub, hasil: dict, mode: str) -> None:
    row, _ = HubPullState.objects.get_or_create(source_profile=source, target_profile=hub)
    sekarang = timezone.now()
    if mode == "arsip" and hasil["status"] not in ("failed", "dry_run"):
        row.arsip_selesai_at = sekarang
    if mode == "cocok" and hasil["status"] not in ("failed", "dry_run"):
        row.cocok_terakhir_at = sekarang
        row.hari_beda = hasil["hari_beda"]
    if mode == "segar" and hasil["status"] not in ("failed", "dry_run"):
        row.segar_terakhir_at = sekarang
    row.rows_header = hasil["header"]
    row.rows_detail = hasil["detail"]
    row.rows_deleted = hasil["dihapus"]
    row.status = "failed" if hasil["status"] == "failed" else "ok"
    row.error_message = hasil["error"][:255]
    row.save()


def pull_source(source, hub, mode: str = "segar", hari: int = JENDELA_SEGAR_HARI,
                dry_run: bool = False, lapor=None, coba: int = COBA_ULANG) -> dict:
    """Satu cabang, satu tingkat. Menyimpan `HubPullState` kecuali dry run."""
    for percobaan in range(1, max(1, coba) + 1):
        if mode == "arsip":
            hasil = pull_arsip(source, hub, dry_run=dry_run, lapor=lapor)
        elif mode == "cocok":
            hasil = cocokkan_harian(source, hub, dry_run=dry_run, lapor=lapor)
        else:
            hasil = pull_segar(source, hub, hari=hari, dry_run=dry_run)
        if hasil["status"] != "failed" or percobaan >= max(1, coba):
            break
        # Blip koneksi sesaat menjatuhkan SELURUH cabang. Terukur: PRAYA gagal
        # `[08001] wait operation timed out` lalu konek 0,7 detik kemudian tanpa
        # ada yang diubah. Mengulang aman DAN murah karena tiap mode idempoten
        # dan hanya mengerjakan sisanya: arsip melompati potongan yang sudah
        # ditandai `arsip_sampai`, cocok membandingkan ulang lalu menemukan
        # hari-hari yang tadi sempat tersalin sudah cocok.
        if lapor:
            lapor(f"  {source.name:<12} percobaan {percobaan} gagal, ulangi: {hasil['error'][:90]}")
        time.sleep(JEDA_ULANG)
    if not dry_run:
        _simpan_state(source, hub, hasil, mode)
    return hasil


def pull_all(hub, sources=None, mode: str = "segar", hari: int = JENDELA_SEGAR_HARI,
             dry_run: bool = False, lapor=None) -> list[dict]:
    """Semua cabang, berurutan dan saling terisolasi.

    Satu cabang mati tidak boleh menahan delapan yang sehat — pelajaran yang sama
    sudah dibayar `hub_sync`, di mana cabang pertama menurut abjad yang tidak bisa
    dihubungi menjatuhkan seluruh run.
    """
    return [
        pull_source(s, hub, mode=mode, hari=hari, dry_run=dry_run, lapor=lapor)
        for s in (sources if sources is not None else sumber_profiles())
    ]

r"""AMPHOREUS: menarik data 9 cabang (gudang + 8 grosir) ke satu pusat milik sendiri.

Berjalan BERDAMPINGAN dengan job SQL Agent legacy; tidak ada yang dimatikan.
Bedanya: jalur ini tidak lewat web legacy sama sekali, tidak memanggil
`xp_cmdshell`, tidak meng-escape data lewat sandi buatan tangan, dan tidak
pernah mengeksekusi SQL kiriman. Nilai selalu lewat parameter pyodbc; nama tabel
dan kolom dicocokkan dengan `HUB_TABLE_SPECS` plus katalog nyata pusat.

## Kanal perubahan

`tbl_log_transaksi` di tiap cabang: `id` IDENTITY + clustered PK, jadi
`WHERE id > ?` adalah seek. `tbl_tmp_post` TIDAK bisa dipakai — job legacy
menghapusnya begitu terkirim, jadi poller berjadwal menit-an akan kehilangan
mayoritas barisnya.

Feed ini tidak dihapus job mana pun, tapi **bukan append-only mutlak**:
pemeliharaan database bisa memangkasnya, dan sudah pernah (1.469.155 id lenyap
semalam 15-16 Mei 2024 di lini PUSAT saat database dipisah). Lihat catatan
lengkapnya di docstring `feed_sync` dan `services_sync._periksa_cursor()`.

Parser `formatted_data` (termasuk prefiks `key__` pada baris `__update`) dipakai
ulang dari `feed_sync` — lihat docstring modul itu untuk jebakan-jebakannya.

## Dua bentuk apply

Pelajaran yang sudah dibayar `cdc_sync.py`, jangan diulang dari nol:

- **Header & master** punya kunci alami → UPDATE by `(kd_sumber, kunci)`, INSERT
  kalau nol baris kena. Idempoten.
- **Detail TIDAK punya kunci per baris yang andal.** Satu nota sah punya dua
  baris untuk `kd_barang` yang sama (dua harga/diskon). Karena itu jangan
  dicocokkan per baris: begitu ada perubahan, hapus SEMUA baris pusat untuk
  `(kd_sumber, no_transaksi)` lalu **ambil ulang seluruh baris terkini nota itu
  dari cabang**. Murah (seek by parent), selalu sama persis dengan cabang, dan
  ikut menangani baris yang dihapus di sana.

Konsekuensinya modul ini membuka DUA koneksi sekaligus (cabang + pusat).

## kd_sumber

Tidak ada satu pun kolom di data legacy yang menandai server asal: `divisi_id`
di feed bernilai DAA000/DAA004 di SEMUA cabang, dan `m_divisi.kd_divisi` juga
DAA000 di semua cabang. Penanda datang dari `ServerProfile.kode_sumber`, dan
`no_transaksi` bisa sama antar-server (RUMAK & RTL RUMAK sama-sama punya
`TR2608010005`). Cabang tanpa `kode_sumber` dilewati, bukan ditebak.

## Detail digantungkan pada header, bukan pada feed detail

Terukur di PRAYA: dalam 2.000 baris feed ada **285 `t_penjualan__insert` dan NOL
`t_penjualan_detail__insert`**. Di GUDANG, tabel yang sama menghasilkan 93.333
baris feed detail. Cakupan trigger berbeda-beda tiap cabang, dan trigger tidak
boleh disentuh.

Karena itu tiap header yang tersentuh SELALU menyeret detailnya ikut diambil
ulang dari cabang, tanpa menunggu feed detail muncul. Feed detail tetap dipakai
kalau ada (menangkap nota yang detailnya diedit tanpa header-nya berubah), tapi
bukan lagi satu-satunya pemicu.

Kalau ini tidak dilakukan, pusat berisi nota-nota tanpa satu pun baris — dan itu
kerusakan yang tidak memunculkan satu pun error: laporan tetap jalan, jumlah nota
tetap benar, hanya omzetnya nol.

## Celah yang diketahui

Tiga, dan ketiganya butuh rekonsiliasi berkala — pekerjaan terpisah yang dicatat
di sini supaya tidak ditemukan sebagai kejutan:

1. **Nota yang dihapus di cabang jadi hantu di pusat.** Feed hanya memuat
   `__insert`/`__update`. Baris detailnya aman (ambil-ulang per nota
   mengembalikan nol baris), tapi header-nya tidak.
2. **Feed yang dipangkas melewati cursor tidak bisa dipulihkan dari feed.** Feed
   tak bisa menceritakan apa yang sudah terhapus darinya, jadi satu-satunya
   pembanding yang jujur adalah jumlah nota per tanggal, cabang vs pusat.
   Kesehatan Sync sekarang MEMBERITAHU kalau itu terjadi
   (`services_sync._periksa_cursor`), tapi memberitahu bukan menambal.
3. **Header ditulis dari payload, bukan dibaca ulang dari cabang.**
   `_terapkan_header` memakai nilai di `formatted_data` apa adanya, sementara
   `feed_sync._baca_dari_sumber` sudah membaca ulang dari tabel asli justru
   karena trigger legacy MEMOTONG kolom. Terukur di pusat: baris `m_barang`
   ber-`kd_sumber=PRAYA` mentok di 30 karakter untuk `nama` DAN `keterangan`
   padahal kedua kolomnya `varchar(50)` dan baris GUDANG mencapai 47. Header
   transaksi tidak bergejala (t_penjualan 20 kolom x 25 nota dan t_pembelian 18
   kolom x 9 nota di PUSAT: nol beda), jadi cakupannya tabel master.
"""
from __future__ import annotations

import pyodbc
from django.utils import timezone

from apps.core.models import FeedSyncCursor, SyncDeadLetter
from apps.transactions.feed_sync import (
    _catat_alasan,
    _kolom_tujuan,
    _kunci_lengkap,
    parse_formatted_data,
    parse_table_aksi,
)
from apps.transactions.hub_schema import KOL_SUMBER
from core import mssql

AKSI_TULIS = {"insert", "update"}
AKSI_HAPUS = {"delete"}

# Daftar-izin pusat. Apa pun di luar ini tidak pernah disentuh.
#
# `key_columns` = tabel berkunci alami (header/master), apply UPDATE-lalu-INSERT.
# `parent_key`  = tabel detail, apply hapus-semua-lalu-ambil-ulang per nota.
# `indeks`      = indeks laporan; `kd_sumber` otomatis jadi kolom pertama.
HUB_TABLE_SPECS = {
    # --- header transaksi ---------------------------------------------------
    #
    # `details` = tabel detail yang HARUS ikut diambil ulang tiap kali header ini
    # berubah. Ini bukan optimasi, ini syarat kebenaran — lihat catatan
    # "Detail digantungkan pada header" di docstring modul.
    "t_penjualan": {
        "key_columns": ["no_transaksi"], "details": ["t_penjualan_detail"],
        "indeks": [["tanggal"], ["kd_customer"]],
    },
    "t_penjualan_retur": {
        "key_columns": ["no_retur"], "details": ["t_penjualan_retur_detail"],
        "indeks": [["tanggal"]],
    },
    "t_pembelian": {
        "key_columns": ["no_transaksi"], "details": ["t_pembelian_detail"],
        "indeks": [["tanggal"], ["kd_supplier"]],
    },
    "t_pembelian_retur": {
        "key_columns": ["no_retur"], "details": ["t_pembelian_retur_detail"],
        "indeks": [["tanggal"]],
    },
    "t_mutasi_stok": {
        "key_columns": ["no_transaksi"], "details": ["t_mutasi_stok_detail"],
        "indeks": [["tanggal"]],
    },
    "t_penjualan_order": {
        "key_columns": ["no_order"], "details": ["t_penjualan_order_detail"],
        "indeks": [["tanggal"]],
    },
    # --- detail transaksi ---------------------------------------------------
    "t_penjualan_detail": {"parent_key": "no_transaksi", "indeks": [["kd_barang"]]},
    "t_penjualan_retur_detail": {"parent_key": "no_retur", "indeks": [["kd_barang"]]},
    "t_pembelian_detail": {"parent_key": "no_transaksi", "indeks": [["kd_barang"]]},
    "t_pembelian_retur_detail": {"parent_key": "no_retur", "indeks": [["kd_barang"]]},
    "t_mutasi_stok_detail": {"parent_key": "no_transaksi", "indeks": [["kd_barang"]]},
    "t_penjualan_order_detail": {"parent_key": "no_order", "indeks": [["kd_barang"]]},
    # t_opname_stok datar (satu baris per barang, tanpa tabel detail terpisah),
    # tapi diperlakukan sebagai detail: satu no_transaksi opname mencakup banyak
    # barang dan tidak ada jaminan (no_transaksi, kd_barang) unik. Ambil-ulang
    # per no_transaksi selalu benar; menebak kunci tidak.
    "t_opname_stok": {"parent_key": "no_transaksi", "indeks": [["tanggal"], ["kd_barang"]]},
    # --- master -------------------------------------------------------------
    "m_barang": {"key_columns": ["kd_barang"], "indeks": [["kd_kategori"], ["kd_merk"]]},
    "m_barang_satuan": {"key_columns": ["kd_barang", "kd_satuan"], "indeks": []},
    "m_barang_divisi": {"key_columns": ["kd_barang", "kd_divisi"], "indeks": []},
    "m_barang_supplier": {"key_columns": ["kd_supplier", "kd_barang"], "indeks": []},
    "m_customer": {"key_columns": ["kd_customer"], "indeks": []},
    "m_supplier": {"key_columns": ["kd_supplier"], "indeks": []},
    "m_merk": {"key_columns": ["kd_merk"], "indeks": []},
    "m_divisi": {"key_columns": ["kd_divisi"], "indeks": []},
    "m_kategori": {"key_columns": ["kd_kategori"], "indeks": []},
    "m_satuan": {"key_columns": ["kd_satuan"], "indeks": []},
    "m_pegawai": {"key_columns": ["kd_pegawai"], "indeks": []},
}

# Tabel master yang disalin sekali saat init (lihat init_hub --seed-master).
# Transaksi TIDAK ikut: pusat sengaja mulai kosong untuk transaksi. Tapi tanpa
# katalog, tiap transaksi yang masuk menunjuk kd_barang yang tak ada padanannya
# di pusat sampai barang itu kebetulan diedit.
SEED_TABLES = [
    "m_divisi", "m_kategori", "m_satuan", "m_merk", "m_supplier", "m_pegawai",
    "m_customer", "m_barang", "m_barang_satuan", "m_barang_divisi", "m_barang_supplier",
]


def sumber_profiles():
    """Profil yang jadi sumber pusat: yang `kode_sumber`-nya terisi."""
    from apps.connections.models import ServerProfile

    return list(ServerProfile.objects.exclude(kode_sumber="").order_by("name"))


def _tandai_gagal(row: FeedSyncCursor, hasil: dict, exc) -> dict:
    """Catat kegagalan satu cabang tanpa memajukan cursor-nya.

    Cursor sengaja TIDAK maju: batch yang sama diulang utuh di tick berikutnya,
    dan karena apply-nya idempoten pengulangan itu tidak berbahaya. Yang
    berbahaya adalah kebalikannya — cursor maju melewati perubahan yang belum
    sempat ditulis, dan lubang itu tidak akan pernah terisi sendiri.
    """
    pesan = str(exc.args[-1] if exc.args else exc)
    row.status = "failed"
    row.error_message = pesan[:255]
    row.save(update_fields=["status", "error_message"])
    hasil["status"] = "failed"
    hasil["error"] = pesan
    return hasil


def _cursor_row(source, hub) -> FeedSyncCursor:
    row, _ = FeedSyncCursor.objects.get_or_create(source_profile=source, target_profile=hub)
    return row


def posisi_awal(source) -> int:
    """`MAX(id)` feed cabang saat ini.

    BUKAN 0 — feed berisi jutaan baris riwayat sejak 2020, dan keputusan yang
    diambil adalah pusat mulai kosong untuk transaksi. `--from-id` untuk sengaja
    mengambil lebih jauh ke belakang.
    """
    with mssql.cursor(source) as cur:
        cur.execute("SELECT ISNULL(MAX(id), 0) FROM tbl_log_transaksi")
        return int(cur.fetchone()[0] or 0)


def ambil_perubahan(cur, dari_id: int, limit: int) -> list[dict]:
    cur.execute(
        "SELECT TOP (?) id, waktu, aksi, divisi_id, formatted_data, table_aksi "
        "FROM tbl_log_transaksi WHERE id > ? ORDER BY id",
        [limit, dari_id],
    )
    kolom = [c[0] for c in cur.description]
    return [dict(zip(kolom, r)) for r in cur.fetchall()]


def _terapkan_header(hub_cur, tabel, spec, kd_sumber, kunci, nilai, kolom_ada) -> None:
    """Cek ada, lalu UPDATE atau INSERT, berkunci `(kd_sumber, kunci alami)`.

    UPDATE (bukan DELETE-lalu-INSERT): `formatted_data` hanya membawa kolom yang
    ditulis trigger, jadi DELETE-lalu-INSERT akan mengosongkan kolom yang
    kebetulan tidak disebut.

    Keberadaan baris ditentukan lewat SELECT, **bukan lewat `rowcount` sesudah
    UPDATE** — lihat penjelasan panjangnya di `feed_sync._terapkan_baris`.
    Ringkasnya: trigger AFTER UPDATE tetap menyala walau UPDATE kena nol baris,
    dan tulisan di dalam trigger membuat `rowcount` terbaca 1, sehingga INSERT-nya
    dilewatkan diam-diam. AMPHOREUS sendiri tidak bertrigger sehingga tidak
    pernah bergejala, tapi bentuk kodenya disamakan: perbedaan halus antara dua
    fungsi yang mengerjakan hal sama adalah cara bug ini kembali.
    """
    boleh = set(kolom_ada)
    kolom_kunci, nilai_kunci = _kunci_lengkap(spec, kunci, nilai, boleh)
    semua = {**nilai, **kunci}

    where = f"[{KOL_SUMBER}] = ? AND " + " AND ".join(f"[{k}] = ?" for k in kolom_kunci)
    arg_where = [kd_sumber] + [nilai_kunci[k] for k in kolom_kunci]

    hub_cur.execute(f"SELECT 1 FROM [{tabel}] WHERE {where}", arg_where)
    if hub_cur.fetchone() is not None:
        set_kolom = [k for k in semua if k in boleh and k not in kolom_kunci and k != KOL_SUMBER]
        if set_kolom:
            hub_cur.execute(
                f"UPDATE [{tabel}] SET " + ", ".join(f"[{k}] = ?" for k in set_kolom)
                + f" WHERE {where}",
                [semua[k] for k in set_kolom] + arg_where,
            )
        return

    kolom_insert = [k for k in semua if k in boleh and k != KOL_SUMBER]
    hub_cur.execute(
        f"INSERT INTO [{tabel}] ([{KOL_SUMBER}], "
        + ", ".join(f"[{k}]" for k in kolom_insert)
        + ") VALUES (" + ", ".join("?" * (len(kolom_insert) + 1)) + ")",
        [kd_sumber] + [semua[k] for k in kolom_insert],
    )


def _ambil_ulang_detail(src_cur, hub_cur, tabel, parent_key, kd_sumber, parents, kolom_ada) -> int:
    """Untuk tiap nota yang tersentuh: hapus semua baris pusat, salin ulang dari cabang.

    Ini satu-satunya cara yang benar untuk tabel tanpa kunci per baris, dan
    kebetulan juga satu-satunya yang menangani baris detail yang DIHAPUS di
    cabang — nota yang dikosongkan diambil ulang jadi nol baris.
    """
    if not parents:
        return 0
    boleh = [k for k in kolom_ada if k != KOL_SUMBER]
    daftar = list(parents)
    for nilai_parent in daftar:
        hub_cur.execute(
            f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] = ? AND [{parent_key}] = ?",
            [kd_sumber, nilai_parent],
        )
    placeholders = ", ".join("?" * len(daftar))
    src_cur.execute(
        f"SELECT {', '.join(f'[{k}]' for k in boleh)} FROM [{tabel}] "
        f"WHERE [{parent_key}] IN ({placeholders})",
        daftar,
    )
    baris = src_cur.fetchall()
    if baris:
        sql = (
            f"INSERT INTO [{tabel}] ([{KOL_SUMBER}], " + ", ".join(f"[{k}]" for k in boleh) + ") "
            f"VALUES (" + ", ".join("?" * (len(boleh) + 1)) + ")"
        )
        hub_cur.executemany(sql, [[kd_sumber] + list(r) for r in baris])
    return len(daftar)


def sync_source(source, hub, limit: int = 2000, dry_run: bool = False, from_id: int | None = None) -> dict:
    """Tarik satu batch feed cabang `source` ke pusat `hub`.

    Cursor maju hanya SESUDAH commit. Satu baris bermasalah masuk dead-letter dan
    run diteruskan — kebalikan `goto hell` di job legacy, yang membuat sisa
    antrean terlewat sesiklus.
    """
    kd_sumber = (source.kode_sumber or "").strip()
    hasil = {
        "source": source.name, "kd_sumber": kd_sumber, "status": "ok",
        "diterapkan": 0, "disaring": 0, "dilewati": 0, "nota": 0,
        "sampai_id": 0, "error": "", "alasan": {},
    }
    if not kd_sumber:
        hasil["status"] = "tanpa_kode"
        return hasil

    row = _cursor_row(source, hub)
    mulai = from_id if from_id is not None else row.last_id
    hasil["sampai_id"] = mulai
    if not mulai and from_id is None:
        # Penetapan posisi awal HARUS ikut terlindung: ia menyentuh jaringan, dan
        # cabang yang belum pernah sync justru yang paling mungkin mati (baru
        # dipasang, atau memang sedang bermasalah). Sebelum ini, cabang mati yang
        # belum punya cursor melempar keluar dan menjatuhkan SELURUH run —
        # delapan cabang sehat tidak pernah jalan hanya karena satu cabang, yang
        # kebetulan pertama menurut abjad, tidak bisa dihubungi.
        try:
            mulai = posisi_awal(source)
        except (pyodbc.Error, RuntimeError) as exc:
            return _tandai_gagal(row, hasil, exc)
        hasil["sampai_id"] = mulai
        hasil["status"] = "posisi_awal"
        # Dry run tidak menetapkan posisi awal: sebuah pratinjau tidak boleh
        # diam-diam meng-arm cabang ini.
        if not dry_run:
            row.last_id = mulai
            row.save(update_fields=["last_id"])
        return hasil

    buang: list[tuple[dict, str]] = []
    try:
        with mssql.cursor(source) as src_cur, mssql.cursor(hub, autocommit=False) as hub_cur:
            perubahan = ambil_perubahan(src_cur, mulai, limit)
            if not perubahan:
                hasil["status"] = "tak_ada_perubahan"
                return hasil

            cache_kolom: dict[str, list[str]] = {}
            # Perubahan detail dikumpulkan dulu per tabel, baru diambil-ulang
            # sekali di akhir. Satu nota dengan 40 baris muncul 40 kali di feed;
            # tanpa penggabungan ini nota itu dihapus-dan-disalin 40 kali.
            parent_tersentuh: dict[str, set] = {}

            for baris in perubahan:
                tabel, aksi = parse_table_aksi(baris["table_aksi"] or "")
                spec = HUB_TABLE_SPECS.get(tabel)
                if spec is None:
                    hasil["disaring"] += 1
                    _catat_alasan(hasil, f"tabel '{tabel}' di luar daftar-izin")
                    continue
                # Aksi KOSONG bukan aksi tak dikenal, dan bedanya menentukan.
                #
                # Untuk tabel detail aksinya memang tak dipakai sama sekali: kita
                # selalu mengambil ulang seluruh nota dari cabang, jadi
                # insert/update/delete/kosong menghasilkan tindakan yang sama —
                # dan feed nyata penuh baris detail tanpa sufiks aksi (133 dari
                # 2.000 pada uji PRAYA).
                #
                # Untuk tabel BERKUNCI, aksi kosong juga aman: `_terapkan_header`
                # tidak pernah peduli insert atau update — ia SELECT dulu, lalu
                # UPDATE atau INSERT menurut ada-tidaknya baris. Kelonggaran ini
                # dulu hanya diberikan ke tabel detail, dan akibatnya 42 baris
                # `t_pembelian` ANDARIA tanpa sufiks aksi masuk dead-letter
                # padahal tak ada yang salah dengannya.
                #
                # Yang TETAP ditolak adalah aksi non-kosong yang tak dikenal:
                # baris yang bentuknya sungguh-sungguh di luar dugaan layak
                # terlihat, bukan ditebak jadi tulisan.
                if "parent_key" not in spec and aksi and aksi not in AKSI_TULIS and aksi not in AKSI_HAPUS:
                    buang.append((baris, f"aksi '{aksi}' tidak dikenal"))
                    continue
                try:
                    if tabel not in cache_kolom:
                        cache_kolom[tabel] = _kolom_tujuan(hub_cur, tabel)
                    kunci, nilai = parse_formatted_data(baris["formatted_data"] or "")
                    semua = {**nilai, **kunci}

                    if "parent_key" in spec:
                        pk = spec["parent_key"]
                        if pk not in semua:
                            raise ValueError(f"parent '{pk}' tak ada di payload")
                        parent_tersentuh.setdefault(tabel, set()).add(semua[pk])
                        hasil["diterapkan"] += 1
                    elif aksi in AKSI_HAPUS:
                        kolom_kunci, nilai_kunci = _kunci_lengkap(
                            spec, kunci, nilai, set(cache_kolom[tabel])
                        )
                        where = f"[{KOL_SUMBER}] = ? AND " + " AND ".join(
                            f"[{k}] = ?" for k in kolom_kunci
                        )
                        hub_cur.execute(
                            f"DELETE FROM [{tabel}] WHERE {where}",
                            [kd_sumber] + [nilai_kunci[k] for k in kolom_kunci],
                        )
                        hasil["diterapkan"] += 1
                    else:
                        _terapkan_header(
                            hub_cur, tabel, spec, kd_sumber, kunci, nilai, cache_kolom[tabel]
                        )
                        hasil["diterapkan"] += 1
                        # Tiap header yang tersentuh menyeret detailnya ikut
                        # diambil ulang, tanpa menunggu feed detail. Lihat
                        # docstring: sebagian cabang tidak mencatat feed detail
                        # sama sekali, dan nota tanpa baris adalah kerusakan yang
                        # tidak menimbulkan satu pun error.
                        induk = next(iter(spec["key_columns"]))
                        if spec.get("details") and induk in semua:
                            for tdet in spec["details"]:
                                if tdet not in cache_kolom:
                                    cache_kolom[tdet] = _kolom_tujuan(hub_cur, tdet)
                                parent_tersentuh.setdefault(tdet, set()).add(semua[induk])
                except (pyodbc.Error, RuntimeError, ValueError) as exc:
                    buang.append((baris, str(exc.args[-1] if exc.args else exc)))

            for tabel, parents in parent_tersentuh.items():
                try:
                    hasil["nota"] += _ambil_ulang_detail(
                        src_cur, hub_cur, tabel, HUB_TABLE_SPECS[tabel]["parent_key"],
                        kd_sumber, parents, cache_kolom[tabel],
                    )
                except (pyodbc.Error, RuntimeError) as exc:
                    buang.append(
                        ({"id": 0, "table_aksi": tabel, "formatted_data": ""},
                         f"ambil-ulang detail gagal: {exc.args[-1] if exc.args else exc}")
                    )

            if dry_run:
                hub_cur.connection.rollback()
            else:
                hub_cur.connection.commit()

        hasil["dilewati"] = len(buang)
        hasil["sampai_id"] = perubahan[-1]["id"]
        for _, alasan in buang:
            _catat_alasan(hasil, alasan)
        if dry_run:
            hasil["status"] = "dry_run"
            return hasil

        for baris, alasan in buang:
            SyncDeadLetter.objects.create(
                source_profile=source, target_profile=hub,
                feed_id=baris.get("id") or 0,
                table_aksi=(baris.get("table_aksi") or "")[:255],
                formatted_data=baris.get("formatted_data") or "",
                reason=alasan[:255],
            )
        row.last_id = hasil["sampai_id"]
        row.last_synced_at = timezone.now()
        row.last_rows_applied = hasil["diterapkan"]
        row.status = "ok"
        row.error_message = ""
        row.save()
    except (pyodbc.Error, RuntimeError) as exc:
        _tandai_gagal(row, hasil, exc)
    return hasil


def sync_all(hub, sources=None, limit: int = 2000, dry_run: bool = False) -> list[dict]:
    """Tarik semua cabang ke pusat. Tiap cabang punya cursor sendiri, jadi satu
    server mati tidak menahan yang lain."""
    return [
        sync_source(s, hub, limit=limit, dry_run=dry_run)
        for s in (sources if sources is not None else sumber_profiles())
    ]

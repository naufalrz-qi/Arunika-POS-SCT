r"""Sinkronisasi master data antar-server lewat feed `tbl_log_transaksi`.

Jalur ini menggantikan sinkronisasi legacy UNTUK ARAH GUDANG -> TOKO saja, dan
berjalan berdampingan dengannya (tidak ada job SQL Agent yang dimatikan).

## Kenapa ada

Sync legacy mengirim **string SQL** lewat query-string HTTP: trigger menulis
`INSERT ...` ke `tbl_tmp_post`, cursor T-SQL melewatkannya melalui ~20 `REPLACE()`
berantai (spasi->`4D4`, titik->`qttt`, ...), `xp_cmdshell` memanggil curl, dan di
ujung sana penerima menjalankannya apa adanya (`exec (@query)`). Tiga akibat yang
tidak bisa ditambal: data yang kebetulan berisi token sandi itu rusak diam-diam,
payload besar terpotong di batas URL, dan siapa pun yang bisa menyisip di jalur
itu memiliki database penerima sepenuhnya.

Modul ini mengirim **data**, bukan SQL. Kolom dan nilainya dipisah, nama tabel
dan kolom dicocokkan dengan daftar-izin plus katalog server tujuan, nilainya
lewat parameter pyodbc. Tidak ada string SQL yang dirakit dari isi feed.

## Sumbernya `tbl_log_transaksi`, bukan `tbl_tmp_post`

Keduanya diisi trigger legacy yang sama, tapi `tbl_tmp_post` **dihapus** job
legacy begitu terkirim (`DELETE ... WHERE status='sent'`). Poller berjadwal
menit-an akan kehilangan mayoritas barisnya. `tbl_log_transaksi` tidak dihapus
job mana pun dan `id`-nya IDENTITY + clustered PK, jadi `WHERE id > ?` adalah
seek satu baris.

**Tapi ia BUKAN append-only mutlak.** Pemeliharaan database bisa memangkasnya,
dan itu sudah terjadi: 1.469.155 id lenyap dalam satu blok utuh semalam 15-16
Mei 2024 di lini PUSAT saat database dipisah untuk meringankannya (sisa lubang
di seluruh feed cuma 19, tiga di antaranya ~1.000 — lompatan identity-cache
biasa saat layanan restart, bukan penghapusan). Cursor karena itu tidak boleh
menganggap `id` hanya bertambah; `services_sync._periksa_cursor()` memeriksa
kedua ujung feed tiap kali Kesehatan Sync dibuka, dan tanpa itu cursor yang
mendahului ujung feed membuat pasangan ini berhenti mengirim selamanya sambil
melaporkan ketinggalan 0.

Trigger legacy tidak disentuh sama sekali — masih dipakai aplikasi POS lama.

## Bentuk `formatted_data`

Dua prefiks, dan membedakannya penting:

    insert:  val__kd_barang__BOXF3;val__nama__BOX CONTAINER;...
    update:  key__kd_barang__SSRPCS005;val__nama__SISIR KEPALA;...

`key__` menandai kolom kunci, `val__` isinya. Baris `insert` tidak memakai
`key__` sama sekali — kuncinya ikut sebagai `val__`, jadi kunci diambil dari
`key_columns` di spec.

Dua jebakan di parsing:

1. **Nilai bisa mengandung `;` dan `__`** (nama barang). Karena itu pemisahan
   antar-record memakai batas `;(?=(?:key|val)__)`, bukan `split(";")`, dan tiap
   record dipotong pada `__` PERTAMA sesudah prefiks — sisanya utuh jadi nilai.
2. **Nilai kosong dan NULL tidak terbedakan** di format ini. Keduanya jadi
   string kosong. Tidak ada cara memperbaikinya dari sisi sini tanpa mengubah
   trigger, yang tidak boleh disentuh.

## Feed itu PEMBERITAHUAN, bukan sumber data

Isi `formatted_data` tidak dipakai untuk menulis. Ia hanya menjawab "baris mana
yang berubah"; nilainya dibaca ulang dari tabel asli di server sumber.

Sebabnya terukur: trigger legacy **memotong** sebagian kolom saat menyusun
payload. `m_barang.keterangan` di feed tidak pernah lebih dari 30 karakter,
padahal kolomnya `varchar(50)` dan tabelnya menyimpan 45 — jadi menulis dari
payload akan MEMENDEKKAN keterangan yang sudah benar di toko. Total payload
hanya 335 karakter, jadi ini bukan batas panjang keseluruhan, melainkan
pemotongan per kolom di dalam trigger. Trigger tidak boleh disentuh.

Membaca ulang dari sumber juga menutup kelas masalah yang sama yang belum
ketahuan di kolom lain, dan sekaligus menggabungkan tiga edit pada barang yang
sama dalam satu batch jadi satu tulisan.

## Efek samping menulis ke toko: TERGANTUNG CABANG

Menulis ke server tujuan bisa menyalakan trigger legacy di server itu, yang lalu
mengantrekan barisnya ke `tbl_tmp_post` untuk dikirim ke web legacy oleh job lama.
Tapi cakupan trigger **berbeda-beda tiap cabang**, jadi jangan menganggapnya
berlaku merata:

- `testgudang` (salinan lokal): antrean naik 4 -> ~1.244 saat 434 baris ditulis.
- `RUMAK` (toko sungguhan): antrean tetap **0** — `m_barang` di sana tidak punya
  trigger sama sekali.

Sebelum menyalakan sebuah toko, periksa `sys.triggers` di tabel yang difan-out
kalau ingin tahu apakah toko itu akan ikut mengantre. Kalaupun mengantre, itu
pemborosan, bukan kerusakan: endpoint legacy memakai `INSERT IGNORE` dan sudah
punya penanganan `gagalDuplicate`. Dan kalau jalur GET legacy JUGA menurunkan
master data yang sama, keduanya menulis nilai akhir yang sama — saling menimpa
tanpa menyimpang, karena kedua jalur idempoten.

Halaman Kesehatan Sync memperlihatkan antrean tiap toko, jadi kalau ada yang
menumpuk itu akan terlihat, bukan ditemukan berbulan-bulan kemudian.

## `divisi_id` bukan kolom

Trigger menambahkan `val__divisi_id__<asal>` ke hampir semua payload sebagai
penanda server asal — padahal `m_barang_satuan` dan `m_merk` tidak punya kolom
itu. Karena itu kolom payload SELALU diiris dengan katalog nyata server tujuan
(`sys.columns`) sebelum ditulis. Tanpa itu setiap INSERT gagal.
"""
from __future__ import annotations

import re

import pyodbc
from django.utils import timezone

from apps.core.models import FeedSyncCursor, SyncDeadLetter
from core import mssql

# Daftar-izin. Apa pun di luar ini tidak pernah disentuh — itulah yang membuat
# feed asing tidak bisa jadi perintah.
#
# `columns=None` berarti "kolom apa pun yang memang ada di tabel tujuan".
# Aman secara mekanis (nama kolom berasal dari katalog server tujuan, nilainya
# parameter), dan cukup untuk tabel katalog yang seluruh isinya memang milik
# gudang. Isi eksplisit hanya diperlukan kalau sebagian kolomnya milik toko.
FEED_TABLE_SPECS = {
    "m_barang": {"key_columns": ["kd_barang"], "columns": None},
    "m_barang_satuan": {"key_columns": ["kd_barang", "kd_satuan"], "columns": None},
    "m_merk": {"key_columns": ["kd_merk"], "columns": None},
    # SENGAJA TIDAK DIDAFTARKAN:
    #
    # m_supplier — supplier itu URUSAN GUDANG, bukan urusan toko. Gudang yang
    #   membeli, jadi gudang yang menyimpan daftar supplier lengkap; server toko
    #   grosir/ecer hanya memakai segelintir supplier miliknya sendiri (di
    #   PAGESANGAN: 3 baris). Mendorong daftar gudang ke sana membanjiri layar
    #   pembelian toko dengan ratusan nama yang tak pernah mereka pakai — dan
    #   itu sudah terjadi sekali, harus dipulihkan manual dari PAGESANGAN.
    #   Aturannya satu arah dan permanen: supplier TIDAK PERNAH difan-out ke
    #   toko. Ke AMPHOREUS tetap ikut (`hub_sync.SEED_TABLES`) — pusat itu milik
    #   kita sendiri, dan laporan pembelian gudang butuh namanya.
    # m_barang_divisi — membawa stok_awal / stok_min / harga_beli_awal yang
    #   MILIK TIAP TOKO. Mendorong baris gudang ke sana menimpa konfigurasi stok
    #   toko itu dengan angka gudang. Kalau nanti dibutuhkan, daftarkan dengan
    #   `columns` eksplisit (mungkin hanya status/point), jangan None.
    # m_customer — belum pasti pelanggan itu global atau per-toko.
    # t_* (penjualan/pembelian/opname/mutasi) — transaksi milik server yang
    #   membuatnya; tidak ada arti menyalinnya ke toko lain.
}

AKSI_TULIS = {"insert", "update"}
AKSI_HAPUS = {"delete"}

_PISAH_RECORD = re.compile(r";(?=(?:key|val)__)")
_PREFIKS = ("key__", "val__")


def parse_formatted_data(raw: str) -> tuple[dict, dict]:
    """`formatted_data` -> (kunci, nilai).

    Potongan yang tidak berprefiks `key__`/`val__` dilewati: format ini tidak
    punya escape, jadi satu-satunya tafsir yang jujur untuk potongan tak dikenal
    adalah "bukan field", bukan menebak.
    """
    kunci: dict[str, str] = {}
    nilai: dict[str, str] = {}
    if not raw:
        return kunci, nilai
    for bagian in _PISAH_RECORD.split(raw):
        if not bagian.startswith(_PREFIKS):
            continue
        prefiks, sisa = bagian[:5], bagian[5:]
        kolom, pemisah, isi = sisa.partition("__")
        if not pemisah or not kolom:
            continue
        (kunci if prefiks == "key__" else nilai)[kolom] = isi
    return kunci, nilai


def parse_table_aksi(table_aksi: str) -> tuple[str, str]:
    """`"m_barang__update"` -> `("m_barang", "update")`.

    Ada baris tanpa sufiks aksi di feed nyata (`t_pembelian_detail`,
    `t_opname_stok`). Aksinya dikembalikan kosong dan pemanggil membuangnya ke
    dead-letter — menebak "mungkin insert" pada baris yang bentuknya sudah tak
    terduga adalah cara paling rapi untuk merusak data diam-diam.
    """
    if not table_aksi:
        return "", ""
    tabel, pemisah, aksi = table_aksi.rpartition("__")
    if not pemisah:
        return table_aksi, ""
    return tabel, aksi


def _kolom_tujuan(cur, tabel: str) -> list[str]:
    """Kolom `tabel` di server TUJUAN yang boleh ditulis (bukan computed/identity).

    Ditanyakan ke tujuan, bukan sumber: yang menerima tulisan dialah yang
    menentukan apa yang sah. Sekaligus menangkap tabel yang belum ada — pola dan
    alasannya sama dengan `cdc_sync._insertable_columns`.
    """
    cur.execute("SELECT OBJECT_ID(?)", [tabel])
    if cur.fetchone()[0] is None:
        raise RuntimeError(f"Tabel '{tabel}' tidak ada di server tujuan.")
    cur.execute(
        "SELECT name FROM sys.columns "
        "WHERE object_id = OBJECT_ID(?) AND is_computed = 0 AND is_identity = 0 "
        "ORDER BY column_id",
        [tabel],
    )
    return [r[0] for r in cur.fetchall()]


def _kunci_lengkap(spec: dict, kunci: dict, nilai: dict, boleh: set) -> tuple[list[str], dict]:
    """Kolom kunci menurut SPEC, beserta nilainya. Menolak kunci yang tak lengkap.

    Otoritasnya `spec["key_columns"]`, bukan prefiks `key__` di payload. Kalau
    payload yang menentukan, satu baris `m_barang_satuan` yang kebetulan hanya
    membawa `key__kd_barang` (tanpa `kd_satuan`) akan menghasilkan
    `WHERE kd_barang = ?` — dan satu perubahan harga menimpa SELURUH satuan
    barang itu. Kunci yang menyempit harus jadi kegagalan yang terlihat
    (dead-letter), bukan WHERE yang melebar diam-diam.
    """
    kolom_kunci = [k for k in spec["key_columns"] if k in boleh]
    if len(kolom_kunci) != len(spec["key_columns"]):
        hilang = set(spec["key_columns"]) - set(kolom_kunci)
        raise ValueError(f"kolom kunci {sorted(hilang)} tak ada di tabel tujuan")
    semua = {**nilai, **kunci}
    hilang = [k for k in kolom_kunci if k not in semua]
    if hilang:
        raise ValueError(f"nilai kunci tak lengkap: {hilang}")
    return kolom_kunci, {k: semua[k] for k in kolom_kunci}


def _terapkan_baris(cur, tabel: str, spec: dict, kunci: dict, nilai: dict, kolom_ada: list[str]) -> None:
    """Tulis satu baris ke tujuan: cek ada, lalu UPDATE atau INSERT.

    UPDATE (bukan DELETE-lalu-INSERT seperti `cdc_sync`) karena `formatted_data`
    hanya membawa kolom yang ditulis trigger; DELETE-lalu-INSERT akan mengosongkan
    kolom yang tidak disebut, UPDATE hanya menyentuh yang disebut.

    **Keberadaan baris ditentukan lewat SELECT, BUKAN lewat `cur.rowcount`
    sesudah UPDATE.** Ini bukan gaya penulisan, ini perbaikan bug yang terukur:
    tabel di server toko punya trigger legacy, trigger AFTER UPDATE di SQL Server
    tetap menyala walau UPDATE mengenai NOL baris, dan `INSERT INTO tbl_tmp_post`
    di dalam trigger itu membuat `rowcount` terbaca 1. Kode lama menyimpulkan
    "sudah ter-update" lalu melewatkan INSERT-nya — barang baru tidak pernah
    sampai ke toko, tanpa error, tanpa dead-letter, dan tetap terhitung
    "diterapkan". Terukur di testgudang: `m_barang__insert` GTK315 ada di feed,
    diproses, dan barisnya tetap tidak ada di tujuan.

    AMPHOREUS tidak punya trigger, jadi pusat tidak pernah memperlihatkan gejala
    ini — hanya toko. Satu SELECT tambahan per baris (seek lewat kunci) adalah
    harga yang murah untuk kepastian.
    """
    izin = spec.get("columns")
    boleh = set(kolom_ada) if izin is None else (set(izin) & set(kolom_ada))

    kolom_kunci, nilai_kunci = _kunci_lengkap(spec, kunci, nilai, boleh)
    semua = {**nilai, **kunci}
    where = " AND ".join(f"{k} = ?" for k in kolom_kunci)
    arg_kunci = [nilai_kunci[k] for k in kolom_kunci]

    cur.execute(f"SELECT 1 FROM {tabel} WHERE {where}", arg_kunci)
    sudah_ada = cur.fetchone() is not None

    if sudah_ada:
        set_kolom = [k for k in semua if k in boleh and k not in kolom_kunci]
        if set_kolom:
            cur.execute(
                f"UPDATE {tabel} SET {', '.join(f'{k} = ?' for k in set_kolom)} WHERE {where}",
                [semua[k] for k in set_kolom] + arg_kunci,
            )
        return

    kolom_insert = [k for k in semua if k in boleh]
    cur.execute(
        f"INSERT INTO {tabel} ({', '.join(kolom_insert)}) "
        f"VALUES ({', '.join('?' * len(kolom_insert))})",
        [semua[k] for k in kolom_insert],
    )


def _hapus_baris(cur, tabel: str, spec: dict, kunci: dict, nilai: dict, kolom_ada: list[str]) -> None:
    """DELETE by kunci. Kunci lengkap wajib — di sini bahkan lebih keras
    akibatnya daripada di UPDATE: WHERE yang melebar menghapus baris."""
    kolom_kunci, nilai_kunci = _kunci_lengkap(spec, kunci, nilai, set(kolom_ada))
    where = " AND ".join(f"{k} = ?" for k in kolom_kunci)
    cur.execute(f"DELETE FROM {tabel} WHERE {where}", [nilai_kunci[k] for k in kolom_kunci])


def _cursor_row(source, target) -> FeedSyncCursor:
    row, _ = FeedSyncCursor.objects.get_or_create(source_profile=source, target_profile=target)
    return row


def posisi_awal(source) -> int:
    """`MAX(id)` feed sumber saat ini — titik mulai untuk pasangan baru.

    BUKAN 0. Feed sumber berisi jutaan baris riwayat bertahun-tahun; memulai dari
    nol berarti run pertama memutar ulang seluruh sejarah gudang ke setiap toko.
    Alasannya sejenis dengan snapshot LSN pra-copy di `cdc_sync.backfill_table`:
    posisi awal ditetapkan sadar-sadar, bukan diwarisi dari nilai default.
    """
    with mssql.cursor(source) as cur:
        cur.execute("SELECT ISNULL(MAX(id), 0) FROM tbl_log_transaksi")
        return int(cur.fetchone()[0] or 0)


def ambil_perubahan(source, dari_id: int, limit: int = 2000) -> list[dict]:
    """Baris feed sesudah `dari_id`, urut naik. Seek lewat clustered PK."""
    with mssql.cursor(source) as cur:
        cur.execute(
            "SELECT TOP (?) id, waktu, aksi, divisi_id, formatted_data, table_aksi "
            "FROM tbl_log_transaksi WHERE id > ? ORDER BY id",
            [limit, dari_id],
        )
        kolom = [c[0] for c in cur.description]
        return [dict(zip(kolom, r)) for r in cur.fetchall()]


def _kolom_sumber(src_cur, tabel: str) -> list[str]:
    """Kolom `tabel` di server SUMBER (tanpa computed)."""
    src_cur.execute("SELECT OBJECT_ID(?)", [tabel])
    if src_cur.fetchone()[0] is None:
        raise RuntimeError(f"Tabel '{tabel}' tidak ada di server sumber.")
    src_cur.execute(
        "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?) AND is_computed = 0 "
        "ORDER BY column_id",
        [tabel],
    )
    return [r[0] for r in src_cur.fetchall()]


def _baca_dari_sumber(src_cur, tabel: str, spec: dict, kv: dict, kolom: list[str]):
    """Keadaan TERKINI satu baris di sumber, atau None kalau sudah tidak ada.

    Inilah yang membuat pemotongan di `formatted_data` tidak lagi jadi masalah:
    payload cuma dipakai untuk tahu kunci mana yang berubah, isinya dibaca dari
    tabel aslinya.
    """
    where = " AND ".join(f"[{k}] = ?" for k in spec["key_columns"])
    src_cur.execute(
        f"SELECT {', '.join(f'[{c}]' for c in kolom)} FROM [{tabel}] WHERE {where}",
        [kv[k] for k in spec["key_columns"]],
    )
    baris = src_cur.fetchone()
    return None if baris is None else dict(zip(kolom, baris))


def _catat_alasan(hasil: dict, alasan: str) -> None:
    """Histogram alasan per run.

    Baris yang disaring tidak disimpan ke mana pun, dan pada dry run baris
    dead-letter pun tidak ditulis — tanpa histogram ini angka "2.566 dilewati"
    tak bisa dibedakan antara penyaringan yang disengaja dan semuanya gagal.
    """
    hasil["alasan"][alasan] = hasil["alasan"].get(alasan, 0) + 1


def _dead_letter(source, target, baris: dict, alasan: str) -> None:
    SyncDeadLetter.objects.create(
        source_profile=source,
        target_profile=target,
        feed_id=baris.get("id") or 0,
        table_aksi=(baris.get("table_aksi") or "")[:255],
        formatted_data=baris.get("formatted_data") or "",
        reason=alasan[:255],
    )


def sync_pair(source, target, limit: int = 2000, dry_run: bool = False, from_id: int | None = None) -> dict:
    """Terapkan satu batch feed `source` ke `target`.

    Cursor hanya maju SESUDAH commit. Satu baris bermasalah masuk dead-letter dan
    run diteruskan — pola `sync_all` di `cdc_sync`, dan kebalikan dari `goto hell`
    di job legacy yang membuat sisa antrean terlewat sesiklus.
    """
    row = _cursor_row(source, target)
    mulai = from_id if from_id is not None else row.last_id
    if not mulai and from_id is None:
        mulai = posisi_awal(source)
        # Dry run tidak menetapkan posisi awal. Kalau ia menetapkannya, sebuah
        # pratinjau diam-diam meng-arm pasangan ini: run berikutnya (yang sungguhan)
        # mulai dari titik yang dipilih pratinjau, bukan dari keputusan sadar.
        if not dry_run:
            row.last_id = mulai
            row.save(update_fields=["last_id"])
        return {
            "source": source.name, "target": target.name, "status": "posisi_awal",
            "diterapkan": 0, "disaring": 0, "dilewati": 0, "dilewati_hilang": 0,
            "sampai_id": mulai, "error": "", "alasan": {},
        }

    hasil = {
        "source": source.name, "target": target.name, "status": "ok",
        "diterapkan": 0, "disaring": 0, "dilewati": 0, "dilewati_hilang": 0,
            "sampai_id": mulai, "error": "", "alasan": {},
    }
    try:
        perubahan = ambil_perubahan(source, mulai, limit)
        if not perubahan:
            hasil["status"] = "tak_ada_perubahan"
            return hasil

        buang: list[tuple[dict, str]] = []
        # Fase 1 — baca feed sebagai PEMBERITAHUAN saja: kumpulkan kunci mana
        # yang berubah. Nilai di `formatted_data` tidak dipakai untuk menulis;
        # lihat catatan "Feed itu pemberitahuan" di docstring modul.
        tersentuh: dict[str, dict] = {}
        hapus: list[tuple[str, dict, dict, dict]] = []
        for baris in perubahan:
            tabel, aksi = parse_table_aksi(baris["table_aksi"] or "")
            spec = FEED_TABLE_SPECS.get(tabel)
            if spec is None:
                # DISARING, bukan gagal. Tabel transaksi memang sengaja tidak
                # difan-out, dan itu mayoritas isi feed — pada uji nyata 2.566
                # dari 3.000 baris. Menulis dead-letter untuk tiap satunya
                # akan menimbun ribuan baris per tick dan menenggelamkan
                # kegagalan yang sungguhan. Dihitung saja.
                hasil["disaring"] += 1
                _catat_alasan(hasil, f"tabel '{tabel}' di luar daftar-izin")
                continue
            if aksi not in AKSI_TULIS and aksi not in AKSI_HAPUS:
                # Ini beda: tabelnya MEMANG difan-out, tapi bentuk barisnya
                # tak terduga. Layak disimpan supaya bisa diperiksa.
                buang.append((baris, f"aksi '{aksi}' tidak dikenal"))
                continue
            kunci, nilai = parse_formatted_data(baris["formatted_data"] or "")
            semua = {**nilai, **kunci}
            hilang = [k for k in spec["key_columns"] if k not in semua]
            if hilang:
                buang.append((baris, f"nilai kunci tak lengkap: {hilang}"))
                continue
            kv = {k: semua[k] for k in spec["key_columns"]}
            if aksi in AKSI_HAPUS:
                hapus.append((tabel, spec, kunci, nilai))
            else:
                # dict berkunci tuple: tiga edit pada barang yang sama dalam satu
                # batch cukup menghasilkan satu tulisan, bukan tiga.
                tersentuh.setdefault(tabel, {})[tuple(kv.values())] = kv

        # Fase 2 — ambil keadaan TERKINI tiap baris dari sumber, lalu tulis.
        with mssql.cursor(source) as src_cur, mssql.cursor(target, autocommit=False) as cur:
            cache_kolom: dict[str, list[str]] = {}
            cache_sumber: dict[str, list[str]] = {}
            for tabel, spec, kunci, nilai in hapus:
                try:
                    if tabel not in cache_kolom:
                        cache_kolom[tabel] = _kolom_tujuan(cur, tabel)
                    _hapus_baris(cur, tabel, spec, kunci, nilai, cache_kolom[tabel])
                    hasil["diterapkan"] += 1
                except (pyodbc.Error, RuntimeError, ValueError) as exc:
                    buang.append(({"id": 0, "table_aksi": tabel, "formatted_data": ""},
                                  str(exc.args[-1] if exc.args else exc)))

            for tabel, kunci_kunci in tersentuh.items():
                spec = FEED_TABLE_SPECS[tabel]
                try:
                    if tabel not in cache_kolom:
                        cache_kolom[tabel] = _kolom_tujuan(cur, tabel)
                        cache_sumber[tabel] = _kolom_sumber(src_cur, tabel)
                except (pyodbc.Error, RuntimeError) as exc:
                    buang.append(({"id": 0, "table_aksi": tabel, "formatted_data": ""},
                                  str(exc.args[-1] if exc.args else exc)))
                    continue
                # Hanya kolom yang ada di KEDUA sisi. Skema cabang bisa sedikit
                # berbeda; kolom yang cuma ada di satu sisi bukan alasan gagal.
                kolom = [c for c in cache_sumber[tabel] if c in set(cache_kolom[tabel])]
                for kv in kunci_kunci.values():
                    try:
                        nilai = _baca_dari_sumber(src_cur, tabel, spec, kv, kolom)
                        if nilai is None:
                            # Sudah tidak ada di sumber. Tidak dihapus di tujuan:
                            # feed master tidak pernah membawa aksi delete, jadi
                            # "tak ketemu" lebih mungkin berarti kita salah baca
                            # daripada berarti perintah menghapus.
                            hasil["dilewati_hilang"] += 1
                            continue
                        _terapkan_baris(cur, tabel, spec, kv, nilai, cache_kolom[tabel])
                        hasil["diterapkan"] += 1
                    except (pyodbc.Error, RuntimeError, ValueError) as exc:
                        buang.append((
                            {"id": 0, "table_aksi": tabel, "formatted_data": str(kv)},
                            str(exc.args[-1] if exc.args else exc),
                        ))
            if dry_run:
                cur.connection.rollback()
            else:
                cur.connection.commit()

        hasil["dilewati"] = len(buang)
        hasil["sampai_id"] = perubahan[-1]["id"]
        for _, alasan in buang:
            _catat_alasan(hasil, alasan)
        if dry_run:
            hasil["status"] = "dry_run"
            return hasil

        for baris, alasan in buang:
            _dead_letter(source, target, baris, alasan)
        row.last_id = hasil["sampai_id"]
        row.last_synced_at = timezone.now()
        row.last_rows_applied = hasil["diterapkan"]
        row.status = "ok"
        row.error_message = ""
        row.save()
    except (pyodbc.Error, RuntimeError) as exc:
        pesan = str(exc.args[-1] if exc.args else exc)
        row.status = "failed"
        row.error_message = pesan[:255]
        row.save()
        hasil["status"] = "failed"
        hasil["error"] = pesan
    return hasil


def sync_all(source, targets, limit: int = 2000, dry_run: bool = False) -> list[dict]:
    """Fan-out satu sumber ke banyak tujuan. Tiap tujuan punya cursor sendiri,
    jadi satu toko yang mati tidak menahan yang lain."""
    return [sync_pair(source, t, limit=limit, dry_run=dry_run) for t in targets]

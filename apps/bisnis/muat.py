"""Memuat data legacy ke tabel Arunika SUNGGUHAN.

Sampai berkas ini ada, mode Arunika tak pernah punya satu baris pun: `init_arunika`
membuat databasenya, menjalankan migrasi, lalu memasang view adapter mode
**legacy** -- yang membaca legacy lintas-database. Tabel `dbo.*` hasil migrasi
berdiri kosong, dan §8.3 dokumen rancangan mencatat bahwa beberapa pertanyaan
tak bisa dijawab sampai ia berisi.

## Transformasinya sudah ada, dan itu inti rancangan modul ini

Yang dibaca BUKAN tabel legacy melainkan `arunika_src.*` milik sebuah database
Arunika bermode legacy. View-view itu sudah memulangkan persis bentuk Arunika --
lengkap dengan kebijakan RTRIM, pemetaan `status` yang berkali-kali nyaris
salah, dan formula uang yang dibangkitkan dari `reports.*`. Membaca dari sana
berarti **nol keputusan pemetaan disalin ulang di sini**; kalau sebuah view
berubah, pemuat ini ikut berubah dengan sendirinya.

    [DB Arunika sumber, mode legacy]        [DB Arunika tujuan, mode arunika]
      arunika_src.penjualan  ── SELECT ──>    dbo.penjualan
        (membaca legacy)                        (tabel nyata)

## Yang diterjemahkan di sini, dan cuma ini

Bentuk baca memakai KODE bisnis (`pelanggan_kode`); tabel berkunci `id`
pengganti. Satu-satunya kerja modul ini menukar kode jadi id, memakai peta yang
dibangun dari tabel tujuan setelah tiap tingkat selesai dimuat.

## Yang TIDAK dimuat, dan sebabnya

`pergerakan_stok` -- di mode Arunika ia tabel nyata, tapi isinya bukan salinan
melainkan turunan dari seluruh dokumen. Membangunnya pekerjaan tersendiri, dan
laporan stok belum termasuk 18 yang sudah pindah.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from __future__ import annotations

import datetime as dt

from django.apps import apps as djapps
from django.db import connections
from django.utils import timezone

from apps.bisnis import master_src

# Ukuran batch INSERT. Bukan angka bulat sembarangan: parameter per statement
# di SQL Server dibatasi 2.100, dan baris terlebar di sini (`penjualan`, 19
# kolom) berarti ~110 baris per statement kalau ORM menggabungkannya. 500 aman
# untuk seluruh entitas dan tetap jauh lebih murah daripada satu-satu.
BATCH = 500

# Kolom view yang memang tak punya tempat di model, beserta alasannya.
# Ditulis eksplisit supaya sebuah kolom yang HILANG tak pernah lolos sebagai
# "mungkin sengaja".
DIABAIKAN = {
    # Konstan 0 di kedua server, tak dirujuk objek legacy mana pun -- sengaja
    # tidak diwarisi model (lihat `Barang`).
    ("barang", "status_pinjam"),
    # Slot 2-4 rantai diskon. Model menyimpan satu `diskon_ghb`; slot 1
    # dipetakan ke sana, sisanya HARUS nol -- dan itu diperiksa, bukan
    # diasumsikan (`_periksa_slot_diskon`).
    ("penjualan", "diskon2"), ("penjualan", "diskon3"), ("penjualan", "diskon4"),
    ("pembelian", "diskon2"), ("pembelian", "diskon3"), ("pembelian", "diskon4"),
    ("penjualan_baris", "diskon2"), ("penjualan_baris", "diskon3"),
    ("penjualan_baris", "diskon4"),
    ("pembelian_baris", "diskon2"), ("pembelian_baris", "diskon3"),
    ("pembelian_baris", "diskon4"),
    # Agregat yang dihitung view dari barisnya sendiri.
    ("penjualan_order", "jml_item"), ("penjualan_order", "total_qty"),
}

# Kolom baris yang membawa `tanggal`/`divisi_kode` kepalanya. Ada di bentuk BACA
# demi laporan tingkat-baris (lihat catatan di `penjualan_baris`), tapi di tabel
# nyata ia milik kepala -- menyimpannya dua kali mengundang keduanya menyimpang.
BAWAAN_KEPALA = ("tanggal", "divisi_kode")

# view -> field model, untuk yang namanya memang berbeda.
NAMA_LAIN = {
    ("penjualan", "diskon1"): "diskon_ghb",
    ("pembelian", "diskon1"): "diskon_ghb",
    ("penjualan_baris", "diskon1"): "diskon_ghb",
    ("pembelian_baris", "diskon1"): "diskon_ghb",
}

# Kolom kode yang menunjuk kolom id TELANJANG, bukan FK sungguhan.
# `Penjualan.pelanggan_id` dan `Pembelian.pemasok_id` masih `BigIntegerField`
# ("FK menyusul di irisan berikutnya"), jadi ORM tak bisa menyelesaikannya
# sendiri dan kodenya ditukar id di sini.
ID_TELANJANG = {
    ("penjualan", "pelanggan_kode"): ("pelanggan", "pelanggan_id"),
    ("pembelian", "pemasok_kode"): ("pemasok", "pemasok_id"),
}

# Urutan muat. Ditulis tangan, bukan diturunkan dari FK: urutan yang salah gagal
# dengan galat integritas yang menyebut tabel, bukan sebabnya, dan daftar
# sepanjang ini lebih mudah dibaca daripada penyelesai ketergantungan.
URUTAN = (
    # Tingkat 1 -- tanpa rujukan
    "negara", "bank", "satuan", "merek", "kategori", "model_barang", "warna",
    "bahan", "kategori_biaya", "voucher", "cara_bayar", "divisi", "pengguna",
    "pegawai",
    # Tingkat 2-3 -- mitra & wilayah
    "kota", "pelanggan", "pemasok", "kas",
    # Tingkat 4-5 -- katalog
    "barang", "barang_satuan", "barang_divisi",
    # Tingkat 6 -- kepala dokumen
    "penjualan", "pembelian", "penjualan_order", "penjualan_retur",
    "pembelian_retur", "koreksi_stok", "jurnal_kas",
    # Tingkat 7 -- baris dokumen
    "penjualan_baris", "pembelian_baris", "penjualan_order_baris",
    "penjualan_retur_baris", "pembelian_retur_baris", "koreksi_stok_baris",
)

# Entitas berjendela tanggal. Master tak pernah dipotong -- sebuah barang yang
# hilang membuat notanya gagal dimuat, bukan sekadar kurang lengkap.
KOLOM_TANGGAL = {
    "penjualan": "tanggal", "pembelian": "tanggal", "penjualan_order": "tanggal",
    "penjualan_retur": "tanggal", "pembelian_retur": "tanggal",
    "koreksi_stok": "tanggal", "jurnal_kas": "tanggal",
    "penjualan_baris": "tanggal", "pembelian_baris": "tanggal",
    "penjualan_order_baris": "tanggal", "penjualan_retur_baris": "tanggal",
    "pembelian_retur_baris": "tanggal", "koreksi_stok_baris": "tanggal",
}


def _model(nama: str):
    for m in djapps.get_app_config("bisnis").get_models():
        if m._meta.db_table == nama:
            return m
    raise LookupError(f"Tak ada model bertabel '{nama}'")


def _kunci_alami(model) -> str:
    """Kolom yang dipakai baris lain merujuk entitas ini: `kode` atau `nomor`."""
    punya = {f.name for f in model._meta.get_fields() if getattr(f, "concrete", False)}
    for k in ("kode", "nomor"):
        if k in punya:
            return k
    return ""


def _rencana(nama: str) -> list[tuple[str, str, str]]:
    """(kolom view, jenis, target) untuk satu entitas.

    jenis: `langsung` (field biasa), `fk` (tukar kode/nomor jadi objek), atau
    `id` (tukar jadi id telanjang).
    """
    model = _model(nama)
    field = {f.name for f in model._meta.get_fields() if getattr(f, "concrete", False)}
    fk = {f.name for f in model._meta.get_fields() if getattr(f, "many_to_one", False)}
    out = []
    for kol in master_src._MASTER[nama]["kolom"]:
        if (nama, kol) in DIABAIKAN:
            continue
        if (nama, kol) in ID_TELANJANG:
            entitas, target = ID_TELANJANG[(nama, kol)]
            out.append((kol, "id", f"{entitas}|{target}"))
            continue
        alias = NAMA_LAIN.get((nama, kol))
        if alias:
            out.append((kol, "langsung", alias))
            continue
        if kol in fk:
            raise RuntimeError(f"{nama}.{kol}: kolom view bernama sama dengan FK")
        for akhiran in ("_kode", "_nomor"):
            medan = kol[: -len(akhiran)]
            if kol.endswith(akhiran) and medan in fk:
                # Kuncinya ENTITAS tujuan, bukan nama field. Keduanya sering
                # berbeda -- `model_kode` menunjuk field `model` yang tabelnya
                # `model_barang`, dan `satuan_dasar_kode` menunjuk `satuan`.
                # Versi pertama memakai nama field dan menjatuhkan SELURUH
                # 53.612 barang tanpa satu galat pun: tiap pencarian peta meleset,
                # tiap baris dihitung "rujukan tak ada".
                f = model._meta.get_field(medan)
                tujuan = f.related_model._meta.db_table
                out.append((kol, "fk_null" if f.null else "fk", f"{medan}|{tujuan}"))
                break
        else:
            if kol in field:
                out.append((kol, "langsung", kol))
            elif nama.endswith("_baris") and kol in BAWAAN_KEPALA:
                continue  # milik kepala; lihat BAWAAN_KEPALA
            else:
                raise RuntimeError(
                    f"{nama}.{kol}: tak ada field model dan tak terdaftar di "
                    "DIABAIKAN. Tambahkan pemetaannya alih-alih membiarkannya hilang."
                )
    return out


def _periksa_slot_diskon(baris: list[dict], nama: str) -> None:
    """Slot 2-4 harus nol; kalau tidak, memuat slot 1 saja MENGHILANGKAN data.

    Diukur sebelumnya: sisi jual nol pada seluruh 3,56 juta baris detail dan
    527 ribu kepala di kedua server; sisi beli memakai slot kedua pada 10 baris
    testGUdang. Karena itu ini pemeriksaan, bukan komentar -- sumber yang
    memakainya harus berhenti, bukan dipotong diam-diam.
    """
    kena = []
    for i, b in enumerate(baris):
        for s in (2, 3, 4):
            if float(b.get(f"diskon{s}") or 0) != 0:
                kena.append((i, s, b.get(f"diskon{s}")))
    if kena:
        contoh = ", ".join(f"baris#{i} diskon{s}={v}" for i, s, v in kena[:5])
        raise RuntimeError(
            f"{nama}: {len(kena)} nilai pada slot diskon 2-4 yang BUKAN nol "
            f"({contoh}). Model hanya menyimpan satu `diskon_ghb`, jadi "
            "memuatnya akan menghilangkan data. Putuskan pemetaannya dulu."
        )


def _peta_kode(alias: str, model) -> dict:
    kunci = _kunci_alami(model)
    if not kunci:
        return {}
    return {
        (k or "").strip().upper(): i
        for i, k in model.objects.using(alias).values_list("id", kunci)
    }


def muat_entitas(nama, src_cur, alias, dari=None, sampai=None, peta=None) -> dict:
    """Muat satu entitas. Pulangkan {'dibaca', 'ditulis', 'dilewati'}."""
    model = _model(nama)
    rencana = _rencana(nama)
    kol_tanggal = KOLOM_TANGGAL.get(nama)

    pilih = ", ".join(k for k, _, _ in rencana)
    # `diskon2..4` ikut DIBACA meski tak dimuat -- hanya supaya bisa diperiksa.
    tambahan = [k for k in master_src._MASTER[nama]["kolom"]
                if (nama, k) in DIABAIKAN and k.startswith("diskon")]
    if tambahan:
        pilih += ", " + ", ".join(tambahan)
    sql = f"SELECT {pilih} FROM {master_src.SKEMA}.{nama}"
    params = []
    if kol_tanggal and dari and sampai:
        sql += f" WHERE {kol_tanggal} >= ? AND {kol_tanggal} <= ?"
        params = [dari, sampai]
    src_cur.execute(sql, *params)
    kolom = [c[0] for c in src_cur.description]
    baris = [dict(zip(kolom, r)) for r in src_cur.fetchall()]
    if tambahan:
        _periksa_slot_diskon(baris, nama)

    peta = peta if peta is not None else {}
    objek, alasan = [], {}
    for b in baris:
        nilai, hilang, sebab = {}, False, ""
        for kol, jenis, target in rencana:
            v = b.get(kol)
            if isinstance(v, dt.datetime) and timezone.is_naive(v):
                # Legacy menyimpan waktu LOKAL tanpa zona. USE_TZ aktif, jadi
                # menyerahkannya apa adanya membuat Django membacanya sebagai
                # UTC -- setiap cap waktu bergeser sebesar offset zona, diam-diam.
                v = timezone.make_aware(v, timezone.get_current_timezone())
            if jenis == "langsung":
                nilai[target] = v
            elif jenis in ("fk", "fk_null"):
                medan, entitas = target.split("|")
                if v is None:
                    # NULL pada FK WAJIB bukan "tanpa rujukan" melainkan baris
                    # yang tak bisa hidup di bentuk baru. Terukur: 62 barang di
                    # grosirPusat dan 167 di testGUdang tak punya satuan dasar
                    # sama sekali -- tak ada baris `m_barang_satuan` ber-jumlah 1.
                    # Dilewati dan DIHITUNG, bukan diledakkan di tengah muat.
                    if jenis == "fk":
                        hilang, sebab = True, f"{kol} kosong (wajib)"
                        break
                    nilai[f"{medan}_id"] = None
                    continue
                pid = peta.get(entitas, {}).get(str(v).strip().upper())
                if pid is None:
                    hilang, sebab = True, f"{kol}={v!r} tak ada di {entitas}"
                    break
                nilai[f"{medan}_id"] = pid
            else:  # id telanjang
                entitas, medan = target.split("|")
                nilai[medan] = (peta.get(entitas, {}).get(str(v).strip().upper())
                                if v is not None else None)
        if hilang:
            alasan[sebab] = alasan.get(sebab, 0) + 1
            continue
        objek.append(model(**nilai))

    model.objects.using(alias).bulk_create(objek, batch_size=BATCH)
    return {
        "dibaca": len(baris),
        "ditulis": len(objek),
        "dilewati": sum(alasan.values()),
        # Sebab dikelompokkan, bukan cuma dihitung: "1.106.476 dilewati" tak
        # memberi tahu apa pun, sementara "satuan_dasar_kode kosong (wajib) x62"
        # langsung menunjuk kondisi datanya.
        "alasan": alasan,
    }


def perbarui_peta(peta: dict, alias: str, nama: str) -> dict:
    """Tambahkan peta kode->id entitas `nama` yang BARU SAJA dimuat.

    Bertahap, bukan dibangun ulang tiap entitas: versi pertama memuat ulang
    seluruh peta sebelum tiap entitas, sehingga `pelanggan` (9.367) dan `barang`
    (53.612) dibaca ulang belasan kali dalam satu jalannya.
    """
    peta[nama] = _peta_kode(alias, _model(nama))
    return peta


def kosongkan(alias: str) -> None:
    """Hapus isi tabel Arunika, urutan terbalik supaya FK tak menahan.

    DELETE, bukan TRUNCATE: TRUNCATE ditolak SQL Server pada tabel yang dirujuk
    FK, sekalipun tabel perujuknya sudah kosong.
    """
    with connections[alias].cursor() as cur:
        for nama in reversed(URUTAN):
            cur.execute(f"DELETE FROM dbo.{nama}")

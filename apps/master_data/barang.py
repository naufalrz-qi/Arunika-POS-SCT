"""Kelola STRUKTUR barang — `m_barang` + satuan + divisi. Buat dan sunting.

Satu-satunya jalur di Arunika yang MEMBUAT baris `m_barang`, dan satu-satunya
yang bisa MENAMBAH satuan atau baris divisi ke barang yang sudah ada. Update
Harga di sebelahnya mengurus angka (harga per satuan, saran harga, audit harga
berpecahan) dan hanya menyentuh baris yang sudah ada — sebelum modul ini, barang
baru cuma bisa lahir dari aplikasi POS lama, dan barang bersatuan PCS akan
selamanya bersatuan PCS.

Pembagian kerjanya satu kalimat: **struktur di sini, harga di sana.** Karena itu
`ubah_barang` tak pernah menulis `harga_jual` baris yang sudah ada.

## Gudang saja, dan itu bukan pembatasan yang bisa dilonggarkan

`m_barang` dan `m_barang_satuan` difan-out gudang → 8 toko lewat trigger feed
(`feed_sync.FEED_TABLE_SPECS`). Kalau toko boleh membuat barang sendiri, dua toko
bisa memakai `kd_barang` yang sama untuk barang berbeda, lalu sapuan gudang
menimpanya — dan tak ada yang menyadarinya, karena INSERT-nya sukses di kedua
sisi. Gerbangnya memakai `services._is_gudang` / `BukanServerGudang` yang sudah
menjaga nama & keterangan barang, bukan pemeriksaan kedua yang bisa berbeda.

## `kd_barang` DIKETIK, tidak dibuatkan

Tidak ada pola untuk ditebak. Contoh nyata dari server: `OCT6555`,
`6941057402239B` (barcode), `JM14062-MU`, `000-06`, `049`. Sebagian barcode
pabrik, sebagian kode internal. Karena itu kodenya datang dari operator, dan
yang dilakukan modul ini memeriksa bentroknya — bukan mengarang urutan.

Sekali tertulis, kode itu **tak pernah boleh diubah**: `ON UPDATE CASCADE` ada di
128 dari 129 FK, jadi mengganti `kd_barang` merambat ke belasan tabel transaksi
sekaligus dan tiap baris yang tersentuh membangunkan trigger feed. Salah kode =
barang baru + nonaktifkan yang lama.

## Nilai bawaan diambil dari data, bukan dikarang

Diukur di testgudang (53.865 barang):
  status         1 (53.490 baris; 0 = 323, 2 = 52)
  status_pinjam  0 — SELURUH 53.865 baris, jadi ia bukan pilihan
  pabrik         0 (49.556 baris)
  tanggal_daftar terisi di SELURUH baris — wajib ditulis, tak ada default-nya
  keterangan     "-" bila tak diisi, sama seperti no_bukti di kas
  satuan.jumlah  1 (53.700 dari 54.232) — faktor konversi satuan dasar
  satuan.margin  terisi di SELURUH baris; ditulis 0 dan dihitung ulang oleh
                 Update Barang saat harganya diubah, supaya rumus margin cuma
                 hidup di satu tempat (`services.update_harga`)

## Baris divisi OPSIONAL

22.927 dari 53.865 barang tak punya satu pun baris `m_barang_divisi`, dan mesin
stok Arunika membaca pergerakan (`t_penjualan_detail` dsb.), bukan tabel itu.
Jadi divisi dipilih kalau memang perlu `stok_awal`/`stok_min`, tidak dipaksakan.
`m_barang_divisi` juga sengaja TIDAK difan-out — isinya milik tiap toko.
"""
from __future__ import annotations

import datetime as dt

from apps.master_data.services import (
    BukanServerGudang,
    _invalidate_inventory_cache,
    _is_gudang,
)
from core import mssql

from apps.core.reporting import clean_rows as _bersih, dictify as _dictify

PANJANG_KODE = 30
PANJANG_NAMA = 50
PANJANG_KETERANGAN = 50
KETERANGAN_KOSONG = "-"

# Urutan tetap: INSERT menyebut kolom eksplisit. `m_barang_divisi` melewati
# column_id 6 (kolom yang pernah dibuang), jadi VALUES posisional akan salah
# kolom di sana.
KOLOM_BARANG = ["kd_barang", "kd_kategori", "kd_jenis_bahan", "kd_model",
                "kd_merk", "kd_warna", "ukuran", "nama", "keterangan",
                "status", "status_pinjam", "pabrik", "tanggal_daftar"]
KOLOM_SATUAN = ["kd_barang", "kd_satuan", "jumlah", "harga_jual", "status", "margin"]
KOLOM_DIVISI = ["kd_divisi", "kd_barang", "stok_awal", "harga_beli_awal",
                "stok_min", "status", "point"]

# Kolom yang boleh DIUBAH pada baris yang sudah ada. Tiga hal sengaja di luar
# daftar ini, dan ketiganya penting:
#
#   kd_barang / kd_satuan / kd_divisi — `ON UPDATE CASCADE` ada di 128 dari 129
#     FK. Mengubah kunci merambat ke belasan tabel transaksi dan membangunkan
#     trigger feed di tiap baris. Salah kode = baris baru + nonaktifkan yang lama.
#   m_barang.status — sudah dikelola layar Update Harga (`master.update_status`).
#     Dua jalur tulis untuk satu kolom akan menyimpang diam-diam.
#   m_barang_satuan.harga_jual — lihat `ubah_barang`. Harga punya satu jalur.
UBAH_BARANG = ["kd_kategori", "kd_jenis_bahan", "kd_model", "kd_merk",
               "kd_warna", "ukuran", "nama", "keterangan"]
UBAH_SATUAN = ["jumlah", "status"]
UBAH_DIVISI = ["stok_awal", "harga_beli_awal", "stok_min", "status"]

# Kode berkunci-asing di m_barang → (tabel, label untuk pesan galat).
LOOKUP_BARANG = {
    "kd_kategori": ("m_kategori", "Kategori"),
    "kd_jenis_bahan": ("m_jenis_bahan", "Jenis bahan"),
    "kd_model": ("m_model", "Model"),
    "kd_merk": ("m_merk", "Merk"),
    "kd_warna": ("m_warna", "Warna"),
}

AKTIF = 1


def _st(nilai) -> str:
    return str(nilai).strip() if nilai is not None else ""


def _angka(nilai, label: str, *, bawaan=None) -> float:
    """Angka desimal yang toleran koma, dengan pesan yang bisa ditindaklanjuti."""
    mentah = _st(nilai).replace(".", "").replace(",", ".")
    if not mentah:
        if bawaan is None:
            raise ValueError(f"{label} belum diisi.")
        return bawaan
    try:
        return float(mentah)
    except ValueError:
        raise ValueError(
            f'{label} bukan angka: "{nilai}". Tulis angkanya saja, mis. 1.') from None


def _periksa_kode(cur, tabel: str, kolom: str, nilai, label: str) -> str:
    """Kode harus ada DAN aktif di server ini.

    Diperiksa di aplikasi karena FK tak bisa dijadikan sandaran: 116 dari 129 FK
    berstatus `not_trusted`, dan 19 FK yang ada di testGudang tidak ada di
    grosirPusat. "INSERT-nya sukses berarti kodenya benar" hanya berlaku di
    sebagian server.
    """
    kode = _st(nilai)
    if not kode:
        raise ValueError(f"{label} belum dipilih.")
    cur.execute(  # nosec B608 — tabel/kolom dari LOOKUP_BARANG
        f"SELECT COUNT(*) FROM {tabel} WHERE {kolom} = ? AND status <> 0", [kode])
    if not (cur.fetchone() or [0])[0]:
        raise ValueError(f"{label} {kode} tidak ada atau tidak aktif di server ini.")
    return kode


def _periksa_satuan(items) -> list[dict]:
    """Minimal satu satuan, dan tiap barisnya lengkap.

    Barang tanpa satuan tak bisa dijual sama sekali — layar kasir memilih
    satuan, bukan barang telanjang. Di server pun ia kejanggalan: 53.699 dari
    53.865 barang punya satuan, dan yang tidak punya tak pernah muncul di nota.
    """
    if not items:
        raise ValueError(
            "Belum ada satuan. Barang tanpa satuan tak bisa dijual — tambahkan "
            "minimal satu, biasanya PCS dengan isi 1.")
    keluar, terpakai = [], set()
    for it in items:
        kd_satuan = _st(it.get("kd_satuan"))
        if not kd_satuan:
            raise ValueError("Ada baris satuan yang satuannya belum dipilih.")
        if kd_satuan in terpakai:
            raise ValueError(
                f"Satuan {kd_satuan} ditulis dua kali. Kunci tabelnya "
                f"(kd_barang, kd_satuan), jadi baris keduanya akan ditolak.")
        terpakai.add(kd_satuan)
        keluar.append({
            "kd_satuan": kd_satuan,
            "jumlah": _angka(it.get("jumlah"), f"Isi satuan {kd_satuan}", bawaan=1),
            "harga_jual": _angka(it.get("harga_jual"),
                                 f"Harga jual {kd_satuan}", bawaan=0),
            "status": _status(it.get("status")),
        })
    return keluar


def _status(nilai) -> int:
    """0 = nonaktif, selain itu aktif. Ini SATU-SATUNYA pembatalan yang ada.

    Tak ada `DELETE` di berkas ini dan tak akan pernah ada — lihat context.md
    § "Hak akses". Baris satuan/divisi yang salah dibuat dinonaktifkan, bukan
    dihapus, supaya nota lama yang menunjuk ke situ tetap terbaca.
    """
    return 0 if _st(nilai) == "0" else AKTIF


def _periksa_divisi(items) -> list[dict]:
    """Baris divisi — boleh kosong. Lihat catatan di atas berkas."""
    keluar, terpakai = [], set()
    for it in items or []:
        kd_divisi = _st(it.get("kd_divisi"))
        if not kd_divisi:
            continue
        if kd_divisi in terpakai:
            raise ValueError(f"Divisi {kd_divisi} ditulis dua kali.")
        terpakai.add(kd_divisi)
        keluar.append({
            "kd_divisi": kd_divisi,
            "stok_awal": _angka(it.get("stok_awal"), f"Stok awal {kd_divisi}", bawaan=0),
            "harga_beli_awal": _angka(it.get("harga_beli_awal"),
                                      f"Harga beli awal {kd_divisi}", bawaan=0),
            "stok_min": _angka(it.get("stok_min"), f"Stok minimum {kd_divisi}", bawaan=0),
            "status": _status(it.get("status")),
        })
    return keluar


def opsi(profile) -> dict:
    """Isi seluruh Select di formulir: lima lookup barang + satuan + divisi."""
    keluar: dict[str, list] = {}
    sumber = {
        **{nama: (tabel, nama) for nama, (tabel, _) in LOOKUP_BARANG.items()},
        "kd_satuan": ("m_satuan", "kd_satuan"),
        "kd_divisi": ("m_divisi", "kd_divisi"),
    }
    with mssql.cursor(profile) as cur:
        for field, (tabel, kunci) in sumber.items():
            cur.execute(  # nosec B608 — dari peta di atas
                f"SELECT {kunci}, nama FROM {tabel} WHERE status <> 0 ORDER BY nama")
            keluar[field] = [{"value": _st(r[0]), "label": _st(r[1]) or _st(r[0])}
                             for r in cur.fetchall()]
    return keluar


def terakhir_didaftar(profile, batas: int = 25) -> list[dict]:
    """Barang yang paling baru didaftarkan, untuk ditampilkan di bawah form."""
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP (?) kd_barang, nama, keterangan, status, tanggal_daftar "
            "FROM m_barang WHERE tanggal_daftar IS NOT NULL "
            "ORDER BY tanggal_daftar DESC", [batas])
        return _bersih(_dictify(cur))


def buat_barang(profile, data) -> dict:
    """Buat satu barang beserta satuan (≥1) dan divisi (opsional).

    Satu transaksi untuk ketiganya: barang yang tersimpan tanpa satuannya adalah
    barang yang tak bisa dijual dan tak akan ada yang tahu sebabnya.
    """
    if not _is_gudang(profile):
        raise BukanServerGudang(
            "Barang baru hanya boleh dibuat di server gudang. Katalog dipakai "
            "bersama seluruh cabang dan disebarkan dari gudang, jadi membuatnya "
            "di sini akan tertimpa sapuan berikutnya.")

    kode = _st(data.get("kd_barang")).upper()[:PANJANG_KODE]
    if not kode:
        raise ValueError(
            "Kode barang belum diisi. Kode diketik sendiri (barcode pabrik atau "
            "kode internal) dan tak bisa diubah setelah tersimpan.")
    nama = _st(data.get("nama"))[:PANJANG_NAMA]
    if not nama:
        raise ValueError("Nama barang wajib diisi.")

    satuan = _periksa_satuan(data.get("satuan") or [])
    divisi = _periksa_divisi(data.get("divisi"))
    sekarang = dt.datetime.now()

    with mssql.cursor(profile, autocommit=False) as cur:
        # Bentrok kode diperiksa DI DALAM transaksi, dan galat PK tetap
        # ditangkap pemanggil: aplikasi POS lama menulis ke tabel yang sama.
        cur.execute("SELECT 1 FROM m_barang WHERE kd_barang = ?", [kode])
        if cur.fetchone():
            raise ValueError(
                f"Kode barang {kode} sudah dipakai di server ini. Pakai kode "
                f"lain — kode yang sudah tertulis tak bisa diubah.")

        nilai = {
            "kd_barang": kode,
            "ukuran": _angka(data.get("ukuran"), "Ukuran", bawaan=1),
            "nama": nama,
            "keterangan": _st(data.get("keterangan"))[:PANJANG_KETERANGAN]
                          or KETERANGAN_KOSONG,
            "status": AKTIF,
            # Nol di SELURUH 53.865 baris — bukan pilihan, dan tak pernah jadi
            # kotak isian di layar.
            "status_pinjam": 0,
            "pabrik": 0,
            # Terisi di seluruh baris dan tak punya default constraint. Jebakan
            # yang sama dengan tanggal_server di t_opname_stok.
            "tanggal_daftar": sekarang,
        }
        for field, (tabel, label) in LOOKUP_BARANG.items():
            nilai[field] = _periksa_kode(cur, tabel, field, data.get(field), label)

        for s in satuan:
            _periksa_kode(cur, "m_satuan", "kd_satuan", s["kd_satuan"], "Satuan")
        for d in divisi:
            _periksa_kode(cur, "m_divisi", "kd_divisi", d["kd_divisi"], "Divisi")

        _sisip(cur, "m_barang", KOLOM_BARANG, nilai)
        for s in satuan:
            _sisip(cur, "m_barang_satuan", KOLOM_SATUAN, {
                "kd_barang": kode,
                # `status` ikut dari baris form (bawaannya aktif) — jangan
                # dipaksa AKTIF di sini, kalau tidak pilihan Nonaktif di layar
                # tersimpan sebagai aktif tanpa memberi tahu siapa pun.
                **s,
                # Nol, lalu dihitung ulang oleh Update Harga saat harganya
                # diubah. Rumus margin hidup di services.update_harga saja —
                # salinan kedua di sini akan menyimpang diam-diam.
                "margin": 0,
            })
        for d in divisi:
            _sisip(cur, "m_barang_divisi", KOLOM_DIVISI, {
                "kd_barang": kode, **d, "point": 0})

        cur.connection.commit()

    _invalidate_inventory_cache(profile)
    return {"kd_barang": kode, "satuan": len(satuan), "divisi": len(divisi)}


def cari_barang(profile, q: str, limit: int = 50) -> list[dict]:
    """Kode + nama saja, untuk kotak pemilih di atas layar Kelola Barang.

    Sengaja BUKAN `master.list_barang_edit`: fungsi itu ikut menarik satuan,
    harga, margin, dan status divisi untuk dua layar lain — beban yang tak ada
    gunanya saat yang dicari cuma "barang mana yang mau saya buka".
    """
    cari = _st(q)
    if not cari:
        return []
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP (?) kd_barang, nama, status FROM m_barang "
            "WHERE nama LIKE ? OR kd_barang LIKE ? ORDER BY nama",
            [limit, f"%{cari}%", f"%{cari}%"])
        return _bersih(_dictify(cur))


def baca_barang(profile, kd_barang: str) -> dict | None:
    """Satu barang lengkap dalam bentuk yang dipakai formulir Kelola Barang.

    Bentuknya tak ada di tempat lain: `list_barang_edit` tak mengembalikan
    keempat kode lookup selain kategori, tak mengembalikan `ukuran`, tak
    mengembalikan `jumlah` satuan, dan tak mengembalikan stok_awal/stok_min —
    persis kolom-kolom yang jadi alasan layar ini ada.
    """
    kode = _st(kd_barang).upper()
    if not kode:
        return None
    with mssql.cursor(profile) as cur:
        cur.execute(
            f"SELECT {', '.join(KOLOM_BARANG)} FROM m_barang WHERE kd_barang = ?",
            [kode])
        baris = _dictify(cur)
        if not baris:
            return None
        barang = _bersih(baris)[0]

        cur.execute(
            "SELECT kd_satuan, jumlah, harga_jual, status FROM m_barang_satuan "
            "WHERE kd_barang = ? ORDER BY jumlah", [kode])
        satuan = _bersih(_dictify(cur))

        cur.execute(
            "SELECT kd_divisi, stok_awal, harga_beli_awal, stok_min, status "
            "FROM m_barang_divisi WHERE kd_barang = ? ORDER BY kd_divisi", [kode])
        divisi = _bersih(_dictify(cur))

    return {**barang, "satuan": satuan, "divisi": divisi}


def ubah_barang(profile, kd_barang: str, data) -> dict:
    """Sunting struktur barang yang sudah ada. Satu transaksi.

    **`harga_jual` baris satuan yang SUDAH ADA tidak pernah disentuh di sini.**
    Harga punya satu jalur — `services.update_harga` — dan jalur itu memvalidasi
    harga bulat, menghitung ulang margin, membatalkan cache inventori, mencatat
    `BarangUpdateLog`, lalu menyebarkannya ke delapan toko lewat `_sebar_harga`.
    Menulis harga langsung dari sini melewati kelimanya, dan yang paling tak
    terlihat: margin jadi basi tanpa satu pun gejala di layar.

    Baris satuan BARU tetap membawa harganya sendiri — belum ada harga lama yang
    perlu dirawat, persis seperti `buat_barang`.
    """
    if not _is_gudang(profile):
        raise BukanServerGudang(
            "Barang hanya boleh disunting di server gudang. Katalog dipakai "
            "bersama seluruh cabang dan disebarkan dari gudang, jadi perubahan "
            "di sini akan tertimpa sapuan berikutnya.")

    kode = _st(kd_barang).upper()
    if not kode:
        raise ValueError("Kode barang kosong.")
    nama = _st(data.get("nama"))[:PANJANG_NAMA]
    if not nama:
        raise ValueError("Nama barang wajib diisi.")

    satuan = _periksa_satuan(data.get("satuan") or [])
    divisi = _periksa_divisi(data.get("divisi"))

    with mssql.cursor(profile, autocommit=False) as cur:
        cur.execute("SELECT 1 FROM m_barang WHERE kd_barang = ?", [kode])
        if not cur.fetchone():
            raise ValueError(f"Barang {kode} tidak ada di server ini.")

        nilai = {
            "ukuran": _angka(data.get("ukuran"), "Ukuran", bawaan=1),
            "nama": nama,
            "keterangan": _st(data.get("keterangan"))[:PANJANG_KETERANGAN]
                          or KETERANGAN_KOSONG,
        }
        for field, (tabel, label) in LOOKUP_BARANG.items():
            nilai[field] = _periksa_kode(cur, tabel, field, data.get(field), label)

        set_sql = ", ".join(f"{k} = ?" for k in UBAH_BARANG)
        cur.execute(  # nosec B608 — kolom dari UBAH_BARANG, bukan dari input
            f"UPDATE m_barang SET {set_sql} WHERE kd_barang = ?",
            [nilai[k] for k in UBAH_BARANG] + [kode])

        baru_satuan = _upsert_satuan(cur, kode, satuan)
        baru_divisi = _upsert_divisi(cur, kode, divisi)
        cur.connection.commit()

    _invalidate_inventory_cache(profile)
    return {"kd_barang": kode, "satuan_baru": baru_satuan, "divisi_baru": baru_divisi}


def _upsert_satuan(cur, kode: str, satuan: list[dict]) -> int:
    """INSERT baris satuan yang belum ada, UPDATE yang sudah. Tak pernah DELETE."""
    cur.execute("SELECT kd_satuan FROM m_barang_satuan WHERE kd_barang = ?", [kode])
    ada = {_st(r[0]) for r in cur.fetchall()}
    baru = 0
    for s in satuan:
        _periksa_kode(cur, "m_satuan", "kd_satuan", s["kd_satuan"], "Satuan")
        if s["kd_satuan"] in ada:
            # `harga_jual` DAN `margin` sengaja di luar UBAH_SATUAN — lihat
            # docstring ubah_barang. Yang berubah di sini cuma konversi dan
            # aktif/nonaktifnya.
            set_sql = ", ".join(f"{k} = ?" for k in UBAH_SATUAN)
            cur.execute(  # nosec B608 — kolom dari UBAH_SATUAN
                f"UPDATE m_barang_satuan SET {set_sql} "
                f"WHERE kd_barang = ? AND kd_satuan = ?",
                [s[k] for k in UBAH_SATUAN] + [kode, s["kd_satuan"]])
        else:
            _sisip(cur, "m_barang_satuan", KOLOM_SATUAN,
                   {"kd_barang": kode, **s, "margin": 0})
            baru += 1
    return baru


def _upsert_divisi(cur, kode: str, divisi: list[dict]) -> int:
    """Sama untuk baris divisi. Kuncinya (kd_divisi, kd_barang)."""
    cur.execute("SELECT kd_divisi FROM m_barang_divisi WHERE kd_barang = ?", [kode])
    ada = {_st(r[0]) for r in cur.fetchall()}
    baru = 0
    for d in divisi:
        _periksa_kode(cur, "m_divisi", "kd_divisi", d["kd_divisi"], "Divisi")
        if d["kd_divisi"] in ada:
            set_sql = ", ".join(f"{k} = ?" for k in UBAH_DIVISI)
            cur.execute(  # nosec B608 — kolom dari UBAH_DIVISI
                f"UPDATE m_barang_divisi SET {set_sql} "
                f"WHERE kd_barang = ? AND kd_divisi = ?",
                [d[k] for k in UBAH_DIVISI] + [kode, d["kd_divisi"]])
        else:
            _sisip(cur, "m_barang_divisi", KOLOM_DIVISI,
                   {"kd_barang": kode, **d, "point": 0})
            baru += 1
    return baru


def _sisip(cur, tabel: str, kolom: list[str], nilai: dict) -> None:
    """Satu baris per `execute`, kolom disebut eksplisit.

    Aturan menyeluruh proyek ini (context.md § Trigger): trigger stok legacy
    memakai skalar dari `inserted`, jadi INSERT banyak baris hanya memproses
    satu baris sembarang — tanpa galat.
    """
    tanya = ", ".join("?" for _ in kolom)
    cur.execute(  # nosec B608 — tabel/kolom dari konstanta di atas
        f"INSERT INTO {tabel} ({', '.join(kolom)}) VALUES ({tanya})",
        [nilai[k] for k in kolom])

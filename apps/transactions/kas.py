"""Jalur tulis kas: biaya operasional, pendapatan lain-lain, penambahan kas, mutasi kas.

Satu mesin untuk empat tabel, dijelaskan sebagai DATA di `SPEC`. Bentuknya sama
persis dengan Koreksi Stok (`opname.py`) dan karena itu mewarisi aturannya:
nomor dari `kepala_nota`, `kd_user` dari tautan (tak pernah dari layar), satu
baris per `execute`, dan kolom disebut eksplisit.

## Yang diukur, dan yang tidak

`t_biaya_operasional` punya **9.563 baris di grosirPusat**, jadi bentuknya bukan
tebakan: `no_transaksi` = `SC2603200006` = `{kepala_nota}{YYMMDD}{NNNN}`,
`kd_jenis` menunjuk `m_jenis_bayar` (JAA000 = TUNAI), `kd_kas` menunjuk `m_kas`,
dan `no_bukti` yang tak diisi ditulis `-` — bukan string kosong.

`t_penambahan_kas` dan `t_mutasi_kas` **nol baris di setiap server yang bisa
dijangkau** (testgudang dan grosirPusat), sama seperti `t_pembelian_order` dulu.
Jadi bentuk nomornya mengikuti konvensi tetangganya, bukan contoh nyata. Kalau
suatu hari ada server yang isinya berbeda, di sinilah tempat memperbaikinya.

## `kd_kas_tujuan` itu KAS, walau tipenya berkata lain

`t_mutasi_kas.kd_kas_tujuan` bertipe `varchar(10)` sedangkan `kd_kas_sumber`
`char(6)`, dan tipe bawaannya (`JR_KODE_ACCOUNT`) sama dengan `m_jurnal.kd_index`
— semua itu mengarah ke "tujuannya sebuah akun". **Itu keliru.** Tiga VIEW
legacy menjawabnya langsung: `v_t_mutasi_kas`, `mon_t_mutasi_kas`, dan
`v_g_kas_histori_detail` sama-sama menulis `t_mutasi_kas.kd_kas_tujuan =
m_kas.kd_kas`. Tipenya yang tidak rapi, bukan artinya yang berbeda.

Ini pengulangan pelajaran yang sama dengan empat jenis koreksi opname: **arti
kolom legacy ada di definisi VIEW, bukan di skema tabelnya.** Cek `sys.sql_modules`
sebelum menyimpulkan apa pun dari nama dan tipe kolom.
"""
from __future__ import annotations

import datetime as dt

from apps.transactions.penomoran import (
    awalan_untuk,
    no_berikutnya,
    simpan_dengan_nomor,
)
from core import mssql

# `no_bukti` NOT NULL, dan yang tak punya nomor bukti ditulis "-" oleh aplikasi
# lama — 9.563 dari 9.563 baris biaya di grosirPusat berbunyi begitu. String
# kosong akan tersimpan, tapi ia jadi satu-satunya baris yang berbeda bentuk.
BUKTI_KOSONG = "-"

# varchar(50) di ketiga tabel. Dipotong di sini supaya isian kepanjangan jadi
# kalimat yang bisa dibaca, bukan galat ODBC yang tak menyebut kolomnya.
PANJANG_KETERANGAN = 50
PANJANG_BUKTI = 20

SPEC = {
    "biaya": {
        "tabel": "t_biaya_operasional",
        "jenis_nomor": "biaya",
        "label": "Biaya operasional",
        # Urutannya tetap: INSERT menyebut kolom secara eksplisit, dan kolom
        # `column_id` 7 di tabel ini sudah pernah dibuang — VALUES posisional
        # akan salah kolom.
        "kolom": ["no_transaksi", "kd_divisi", "kd_biaya", "kd_jenis", "kd_kas",
                  "tanggal", "nominal", "no_bukti", "keterangan", "kd_user",
                  "tanggal_server"],
        # Divisi DIPILIH di layar, bukan diambil dari tautan: ia menentukan
        # awalan nomornya, dan gudang punya lima divisi dengan lima kepala_nota
        # berbeda (UM/GP/GO/KN/FR).
        "divisi_dari_layar": True,
        "kode": {
            "kd_biaya": ("m_biaya", "Jenis biaya"),
            "kd_jenis": ("m_jenis_bayar", "Cara bayar"),
            "kd_kas": ("m_kas", "Kas"),
        },
        "bukti": ["no_bukti"],
    },
    "pendapatan": {
        "tabel": "t_pendapatan",
        "jenis_nomor": "pendapatan",
        "label": "Pendapatan lain-lain",
        # Kembarannya `biaya`: kolomnya sama persis kecuali kd_biaya → kd_pendapatan.
        # Bentuknya diukur, bukan ditebak — 6 baris di grosirPusat semuanya
        # SC2203310001 / DAA000 / PAA000 / JAA000 / KAA000 / no_bukti "-".
        #
        # Bertrigger `insert_temp_m_t_pendapatan` (aktif di GUDANG dan testgudang,
        # sama seperti t_biaya_operasional), jadi barisnya masuk antrean kirim ke
        # sink pusat SEKETIKA disimpan — bukan sesuatu yang bisa ditarik kembali.
        # Itu alasan menunya admin_only + butuh_tautan seperti tiga saudaranya.
        "kolom": ["no_transaksi", "kd_divisi", "kd_pendapatan", "kd_jenis", "kd_kas",
                  "tanggal", "nominal", "no_bukti", "keterangan", "kd_user",
                  "tanggal_server"],
        "divisi_dari_layar": True,
        "kode": {
            "kd_pendapatan": ("m_pendapatan", "Jenis pendapatan"),
            "kd_jenis": ("m_jenis_bayar", "Cara bayar"),
            "kd_kas": ("m_kas", "Kas"),
        },
        "bukti": ["no_bukti"],
    },
    "penambahan": {
        "tabel": "t_penambahan_kas",
        "jenis_nomor": "penambahan_kas",
        "label": "Penambahan kas",
        # Tak punya `tanggal_server` — satu-satunya dari ketiganya.
        "kolom": ["no_transaksi", "tanggal", "kd_kas", "nominal", "keterangan",
                  "kd_user"],
        "divisi_dari_layar": False,
        "kode": {"kd_kas": ("m_kas", "Kas")},
        "bukti": [],
    },
    "mutasi": {
        "tabel": "t_mutasi_kas",
        "jenis_nomor": "mutasi_kas",
        "label": "Mutasi kas",
        "kolom": ["no_transaksi", "tanggal", "kd_kas_sumber", "kd_kas_tujuan",
                  "nominal", "no_bukti_sumber", "no_bukti_tujuan", "keterangan",
                  "kd_user", "tanggal_server"],
        "divisi_dari_layar": False,
        # Keduanya ke m_kas — lihat catatan `kd_kas_tujuan` di atas berkas.
        "kode": {"kd_kas_sumber": ("m_kas", "Kas sumber"),
                 "kd_kas_tujuan": ("m_kas", "Kas tujuan")},
        "bukti": ["no_bukti_sumber", "no_bukti_tujuan"],
    },
}


# Bentuk formulir tiap jenis, dipakai layar. Di sini dan bukan di Vue supaya
# kolom yang ada, urutannya, dan sumber pilihannya punya satu sumber kebenaran —
# daftar yang terpisah akan pelan-pelan berbeda dari `SPEC["kolom"]`.
#   tipe: "pilih" (Select, isinya dari `lookups[opsi]`) | "uang" | "teks"
FORM = {
    "biaya": [
        {"name": "kd_divisi", "label": "Divisi", "tipe": "pilih", "opsi": "divisi"},
        {"name": "kd_biaya", "label": "Jenis Biaya", "tipe": "pilih", "opsi": "biaya"},
        {"name": "kd_jenis", "label": "Cara Bayar", "tipe": "pilih", "opsi": "jenis_bayar"},
        {"name": "kd_kas", "label": "Kas", "tipe": "pilih", "opsi": "kas"},
        {"name": "nominal", "label": "Nominal", "tipe": "uang"},
        {"name": "no_bukti", "label": "No. Bukti", "tipe": "teks"},
        {"name": "keterangan", "label": "Keterangan", "tipe": "teks"},
    ],
    "pendapatan": [
        {"name": "kd_divisi", "label": "Divisi", "tipe": "pilih", "opsi": "divisi"},
        {"name": "kd_pendapatan", "label": "Jenis Pendapatan", "tipe": "pilih", "opsi": "pendapatan"},
        {"name": "kd_jenis", "label": "Cara Bayar", "tipe": "pilih", "opsi": "jenis_bayar"},
        {"name": "kd_kas", "label": "Kas", "tipe": "pilih", "opsi": "kas"},
        {"name": "nominal", "label": "Nominal", "tipe": "uang"},
        {"name": "no_bukti", "label": "No. Bukti", "tipe": "teks"},
        {"name": "keterangan", "label": "Keterangan", "tipe": "teks"},
    ],
    "penambahan": [
        {"name": "kd_kas", "label": "Kas", "tipe": "pilih", "opsi": "kas"},
        {"name": "nominal", "label": "Nominal", "tipe": "uang"},
        {"name": "keterangan", "label": "Keterangan", "tipe": "teks"},
    ],
    "mutasi": [
        {"name": "kd_kas_sumber", "label": "Kas Sumber", "tipe": "pilih", "opsi": "kas"},
        {"name": "kd_kas_tujuan", "label": "Kas Tujuan", "tipe": "pilih", "opsi": "kas"},
        {"name": "nominal", "label": "Nominal", "tipe": "uang"},
        {"name": "no_bukti_sumber", "label": "No. Bukti Sumber", "tipe": "teks"},
        {"name": "no_bukti_tujuan", "label": "No. Bukti Tujuan", "tipe": "teks"},
        {"name": "keterangan", "label": "Keterangan", "tipe": "teks"},
    ],
}

# Sumber pilihan → (tabel, kolom kunci, kolom label). `m_kas` memakai `cabang`
# karena tabelnya tak punya kolom `nama` sama sekali.
LOOKUP = {
    "divisi": ("m_divisi", "kd_divisi", "nama"),
    "biaya": ("m_biaya", "kd_biaya", "nama"),
    "pendapatan": ("m_pendapatan", "kd_pendapatan", "nama"),
    "jenis_bayar": ("m_jenis_bayar", "kd_jenis", "nama"),
    "kas": ("m_kas", "kd_kas", "cabang"),
}


def _st(nilai) -> str:
    return str(nilai).strip() if nilai is not None else ""


def list_lookups(profile, jenis: str) -> dict:
    """Pilihan untuk seluruh Select di formulir jenis ini, yang AKTIF saja."""
    perlu = {f["opsi"] for f in FORM[jenis] if f["tipe"] == "pilih"}
    keluar: dict[str, list] = {}
    with mssql.cursor(profile) as cur:
        for nama in sorted(perlu):
            tabel, kunci, label = LOOKUP[nama]
            cur.execute(  # nosec B608 — dari LOOKUP
                f"SELECT {kunci}, {label} FROM {tabel} WHERE status <> 0 "
                f"ORDER BY {label}")
            keluar[nama] = [{"value": _st(r[0]), "label": _st(r[1]) or _st(r[0])}
                            for r in cur.fetchall()]
    return keluar


def _nominal(nilai) -> float:
    """Nominal, atau ValueError yang bisa dibaca orang yang sedang mengetik.

    `float()` telanjang berbunyi "could not convert string to float: '1.500,00'"
    — kalimat yang tak berarti apa-apa bagi staf kasir, dan justru bentuk itulah
    yang paling mungkin diketik (pemisah ribuan Indonesia).
    """
    mentah = _st(nilai).replace(".", "").replace(",", ".")
    if not mentah:
        raise ValueError("Nominal belum diisi.")
    try:
        angka = float(mentah)
    except ValueError:
        raise ValueError(
            f'Nominal bukan angka: "{nilai}". Tulis angkanya saja, mis. 250000.'
        ) from None
    if angka <= 0:
        raise ValueError("Nominal harus lebih dari nol.")
    return angka


def _periksa_kode(cur, tabel: str, kolom: str, nilai: str, label: str) -> str:
    """Pastikan kode itu ada DAN aktif di server ini.

    Diperiksa di aplikasi, bukan digantungkan ke FK: `t_biaya_operasional` cuma
    punya FK ke `m_biaya` dan `m_jenis_bayar` — `kd_kas` dan `kd_divisi` tak
    dijaga sama sekali — dan `t_penambahan_kas`/`t_mutasi_kas` tak punya FK satu
    pun. "INSERT-nya sukses berarti kodenya benar" tidak berlaku di sini.
    """
    kode = _st(nilai)
    if not kode:
        raise ValueError(f"{label} belum dipilih.")
    cur.execute(  # nosec B608 — tabel/kolom dari SPEC, bukan dari input
        f"SELECT COUNT(*) FROM {tabel} WHERE {kolom} = ? AND status <> 0", [kode])
    if not (cur.fetchone() or [0])[0]:
        raise ValueError(f"{label} {kode} tidak ada atau tidak aktif di server ini.")
    return kode


def _periksa_divisi(cur, kd_divisi: str) -> str:
    kode = _st(kd_divisi)
    if not kode:
        raise ValueError(
            "Divisi belum dipilih. Divisi menentukan awalan nomor transaksinya, "
            "jadi ia tak boleh ditebak.")
    cur.execute(
        "SELECT COUNT(*) FROM m_divisi WHERE kd_divisi = ? AND status <> 0", [kode])
    if not (cur.fetchone() or [0])[0]:
        raise ValueError(f"Divisi {kode} tidak ada atau tidak aktif di server ini.")
    return kode


def simpan(profile, jenis: str, *, kd_user: str, data, tanggal=None) -> dict:
    """Tulis satu transaksi kas. Mengembalikan {"nomor": …, "label": …}.

    Satu baris per simpan — ketiga tabel ber-PK `no_transaksi`, jadi satu nomor
    memang satu baris. Tak ada mode banyak-baris seperti Koreksi Stok.
    """
    s = SPEC[jenis]  # KeyError kalau jenisnya tak dikenal — memang.
    if not kd_user:
        raise ValueError(
            "Akun Anda belum ditautkan ke user legacy untuk koneksi ini, jadi "
            f"{s['label'].lower()} tak bisa dicatat atas nama Anda. Minta "
            "pengelola aplikasi mengisinya di Kelola Tautan User.")

    nominal = _nominal(data.get("nominal"))
    keterangan = _st(data.get("keterangan"))[:PANJANG_KETERANGAN]
    if not keterangan:
        raise ValueError(
            "Keterangan wajib diisi — itu satu-satunya tempat sebab transaksi "
            "ini tercatat, dan yang dibaca orang saat mencocokkan kas nanti.")
    tanggal = tanggal or dt.datetime.now()

    with mssql.cursor(profile, autocommit=False) as cur:
        nilai = {
            "tanggal": tanggal,
            "nominal": nominal,
            "keterangan": keterangan,
            "kd_user": kd_user,
        }
        for kolom, (tabel, label) in s["kode"].items():
            # Kolom kunci di tabel tujuannya sama namanya, kecuali dua kolom kas
            # di t_mutasi_kas yang keduanya menunjuk m_kas.kd_kas.
            kunci = "kd_kas" if kolom.startswith("kd_kas") else kolom
            nilai[kolom] = _periksa_kode(cur, tabel, kunci, data.get(kolom), label)
        for kolom in s["bukti"]:
            nilai[kolom] = _st(data.get(kolom))[:PANJANG_BUKTI] or BUKTI_KOSONG
        if "tanggal_server" in s["kolom"]:
            # Tak ada default constraint di kolom ini — aplikasi lama menulisnya
            # sendiri. Jebakan yang sama dengan t_penjualan_order dan t_opname_stok.
            nilai["tanggal_server"] = dt.datetime.now()

        if s["divisi_dari_layar"]:
            kd_divisi = _periksa_divisi(cur, data.get("kd_divisi"))
            nilai["kd_divisi"] = kd_divisi
        else:
            # Tabelnya tak punya kolom divisi, tapi nomornya tetap butuh awalan.
            # Diambil dari divisi TAUTAN akun ini — tautannya memang sudah
            # menyebut divisi, dan "divisi aktif pertama" salah di gudang.
            kd_divisi = _st(data.get("kd_divisi"))
        awalan = awalan_untuk(cur, kd_divisi or None)

        kolom = s["kolom"]
        tanya = ", ".join("?" for _ in kolom)

        def tulis(no):
            nilai["no_transaksi"] = no
            cur.execute(  # nosec B608 — tabel/kolom dari SPEC
                f"INSERT INTO {s['tabel']} ({', '.join(kolom)}) VALUES ({tanya})",
                [nilai[k] for k in kolom],
            )

        nomor = simpan_dengan_nomor(
            cur, lambda: no_berikutnya(cur, s["jenis_nomor"], awalan, tanggal), tulis)
        cur.connection.commit()

    return {"nomor": nomor, "label": s["label"]}


def riwayat(profile, jenis: str, batas: int = 50) -> list[dict]:
    """Transaksi terakhir jenis ini, untuk ditampilkan di bawah formnya.

    Ada supaya operator melihat apa yang baru saja ia simpan tanpa berpindah ke
    layar laporan — dan supaya nomor ganda ketahuan segera, bukan saat tutup buku.
    """
    from apps.core.reporting import clean_rows as _bersih, dictify as _dictify

    s = SPEC[jenis]
    kolom = [k for k in s["kolom"] if k != "tanggal_server"]
    with mssql.cursor(profile) as cur:
        cur.execute(  # nosec B608 — tabel/kolom dari SPEC
            f"SELECT TOP (?) {', '.join(kolom)} FROM {s['tabel']} "
            f"ORDER BY tanggal DESC, no_transaksi DESC", [batas])
        return _bersih(_dictify(cur))

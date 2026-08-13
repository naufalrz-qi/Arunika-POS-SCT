"""Laporan Laba Rugi — pengganti set-based untuk `GetRekapHarian` legacy.

Modul tersendiri, bukan di `reports.py`, karena bentuk keluarannya (daftar baris
berlabel) tak muat ke kontrak `(inner_sql, params)` yang dipatuhi seluruh berkas
itu. Ia tetap memakai ulang pembangun SQL di sana — `_nota_net`, `_pembelian_nota`,
`_BIAYA_KATEGORI_CASE` — supaya angkanya cocok dengan laporan penjualan dan
pembelian di sebelahnya, bukan versi kedua yang pelan-pelan menyimpang.

## Kenapa tidak memanggil GetRekapHarian saja

Dua alasan, keduanya diukur di GUDANG:

1. **Terlalu lambat.** `SELECT * FROM GetRekapHarian(...)` timeout >60 dtk;
   `GetHargaAverageBarangPerTanggal` sendiri makan **171 detik** (kursor bersarang
   per barang + UDF skalar per nota atas 593rb baris detail). Versi ini ~7 dtk.
2. **Metodenya tidak sah.** Legacy menilai persediaan dengan penelusuran lapisan
   **LIFO**, yang dilarang PSAK 14 / IAS 2 sejak revisi 2008 — dan menilai stok
   hasil opname masuk Rp 0 (di GUDANG: 14,3 juta unit). Lihat
   `inventory.services._harga_pokok_rata` untuk metode penggantinya.

**Angkanya karena itu TIDAK akan sama dengan aplikasi lama**, dan layar harus
mengatakannya. Selisihnya terukur: Juli 2026 di GUDANG, laba kotor legacy
Rp 1.571 juta (43,5%) vs rata-rata tertimbang Rp 1.558 juta (43,0%).

## Yang juga perlu diketahui pembaca angkanya

Laporan periode lampau **tidak reproducible persis**: baris bertanggal lampau
masih berdatangan lewat sync. Terukur saat modul ini ditulis — 3 pembelian dan 1
retur bertanggal Juli masuk ke GUDANG dalam 6 jam, menggeser persediaan akhir
Juli sebesar Rp 97 juta. Itu sifat datanya, bukan cacat laporan.
"""
from __future__ import annotations

import datetime as dt

from apps.core.reporting import dictify, one_row
from apps.inventory import services as inv
from apps.transactions import reports as rpt
from core import mssql

# jenis baris, dipakai layar untuk memilih gaya — bukan sekadar hiasan: "total"
# dan "subtotal" adalah baris hasil hitungan, "nilai" adalah masukan, dan
# membedakannya mencegah orang menjumlah kolom yang sudah berisi jumlah.
NILAI, SUBTOTAL, TOTAL, PERSEN, PEMISAH = "nilai", "subtotal", "total", "persen", "pemisah"


class PeriodeTertutup(ValueError):
    """Periode yang diminta seluruhnya sebelum tutup buku — tak bisa dilaporkan."""


def _b(label, nilai, jenis=NILAI) -> dict:
    # `+ 0.0` menormalkan -0.0 jadi 0.0: baris nol yang tercetak "-0,00" terbaca
    # sebagai angka negatif kecil yang dibulatkan, padahal memang tak ada isinya.
    return {"label": label, "nilai": round(nilai, 2) + 0.0, "jenis": jenis}


def _persen(pembilang: float, penyebut: float) -> float:
    """Persentase terhadap penjualan bersih. Penyebut nol -> 0, bukan galat.

    Legacy membagi laba dengan HPP dan menamainya "Rasio Kontribusi" — itu markup
    atas modal, bukan margin, dan labelnya menyesatkan pembaca laporan keuangan.
    """
    return round(pembilang / penyebut * 100, 2) if penyebut else 0.0


def _where(date_from, date_to, kd_divisi, kolom_divisi="h.kd_divisi"):
    where = ["h.tanggal >= ?", "h.tanggal <= ?"]
    params = [date_from, date_to]
    if kd_divisi:
        where.append(f"{kolom_divisi} = ?")
        params.append(kd_divisi)
    return " AND ".join(where), params


def _penjualan(cur, date_from, date_to, kd_divisi) -> dict:
    """Bruto / potongan / pajak / netto / tunai / kredit — satu query lewat _nota_net.

    Identitas yang dijaga: bruto - potongan + pajak = netto sebelum retur. Potongan
    diturunkan (bukan dihitung ulang) supaya laporan ini FOOT: kalau baris-barisnya
    tak menjumlah, laporan laba rugi tak ada gunanya.
    """
    w, params = _where(date_from, date_to, kd_divisi)
    nota = rpt._nota_net(w)
    cur.execute(
        "SELECT COALESCE(SUM(n.total_kotor), 0) AS bruto, "
        "COALESCE(SUM(n.pajak), 0) AS pajak, "
        "COALESCE(SUM(n.total_bersih), 0) AS netto, "
        "COALESCE(SUM(CASE WHEN n.status_raw = 1 THEN n.total_bersih ELSE 0 END), 0) AS tunai, "
        "COALESCE(SUM(CASE WHEN n.status_raw = 0 THEN n.total_bersih ELSE 0 END), 0) AS kredit "
        f"FROM ({nota}) n",
        params,
    )
    return one_row(cur)


def _skalar(cur, sql, params) -> float:
    cur.execute(sql, params)
    row = cur.fetchone()
    return float(row[0] or 0) if row else 0.0


def hitung(profile, date_from, date_to, kd_divisi=None) -> dict:
    """Laba rugi satu periode. Mengembalikan {baris, memo, info, notice}.

    `date_from`/`date_to` datetime; `date_to` diharapkan sudah akhir-hari
    (`parse_report_params` sudah melakukannya).
    """
    notice = None
    with mssql.cursor(profile) as cur:
        tutup_buku = inv._closing_date(cur)

    # Mesin stok tak bisa menjawab sebelum tutup buku — blok "Stok Awal" memang
    # BERTANGGAL di situ. Legacy menggeser diam-diam; kita menggeser lalu bilang.
    # Bukan kasus teoretis: tutup buku PUSAT 2025-12-31, jadi setiap permintaan
    # periode 2025 di sana diam-diam berubah jadi 2026 di aplikasi lama.
    # Seluruh periode di belakang tutup buku: TIDAK bisa dilaporkan. Menggeser
    # tanggal mulai ke depan di sini akan menghasilkan periode satu hari sesudah
    # tutup buku yang dibaca orang sebagai "November", persis penggantian diam-diam
    # yang jadi alasan laporan ini ditulis ulang.
    if date_to <= tutup_buku:
        raise PeriodeTertutup(
            f"Periode {date_from:%d-%m-%Y} s.d. {date_to:%d-%m-%Y} sudah tertutup: buku "
            f"ditutup s.d. {tutup_buku:%d-%m-%Y}, dan saldo persediaan sebelum "
            "tanggal itu tidak lagi tersimpan per transaksi. Pilih periode yang "
            f"berakhir setelah {tutup_buku:%d-%m-%Y}."
        )
    if date_from <= tutup_buku:
        asal = date_from
        date_from = (tutup_buku + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        notice = (
            f"Tanggal mulai digeser dari {asal:%d-%m-%Y} ke {date_from:%d-%m-%Y}: "
            f"buku sudah ditutup s.d. {tutup_buku:%d-%m-%Y}, dan saldo persediaan "
            "sebelum tanggal itu tidak tersimpan per transaksi."
        )

    # Persediaan: dua panggilan, awal = sehari sebelum periode mulai.
    sebelum = (date_from - dt.timedelta(days=1)).replace(hour=23, minute=59, second=59)
    awal = inv.nilai_persediaan(profile, sebelum, kd_divisi=kd_divisi)
    akhir = inv.nilai_persediaan(profile, date_to, kd_divisi=kd_divisi)

    with mssql.cursor(profile) as cur:
        jual = _penjualan(cur, date_from, date_to, kd_divisi)

        w, params = _where(date_from, date_to, kd_divisi)
        beli = _skalar(
            cur, f"SELECT COALESCE(SUM(n.total_bersih), 0) FROM ({rpt._pembelian_nota(w)}) n", params)
        retur_beli = _skalar(
            cur, "SELECT COALESCE(SUM(d.qty * d.harga), 0) FROM t_pembelian_retur h "
                 f"INNER JOIN t_pembelian_retur_detail d ON h.no_retur = d.no_retur WHERE {w}", params)
        retur_jual = _skalar(
            cur, "SELECT COALESCE(SUM(d.qty * d.harga_jual), 0) FROM t_penjualan_retur h "
                 f"INNER JOIN t_penjualan_retur_detail d ON h.no_retur = d.no_retur WHERE {w}", params)

        # Biaya dipecah per kategori m_biaya.status lewat CASE yang sudah dipakai
        # laporan Biaya per Kategori — satu definisi, bukan dua yang bisa berbeda.
        cur.execute(
            f"SELECT {rpt._BIAYA_KATEGORI_CASE} AS kategori, SUM(h.nominal) AS total "
            "FROM t_biaya_operasional h INNER JOIN m_biaya b ON h.kd_biaya = b.kd_biaya "
            f"WHERE {w} GROUP BY b.status", params)
        biaya = {r["kategori"]: float(r["total"] or 0) for r in dictify(cur)}

        pendapatan = _skalar(
            cur, f"SELECT COALESCE(SUM(h.nominal), 0) FROM t_pendapatan h WHERE {w}", params)
        # Tagihan piutang & cicilan tak punya kd_divisi — filter divisi tak berlaku.
        w_tgl, p_tgl = _where(date_from, date_to, None)
        tagihan = _skalar(
            cur, f"SELECT COALESCE(SUM(h.nominal), 0) FROM t_piutang_cicilan h WHERE {w_tgl}", p_tgl)

    bruto = float(jual.get("bruto") or 0)
    pajak = float(jual.get("pajak") or 0)
    netto_nota = float(jual.get("netto") or 0)
    potongan = bruto - netto_nota + pajak
    penjualan_bersih = netto_nota - retur_jual

    tersedia = awal["nilai"] + beli - retur_beli
    hpp = tersedia - akhir["nilai"]
    laba_kotor = penjualan_bersih - hpp
    biaya_total = sum(biaya.values())
    laba_bersih = laba_kotor - biaya_total + pendapatan

    baris = [
        _b("Persediaan Awal", awal["nilai"]),
        _b("Pembelian", beli),
        _b("Retur Pembelian", -retur_beli),
        _b("Barang Tersedia Dijual", tersedia, SUBTOTAL),
        _b("", 0, PEMISAH),
        _b("Penjualan Bruto", bruto),
        _b("Potongan Penjualan", -potongan),
        _b("Pajak Penjualan", pajak),
        _b("Retur Penjualan", -retur_jual),
        _b("Penjualan Bersih", penjualan_bersih, SUBTOTAL),
        _b("", 0, PEMISAH),
        _b("Persediaan Akhir", -akhir["nilai"]),
        _b("Harga Pokok Penjualan", hpp, SUBTOTAL),
        _b("Laba Kotor", laba_kotor, TOTAL),
        _b("Margin Kotor (% penjualan bersih)", _persen(laba_kotor, penjualan_bersih), PERSEN),
        _b("", 0, PEMISAH),
    ]
    # Kategori didaftar tetap supaya baris yang nol tetap tampil — biaya yang
    # hilang dari laporan terbaca sebagai "tidak ada", bukan "belum diisi".
    for kategori in ("Operasional (Penjualan)", "Operasional (Adm. dan Umum)",
                     "Produksi (Biaya Langsung)", "Produksi (Biaya Tak Langsung)"):
        if kategori in biaya or kategori.startswith("Operasional"):
            baris.append(_b(kategori, -biaya.get(kategori, 0.0)))
    baris += [
        _b("Pendapatan Lain-Lain", pendapatan),
        _b("Laba Bersih", laba_bersih, TOTAL),
        _b("Margin Bersih (% penjualan bersih)", _persen(laba_bersih, penjualan_bersih), PERSEN),
    ]

    memo = [
        _b("Penjualan Tunai", float(jual.get("tunai") or 0)),
        _b("Penjualan Kredit", float(jual.get("kredit") or 0)),
        _b("Tagihan Piutang (cicilan diterima)", tagihan),
    ]

    return {
        "baris": baris,
        "memo": memo,
        "info": {
            "tutup_buku": tutup_buku,
            "barang_awal": awal["barang"], "barang_akhir": akhir["barang"],
            "tanpa_harga": akhir["tanpa_harga"],
            "stok_negatif": akhir["stok_negatif"],
            "unit_akhir": akhir["unit"],
        },
        "notice": notice,
        "periode": {"dari": date_from, "sampai": date_to},
    }

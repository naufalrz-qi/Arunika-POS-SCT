"""Self-check mesin stok, dijalankan terhadap koneksi aktif:
    python manage.py check_stock_agg

Tiga pemeriksaan: agregasi SQL == agregasi Python, snapshot+delta == hitung ulang
penuh, dan SATUAN harga rata-rata. Yang ketiga ada karena satuan tak punya gejala
di layar — sebuah harga yang salah faktor kemasan tetap tampil sebagai rupiah
yang masuk akal, dan itu lolos sampai ada yang membandingkannya dengan nota.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.services import (
    _f,
    _fetch_movements,
    _k,
    _movement_sums,
    _purchase_prices,
    _unit_factors,
)
from core import mssql

# Harga beli TERTINGGI per satuan terkecil untuk tiap barang. Rata-rata tertimbang
# tak mungkin melampauinya — kecuali kalau satuannya keliru.
_SQL_HARGA_MAKS = """
SELECT pd.kd_barang, MAX(pd.harga_beli / NULLIF(COALESCE(bs.jumlah, 1), 0)) AS maks
FROM t_pembelian_detail pd
INNER JOIN t_pembelian p ON pd.no_transaksi = p.no_transaksi
LEFT JOIN (SELECT kd_barang, kd_satuan, MAX(jumlah) AS jumlah
           FROM m_barang_satuan GROUP BY kd_barang, kd_satuan) bs
  ON bs.kd_barang = pd.kd_barang AND bs.kd_satuan = pd.kd_satuan
WHERE CONVERT(DATE, p.tanggal) <= ? AND p.status IN (0, 1)
GROUP BY pd.kd_barang
"""


class Command(BaseCommand):
    help = "Verify _movement_sums (SQL GROUP BY) matches Python aggregation of _fetch_movements."

    def handle(self, *args, **options):
        profile = mssql.get_active_profile()
        if not profile:
            raise CommandError("Tidak ada koneksi aktif.")
        date_to = dt.datetime.now()

        with mssql.cursor(profile) as cur:
            factors = _unit_factors(cur)
            moves = _fetch_movements(cur, date_to=date_to)
            agg_py: dict = {}
            for m in moves:
                f = factors.get((_k(m["kd_barang"]), _k(m["kd_satuan"])), 1.0)
                key = (_k(m["kd_divisi"]), _k(m["kd_barang"]))
                agg_py[key] = agg_py.get(key, 0.0) + f * (_f(m["debet"]) - _f(m["kredit"]))

            sums = _movement_sums(cur, date_to=date_to)

        # SQL may return several case/padding variants of the same CI key; merge.
        agg_sql: dict = {}
        for r in sums:
            key = (_k(r["kd_divisi"]), _k(r["kd_barang"]))
            agg_sql[key] = agg_sql.get(key, 0.0) + _f(r["stok_awal"]) + _f(r["masuk"]) - _f(r["keluar"])
        bad = [
            k for k in set(agg_py) | set(agg_sql)
            if abs(agg_py.get(k, 0.0) - agg_sql.get(k, 0.0)) > 0.001
        ]
        if bad:
            for k in bad[:10]:
                self.stderr.write(f"  {k}: py={agg_py.get(k)} sql={agg_sql.get(k)}")
            raise CommandError(f"{len(bad)} key beda (dari {len(agg_py)}).")
        self.stdout.write(self.style.SUCCESS(f"OK: {len(agg_py)} key identik ({len(moves)} movement)."))

        # --- Snapshot check: snapshot+delta == full recompute (Fase 1 §1.6) ---
        from apps.inventory.services import _snapshot_meta

        with mssql.cursor(profile) as cur:
            if _snapshot_meta(cur) is None:
                self.stdout.write("Snapshot: pos_stok_snapshot belum ada/kosong — lewati cek snapshot.")
                return
            snap = {  # jalur snapshot+delta
                (_k(r["kd_divisi"]), _k(r["kd_barang"])): _f(r["stok_awal"]) + _f(r["masuk"]) - _f(r["keluar"])
                for r in _movement_sums(cur, date_to=date_to, use_snapshot=True)
            }
        # agg_sql di atas = jalur penuh (use_snapshot default True tapi tanpa snapshot
        # saat itu?) — hitung ulang penuh eksplisit untuk perbandingan yang jelas.
        with mssql.cursor(profile) as cur:
            full = {
                (_k(r["kd_divisi"]), _k(r["kd_barang"])): _f(r["stok_awal"]) + _f(r["masuk"]) - _f(r["keluar"])
                for r in _movement_sums(cur, date_to=date_to, use_snapshot=False)
            }
        bad2 = [k for k in set(snap) | set(full) if abs(snap.get(k, 0.0) - full.get(k, 0.0)) > 0.001]
        if bad2:
            for k in bad2[:10]:
                self.stderr.write(f"  {k}: snapshot={snap.get(k)} full={full.get(k)}")
            raise CommandError(f"Snapshot: {len(bad2)} key beda vs recompute penuh (dari {len(full)}).")
        self.stdout.write(self.style.SUCCESS(f"Snapshot OK: {len(full)} key identik (snapshot+delta == penuh)."))

        self._cek_satuan_harga(profile, date_to)

    def _cek_satuan_harga(self, profile, date_to):
        """`harga_average` harus per satuan TERKECIL, sama seperti `stok_akhir`
        yang mengalikannya.

        Rata-rata tertimbang tak pernah melampaui harga tertinggi penyusunnya,
        jadi `harga_average > MAX(harga per satuan terkecil)` hanya bisa berarti
        satuannya salah. Persis itu yang terjadi: rumus lama membagi pembilang DAN
        penyebut dengan `bs.jumlah` sehingga menghasilkan harga per satuan BELI,
        dan kolom `nominal` di Stok Akhir menggelembung sebesar faktor kemasan.
        Diukur ulang saat cek ini ditulis: rumus lama melanggar pada 181 dari
        26.118 barang di testgudang (sampai 12x), rumus sekarang nol pelanggaran
        di testgudang, PUSAT, dan PAGESANGAN.

        Batas BAWAH sengaja tak diperiksa: pembelian berharga 0 ada di data nyata
        dan menarik rata-rata di bawah harga terendah yang bukan nol — itu benar,
        dan memeriksanya hanya akan menghasilkan kegagalan palsu.
        """
        with mssql.cursor(profile) as cur:
            avg_map, _, _ = _purchase_prices(cur, date_to)
            cur.execute(_SQL_HARGA_MAKS, [date_to.date()])
            maks = {_k(r[0]): _f(r[1]) for r in cur.fetchall()}

        # Toleransi 0,1% untuk pembulatan money/float, bukan untuk selisih satuan:
        # faktor kemasan terkecil yang mungkin adalah 2x.
        langgar = [(k, v, maks[k]) for k, v in avg_map.items()
                   if k in maks and maks[k] > 0 and v > maks[k] * 1.001]
        if langgar:
            for k, v, m in sorted(langgar, key=lambda x: -x[1] / x[2])[:10]:
                self.stderr.write(f"  {k}: harga_average={v:,.2f} > maks/satuan-terkecil={m:,.2f} ({v / m:.2f}x)")
            raise CommandError(
                f"Satuan harga: {len(langgar)} dari {len(avg_map)} barang melampaui harga beli "
                "tertinggi per satuan terkecil — harga_average kemungkinan per satuan BELI.")
        self.stdout.write(self.style.SUCCESS(
            f"Satuan harga OK: {len(avg_map)} barang, harga_average per satuan terkecil."))

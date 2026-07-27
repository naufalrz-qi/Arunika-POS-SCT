"""Diagnostik READ-ONLY: dari mana harga beli di server toko sebenarnya berasal?

    python manage.py audit_harga_beli_diag
    python manage.py audit_harga_beli_diag --toko 1 --gudang 13 --csv out.csv

Barang mengalir: gudang beli dari supplier -> gudang jual ke toko -> nota itu
terbit di server toko sebagai pembelian. Dugaan pemilik sistem: `harga_beli` yang
tercatat di toko sebenarnya adalah HARGA JUAL gudang, padahal yang benar adalah
harga beli gudang ke supplier. Sebagian nota gudang juga berharga 0, sebabnya
belum diketahui.

Perintah ini TIDAK memperbaiki apa pun. Ia hanya menjawab lima pertanyaan yang
harus terjawab sebelum halaman audit dirancang, karena jawabannya belum diketahui
siapa pun dan menebak akan membuang pekerjaan:

  1. Apakah kedua DB uji benar-benar berpasangan (ada nota yang sama)?
  2. Seperti apa tabel kanal sync (tbl_log / tbl_tmp_post / tbl_tmp_get)?
  3. Adakah penaut pasti dari pembelian toko ke nota penjualan gudang?
  4. Berapa banyak harga 0, di sisi mana, periode kapan?
  5. Benarkah harga_beli toko == harga_jual gudang?

HANYA SELECT. Menolak jalan di luar DB uji (lihat _ALLOWED) — pemilik sistem
melarang server produksi dipakai untuk analisis, jadi itu dijaga di kode, bukan
diserahkan ke kehati-hatian saat mengetik.
"""
import bisect
import csv

import pyodbc
from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions.reports import _ghb
from core import mssql

# (host, db_name) yang boleh disentuh, huruf kecil. Sengaja daftar-putih, bukan
# daftar-hitam: profil baru yang belum dikenal ditolak, bukan diizinkan diam-diam.
_ALLOWED = {("localhost", "grosirpusat"), ("localhost", "testgudang")}

SEP = "=" * 78


def _rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(cur, sql, params=None):
    cur.execute(sql, params or [])
    row = cur.fetchone()
    return row[0] if row else None


def _table_exists(cur, name) -> bool:
    return _one(cur, "SELECT OBJECT_ID(?)", [name]) is not None


class Command(BaseCommand):
    help = "Diagnostik read-only asal harga beli toko vs pembelian gudang (DB uji saja)."

    def add_arguments(self, parser):
        parser.add_argument("--toko", type=int, default=None, help="ServerProfile id sisi toko (default: nama 'Testing')")
        parser.add_argument("--gudang", type=int, default=None, help="ServerProfile id sisi gudang (default: nama 'testgudang')")
        parser.add_argument("--csv", default=None, help="Tulis baris pembanding harga ke CSV")
        parser.add_argument("--sample", type=int, default=8, help="Jumlah baris contoh per bagian (default 8)")
        parser.add_argument(
            "--baris", type=int, default=5000,
            help="Baris pembelian toko yang diperiksa di bagian 5; 0 = SEMUA (default 5000)",
        )
        parser.add_argument(
            "--lewati-log", action="store_true",
            help="Lewati bagian 3 (memindai tbl_log berjuta baris dengan LIKE '%%…%%' — lambat)",
        )

    # --- resolusi profil + penjaga -----------------------------------------

    def _resolve(self, pk, fallback_name, label):
        if pk:
            p = ServerProfile.objects.filter(pk=pk).first()
            if not p:
                raise CommandError(f"Profil {label} id={pk} tidak ditemukan.")
        else:
            p = ServerProfile.objects.filter(name__iexact=fallback_name).first()
            if not p:
                raise CommandError(
                    f"Profil {label} tak diberikan dan tak ada profil bernama '{fallback_name}'. "
                    f"Sebutkan dengan --{label}."
                )
        key = (p.host.strip().lower(), p.db_name.strip().lower())
        if key not in _ALLOWED:
            raise CommandError(
                f"DITOLAK: {p.name} ({p.host}/{p.db_name}) bukan DB uji. Diagnostik ini "
                f"hanya boleh menyentuh: {sorted(_ALLOWED)}. Server produksi tidak boleh "
                f"dipakai untuk analisis."
            )
        return p

    def handle(self, *args, **opts):
        toko = self._resolve(opts["toko"], "Testing", "toko")
        gudang = self._resolve(opts["gudang"], "testgudang", "gudang")
        n = opts["sample"]
        self._top = f"TOP {opts['baris']}" if opts["baris"] else ""

        self.stdout.write(SEP)
        self.stdout.write(f"DIAGNOSTIK HARGA BELI  (read-only)")
        self.stdout.write(f"  toko   : {toko.name} -> {toko.host}/{toko.db_name}")
        self.stdout.write(f"  gudang : {gudang.name} -> {gudang.host}/{gudang.db_name}")
        self.stdout.write(SEP)

        try:
            with mssql.cursor(toko) as tcur, mssql.cursor(gudang) as gcur:
                self._q1_pasangan(tcur, gcur, n)
                self._q2_kanal_sync(tcur, gcur, n)
                if opts["lewati_log"]:
                    self._head("3. PENAUT NOTA — DILEWATI (--lewati-log)")
                else:
                    self._q3_penaut(tcur, gcur, n)
                self._q4_harga_nol(tcur, gcur)
                self._q5_hipotesis(tcur, gcur, n, opts["csv"])
        except pyodbc.Error as exc:
            raise CommandError(f"Gagal terhubung / query: {exc}")

        self.stdout.write("\n" + SEP)
        self.stdout.write("SELESAI. Tinjau angka di atas sebelum merancang halaman audit.")
        self.stdout.write(SEP)

    # --- 1. apakah DB uji berpasangan --------------------------------------

    def _q1_pasangan(self, tcur, gcur, n):
        self._head("1. APAKAH KEDUA DB UJI BERPASANGAN?")

        for label, cur, hdr, det in (
            ("toko  pembelian", tcur, "t_pembelian", "t_pembelian_detail"),
            ("gudang penjualan", gcur, "t_penjualan", "t_penjualan_detail"),
            ("gudang pembelian", gcur, "t_pembelian", "t_pembelian_detail"),
        ):
            if not _table_exists(cur, hdr):
                self.stdout.write(f"  {label:<17} : tabel {hdr} TIDAK ADA")
                continue
            cur.execute(
                f"SELECT COUNT(*) AS nota, MIN(tanggal) AS dari, MAX(tanggal) AS sampai FROM {hdr}"
            )
            r = _rows(cur)[0]
            brg = _one(cur, f"SELECT COUNT(DISTINCT kd_barang) FROM {det}")
            self.stdout.write(
                f"  {label:<17} : {r['nota'] or 0:>7} nota | {brg or 0:>6} barang | "
                f"{r['dari']} .. {r['sampai']}"
            )

        # Irisan nomor nota: kalau pembelian toko memang berasal dari penjualan
        # gudang, sebagian no_transaksi mestinya sama persis.
        gudang_nota = self._nota_set(gcur, "t_penjualan", n * 40)
        toko_nota = self._nota_set(tcur, "t_pembelian", n * 40)
        irisan = gudang_nota & toko_nota
        self.stdout.write(
            f"\n  Irisan no_transaksi (contoh {len(gudang_nota)} gudang x {len(toko_nota)} toko): "
            f"{len(irisan)}"
        )
        if irisan:
            self.stdout.write(f"    contoh: {sorted(irisan)[:n]}")
            self.stdout.write("    -> PENAUTAN NOTA PERSIS MUNGKIN. Fase 2 pakai ini, bukan aturan temporal.")
        else:
            self.stdout.write("    -> tak ada nomor nota yang sama pada contoh ini.")

        # Irisan barang: tanpa ini, pembandingan harga apa pun tak bermakna.
        gb = self._barang_set(gcur, "t_penjualan_detail")
        tb = self._barang_set(tcur, "t_pembelian_detail")
        self.stdout.write(
            f"  Irisan kd_barang : {len(gb & tb)} (gudang {len(gb)}, toko {len(tb)})"
        )
        if not (gb & tb):
            self.stdout.write(
                "    -> PERINGATAN: nol irisan barang. Kedua DB kemungkinan salinan server "
                "berbeda yang tak berpasangan; pembandingan harga tak akan bermakna."
            )

    def _nota_set(self, cur, table, limit):
        if not _table_exists(cur, table):
            return set()
        cur.execute(f"SELECT TOP {limit} no_transaksi FROM {table} ORDER BY tanggal DESC")
        return {(r[0] or "").strip().upper() for r in cur.fetchall()}

    def _barang_set(self, cur, table):
        if not _table_exists(cur, table):
            return set()
        cur.execute(f"SELECT DISTINCT kd_barang FROM {table}")
        return {(r[0] or "").strip().upper() for r in cur.fetchall()}

    # --- 2. tabel kanal sync ------------------------------------------------

    def _q2_kanal_sync(self, tcur, gcur, n):
        self._head("2. TABEL KANAL SYNC")
        for sisi, cur in (("toko", tcur), ("gudang", gcur)):
            for tbl in ("tbl_tmp_post", "tbl_tmp_get", "tbl_log", "tbl_log_transaksi"):
                if not _table_exists(cur, tbl):
                    self.stdout.write(f"  {sisi:<6} {tbl:<18} : tidak ada")
                    continue
                jml = _one(cur, f"SELECT COUNT(*) FROM {tbl}")
                cur.execute(
                    "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", [tbl],
                )
                kol = ", ".join(f"{r[0]}:{r[1]}" for r in cur.fetchall())
                self.stdout.write(f"  {sisi:<6} {tbl:<18} : {jml:>7} baris | {kol}")

    # --- 3. penaut nota di teks SQL yang disinkronkan -----------------------

    def _q3_penaut(self, tcur, gcur, n):
        self._head("3. ADAKAH PENAUT PEMBELIAN TOKO -> NOTA GUDANG?")

        kolom = self._text_column(tcur, "tbl_log")
        if not kolom:
            self.stdout.write(
                "  tbl_log tak ada / tak punya kolom teks di sisi toko — penautan lewat "
                "kanal sync tak bisa diperiksa di DB uji ini."
            )
        else:
            jml = _one(
                tcur,
                f"SELECT COUNT(*) FROM tbl_log WHERE {kolom} LIKE '%t_pembelian%'",
            )
            self.stdout.write(f"  tbl_log.{kolom} menyinggung t_pembelian: {jml or 0} baris")
            if jml:
                tcur.execute(
                    f"SELECT TOP {n} LEFT({kolom}, 400) FROM tbl_log "
                    f"WHERE {kolom} LIKE '%t_pembelian%'"
                )
                self.stdout.write("  contoh teks (400 char pertama) — cari nomor nota gudang di sini:")
                for (teks,) in tcur.fetchall():
                    self.stdout.write(f"    | {teks}")

            # Uji terarah: apakah nomor nota penjualan gudang muncul di teks toko?
            # SATU query lalu cocokkan di Python. Versi sebelumnya menjalankan satu
            # `LIKE '%no%'` per nomor nota — 40 pemindaian penuh atas tabel log yang
            # bisa berjuta baris, masing-masing berplafon 60 detik.
            tcur.execute(
                f"SELECT TOP 500 {kolom} FROM tbl_log WHERE {kolom} LIKE '%t_pembelian%'"
            )
            teks_log = [(t or "") for (t,) in tcur.fetchall()]
            gcur.execute("SELECT TOP 200 no_transaksi FROM t_penjualan ORDER BY tanggal DESC")
            nota = [(r[0] or "").strip() for r in gcur.fetchall()]
            nota = [x for x in nota if x]
            ketemu = [no for no in nota if any(no in t for t in teks_log)]
            self.stdout.write(
                f"  Nomor nota penjualan gudang yang muncul di {len(teks_log)} contoh teks "
                f"tbl_log toko: {len(ketemu)}/{len(nota)}"
            )
            if ketemu:
                self.stdout.write(f"    contoh: {ketemu[:n]}")
                self.stdout.write("    -> penaut pasti ADA lewat kanal sync.")
            elif teks_log:
                self.stdout.write(
                    "    -> tak ada. Penautan harus lewat aturan temporal (pembelian gudang "
                    "terakhir sebelum tanggal penjualan)."
                )

    def _text_column(self, cur, tbl):
        """Kolom teks terpanjang di `tbl` — nama kolomnya beda antar server legacy."""
        if not _table_exists(cur, tbl):
            return None
        cur.execute(
            "SELECT TOP 1 COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? AND DATA_TYPE IN ('varchar','nvarchar','text','ntext') "
            "ORDER BY CASE WHEN CHARACTER_MAXIMUM_LENGTH = -1 THEN 999999 "
            "ELSE COALESCE(CHARACTER_MAXIMUM_LENGTH, 0) END DESC", [tbl],
        )
        row = cur.fetchone()
        return row[0] if row else None

    # --- 4. sebaran harga 0 -------------------------------------------------

    def _q4_harga_nol(self, tcur, gcur):
        self._head("4. SEBARAN HARGA 0")
        for label, cur, hdr, det, kol in (
            ("gudang jual   ", gcur, "t_penjualan", "t_penjualan_detail", "harga_jual"),
            ("gudang beli   ", gcur, "t_pembelian", "t_pembelian_detail", "harga_beli"),
            ("toko   beli   ", tcur, "t_pembelian", "t_pembelian_detail", "harga_beli"),
        ):
            if not _table_exists(cur, det):
                self.stdout.write(f"  {label}: tabel {det} tidak ada")
                continue
            cur.execute(
                f"SELECT COUNT(*) AS total, "
                f"SUM(CASE WHEN COALESCE(d.{kol}, 0) = 0 THEN 1 ELSE 0 END) AS nol "
                f"FROM {det} d"
            )
            r = _rows(cur)[0]
            total, nol = r["total"] or 0, r["nol"] or 0
            pct = (nol / total * 100) if total else 0
            self.stdout.write(f"  {label}: {nol:>7} / {total:<8} baris berharga 0  ({pct:.2f}%)")

            if nol:
                cur.execute(
                    f"SELECT YEAR(h.tanggal) AS thn, COUNT(*) AS nol FROM {det} d "
                    f"INNER JOIN {hdr} h ON d.no_transaksi = h.no_transaksi "
                    f"WHERE COALESCE(d.{kol}, 0) = 0 GROUP BY YEAR(h.tanggal) ORDER BY thn"
                )
                per_thn = " ".join(f"{r['thn']}:{r['nol']}" for r in _rows(cur))
                self.stdout.write(f"                  per tahun -> {per_thn}")

    # --- 5. hipotesis: harga_beli toko == harga_jual gudang -----------------

    def _q5_hipotesis(self, tcur, gcur, n, csv_path):
        self._head("5. BENARKAH harga_beli TOKO == harga_jual GUDANG?")

        if not (_table_exists(tcur, "t_pembelian_detail") and _table_exists(gcur, "t_penjualan_detail")):
            self.stdout.write("  Tabel detail tak lengkap — uji dilewati.")
            return

        # Harga jual gudang terakhir per (barang, satuan), dan harga beli gudang
        # terakhir yang > 0 — dua kandidat sumber untuk harga beli toko.
        gcur.execute(
            "SELECT kd_barang, kd_satuan, harga_jual FROM ("
            "  SELECT d.kd_barang, d.kd_satuan, d.harga_jual,"
            "         ROW_NUMBER() OVER (PARTITION BY d.kd_barang, d.kd_satuan "
            "                            ORDER BY h.tanggal DESC, h.no_transaksi DESC) AS rn"
            "  FROM t_penjualan_detail d"
            "  INNER JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi"
            ") z WHERE z.rn = 1"
        )
        jual = {(r["kd_barang"].strip().upper(), (r["kd_satuan"] or "").strip().upper()): float(r["harga_jual"] or 0)
                for r in _rows(gcur)}

        # SEMUA pembelian gudang, terurut waktu per (barang, satuan). Dipakai dua
        # aturan sekaligus: "terakhir kapan pun" dan "terakhir <= tanggal nota toko".
        # 74rb baris — muat di memori, jadi pencarian per baris cukup bisect.
        # Harga net = mentah setelah diskon baris + pajak/ppnbm nota, memakai
        # ekspresi _ghb yang sama dengan penjualan_hpp — sudah diverifikasi lawan
        # UDF legacy oleh scripts/verify_ghb_semantics.py, jadi jangan tulis ulang.
        net = _ghb(
            "d.harga_beli",
            ["COALESCE(d.diskon1,0)", "COALESCE(d.diskon2,0)",
             "COALESCE(d.diskon3,0)", "COALESCE(d.diskon4,0)"],
            pajak="COALESCE(h.pajak,0)", ppnbm="COALESCE(h.ppnbm,0)",
        )
        gcur.execute(
            f"SELECT d.kd_barang, d.kd_satuan, h.tanggal, d.harga_beli, ({net}) AS harga_net "
            "FROM t_pembelian_detail d "
            "INNER JOIN t_pembelian h ON d.no_transaksi = h.no_transaksi "
            "WHERE COALESCE(d.harga_beli, 0) > 0 "
            "ORDER BY h.tanggal"
        )
        riwayat: dict = {}
        for r in _rows(gcur):
            key = ((r["kd_barang"] or "").strip().upper(), (r["kd_satuan"] or "").strip().upper())
            riwayat.setdefault(key, []).append(
                (r["tanggal"], float(r["harga_beli"] or 0), float(r["harga_net"] or 0))
            )
        beli = {k: v[-1][1] for k, v in riwayat.items()}

        tcur.execute(
            f"SELECT {self._top} h.no_transaksi, h.tanggal, d.kd_barang, d.kd_satuan, d.qty, d.harga_beli "
            "FROM t_pembelian_detail d "
            "INNER JOIN t_pembelian h ON d.no_transaksi = h.no_transaksi "
            "ORDER BY h.tanggal DESC"
        )
        baris = _rows(tcur)

        cocok_jual = cocok_beli = beda = tanpa_pasangan = nol_toko = 0
        contoh, semua = [], []
        for r in baris:
            key = ((r["kd_barang"] or "").strip().upper(), (r["kd_satuan"] or "").strip().upper())
            hb = float(r["harga_beli"] or 0)
            gj, gb = jual.get(key), beli.get(key)
            if hb == 0:
                nol_toko += 1
            # Urutan periksa penting: harga beli gudang diuji LEBIH DULU. Diagnostik
            # putaran pertama hanya menguji harga jual dan menyimpulkan "beda" untuk
            # 4982 baris — padahal contohnya justru cocok sempurna dengan harga beli.
            if gj is None and gb is None:
                tanpa_pasangan += 1
                status = "tanpa pasangan"
            elif gb is not None and abs(hb - gb) < 0.01:
                cocok_beli += 1
                status = "= harga beli gudang"
            elif gj is not None and abs(hb - gj) < 0.01:
                cocok_jual += 1
                status = "= harga jual gudang"
            else:
                beda += 1
                status = "beda"
                if len(contoh) < n:
                    contoh.append((r["no_transaksi"].strip(), r["kd_barang"].strip(), hb, gj, gb))
            semua.append({
                "no_transaksi": (r["no_transaksi"] or "").strip(),
                "tanggal": r["tanggal"], "kd_barang": (r["kd_barang"] or "").strip(),
                "kd_satuan": (r["kd_satuan"] or "").strip(), "qty": r["qty"],
                "harga_beli_toko": hb, "harga_jual_gudang": gj, "harga_beli_gudang": gb,
                "status": status,
            })

        total = len(baris)
        self.stdout.write(f"  Diperiksa {total} baris pembelian toko terbaru:")
        self.stdout.write(f"    == harga BELI gudang : {cocok_beli:>6}  <- sudah dikoreksi admin")
        self.stdout.write(f"    == harga JUAL gudang : {cocok_jual:>6}  <- BELUM dikoreksi (tunggakan)")
        self.stdout.write(f"    tak cocok keduanya   : {beda:>6}")
        self.stdout.write(f"    tanpa pasangan       : {tanpa_pasangan:>6}")
        self.stdout.write(f"    harga_beli toko = 0  : {nol_toko:>6}")

        self._q5b_aturan(baris, riwayat, jual)

        if contoh:
            self.stdout.write("\n  Contoh yang BEDA (nota, barang, beli_toko, jual_gudang, beli_gudang):")
            for c in contoh:
                self.stdout.write(f"    {c[0]:<16} {c[1]:<14} {c[2]:>12,.2f} {c[3]:>12,.2f} "
                                  f"{'-' if c[4] is None else format(c[4], ',.2f'):>12}")

        if csv_path and semua:
            with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(semua[0].keys()))
                w.writeheader()
                w.writerows(semua)
            self.stdout.write(f"\n  CSV: {csv_path} ({len(semua)} baris)")

    def _q5b_aturan(self, baris, riwayat, jual):
        """Aturan otomatis mana yang mereproduksi angka koreksi manual admin?

        Admin mengoreksi harga beli toko satu per satu ke harga beli gudang. Ribuan
        koreksi itu adalah KUNCI JAWABAN: aturan yang mereproduksi angka mereka
        paling sering adalah aturan yang sebenarnya mereka pakai. Jadi aturan untuk
        otomatisasi dipilih dengan diuji, bukan ditebak.
        """
        # kolom 1 = harga mentah, kolom 2 = harga net (diskon+pajak). Dua deret
        # harga, aturan temporal yang sama diuji atas keduanya.
        idx = {k: ([x[0] for x in v], [x[1] for x in v], [x[2] for x in v])
               for k, v in riwayat.items()}

        def terakhir(kol):
            def fn(key, _tgl):
                v = idx.get(key)
                return v[kol][-1] if v else None
            return fn

        def terakhir_sebelum(kol):
            def fn(key, tgl):
                v = idx.get(key)
                if not v:
                    return None
                i = bisect.bisect_right(v[0], tgl)
                return v[kol][i - 1] if i > 0 else None
            return fn

        def terdekat(kol):
            """Sebelum kalau ada; kalau nota toko mendahului pembelian gudang mana
            pun, pakai pembelian paling awal sesudahnya."""
            def fn(key, tgl):
                v = idx.get(key)
                if not v:
                    return None
                i = bisect.bisect_right(v[0], tgl)
                return v[kol][i - 1] if i > 0 else v[kol][0]
            return fn

        kandidat = (
            ("A. MENTAH, terakhir kapan pun", terakhir(1)),
            ("B. MENTAH, terakhir <= tanggal nota", terakhir_sebelum(1)),
            ("C. MENTAH, B + fallback maju", terdekat(1)),
            ("D. NET (diskon+pajak), terakhir kapan pun", terakhir(2)),
            ("E. NET (diskon+pajak), terakhir <= tanggal", terakhir_sebelum(2)),
            ("F. NET (diskon+pajak), E + fallback maju", terdekat(2)),
        )

        # Kunci jawaban = baris yang harga belinya sudah masuk akal (>0 dan bukan
        # sisa harga jual gudang yang belum dikoreksi).
        oracle = []
        for r in baris:
            key = ((r["kd_barang"] or "").strip().upper(), (r["kd_satuan"] or "").strip().upper())
            hb = float(r["harga_beli"] or 0)
            gj = jual.get(key)
            if hb > 0 and not (gj is not None and abs(hb - gj) < 0.01):
                oracle.append((key, r["tanggal"], hb))

        self.stdout.write(
            f"\n  Aturan mana yang mereproduksi {len(oracle)} koreksi admin? "
            f"(makin tinggi makin tepat aturannya)"
        )
        for nama, fn in kandidat:
            tepat = kosong = 0
            for key, tgl, hb in oracle:
                v = fn(key, tgl)
                if v is None:
                    kosong += 1
                elif abs(hb - v) < 0.01:
                    tepat += 1
            pct = (tepat / len(oracle) * 100) if oracle else 0
            self.stdout.write(f"    {nama:<44} {tepat:>6} tepat ({pct:5.1f}%), {kosong} tanpa data")

        # Sisa yang tak tereproduksi: kalau rasionya menggerombol di beberapa nilai,
        # itu tarif diskon tetap, bukan keacakan — dan berarti aturannya masih bisa
        # dilengkapi. Kalau tersebar rata, sisanya memang penyuntingan bebas admin.
        terbaik = kandidat[-1][1]
        rasio: dict = {}
        for key, tgl, hb in oracle:
            v = terbaik(key, tgl)
            if not v or abs(hb - v) < 0.01:
                continue
            rasio[round(hb / v, 4)] = rasio.get(round(hb / v, 4), 0) + 1
        if rasio:
            atas = sorted(rasio.items(), key=lambda kv: -kv[1])[:12]
            sisa = sum(rasio.values())
            self.stdout.write(f"\n  Sisa {sisa} baris tak tereproduksi aturan F — sebaran rasio toko/gudang:")
            for r, c in atas:
                tanda = "  <- potongan tetap" if c >= 10 else ""
                self.stdout.write(f"    rasio {r:<8} : {c:>5} baris  ({(1 - r) * 100:+6.2f}%){tanda}")
            self.stdout.write(
                f"    ({len(rasio)} rasio berbeda; {sum(c for _, c in atas)}/{sisa} baris tercakup 12 teratas)"
            )

    def _head(self, judul):
        # Flush eksplisit: stdout ter-buffer blok saat dialihkan ke berkas, jadi
        # tanpa ini diagnostik yang berjalan lama tampak menggantung tanpa kabar.
        self.stdout.write(f"\n{SEP}\n{judul}\n{'-' * 78}")
        self.stdout.flush()

"""Salin tabel legacy dari server mana pun ke database salinan LOKAL untuk uji.

    manage.py salin_legacy --sumber PUSAT --tujuan "salinan pusat 2025" \\
        --dari 2025-01-01 --sampai 2025-12-31 [--dry-run]

Sumber hanya DIBACA (READ UNCOMMITTED). Tujuan harus profil ber-lingkungan
`uji`, dan databasenya harus kosong atau salinan buatan perintah ini sendiri --
lihat `apps/bisnis/salin_legacy.py`.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
import datetime as dt
import time

from django.core.management.base import BaseCommand, CommandError

from apps.bisnis import salin_legacy as sl
from apps.connections.models import Lingkungan, ServerProfile
from core import mssql
from core.encryption import decrypt_checked

BATCH = 5000


class Command(BaseCommand):
    help = "Salin tabel legacy (jendela tanggal) ke database salinan lokal untuk uji."

    def add_arguments(self, p):
        p.add_argument("--sumber", required=True, help="Profil yang dibaca (boleh produksi)")
        p.add_argument("--tujuan", required=True, help="Profil salinan (wajib lingkungan uji)")
        p.add_argument("--dari", required=True)
        p.add_argument("--sampai", required=True)
        p.add_argument("--dry-run", action="store_true")

    def handle(self, *a, **o):
        sumber, tujuan = self._profil(o["sumber"]), self._profil(o["tujuan"])
        if tujuan.lingkungan != Lingkungan.UJI:
            raise CommandError(f"Profil tujuan '{tujuan.name}' bukan lingkungan 'uji'.")
        if (sumber.host.lower(), sumber.db_name.lower()) == (tujuan.host.lower(), tujuan.db_name.lower()):
            raise CommandError("Sumber dan tujuan menunjuk database yang sama.")
        if "]" in tujuan.db_name:
            raise CommandError(f"Nama database tak bisa dikutip aman: {tujuan.db_name!r}")
        try:
            dari = dt.datetime.strptime(o["dari"], "%Y-%m-%d")
            sampai = dt.datetime.strptime(o["sampai"], "%Y-%m-%d") + dt.timedelta(days=1)
        except ValueError:
            raise CommandError("--dari/--sampai harus YYYY-MM-DD")

        tabel = sl.tabel_dirujuk()
        awalan = "[dry-run] " if o["dry_run"] else ""
        self.stdout.write(
            f"{awalan}{sumber.name} ({sumber.host}/{sumber.db_name}) -> "
            f"{tujuan.name} ({tujuan.host}/{tujuan.db_name})  "
            f"dokumen {o['dari']}..{o['sampai']}  {len(tabel)} tabel"
        )

        # --- Metadata sumber: satu kueri, tanpa membaca isi -----------------
        with mssql.report_cursor(sumber) as src:
            src.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
                "NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION, COLLATION_NAME "
                "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION"
            )
            nama_kol = [d[0] for d in src.description]
            meta = {}
            for r in src.fetchall():
                baris = dict(zip(nama_kol, r))
                meta.setdefault(baris["TABLE_NAME"], []).append(baris)
        hilang = [t for t in tabel if t not in meta]
        if hilang:
            raise CommandError(f"Tabel dirujuk adapter tapi tak ada di sumber: {hilang}")
        kolom_per_tabel = {t: [c["COLUMN_NAME"] for c in cs] for t, cs in meta.items()}
        rencana = {t: sl.kelas_tabel(t, kolom_per_tabel) for t in tabel}

        if o["dry_run"]:
            for t in tabel:
                k, kepala, kunci = rencana[t]
                self.stdout.write(f"  {t:<28} {k}" + (f" <- {kepala}.{kunci}" if kepala else ""))
            return

        self._siapkan_database(tujuan)

        total, t0 = 0, time.time()
        pw = decrypt_checked(tujuan.password_encrypted)
        dst_conn = mssql._connect(tujuan.host, tujuan.port, tujuan.db_name,
                                  tujuan.username, pw, autocommit=False)
        try:
            dst = dst_conn.cursor()
            with mssql.report_cursor(sumber) as src:
                for t in tabel:
                    t1 = time.time()
                    kelas, kepala, kunci = rencana[t]
                    n = self._salin_tabel(src, dst, dst_conn, t, meta[t], kelas, kepala, kunci,
                                          dari, sampai)
                    total += n
                    self.stdout.write("  %-28s %-7s %9d baris  %6.1f dtk"
                                      % (t, kelas, n, time.time() - t1))
            dst.execute(f"INSERT INTO dbo.[{sl.PENANDA}] VALUES (?, ?, ?, ?, SYSDATETIME())",
                        f"{sumber.host}/{sumber.db_name}", dari, sampai - dt.timedelta(days=1),
                        len(tabel))
            dst_conn.commit()
        finally:
            dst_conn.close()
        self.stdout.write(self.style.SUCCESS(
            f"Selesai: {total:,} baris, {len(tabel)} tabel, {time.time() - t0:.1f} dtk"))

    # ------------------------------------------------------------------
    def _siapkan_database(self, tujuan):
        """Buat database kalau belum ada; kalau ada, WAJIB salinan buatan kita.

        Penjaga ini yang mencegah `--tujuan Testing` menghapus salinan grosirPusat:
        profil itu juga ber-lingkungan uji, jadi penanda lingkungan saja tak cukup.
        """
        pw = decrypt_checked(tujuan.password_encrypted)
        db = tujuan.db_name
        conn = mssql._connect(tujuan.host, tujuan.port, "master", tujuan.username, pw)
        try:
            cur = conn.cursor()
            cur.execute("SELECT DB_ID(?)", [db])
            if cur.fetchone()[0] is None:
                cur.execute(f"CREATE DATABASE [{db}]")
                cur.execute(f"ALTER DATABASE [{db}] SET RECOVERY SIMPLE")
                self.stdout.write(f"  database [{db}] dibuat")
            else:
                cur.execute(
                    f"SELECT OBJECT_ID('[{db}].dbo.[{sl.PENANDA}]'), "
                    f"(SELECT COUNT(*) FROM [{db}].sys.tables)"
                )
                penanda, n_tabel = cur.fetchone()
                if penanda is None and n_tabel:
                    raise CommandError(
                        f"Database [{db}] sudah berisi {n_tabel} tabel dan BUKAN salinan "
                        "buatan perintah ini. Menolak menimpanya."
                    )
                self.stdout.write(f"  database [{db}] salinan lama, ditimpa")
        finally:
            conn.close()

        conn = mssql._connect(tujuan.host, tujuan.port, db, tujuan.username, pw)
        try:
            conn.cursor().execute(
                f"IF OBJECT_ID('dbo.[{sl.PENANDA}]') IS NULL "
                f"CREATE TABLE dbo.[{sl.PENANDA}] (sumber varchar(300), dari datetime, "
                "sampai datetime, jumlah_tabel int, disalin_pada datetime2)"
            )
        finally:
            conn.close()

    def _salin_tabel(self, src, dst, dst_conn, t, kolom, kelas, kepala, kunci, dari, sampai):
        dst.execute(f"IF OBJECT_ID('dbo.[{t}]') IS NOT NULL DROP TABLE dbo.[{t}]")
        dst.execute(f"CREATE TABLE dbo.[{t}] (" + ", ".join(sl.tipe_kolom(c) for c in kolom) + ")")
        nama = [c["COLUMN_NAME"] for c in kolom]
        sql = sl.sql_baca(t, nama, kelas, kepala, kunci)
        src.execute(sql, *([] if kelas == "utuh" else [dari, sampai]))

        ins = (f"INSERT INTO dbo.[{t}] (" + ", ".join(f"[{k}]" for k in nama)
               + ") VALUES (" + ", ".join("?" * len(nama)) + ")")
        dst.fast_executemany = not sl.punya_lob(kolom)
        n = 0
        while True:
            potong = src.fetchmany(BATCH)
            if not potong:
                break
            dst.executemany(ins, [tuple(r) for r in potong])
            n += len(potong)
        # Indeks secukupnya supaya view di atas salinan tak memindai tiap kali:
        # tanpanya `_nota_net` meng-GROUP BY 800 ribu baris detail tanpa bantuan.
        for k in ("no_transaksi", "no_retur", "no_order", "tanggal", "kd_barang"):
            if k in nama:
                dst.execute(f"CREATE INDEX [ix_{t}_{k}] ON dbo.[{t}] ([{k}])")
        dst_conn.commit()
        return n

    def _profil(self, nama):
        p = ServerProfile.objects.filter(name=nama).first()
        if not p:
            raise CommandError(f"Profil '{nama}' tak ada.")
        return p

"""Siapkan skema pusat AMPHOREUS, dan (opsional) isi katalog master sekali.

    python manage.py init_hub --hub AMPHOREUS --ref GUDANG --dry-run
    python manage.py init_hub --hub AMPHOREUS --ref GUDANG
    python manage.py init_hub --hub AMPHOREUS --ref GUDANG --seed-master

Idempoten: tabel yang sudah ada dilewati, tidak pernah ALTER atau DROP. Kalau
skema cabang berubah, perbedaannya DILAPORKAN sebagai `kolom_baru` dan berhenti
di situ — menyesuaikan tabel berisi data adalah keputusan manusia, bukan efek
samping sebuah command.

`--seed-master` menyalin tabel master (~500rb baris total) dari tiap cabang
ber-`kode_sumber`. Transaksi TIDAK ikut: pusat sengaja mulai kosong untuk
transaksi. Tanpa katalog, tiap transaksi yang masuk menunjuk kd_barang yang tak
ada padanannya di pusat sampai barang itu kebetulan diedit.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions import hub_schema, hub_sync
from core import mssql


class Command(BaseCommand):
    help = "Buat skema pusat AMPHOREUS dari katalog server acuan."

    def add_arguments(self, parser):
        parser.add_argument("--hub", required=True, help="Nama ServerProfile pusat.")
        parser.add_argument("--ref", required=True, help="Nama ServerProfile acuan skema (mis. GUDANG).")
        parser.add_argument("--dry-run", action="store_true", help="Jalankan lalu ROLLBACK.")
        parser.add_argument(
            "--seed-master", action="store_true",
            help="Salin tabel master sekali dari tiap cabang ber-kode_sumber.",
        )

    def _profil(self, nama):
        p = ServerProfile.objects.filter(name=nama).first()
        if not p:
            raise CommandError(f"ServerProfile '{nama}' tidak ditemukan.")
        return p

    def handle(self, *args, **opts):
        hub = self._profil(opts["hub"])
        ref = self._profil(opts["ref"])
        mode = " (DRY RUN)" if opts["dry_run"] else ""
        self.stdout.write(f"Pusat: {hub.name} ({hub.host}/{hub.db_name}) | acuan skema: {ref.name}{mode}")

        try:
            hasil = hub_schema.buat_skema(
                ref, hub, hub_sync.HUB_TABLE_SPECS, dry_run=opts["dry_run"]
            )
        except RuntimeError as exc:
            raise CommandError(str(exc))

        dibuat = [r for r in hasil if r["dibuat"]]
        drift = [r for r in hasil if r["kolom_baru"]]
        self.stdout.write(f"  {len(dibuat)} tabel dibuat, {len(hasil) - len(dibuat)} sudah ada.")
        for r in dibuat:
            self.stdout.write(f"    + {r['tabel']}")
        for r in drift:
            # Bukan error: pusat tetap bisa dipakai, kolom baru saja tak terisi.
            # Tapi harus terlihat, karena diam-diam itulah bentuk kegagalannya.
            self.stderr.write(
                f"    ! {r['tabel']}: cabang punya kolom yang pusat belum punya: "
                f"{', '.join(r['kolom_baru'])}"
            )

        if not opts["seed_master"]:
            return
        if opts["dry_run"]:
            self.stdout.write("  --seed-master dilewati pada dry run.")
            return

        sumber = hub_sync.sumber_profiles()
        if not sumber:
            raise CommandError(
                "Tidak ada profil ber-kode_sumber. Isi dulu kode_sumber tiap cabang "
                "(lihat apps/connections/models.py) — tanpa itu baris tiap cabang "
                "tidak bisa dibedakan di pusat."
            )
        self.stdout.write(f"Seed master dari {len(sumber)} cabang:")
        for src in sumber:
            for tabel in hub_sync.SEED_TABLES:
                try:
                    n = self._seed(src, hub, tabel)
                except Exception as exc:  # satu tabel gagal tak menghentikan sisanya
                    self.stderr.write(f"    {src.kode_sumber}/{tabel}: GAGAL — {exc}")
                    continue
                self.stdout.write(f"    {src.kode_sumber}/{tabel}: {n} baris")

    def _seed(self, src, hub, tabel: str) -> int:
        """Salin satu tabel master milik satu cabang ke pusat.

        Hapus-lalu-salin per `kd_sumber`, bukan per baris: idempoten, dan cabang
        lain tidak tersentuh. Pola batch + fast_executemany diambil dari
        `cdc_sync.backfill_table`, termasuk penjagaan LOB — `m_pegawai.foto`
        membuat pyodbc mengalokasikan buffer selebar kolom untuk seluruh batch
        dan memorinya meledak kalau fast_executemany dipakai apa adanya.
        """
        from apps.transactions.cdc_sync import _has_lob_columns
        from apps.transactions.hub_schema import KOL_SUMBER

        kd = src.kode_sumber.strip()
        with mssql.cursor(src) as s_cur, mssql.cursor(hub, autocommit=False) as h_cur:
            h_cur.execute("SELECT OBJECT_ID(?)", [tabel])
            if h_cur.fetchone()[0] is None:
                raise RuntimeError("tabel belum ada di pusat")
            h_cur.execute(
                "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?) "
                "AND is_computed = 0 AND is_identity = 0 ORDER BY column_id",
                [tabel],
            )
            kolom = [r[0] for r in h_cur.fetchall() if r[0] != KOL_SUMBER]

            h_cur.execute(f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] = ?", [kd])
            h_cur.connection.commit()

            lob = _has_lob_columns(h_cur, tabel)
            h_cur.fast_executemany = not lob
            batch = 50 if lob else 2000
            sql = (
                f"INSERT INTO [{tabel}] ([{KOL_SUMBER}], " + ", ".join(f"[{c}]" for c in kolom) + ") "
                f"VALUES (" + ", ".join("?" * (len(kolom) + 1)) + ")"
            )
            s_cur.execute(f"SELECT {', '.join(f'[{c}]' for c in kolom)} FROM [{tabel}]")
            n = 0
            while True:
                rows = s_cur.fetchmany(batch)
                if not rows:
                    break
                h_cur.executemany(sql, [[kd] + list(r) for r in rows])
                h_cur.connection.commit()  # log transaksi pusat tetap terbatas
                n += len(rows)
        return n

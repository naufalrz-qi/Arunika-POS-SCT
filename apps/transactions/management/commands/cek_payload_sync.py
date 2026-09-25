"""Periksa, di server HIDUP, kolom yang bisa membuat payload sync jadi NULL.

    manage.py cek_payload_sync --profile testgudang
    manage.py cek_payload_sync --profile Testing --hari 90

HANYA MEMBACA (`report_cursor`, READ UNCOMMITTED). Tak ada yang ditulis ke
server mana pun — termasuk untuk "memperbaiki" baris lama: meng-UPDATE-nya
memicu `update_temp_m_*`, dan pusat lalu menerima UPDATE untuk baris yang
INSERT-nya tak pernah sampai. Itu keputusan terpisah, berbekal angka di sini.

Per tabel yang ditulis Arunika (`payload_sync.kolom_ditulis()`):

1. Trigger feed dibaca dari katalog server itu sendiri (`OBJECT_DEFINITION`),
   bukan dari dump — trigger GUDANG dan grosir memang berbeda.
2. DEFAULT dibaca dari `sys.columns` DAN tipe alias kolomnya (`sys.types`), jadi
   bound default gaya lama (`sp_bindefault`) ikut terlihat. Dump skema di
   `docs/skema/` tak memuatnya; di sinilah pertanyaan "kolom ini ber-DEFAULT
   atau tidak" dijawab.
3. Untuk setiap kolom payload yang boleh NULL: apakah Arunika menulisnya, apa
   DEFAULT-nya, dan berapa baris yang SUDAH NULL (seluruhnya, dan `--hari`
   terakhir). Untuk `t_penjualan`, juga yang `kd_user`-nya milik akun Arunika
   bertautan di profil ini — pendekatan "nota buatan Arunika" (edit dari
   aplikasi lama menimpa `kd_user`, jadi angkanya batas atas, bukan pasti).
4. Payload yang sudah NULL: `tbl_tmp_post.query` per `table_aksi`/`status`, dan
   `tbl_log_transaksi.formatted_data` dalam `--hari` — yang terakhir hanya bila
   index log ada; tanpa index, lewati, jangan pindai jutaan baris.

Kode keluar 1 bila masih ada kolom berisiko (nullable, tanpa DEFAULT, tak
ditulis Arunika), supaya bisa dijadwalkan.
"""
import datetime as dt
import sys

import pyodbc
from django.core.management.base import BaseCommand, CommandError

from apps.auth_app.models import TautanUser
from apps.connections.models import ServerProfile
from apps.transactions import payload_sync as ps
from apps.transactions.reports import LOG_INDEX
from core import mssql

_KOLOM = """
SELECT c.name, c.is_nullable, c.is_computed,
       OBJECT_DEFINITION(NULLIF(c.default_object_id, 0)),
       OBJECT_DEFINITION(NULLIF(t.default_object_id, 0))
FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID(?)
"""
_TRIGGER = """
SELECT name, OBJECT_DEFINITION(object_id), is_disabled
FROM sys.triggers WHERE parent_id = OBJECT_ID(?)
"""


def _kolom(cur, tabel: str) -> dict:
    mssql.execute_varchar(cur, _KOLOM, [tabel])
    return {
        r[0].lower(): {"nullable": bool(r[1]), "computed": bool(r[2]),
                       "default": (r[3] or r[4] or "").strip() or None}
        for r in cur.fetchall()
    }


class Command(BaseCommand):
    help = "Read-only: kolom payload trigger feed yang bisa NULL untuk baris tulisan Arunika, + hitungan baris NULL."

    def add_arguments(self, parser):
        parser.add_argument("--profile", required=True, help="Nama ServerProfile.")
        parser.add_argument("--hari", type=int, default=365,
                            help="Jendela hitungan 'terbaru' (hari). Default 365.")

    def handle(self, *args, **o):
        try:
            profil = ServerProfile.objects.get(name=o["profile"])
        except ServerProfile.DoesNotExist:
            raise CommandError(f"ServerProfile '{o['profile']}' tidak ada.")
        sejak = dt.datetime.now() - dt.timedelta(days=max(1, o["hari"]))
        kd_arunika = sorted({k for k in TautanUser.objects.filter(profile=profil)
                             .values_list("kd_user", flat=True) if k})

        self.stdout.write(f"{profil.name} [{profil.db_name}] — read-only, jendela {o['hari']} hari "
                          f"(sejak {sejak:%Y-%m-%d}); kd_user Arunika: {', '.join(kd_arunika) or '-'}")
        berisiko_total = []
        try:
            with mssql.report_cursor(profil, query_timeout=600) as cur:
                for tabel, ditulis in sorted(ps.kolom_ditulis().items()):
                    berisiko_total += self._tabel(cur, tabel, ditulis, sejak, kd_arunika)
                self._antrean(cur, sejak)
        except pyodbc.Error as exc:
            raise CommandError(mssql.friendly_error(exc, "Gagal membaca server"))

        if berisiko_total:
            self.stdout.write(self.style.ERROR(
                f"BERISIKO: {len(berisiko_total)} kolom payload bisa NULL untuk baris tulisan "
                f"Arunika — {', '.join(berisiko_total)}"))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(
            "Tak ada kolom payload berisiko: setiap kolom nullable ditulis Arunika atau ber-DEFAULT."))

    def _tabel(self, cur, tabel, ditulis, sejak, kd_arunika) -> list[str]:
        kolom = _kolom(cur, tabel)
        if not kolom:
            self.stdout.write(f"  {tabel}: tabel tak ada di server ini — dilewati")
            return []
        mssql.execute_varchar(cur, _TRIGGER, [tabel])
        trigger = [(n, d or "", mati) for n, d, mati in cur.fetchall()
                   if n.lower().startswith(ps.AWALAN_TRIGGER)]
        if not trigger:
            return []
        payload = set().union(*(ps.kolom_payload(d) for _, d, _ in trigger))
        risiko = ps.berisiko(payload, kolom, ditulis)
        nullable = sorted(k for k in payload if kolom.get(k, {}).get("nullable")
                          and not kolom[k]["computed"])
        status = self.style.ERROR("BERISIKO") if risiko else "ok"
        mati = [n for n, _, m in trigger if m]
        self.stdout.write(f"  {tabel}: {status} — {len(trigger)} trigger feed"
                          + (f" ({', '.join(mati)} DISABLED)" if mati else "")
                          + f", {len(payload)} kolom payload")
        ada_tanggal = "tanggal" in kolom
        for k in nullable:
            nilai = [f"ditulis Arunika: {'ya' if k in ditulis else 'TIDAK'}",
                     f"DEFAULT: {kolom[k]['default'] or 'tidak ada'}"]
            mssql.execute_varchar(cur, f"SELECT COUNT(*) FROM [{tabel}] WHERE [{k}] IS NULL", [])
            nilai.append(f"NULL: {cur.fetchone()[0]:,}")
            if ada_tanggal:
                mssql.execute_varchar(
                    cur, f"SELECT COUNT(*) FROM [{tabel}] WHERE [{k}] IS NULL AND tanggal >= ?", [sejak])
                nilai.append(f"{cur.fetchone()[0]:,} dalam jendela")
            if tabel == "t_penjualan" and kd_arunika and "kd_user" in kolom:
                tanya = ", ".join("?" for _ in kd_arunika)
                mssql.execute_varchar(
                    cur, f"SELECT COUNT(*) FROM [{tabel}] WHERE [{k}] IS NULL AND kd_user IN ({tanya})",
                    list(kd_arunika))
                nilai.append(f"{cur.fetchone()[0]:,} ber-kd_user Arunika")
            tanda = self.style.ERROR("  !") if k in risiko else "   "
            self.stdout.write(f"  {tanda} {tabel}.{k}: " + "; ".join(nilai))
        return [f"{tabel}.{k}" for k in risiko]

    def _antrean(self, cur, sejak):
        self.stdout.write("  Payload yang SUDAH NULL:")
        try:
            cur.execute("SELECT table_aksi, status, COUNT(*) FROM tbl_tmp_post "
                        "WHERE query IS NULL GROUP BY table_aksi, status ORDER BY 1, 2")
            baris = cur.fetchall()
        except pyodbc.Error:
            baris = None
        if baris is None:
            self.stdout.write("    tbl_tmp_post: tak terbaca di server ini")
        elif not baris:
            self.stdout.write("    tbl_tmp_post: 0 baris ber-query NULL (antrean yang tersisa)")
        for aksi, status, n in baris or []:
            self.stdout.write(f"    tbl_tmp_post {aksi or '-'} [{status or '-'}]: {n:,}")

        cur.execute("SELECT 1 FROM sys.indexes WHERE name = ? AND object_id = OBJECT_ID('tbl_log_transaksi')",
                    [LOG_INDEX])
        if cur.fetchone() is None:
            self.stdout.write(f"    tbl_log_transaksi: dilewati — index {LOG_INDEX} belum ada, "
                              "dan tanpa itu hitungannya memindai jutaan baris")
            return
        for tabel in sorted(ps.kolom_ditulis()):
            for aksi in (f"{tabel}__insert", f"{tabel}__update"):
                mssql.execute_varchar(
                    cur, "SELECT COUNT(*) FROM tbl_log_transaksi WHERE table_aksi = ? AND waktu >= ? "
                         "AND formatted_data IS NULL", [aksi, sejak])
                n = cur.fetchone()[0]
                if n:
                    self.stdout.write(f"    tbl_log_transaksi {aksi}: {n:,} formatted_data NULL")
        self.stdout.write("    tbl_log_transaksi: selesai diperiksa (hanya yang > 0 ditampilkan)")

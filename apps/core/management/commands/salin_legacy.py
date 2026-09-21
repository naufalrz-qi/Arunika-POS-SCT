"""Salin tabel legacy dari server mana pun ke database salinan LOKAL untuk uji.

    manage.py salin_legacy --sumber PUSAT --tujuan "salinan pusat 2025" \\
        --dari 2025-01-01 --sampai 2025-12-31 [--dry-run]

Sumber hanya DIBACA (READ UNCOMMITTED). Tujuan harus profil ber-lingkungan
`uji`, dan databasenya harus kosong atau salinan buatan fitur ini sendiri.
Badannya tinggal di `apps/bisnis/salin_legacy.py`, dipakai juga layar Transfer
ke Arunika.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.bisnis import salin_legacy as sl
from apps.bisnis.siapkan import Ditolak
from apps.connections.models import ServerProfile


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
        try:
            dari = dt.datetime.strptime(o["dari"], "%Y-%m-%d").date()
            sampai = dt.datetime.strptime(o["sampai"], "%Y-%m-%d").date()
        except ValueError:
            raise CommandError("--dari/--sampai harus YYYY-MM-DD")
        awalan = "[dry-run] " if o["dry_run"] else ""
        self.stdout.write(
            f"{awalan}{sumber.name} ({sumber.host}/{sumber.db_name}) -> "
            f"{tujuan.name} ({tujuan.host}/{tujuan.db_name})  dokumen {dari}..{sampai}"
        )
        try:
            if o["dry_run"]:
                tabel, rencana, _ = sl.rencana(sumber)
                for t in tabel:
                    k, kepala, kunci = rencana[t]
                    self.stdout.write(f"  {t:<28} {k}" + (f" <- {kepala}.{kunci}" if kepala else ""))
                return
            hasil = sl.salin(sumber, tujuan, dari, sampai, lapor=self._lapor)
        except Ditolak as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            f"Selesai: {hasil['baris']:,} baris, {hasil['tabel']} tabel, {hasil['detik']:.1f} dtk"))

    def _lapor(self, p):
        if p["jenis"] == "langkah":
            self.stdout.write("  %-28s %-7s %9d baris  %6.1f dtk"
                              % (p["nama"], p["kelas"], p["baris"], p["detik"]))
        else:
            self.stdout.write("  " + p["pesan"])

    def _profil(self, nama):
        p = ServerProfile.objects.filter(name=nama).first()
        if not p:
            raise CommandError(f"Profil '{nama}' tak ada.")
        return p

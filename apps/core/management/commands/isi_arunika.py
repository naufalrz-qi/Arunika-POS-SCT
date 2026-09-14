"""Isi tabel Arunika sungguhan dari sebuah profil bermode legacy.

    manage.py isi_arunika --sumber Testing --tujuan "testing arunika" \\
        --dari 2025-01-01 --sampai 2025-12-31 [--kosongkan] [--dry-run]

`--sumber` adalah profil yang database Arunika-nya berisi view `arunika_src.*`
mode **legacy** (dipasang `init_arunika`, membaca legacy lintas-database).
`--tujuan` profil yang database Arunika-nya menampung tabel nyata.

Master (barang, pelanggan, referensi) SELALU dimuat penuh; jendela tanggal hanya
berlaku untuk dokumen. Sebuah barang yang terpotong tak membuat datanya kurang
lengkap -- ia membuat notanya gagal dimuat. Badannya `apps/bisnis/muat.py`.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.bisnis import muat
from apps.bisnis.siapkan import Ditolak
from apps.connections.models import ServerProfile


def _tanggal(teks, nama):
    try:
        return dt.datetime.strptime(teks, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"--{nama} harus YYYY-MM-DD, bukan {teks!r}")


class Command(BaseCommand):
    help = "Muat data dari view adapter mode legacy ke tabel Arunika sungguhan."

    def add_arguments(self, p):
        p.add_argument("--sumber", required=True, help="Nama profil sumber (mode legacy)")
        p.add_argument("--tujuan", required=True, help="Nama profil tujuan (tabel nyata)")
        p.add_argument("--dari", default="2025-01-01")
        p.add_argument("--sampai", default="2025-12-31")
        p.add_argument("--kosongkan", action="store_true",
                       help="Hapus isi tabel tujuan lebih dulu (muat ulang bersih)")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--hanya", default="", help="Batasi ke satu entitas (untuk debug)")

    def handle(self, *a, **o):
        sumber, tujuan = self._profil(o["sumber"]), self._profil(o["tujuan"])
        dari, sampai = _tanggal(o["dari"], "dari"), _tanggal(o["sampai"], "sampai")
        awalan = "[dry-run] " if o["dry_run"] else ""
        self.stdout.write(
            f"{awalan}{sumber.name} [{sumber.db_arunika}] -> "
            f"{tujuan.name} [{tujuan.db_arunika}]  dokumen {dari}..{sampai}"
        )
        if o["dry_run"]:
            n = 1 if o["hanya"] else len(muat.URUTAN)
            self.stdout.write(f"  AKAN memuat {n} entitas")
            return
        try:
            h = muat.muat_semua(sumber, tujuan, dari, sampai, kosongkan_dulu=o["kosongkan"],
                                hanya=o["hanya"] or None, lapor=self._lapor)
        except Ditolak as exc:
            raise CommandError(str(exc))
        gaya = self.style.WARNING if h["dilewati"] else self.style.SUCCESS
        self.stdout.write(gaya(
            f"Selesai: {h['baris']:,} baris dalam {h['detik']:.1f} dtk"
            + (f", {h['dilewati']:,} dilewati" if h["dilewati"] else "")
        ))

    def _lapor(self, p):
        if p["jenis"] != "langkah":
            self.stdout.write("  " + p["pesan"])
            return
        self.stdout.write("  %-24s %7d baris  %5.1f dtk%s"
                          % (p["nama"], p["baris"], p["detik"],
                             f"  {p['dilewati']} DILEWATI" if p["dilewati"] else ""))
        for sebab, n in sorted(p["alasan"].items(), key=lambda x: -x[1])[:3]:
            self.stdout.write(self.style.WARNING(f"        {n:>7} x {sebab}"))

    def _profil(self, nama):
        p = ServerProfile.objects.filter(name=nama).first()
        if not p:
            ada = ", ".join(ServerProfile.objects.values_list("name", flat=True))
            raise CommandError(f"Profil '{nama}' tak ada. Yang ada: {ada}")
        return p

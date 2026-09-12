"""Isi tabel Arunika sungguhan dari sebuah profil bermode legacy.

    manage.py isi_arunika --sumber Testing --tujuan "testing arunika" \\
        --dari 2025-01-01 --sampai 2025-12-31 [--kosongkan] [--dry-run]

`--sumber` adalah profil yang database Arunika-nya berisi view `arunika_src.*`
mode **legacy** (dipasang `init_arunika`, membaca legacy lintas-database).
`--tujuan` profil yang database Arunika-nya menampung tabel nyata.

Master (barang, pelanggan, referensi) SELALU dimuat penuh; jendela tanggal hanya
berlaku untuk dokumen. Sebuah barang yang terpotong tak membuat datanya kurang
lengkap -- ia membuat notanya gagal dimuat.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
import datetime as dt
import time

from django.core.management.base import BaseCommand, CommandError

from apps.bisnis import muat
from apps.connections.models import Lingkungan, ServerProfile
from apps.core import db_alias
from core import mssql


def _tanggal(teks, nama):
    try:
        return dt.datetime.strptime(teks, "%Y-%m-%d")
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
        sumber = self._profil(o["sumber"])
        tujuan = self._profil(o["tujuan"])
        if not sumber.db_arunika:
            raise CommandError(f"Profil sumber '{sumber.name}' belum punya db_arunika. "
                               "Jalankan init_arunika lebih dulu.")
        if not tujuan.db_arunika:
            raise CommandError(f"Profil tujuan '{tujuan.name}' belum punya db_arunika.")
        if sumber.db_arunika == tujuan.db_arunika:
            raise CommandError("Sumber dan tujuan menunjuk database yang sama.")
        # Menulis puluhan ribu baris ke database yang ditandai produksi hampir
        # pasti bukan yang dimaksud. Ditolak, bukan sekadar diperingatkan.
        if tujuan.lingkungan != Lingkungan.UJI:
            raise CommandError(
                f"Profil tujuan '{tujuan.name}' bertanda '{tujuan.lingkungan}'. "
                "Perintah ini hanya menulis ke profil ber-lingkungan 'uji'."
            )

        dari, sampai = _tanggal(o["dari"], "dari"), _tanggal(o["sampai"], "sampai")
        sampai = sampai.replace(hour=23, minute=59, second=59)
        alias = db_alias.daftarkan(tujuan)
        urutan = [o["hanya"]] if o["hanya"] else list(muat.URUTAN)
        if o["hanya"] and o["hanya"] not in muat.URUTAN:
            raise CommandError(f"Entitas tak dikenal: {o['hanya']}")

        awalan = "[dry-run] " if o["dry_run"] else ""
        self.stdout.write(
            f"{awalan}{sumber.name} [{sumber.db_arunika}] -> "
            f"{tujuan.name} [{tujuan.db_arunika}]  dokumen {o['dari']}..{o['sampai']}"
        )
        if o["dry_run"]:
            self.stdout.write(f"  AKAN memuat {len(urutan)} entitas")
            return

        if o["kosongkan"]:
            muat.kosongkan(alias)
            self.stdout.write("  tabel tujuan dikosongkan")

        total_tulis, total_lewat, t0 = 0, 0, time.time()
        peta = {}
        with mssql.arunika_cursor(sumber) as src:
            for nama in urutan:
                t = time.time()
                h = muat.muat_entitas(nama, src, alias, dari, sampai, peta)
                muat.perbarui_peta(peta, alias, nama)
                total_tulis += h["ditulis"]
                total_lewat += h["dilewati"]
                self.stdout.write(
                    "  %-24s %7d baris  %5.1f dtk%s"
                    % (nama, h["ditulis"], time.time() - t,
                       f"  {h['dilewati']} DILEWATI" if h["dilewati"] else "")
                )
                for sebab, n in sorted(h["alasan"].items(), key=lambda x: -x[1])[:3]:
                    self.stdout.write(self.style.WARNING(f"        {n:>7} x {sebab}"))

        gaya = self.style.WARNING if total_lewat else self.style.SUCCESS
        self.stdout.write(gaya(
            f"Selesai: {total_tulis:,} baris dalam {time.time() - t0:.1f} dtk"
            + (f", {total_lewat:,} dilewati" if total_lewat else "")
        ))

    def _profil(self, nama):
        p = ServerProfile.objects.filter(name=nama).first()
        if not p:
            ada = ", ".join(ServerProfile.objects.values_list("name", flat=True))
            raise CommandError(f"Profil '{nama}' tak ada. Yang ada: {ada}")
        return p

"""Sebar harga GUDANG -> toko grosir, tanpa lewat tbl_log_transaksi.

    python manage.py sync_harga --dry-run     # cuma laporkan yang beda
    python manage.py sync_harga               # sapuan penuh, benar-benar menulis

Selalu mode PENUH (membandingkan keadaan nyata tiap toko). Mode cepat hanya
masuk akal di dalam loop scheduler, yang menyimpan salinan harga sebelumnya di
memori proses — satu proses `manage.py` yang mati sesudah selesai tidak punya
salinan itu.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.transactions import harga_sync


class Command(BaseCommand):
    help = "Sebar harga GUDANG ke toko grosir (perbandingan langsung, bukan feed)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        source, targets = harga_sync.profil_fanout()
        if not source:
            raise CommandError("Profil sumber (FEED_SYNC_SOURCE) tidak ada.")
        if not targets:
            raise CommandError("Tidak ada toko tujuan (FEED_SYNC_TARGETS).")

        self.stdout.write(f"{source.name} -> {', '.join(t.name for t in targets)}")
        hasil = harga_sync.sapu(source, targets, penuh=True, dry_run=o["dry_run"])
        if hasil["error"]:
            raise CommandError(hasil["error"])

        self.stdout.write(f"  mode      : {hasil['mode']}")
        self.stdout.write(f"  SKU beda  : {hasil['sku']:,}")
        if hasil["contoh"]:
            self.stdout.write(f"  contoh    : {hasil['contoh']}")
        for nama, n in sorted(hasil["per_toko"].items()):
            self.stdout.write(f"  {nama:<14} {n:,} baris ditulis")
        for nama, pesan in sorted(hasil["gagal"].items()):
            # Toko yang gagal bukan sekadar catatan: sampai sapuan berikutnya,
            # harga di sana basi tanpa gejala apa pun di layar siapa pun.
            self.stdout.write(self.style.ERROR(f"  {nama:<14} GAGAL {pesan}"))

        gaya = self.style.WARNING if hasil["gagal"] else self.style.SUCCESS
        self.stdout.write(gaya("selesai" if not o["dry_run"] else "dry run - tidak ada yang ditulis"))

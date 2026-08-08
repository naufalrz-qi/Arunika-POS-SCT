"""Master data AMPHOREUS mengikuti GUDANG saja.

    python manage.py pull_master --dry-run
    python manage.py pull_master
    python manage.py pull_master --purge-lain --dry-run
    python manage.py pull_master --purge-lain --hapus-beneran

`--purge-lain` menghapus baris master milik cabang selain GUDANG (termasuk baris
`m_barang` PRAYA yang namanya terpotong 30 karakter oleh trigger legacy). Ia
menuntut `--hapus-beneran` secara terpisah: ini satu-satunya jalur yang menghapus
data tanpa menyalin ulang penggantinya.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions import hub_master


class Command(BaseCommand):
    help = "Salin master data GUDANG ke AMPHOREUS (dan bersihkan sisa cabang lain)."

    def add_arguments(self, parser):
        parser.add_argument("--hub", default=os.environ.get("HUB_NAME", "AMPHOREUS"))
        parser.add_argument("--source", default=os.environ.get("FEED_SYNC_SOURCE", "GUDANG"))
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--purge-lain", action="store_true",
                            help="Hapus baris master ber-kd_sumber selain GUDANG")
        parser.add_argument("--hapus-beneran", action="store_true",
                            help="Wajib menyertai --purge-lain agar benar-benar menghapus")

    def handle(self, *args, **o):
        hub = ServerProfile.objects.filter(name=o["hub"]).first()
        if not hub:
            raise CommandError(f"Profil AMPHOREUS '{o['hub']}' tidak ada.")

        if o["purge_lain"]:
            hasil = hub_master.purge_lain(hub, dry_run=not o["hapus_beneran"])
            total = sum(t["total"] for t in hasil["tabel"])
            for t in hasil["tabel"]:
                if t["total"]:
                    rincian = ", ".join(f"{k}={v}" for k, v in sorted(t["per_sumber"].items()))
                    self.stdout.write(f"  {t['tabel']:<22} {t['total']:>8,}  ({rincian})")
            if hasil["error"]:
                raise CommandError(hasil["error"])
            if o["hapus_beneran"]:
                self.stdout.write(self.style.SUCCESS(f"{total:,} baris master non-GUDANG dihapus."))
            else:
                self.stdout.write(self.style.WARNING(
                    f"DRY RUN: {total:,} baris akan dihapus. "
                    "Tambahkan --hapus-beneran untuk benar-benar menjalankannya."
                ))
            return

        source = ServerProfile.objects.filter(name=o["source"]).first()
        if not source:
            raise CommandError(f"Profil sumber '{o['source']}' tidak ada.")
        hasil = hub_master.sync_master(source, hub, dry_run=o["dry_run"])
        for t in hasil["tabel"]:
            self.stdout.write(
                f"  {t['tabel']:<22} baru={t['baru']:<6} ubah={t['ubah']:<6} "
                f"hapus={t['hapus']:<5} sama={t['sama']:,}"
            )
        if hasil["status"] == "failed":
            raise CommandError(hasil["error"])
        self.stdout.write(self.style.SUCCESS(f"master {hasil['source']}: {hasil['status']}"))

"""Tarik transaksi cabang ke AMPHOREUS langsung dari tabel aslinya.

    python manage.py pull_hub --mode segar --hari 7
    python manage.py pull_hub --mode cocok --dry-run
    python manage.py pull_hub --mode arsip --source PUSAT

Tiga mode = tiga tingkat di `apps/transactions/hub_pull.py`. `arsip` sengaja
tidak pernah dijadwalkan: ia menyapu seluruh riwayat di bawah tutup buku dan itu
keputusan manusia, bukan sesuatu yang boleh terjadi karena scheduler menyala.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions import hub_pull


class Command(BaseCommand):
    help = "Tarik transaksi cabang ke AMPHOREUS (tanpa tbl_log_transaksi)."

    def add_arguments(self, parser):
        parser.add_argument("--hub", default=os.environ.get("HUB_NAME", "AMPHOREUS"))
        parser.add_argument("--source", default="", help="Nama profil cabang; kosong = semua")
        parser.add_argument("--mode", default="segar", choices=["segar", "cocok", "arsip"])
        parser.add_argument("--hari", type=int, default=hub_pull.JENDELA_SEGAR_HARI)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        hub = ServerProfile.objects.filter(name=o["hub"]).first()
        if not hub:
            raise CommandError(f"Profil AMPHOREUS '{o['hub']}' tidak ada.")

        if o["source"]:
            sumber = list(ServerProfile.objects.filter(name=o["source"]))
            if not sumber:
                raise CommandError(f"Profil cabang '{o['source']}' tidak ada.")
        else:
            sumber = hub_pull.sumber_profiles()
        if not sumber:
            raise CommandError("Tidak ada cabang ber-kode_sumber.")

        # Arsip berjalan berjam-jam. Perintah yang diam sampai akhir tidak bisa
        # dibedakan dari perintah yang menggantung, jadi tiap potongan bulanan
        # yang menghasilkan baris ikut dicetak.
        def lapor(teks):
            self.stdout.write(teks)
            self.stdout.flush()

        for hasil in hub_pull.pull_all(
            hub, sumber, mode=o["mode"], hari=o["hari"], dry_run=o["dry_run"],
            lapor=lapor if o["mode"] in ("arsip", "cocok") else None,
        ):
            gaya = self.style.ERROR if hasil["status"] == "failed" else self.style.SUCCESS
            self.stdout.write(gaya(
                f"{hasil['source']:<14} [{hasil['status']}] "
                f"header={hasil['header']} nota={hasil['nota']} detail={hasil['detail']} "
                f"hapus={hasil['dihapus']} hari_beda={hasil['hari_beda']}"
            ))
            if hasil["anomali_tanggal"]:
                # Bukan kegagalan, tapi juga bukan sesuatu yang boleh lewat diam:
                # baris bertanggal di luar akal (ANDARIA punya nota 7252-01-09)
                # tidak pernah ikut tersalin, dan itu perlu diperbaiki di cabang.
                self.stdout.write(self.style.WARNING(
                    f"  {hasil['anomali_tanggal']} baris bertanggal >= "
                    f"{hub_pull.TANGGAL_MAKS:%Y} DILEWATI - perbaiki di cabang"
                ))
            if hasil["error"]:
                self.stdout.write(self.style.ERROR(f"  {hasil['error']}"))

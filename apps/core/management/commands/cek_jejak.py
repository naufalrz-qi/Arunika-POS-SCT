"""Periksa keutuhan rantai hash jejak audit (`ActivityLog`).

Setiap baris jejak sejak migrasi 0019 menyimpan hash dari isinya sendiri dan
hash baris sebelumnya. Perintah ini menelusuri rantai itu dari awal, lalu
melaporkan mata rantai PERTAMA yang putus:

- isi baris tak cocok dengan hash-nya → baris itu diubah langsung di database;
- `hash_prev` tak menyambung → ada baris yang dihapus atau disisipkan;
- kepala rantai menunjuk baris yang tak ada → ekor rantai dihapus.

Hanya membaca. Kode keluar 1 kalau rantai putus, supaya bisa dijadwalkan dan
kegagalannya terlihat di Task Scheduler.
"""
import sys

from django.core.management.base import BaseCommand

from apps.core.models import periksa_rantai


class Command(BaseCommand):
    help = "Periksa rantai hash jejak audit; laporkan baris pertama yang diubah/dihapus."

    def handle(self, *args, **o):
        hasil = periksa_rantai()
        if hasil["putus"] is None:
            self.stdout.write(self.style.SUCCESS(
                f"Rantai utuh: {hasil['jumlah']:,} baris jejak terverifikasi."))
            return
        p = hasil["putus"]
        self.stdout.write(self.style.ERROR(
            f"Rantai PUTUS di jejak #{p['id']}: {p['sebab']}. "
            f"{hasil['jumlah']:,} baris diperiksa sampai titik itu."))
        sys.exit(1)

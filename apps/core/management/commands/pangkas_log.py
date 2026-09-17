"""Pangkas tabel riwayat yang tumbuh tanpa batas.

Tiga tabel, semuanya di database pangkal, semuanya append-only dan sampai
sekarang tak pernah dipangkas oleh apa pun:

- `SyncHealthSample` — ditulis TIAP TICK untuk TIAP profil. 13 profil × 48
  tick/hari = 228.000 baris/tahun, untuk data yang hanya dipakai membandingkan
  "antre sekarang" dengan "antre seminggu lalu". Ini yang paling mendesak.
- `SyncDeadLetter` — baris feed yang tak bisa diterapkan. Idealnya kosong, tapi
  satu cabang yang skemanya bergeser bisa menumpahkan ribuan baris dalam
  semalam dan tak ada yang membersihkannya.
- `SyncLog` — riwayat operasi. Tumbuh pelan (aturan sunyi menjaganya), tapi
  tidak nol.

Retensi dipakai bersama satu ambang, bukan satu per tabel: tiga angka yang bisa
diatur sendiri-sendiri berarti tiga angka yang harus dijelaskan, sementara
pertanyaan operatornya cuma satu — "simpan berapa lama".

`ActivityLog` sengaja TIDAK ikut: ia jejak audit siapa-melakukan-apa, dan
memangkasnya diam-diam lewat job terjadwal adalah keputusan yang harus diambil
sadar, bukan efek samping pembersihan tabel telemetri.
"""
import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import SyncDeadLetter, SyncHealthSample, SyncLog

# Nama yang tampil -> model. Urutan menentukan urutan cetak saja.
TABEL = (
    ("Sampel kesehatan sync", SyncHealthSample),
    ("Dead-letter sync", SyncDeadLetter),
    ("Riwayat operasi", SyncLog),
)


def pangkas(hari: int, dry_run: bool = False) -> dict:
    """Hapus baris yang lebih tua dari `hari`. Mengembalikan `{nama: jumlah}`."""
    batas = timezone.now() - dt.timedelta(days=max(1, hari))
    hasil = {}
    for nama, model in TABEL:
        qs = model.objects.filter(created_at__lt=batas)
        hasil[nama] = qs.count() if dry_run else qs.delete()[0]
    return hasil


class Command(BaseCommand):
    help = "Pangkas sampel kesehatan sync, dead-letter, dan riwayat operasi yang sudah tua."

    def add_arguments(self, parser):
        parser.add_argument("--keep-days", type=int, default=90,
                            help="Simpan baris semuda ini (hari). Default 90.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Hitung saja, jangan hapus.")

    def handle(self, *args, **o):
        mode = " (DRY RUN — tidak ada yang dihapus)" if o["dry_run"] else ""
        self.stdout.write(f"Memangkas baris lebih tua dari {o['keep_days']} hari{mode}")
        hasil = pangkas(o["keep_days"], dry_run=o["dry_run"])
        for nama, n in hasil.items():
            gaya = self.style.WARNING if n else self.style.SUCCESS
            kata = "akan dihapus" if o["dry_run"] else "dihapus"
            self.stdout.write(gaya(f"  {nama:<24} {n:>8,} baris {kata}"))
        if not any(hasil.values()):
            self.stdout.write(self.style.SUCCESS("Tidak ada yang perlu dipangkas."))

r"""Siapkan database Arunika pendamping untuk sebuah `ServerProfile`.

Tiga langkah, idempoten, dan **tidak satu pun menyentuh database legacy**:

  1. `CREATE DATABASE` pendamping bila belum ada
  2. `migrate` skema Arunika ke sana lewat alias runtime
  3. Pasang view adapter `arunika_src.*` di dalamnya

Yang membaca database legacy hanyalah isi view-nya, lintas-database. Objek yang
dibuat semuanya duduk di database pendamping. Bandingkan `sys.objects` di
database legacy sebelum dan sesudah perintah ini: harus sama persis.

    manage.py init_arunika --profile testgudang
    manage.py init_arunika --profile testgudang --dry-run

Bentuknya sengaja mencerminkan `init_hub`: idempoten, `--dry-run` yang benar-
benar tidak menulis, dan berhenti dengan galat alih-alih menebak.

Badannya tinggal di `apps/bisnis/siapkan.py`, dipakai juga layar Transfer ke Arunika.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.bisnis import master_src
from apps.bisnis.siapkan import NAMA_BAWAAN, Ditolak, siapkan_arunika
from apps.connections.models import ServerProfile


class Command(BaseCommand):
    help = "Buat database Arunika pendamping + migrate + pasang view adapter."

    def add_arguments(self, parser):
        parser.add_argument("--profile", required=True, help="Nama ServerProfile.")
        parser.add_argument(
            "--db", default=None,
            help=f"Nama database pendamping. Bawaan: kolom db_arunika, atau '{NAMA_BAWAAN}'.",
        )
        parser.add_argument(
            "--mode", choices=master_src.MODE, default="legacy",
            help="legacy = view membaca database legacy lintas-database. "
                 "arunika = view membaca tabel Arunika sendiri (pemasangan mandiri).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Laporkan saja, jangan tulis.")

    def handle(self, *args, **o):
        try:
            profil = ServerProfile.objects.get(name=o["profile"])
        except ServerProfile.DoesNotExist:
            raise CommandError(f"ServerProfile '{o['profile']}' tidak ada.")
        awalan = "[dry-run] " if o["dry_run"] else ""
        self.stdout.write(f"{awalan}Profil {profil.name} ({profil.host}) legacy={profil.db_name}")
        try:
            siapkan_arunika(profil, db=o["db"], mode=o["mode"], kering=o["dry_run"],
                            lapor=lambda p: self.stdout.write("  " + p["pesan"]))
        except Ditolak as exc:
            raise CommandError(str(exc))
        if not o["dry_run"]:
            self.stdout.write(
                "\nDatabase legacy tidak menerima objek apa pun. Verifikasi dengan "
                f"membandingkan COUNT(*) sys.objects di [{profil.db_name}] sebelum/sesudah."
            )

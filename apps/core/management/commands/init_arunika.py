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
"""
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.db import connections

from apps.bisnis import adapter, master_src
from apps.connections.models import ServerProfile
from apps.core import db_alias
from core import mssql
from core.encryption import decrypt_checked

# Nama bawaan database pendamping. Bukan `db_name` + akhiran: nama database
# legacy sama (`SOLID_SIM`) di seluruh cabang, jadi akhiran tak menambah apa pun.
NAMA_BAWAAN = "arunika"


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

        db = (o["db"] or profil.db_arunika or NAMA_BAWAAN).strip()
        if "]" in db:
            raise CommandError(f"Nama database tak bisa dikutip aman: {db!r}")
        if db.lower() == (profil.db_name or "").lower():
            raise CommandError(
                f"Database pendamping tak boleh sama dengan database legacy ({db!r}). "
                "Seluruh rancangan ini bertumpu pada keduanya terpisah."
            )
        kering = o["dry_run"]
        awalan = "[dry-run] " if kering else ""
        self.stdout.write(f"{awalan}Profil {profil.name} ({profil.host}) legacy={profil.db_name}")

        # --- 1. Database pendamping ---------------------------------------
        pw = decrypt_checked(profil.password_encrypted)
        conn = mssql._connect(profil.host, profil.port, "master", profil.username, pw,
                              autocommit=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT DB_ID(?)", [db])
            ada = cur.fetchone()[0] is not None
            if ada:
                self.stdout.write(f"  1. database [{db}] sudah ada")
            elif kering:
                self.stdout.write(f"  1. AKAN membuat database [{db}]")
            else:
                cur.execute(f"CREATE DATABASE [{db}]")
                self.stdout.write(self.style.SUCCESS(f"  1. database [{db}] dibuat"))
        finally:
            conn.close()

        if kering and not ada:
            self.stdout.write("     (langkah 2-3 dilewati: databasenya belum ada)")
            return

        # `db_arunika` harus terisi SEBELUM daftarkan(), karena alias dibangun
        # dari kolom itu. Di dry-run ditimpa sementara di memori saja.
        semula, profil.db_arunika = profil.db_arunika, db
        if not kering and semula != db:
            profil.save(update_fields=["db_arunika"])
            self.stdout.write(f"     db_arunika profil di-set ke '{db}'")

        alias = db_alias.daftarkan(profil)

        # --- 2. Migrasi ----------------------------------------------------
        if kering:
            self.stdout.write(f"  2. AKAN migrate 'bisnis' ke alias {alias}")
        else:
            call_command("migrate", "bisnis", database=alias, verbosity=0)
            with connections[alias].cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME NOT LIKE 'django_%'"
                )
                n = cur.fetchone()[0]
            self.stdout.write(self.style.SUCCESS(f"  2. migrate OK -> {n} tabel di [{db}]"))

        # --- 3. View adapter ------------------------------------------------
        if kering:
            self.stdout.write(
                f"  3. AKAN memasang {len(master_src.daftar())} view + 1 iTVF "
                f"{master_src.SKEMA}.* (mode {o['mode']})"
            )
            return

        sumber = profil.db_name if o["mode"] == "legacy" else None
        with connections[alias].cursor() as cur:
            dibuat = master_src.pasang(cur, o["mode"], sumber)
            self.stdout.write(self.style.SUCCESS(
                f"  3. {len(dibuat)} view {master_src.SKEMA}.* dipasang (mode {o['mode']}): "
                + ", ".join(dibuat)
            ))
            # Buku besar stok: iTVF, bukan view, karena filternya berparameter
            # dan harus menembus tabel ratusan ribu baris. Hanya untuk mode
            # legacy -- di mode Arunika `pergerakan_stok` sudah tabel nyata.
            if o["mode"] == "legacy":
                adapter.pasang(cur, sumber)
                self.stdout.write(self.style.SUCCESS(
                    f"  4. iTVF {adapter.SKEMA}.pergerakan_stok dipasang"
                ))
        self.stdout.write(
            "\nDatabase legacy tidak menerima objek apa pun. Verifikasi dengan "
            f"membandingkan COUNT(*) sys.objects di [{profil.db_name}] sebelum/sesudah."
        )

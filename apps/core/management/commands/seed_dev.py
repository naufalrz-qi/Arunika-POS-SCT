"""Seed dev data: users (real login) + the grosir connection profile from .env."""
import os

from django.core.management.base import BaseCommand

from apps.auth_app.models import Role, User
from apps.connections.models import DbType, ServerProfile


class Command(BaseCommand):
    help = "Create dev users and the grosir ServerProfile (idempotent)."

    def handle(self, *args, **options):
        self._seed_users()
        self._seed_grosir()

    def _seed_users(self):
        users = [
            ("superadmin", "superadmin", Role.SUPERADMIN, "Naufal", "Superadmin"),
            ("admin", "admin", Role.ADMIN, "Andi", "Admin"),
            ("spv01", "spv01", Role.SUPERVISOR, "Dewi", "Lestari"),
            ("kasir01", "kasir01", Role.KASIR, "Budi", "Hartono"),
        ]
        for username, password, role, first, last in users:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "first_name": first, "last_name": last},
            )
            user.role = role
            user.first_name, user.last_name = first, last
            user.is_staff = role == Role.SUPERADMIN
            user.is_superuser = role == Role.SUPERADMIN
            user.set_password(password)
            user.save()
            self.stdout.write(f"  user {username} ({role}) {'created' if created else 'updated'}")

    def _seed_grosir(self):
        password = os.environ.get("POS_DB_GROSIR_PASSWORD", "")
        profile, created = ServerProfile.objects.get_or_create(
            db_type=DbType.GROSIR,
            name="Grosir Pusat",
            defaults={
                "host": os.environ.get("POS_DB_GROSIR_HOST", "localhost"),
                "port": int(os.environ.get("POS_DB_GROSIR_PORT", "1433")),
                "db_name": os.environ.get("POS_DB_GROSIR_NAME", "grosirPusat"),
                "username": os.environ.get("POS_DB_GROSIR_USER", "sa"),
                "is_default": True,
            },
        )
        if password:
            profile.set_password(password)
            profile.save(update_fields=["password_encrypted"])
            self.stdout.write(self.style.SUCCESS(f"  grosir profile {'created' if created else 'updated'} (password set)"))
        else:
            self.stdout.write(self.style.WARNING("  POS_DB_GROSIR_PASSWORD kosong — set di .env lalu jalankan ulang."))

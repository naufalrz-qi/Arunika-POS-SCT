from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate a new Fernet key for POS_FERNET_KEY (paste into .env)."

    def handle(self, *args, **options):
        self.stdout.write(Fernet.generate_key().decode())

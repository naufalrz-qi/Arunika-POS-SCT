import os, django
from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.connections.models import ServerProfile
from core import mssql

profile = ServerProfile.objects.first()

tables = ['t_pembelian', 't_biaya']

with mssql.cursor(profile) as cur:
    for t in tables:
        print(f'\n--- {t} ---')
        try:
            cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?", [t])
            cols = cur.fetchall()
            print([c[0] for c in cols] if cols else 'Table not found.')
        except Exception as e:
            pass

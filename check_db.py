import os, django
from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.connections.models import ServerProfile
from core import mssql

profile = ServerProfile.objects.first()
if not profile:
    print("No profile found.")
    exit()

print(f"Using profile: {profile.name}")

tables = ['t_mutasi_kas', 't_arus_kas', 't_kas', 't_pembelian_retur_detail', 't_opname_stok', 't_penjualan', 'm_customer']

try:
    with mssql.cursor(profile) as cur:
        for t in tables:
            print(f'\n--- {t} ---')
            cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?", [t])
            cols = cur.fetchall()
            if cols:
                print([c[0] for c in cols])
            else:
                print('Table not found.')
except Exception as e:
    print(f"Error: {e}")

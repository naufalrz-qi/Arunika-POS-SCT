import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.db import connection

tables = ['m_customer', 't_pembelian_retur_detail', 't_opname_stok', 't_opname_stok_detail', 't_mutasi_kas', 't_stok', 't_kas', 't_arus_kas']
with connection.cursor() as cursor:
    for t in tables:
        print(f'\n--- {t} ---')
        try:
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s", [t])
            cols = cursor.fetchall()
            if cols:
                print([c[0] for c in cols])
            else:
                print('Table not found.')
        except Exception as e:
            print(f'Error: {e}')

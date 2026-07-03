# Database Schema Inspection Scripts

Scripts untuk melihat struktur database MSSQL Server (tables, views, functions, stored procedures).

## Setup

Install dependency:
```bash
pip install pyodbc python-dotenv
```

Pastikan ODBC Driver 17 for SQL Server sudah terinstall di system.

## Scripts

### 1. `inspect_database_schema.py`

Interactive tool untuk browse schema database secara interaktif.

**Cara pakai:**
```bash
python scripts/inspect_database_schema.py
```

**Menu:**
- List all tables (dengan jumlah columns)
- List all views
- List all functions & table-valued functions
- List all stored procedures
- Show detail columns untuk table tertentu
- Show all (comprehensive view)

**Contoh output:**
```
================================================================================
  TABLES
================================================================================
  [dbo].[Users]  (5 cols)
  [dbo].[Products]  (8 cols)
  [dbo].[Orders]  (6 cols)

================================================================================
  COLUMNS: [dbo].[Users]
================================================================================
  Name                           Type                 Nullable   Default
  ------------------------------- -------------------- ---------- -----
  UserID                         int                  NO         (none)
  Name                           nvarchar(100)        NO         (none)
  Email                          nvarchar(100)        YES        (none)
```

---

### 2. `export_database_schema.py`

Export schema ke file JSON atau CSV untuk dokumentasi/analysis.

**Cara pakai:**

Export ke JSON (default):
```bash
python scripts/export_database_schema.py
# Hasil: schema_gs-pusat_20250704_150530.json
```

Export ke CSV (multiple files):
```bash
python scripts/export_database_schema.py --format csv
# Hasil folder berisi:
#   - tables.csv
#   - columns.csv
#   - views.csv
#   - functions.csv
#   - stored_procedures.csv
```

Dengan custom output:
```bash
python scripts/export_database_schema.py --format json --output my_schema.json
python scripts/export_database_schema.py --format csv --output schema_backup
```

**Output JSON structure:**
```json
{
  "database": "gs-pusat",
  "host": "localhost:1433",
  "exported_at": "2025-07-04T15:05:30.123456",
  "tables": [
    {
      "schema": "dbo",
      "name": "Users",
      "column_count": 5,
      "columns": [
        {
          "name": "UserID",
          "type": "int",
          "nullable": false,
          "default": null
        }
      ]
    }
  ],
  "views": [...],
  "functions": [...],
  "stored_procedures": [...]
}
```

---

## Connection Config

Koneksi database dibaca dari `.env` file:
- `POS_DB_GROSIR_HOST` - Host (default: localhost)
- `POS_DB_GROSIR_PORT` - Port (default: 1433)
- `POS_DB_GROSIR_NAME` - Database name (default: gs-pusat)
- `POS_DB_GROSIR_USER` - Username (default: sa)
- `POS_DB_GROSIR_PASSWORD` - Password

Ubah di `.env` kalau perlu connect ke database lain.

---

## Troubleshooting

**Connection refused:**
- Pastikan MSSQL Server running
- Check host/port di `.env`

**ODBC Driver not found:**
```bash
# Install driver (Windows)
# Download dari: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

# Verify installed drivers
odbcad32.exe  # (Windows ODBC Data Source Administrator)
```

**Permission denied:**
- Verify username/password di `.env`
- Check SQL Server credentials

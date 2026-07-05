#!/usr/bin/env python3
"""
Cek kolom yang dihasilkan oleh VIEW dan FUNCTION (table-valued) di sebuah MS SQL Server.

Beda dari scripts/inspect_database_schema.py (yang cuma me-list nama view/function):
script ini menampilkan kolom keluaran tiap view & table-valued function, lengkap
dengan tipe data dan nullability -- berguna untuk memahami skema legacy sebelum
menulis query Python di services.py.

Standalone (tidak baca .env / Django) karena koneksi target beda dari POS_DB_GROSIR_*
di .env. Deteksi driver ODBC & fallback Encrypt mengikuti pola yang sudah diperbaiki
di core/mssql.py, supaya tidak kena bug driver/SSL yang sama.

Password TIDAK di-hardcode di sini (supaya tidak ikut ter-commit ke git) --
selalu wajib diisi lewat --password.

Output ditulis ke scripts/output/ (mengikuti konvensi export_database_schema.py /
quick_schema.py di folder yang sama): satu file .txt (ringkasan yang sama seperti
di layar) dan satu file .json (terstruktur, gampang diproses lagi).

Contoh pakai:
    python scripts/inspect_view_function_columns.py --password "12qwaszxX"
    python scripts/inspect_view_function_columns.py --password "..." --database lain_db
    python scripts/inspect_view_function_columns.py --password "..." --output-dir scripts/output
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc belum terinstall. Jalankan: pip install pyodbc")
    sys.exit(1)

# Sama seperti core/mssql.py: pilih driver terbaik yang benar-benar terdaftar di
# mesin ini, bukan hardcode "ODBC Driver 17" yang bisa saja tidak terinstall.
_DRIVER_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)
_MODERN_DRIVERS = {"ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"}


def _detect_driver() -> str:
    installed = set(pyodbc.drivers())
    for name in _DRIVER_PREFERENCE:
        if name in installed:
            return name
    return _DRIVER_PREFERENCE[1]


def _build_conn_str(host, port, database, user, password, driver) -> str:
    # Driver lawas ("SQL Server") gagal handshake TLS kalau dipaksa Encrypt=yes;
    # lihat core/mssql.py untuk detail kenapa ini dibedakan per driver.
    encrypt_clause = "Encrypt=yes;TrustServerCertificate=yes;" if driver in _MODERN_DRIVERS else "Encrypt=no;"
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"{encrypt_clause}"
        "Connection Timeout=5"
    )


def connect(host, port, database, user, password) -> pyodbc.Connection:
    driver = _detect_driver()
    conn_str = _build_conn_str(host, port, database, user, password, driver)
    try:
        return pyodbc.connect(conn_str, timeout=5)
    except pyodbc.Error as exc:
        detail = exc.args[1] if len(exc.args) > 1 else str(exc)
        print(f"ERROR koneksi ke {host}:{port}/{database} (driver={driver!r}): {detail}")
        sys.exit(1)


def view_columns(conn):
    """Kolom keluaran tiap VIEW (INFORMATION_SCHEMA.COLUMNS juga mencakup view)."""
    query = """
    SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE, c.ORDINAL_POSITION
    FROM INFORMATION_SCHEMA.COLUMNS c
    JOIN INFORMATION_SCHEMA.VIEWS v
        ON c.TABLE_SCHEMA = v.TABLE_SCHEMA AND c.TABLE_NAME = v.TABLE_NAME
    ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
    """
    return conn.cursor().execute(query).fetchall()


def table_valued_function_columns(conn):
    """Kolom keluaran tiap table-valued function."""
    query = """
    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION
    FROM INFORMATION_SCHEMA.ROUTINE_COLUMNS
    ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
    """
    return conn.cursor().execute(query).fetchall()


def scalar_function_returns(conn):
    """Scalar function tidak punya 'kolom' -- cuma satu nilai balik bertipe X."""
    query = """
    SELECT ROUTINE_SCHEMA, ROUTINE_NAME, DATA_TYPE
    FROM INFORMATION_SCHEMA.ROUTINES
    WHERE ROUTINE_TYPE = 'FUNCTION'
        AND ROUTINE_NAME NOT IN (SELECT DISTINCT TABLE_NAME FROM INFORMATION_SCHEMA.ROUTINE_COLUMNS)
    ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
    """
    return conn.cursor().execute(query).fetchall()


def _grouped_objects(rows):
    """[(schema, name, [ {name, type, nullable}, ... ]), ...] preserving row order."""
    objects = []
    current_key = None
    current_cols = None
    for schema, name, col, dtype, nullable, _pos in rows:
        key = (schema, name)
        if key != current_key:
            current_cols = []
            objects.append({"schema": schema, "name": name, "columns": current_cols})
            current_key = key
        current_cols.append({"name": col, "type": dtype, "nullable": nullable == "YES"})
    return objects


def _render_grouped(lines, objects, empty_label):
    if not objects:
        lines.append(f"  ({empty_label})")
        return
    for obj in objects:
        lines.append(f"\n  [{obj['schema']}].[{obj['name']}]")
        for col in obj["columns"]:
            null_label = "NULL" if col["nullable"] else "NOT NULL"
            lines.append(f"      {col['name']:<30} {col['type']:<20} {null_label}")


def main():
    parser = argparse.ArgumentParser(description="Cek kolom yang dihasilkan VIEW dan FUNCTION di MS SQL Server")
    parser.add_argument("--host", default="server-retail")
    parser.add_argument("--port", type=int, default=1433)
    parser.add_argument("--user", default="tester")
    parser.add_argument("--password", required=True, help="Wajib diisi manual, tidak disimpan di script.")
    parser.add_argument("--database", default="testing", help="Default 'testing' (sesuai profil Kelola Koneksi yang sudah ada).")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent / "output"),
        help="Folder tujuan file .txt/.json (default: scripts/output).",
    )
    args = parser.parse_args()

    conn = connect(args.host, args.port, args.database, args.user, args.password)
    try:
        views = _grouped_objects(view_columns(conn))
        tvfs = _grouped_objects(table_valued_function_columns(conn))
        scalars = [
            {"schema": schema, "name": func, "returns": dtype}
            for schema, func, dtype in scalar_function_returns(conn)
        ]

        lines = [f"Tersambung ke {args.host}:{args.port}/{args.database} sebagai {args.user}"]

        lines.append(f"\n{'=' * 100}\n  VIEWS\n{'=' * 100}")
        _render_grouped(lines, views, "tidak ada view")

        lines.append(f"\n{'=' * 100}\n  TABLE-VALUED FUNCTIONS\n{'=' * 100}")
        _render_grouped(lines, tvfs, "tidak ada table-valued function")

        lines.append(f"\n{'=' * 100}\n  SCALAR FUNCTIONS (return satu nilai, bukan kolom)\n{'=' * 100}")
        if not scalars:
            lines.append("  (tidak ada scalar function)")
        else:
            for item in scalars:
                lines.append(f"  [{item['schema']}].[{item['name']}]  -> returns {item['returns']}")

        report_text = "\n".join(lines) + "\n"
        print(report_text)

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        txt_path = output_dir / f"view_function_columns_{args.database}.txt"
        txt_path.write_text(report_text, encoding="utf-8")

        json_path = output_dir / f"view_function_columns_{args.database}.json"
        json_path.write_text(
            json.dumps(
                {
                    "host": args.host,
                    "port": args.port,
                    "database": args.database,
                    "views": views,
                    "table_valued_functions": tvfs,
                    "scalar_functions": scalars,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(f"[OK] Ditulis ke {txt_path}")
        print(f"[OK] Ditulis ke {json_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

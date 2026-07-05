#!/usr/bin/env python3
"""
Ambil definisi SQL (query/join) asli di balik tiap VIEW dan FUNCTION di MS SQL Server.

Beda dari scripts/inspect_view_function_columns.py (yang cuma menampilkan nama
kolom keluaran): script ini mengambil teks CREATE VIEW / CREATE FUNCTION apa
adanya -- join, WHERE, subquery, dll -- supaya bisa dibaca ulang saat menulis
query Python pengganti di services.py (PRD SS5.3: table-level access only, view/
function legacy tidak dipanggil langsung dari aplikasi, tapi query di baliknya
tetap jadi referensi).

Pakai sys.sql_modules (nvarchar(max), tidak terpotong) alih-alih
INFORMATION_SCHEMA.VIEWS.VIEW_DEFINITION / ROUTINES.ROUTINE_DEFINITION yang
dibatasi nvarchar(4000) dan bisa kepotong untuk view/function panjang.

Standalone (tidak baca .env / Django) karena koneksi target beda dari
POS_DB_GROSIR_* di .env. Deteksi driver ODBC & fallback Encrypt mengikuti pola
yang sudah diperbaiki di core/mssql.py.

Password TIDAK di-hardcode (supaya tidak ikut ter-commit ke git) -- selalu
wajib diisi lewat --password.

Catatan izin: membaca sys.sql_modules.definition butuh permission VIEW
DEFINITION. Akun "tester" (dipakai di scripts/inspect_view_function_columns.py)
TIDAK punya izin ini -- sudah dicek langsung: HAS_PERMS_BY_NAME(...,
'VIEW ANY DEFINITION') = False untuknya, sehingga semua definition kembali NULL
walau objectnya sendiri tidak di-WITH ENCRYPTION. Makanya default akun di sini
"sa", bukan "tester".

Contoh pakai:
    python scripts/inspect_view_function_definitions.py --password "..."
    python scripts/inspect_view_function_definitions.py --password "..." --database lain_db
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

# o.type di sys.objects untuk tipe yang kita mau.
_OBJECT_TYPES = {
    "V": "VIEW",
    "FN": "SCALAR_FUNCTION",
    "IF": "INLINE_TABLE_FUNCTION",
    "TF": "MULTI_STATEMENT_TABLE_FUNCTION",
}


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


def fetch_definitions(conn):
    """Definisi SQL tiap view & function.

    `definition` bisa NULL karena dua alasan berbeda -- makanya is_encrypted
    ikut diambil terpisah lewat OBJECTPROPERTY: NULL + is_encrypted=1 berarti
    object memang WITH ENCRYPTION (tidak bisa dibaca oleh siapa pun); NULL +
    is_encrypted=0 berarti akun yang dipakai tidak punya izin VIEW DEFINITION
    (bukan objectnya yang terenkripsi).
    """
    query = """
    SELECT
        s.name AS schema_name,
        o.name AS object_name,
        o.type AS object_type_code,
        OBJECTPROPERTY(o.object_id, 'IsEncrypted') AS is_encrypted,
        m.definition AS definition
    FROM sys.objects o
    JOIN sys.schemas s ON o.schema_id = s.schema_id
    LEFT JOIN sys.sql_modules m ON m.object_id = o.object_id
    WHERE o.type IN ('V', 'FN', 'IF', 'TF')
    ORDER BY o.type, s.name, o.name
    """
    return conn.cursor().execute(query).fetchall()


def has_view_definition_permission(conn) -> bool:
    row = conn.cursor().execute("SELECT HAS_PERMS_BY_NAME(NULL, NULL, 'VIEW ANY DEFINITION')").fetchone()
    return bool(row[0])


def main():
    parser = argparse.ArgumentParser(description="Ambil definisi SQL (join/query) di balik VIEW dan FUNCTION")
    parser.add_argument("--host", default="server-retail")
    parser.add_argument("--port", type=int, default=1433)
    parser.add_argument("--user", default="sa", help="Default 'sa' -- akun 'tester' biasanya tidak punya izin VIEW DEFINITION.")
    parser.add_argument("--password", required=True, help="Wajib diisi manual, tidak disimpan di script.")
    parser.add_argument("--database", default="testing", help="Default 'testing' (sesuai profil Kelola Koneksi yang sudah ada).")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent / "output"),
        help="Folder tujuan file .json (default: scripts/output).",
    )
    args = parser.parse_args()

    conn = connect(args.host, args.port, args.database, args.user, args.password)
    try:
        can_view_definitions = has_view_definition_permission(conn)
        rows = fetch_definitions(conn)

        objects = {"VIEW": [], "SCALAR_FUNCTION": [], "INLINE_TABLE_FUNCTION": [], "MULTI_STATEMENT_TABLE_FUNCTION": []}
        encrypted_count = 0
        permission_denied_count = 0
        for schema_name, object_name, type_code, is_encrypted, definition in rows:
            # o.type is char(2) in sys.objects -- SQL Server pads single-char
            # codes like "V" with a trailing space.
            type_label = _OBJECT_TYPES.get(type_code.strip(), type_code)
            unavailable_reason = None
            if definition is None:
                if is_encrypted:
                    unavailable_reason = "encrypted"
                    encrypted_count += 1
                else:
                    unavailable_reason = "permission_denied"
                    permission_denied_count += 1
            objects[type_label].append(
                {
                    "schema": schema_name,
                    "name": object_name,
                    "definition": definition,
                    "unavailable_reason": unavailable_reason,
                }
            )

        print(f"\nTersambung ke {args.host}:{args.port}/{args.database} sebagai {args.user}\n")
        for label, items in objects.items():
            print(f"  {label:<32} : {len(items)}")
        if encrypted_count:
            print(f"\n  ({encrypted_count} objek memang WITH ENCRYPTION -- tidak bisa dibaca oleh akun manapun)")
        if permission_denied_count:
            print(
                f"  ({permission_denied_count} objek TIDAK terenkripsi tapi definisinya kosong -- akun "
                f"'{args.user}' tidak punya izin VIEW DEFINITION di database ini, bukan karena objectnya "
                "dienkripsi. Minta admin GRANT VIEW DEFINITION, atau jalankan ulang dengan akun yang punya akses "
                "lebih tinggi, misal akun di POS_DB_GROSIR_* / sa.)"
            )
        if not can_view_definitions and permission_denied_count:
            print(f"  -> dikonfirmasi: HAS_PERMS_BY_NAME('VIEW ANY DEFINITION') = False untuk akun '{args.user}'")

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"view_function_definitions_{args.database}.json"
        json_path.write_text(
            json.dumps(
                {
                    "host": args.host,
                    "port": args.port,
                    "database": args.database,
                    **objects,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\n[OK] Ditulis ke {json_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

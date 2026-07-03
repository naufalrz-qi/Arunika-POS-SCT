#!/usr/bin/env python3
"""
Quick schema listing (non-interactive). Print all tables, views, functions, procedures.
"""

import os
import sys
from pathlib import Path

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed. Run: pip install pyodbc")
    sys.exit(1)

from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def get_connection():
    """Create MSSQL connection from .env."""
    host = os.getenv("POS_DB_GROSIR_HOST", "localhost")
    port = int(os.getenv("POS_DB_GROSIR_PORT", 1433))
    database = os.getenv("POS_DB_GROSIR_NAME", "gs-pusat")
    user = os.getenv("POS_DB_GROSIR_USER", "sa")
    password = os.getenv("POS_DB_GROSIR_PASSWORD", "")

    connection_string = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
    )

    try:
        conn = pyodbc.connect(connection_string)
        return conn
    except pyodbc.Error as e:
        print(f"Connection error: {e}")
        sys.exit(1)


def print_tables(conn):
    """Print all tables."""
    query = """
    SELECT
        TABLE_SCHEMA as [schema],
        TABLE_NAME as [table],
        (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = T.TABLE_SCHEMA AND TABLE_NAME = T.TABLE_NAME) as cols
    FROM INFORMATION_SCHEMA.TABLES T
    WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA != 'information_schema'
    ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    cursor = conn.cursor()
    cursor.execute(query)

    print("\n" + "=" * 100)
    print("TABLES")
    print("=" * 100)

    rows = cursor.fetchall()
    if not rows:
        print("(none)")
        return

    for schema, table, cols in rows:
        print(f"[{schema}].[{table:40s}]  {cols} cols")


def print_views(conn):
    """Print all views."""
    query = """
    SELECT
        TABLE_SCHEMA,
        TABLE_NAME
    FROM INFORMATION_SCHEMA.VIEWS
    WHERE TABLE_SCHEMA NOT IN ('information_schema', 'sys')
    ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    cursor = conn.cursor()
    cursor.execute(query)

    print("\n" + "=" * 100)
    print("VIEWS")
    print("=" * 100)

    rows = cursor.fetchall()
    if not rows:
        print("(none)")
        return

    for schema, view in rows:
        print(f"[{schema}].[{view}]")


def print_functions(conn):
    """Print all scalar & table-valued functions."""
    query = """
    SELECT
        ROUTINE_SCHEMA,
        ROUTINE_NAME,
        ROUTINE_TYPE
    FROM INFORMATION_SCHEMA.ROUTINES
    WHERE ROUTINE_SCHEMA NOT IN ('information_schema', 'sys')
        AND ROUTINE_TYPE != 'PROCEDURE'
    ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
    """
    cursor = conn.cursor()
    cursor.execute(query)

    print("\n" + "=" * 100)
    print("FUNCTIONS & TABLE-VALUED FUNCTIONS")
    print("=" * 100)

    rows = cursor.fetchall()
    if not rows:
        print("(none)")
        return

    for schema, func, ftype in rows:
        print(f"[{schema}].[{func:40s}]  ({ftype})")


def print_stored_procedures(conn):
    """Print all stored procedures."""
    query = """
    SELECT
        ROUTINE_SCHEMA,
        ROUTINE_NAME
    FROM INFORMATION_SCHEMA.ROUTINES
    WHERE ROUTINE_TYPE = 'PROCEDURE'
        AND ROUTINE_SCHEMA NOT IN ('information_schema', 'sys')
    ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
    """
    cursor = conn.cursor()
    cursor.execute(query)

    print("\n" + "=" * 100)
    print("STORED PROCEDURES")
    print("=" * 100)

    rows = cursor.fetchall()
    if not rows:
        print("(none)")
        return

    for schema, proc in rows:
        print(f"[{schema}].[{proc}]")


def print_summary(conn):
    """Print summary counts."""
    queries = {
        "Tables": "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA != 'information_schema'",
        "Views": "SELECT COUNT(*) FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA NOT IN ('information_schema', 'sys')",
        "Functions": "SELECT COUNT(*) FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_SCHEMA NOT IN ('information_schema', 'sys') AND ROUTINE_TYPE != 'PROCEDURE'",
        "Stored Procedures": "SELECT COUNT(*) FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_SCHEMA NOT IN ('information_schema', 'sys')",
    }

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)

    cursor = conn.cursor()
    for name, query in queries.items():
        cursor.execute(query)
        count = cursor.fetchone()[0]
        print(f"  {name:20s}: {count}")
    print()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Quick database schema listing")
    parser.add_argument("--summary-only", action="store_true", help="Show only summary counts")
    args = parser.parse_args()

    conn = get_connection()

    try:
        if args.summary_only:
            print_summary(conn)
        else:
            print_summary(conn)
            print_tables(conn)
            print_views(conn)
            print_functions(conn)
            print_stored_procedures(conn)
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()

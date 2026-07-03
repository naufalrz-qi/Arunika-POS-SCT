#!/usr/bin/env python3
"""
Inspect MSSQL Server database schema: tables, views, functions, stored procedures.
Reads connection from .env (POS_DB_GROSIR_*).
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed. Run: pip install pyodbc")
    sys.exit(1)

from dotenv import load_dotenv

# Load .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


@dataclass
class DBConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "DBConfig":
        return cls(
            host=os.getenv("POS_DB_GROSIR_HOST", "localhost"),
            port=int(os.getenv("POS_DB_GROSIR_PORT", 1433)),
            database=os.getenv("POS_DB_GROSIR_NAME", "gs-pusat"),
            user=os.getenv("POS_DB_GROSIR_USER", "sa"),
            password=os.getenv("POS_DB_GROSIR_PASSWORD", ""),
        )

    def connection_string(self) -> str:
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={self.host},{self.port};"
            f"DATABASE={self.database};"
            f"UID={self.user};"
            f"PWD={self.password};"
        )


class DatabaseInspector:
    def __init__(self, config: DBConfig):
        self.config = config
        self.conn: Optional[pyodbc.Connection] = None

    def connect(self):
        """Connect to database."""
        try:
            self.conn = pyodbc.connect(self.config.connection_string())
            print(f"✓ Connected to {self.config.database} on {self.config.host}:{self.config.port}")
        except pyodbc.Error as e:
            print(f"✗ Connection failed: {e}")
            sys.exit(1)

    def disconnect(self):
        """Close connection."""
        if self.conn:
            self.conn.close()

    def get_tables(self) -> list[dict]:
        """List all user tables."""
        query = """
        SELECT
            TABLE_SCHEMA as [schema],
            TABLE_NAME as [table],
            (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = T.TABLE_SCHEMA AND TABLE_NAME = T.TABLE_NAME) as column_count
        FROM INFORMATION_SCHEMA.TABLES T
        WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA != 'information_schema'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        return [{"schema": row[0], "table": row[1], "columns": row[2]} for row in cursor.fetchall()]

    def get_views(self) -> list[dict]:
        """List all views."""
        query = """
        SELECT
            TABLE_SCHEMA as [schema],
            TABLE_NAME as [view]
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA NOT IN ('information_schema', 'sys')
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        return [{"schema": row[0], "view": row[1]} for row in cursor.fetchall()]

    def get_functions(self) -> list[dict]:
        """List all scalar functions and table-valued functions."""
        query = """
        SELECT
            ROUTINE_SCHEMA as [schema],
            ROUTINE_NAME as [function],
            ROUTINE_TYPE as type
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_SCHEMA NOT IN ('information_schema', 'sys')
        ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        return [{"schema": row[0], "function": row[1], "type": row[2]} for row in cursor.fetchall()]

    def get_stored_procedures(self) -> list[dict]:
        """List all stored procedures."""
        query = """
        SELECT
            ROUTINE_SCHEMA as [schema],
            ROUTINE_NAME as [procedure]
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_SCHEMA NOT IN ('information_schema', 'sys')
        ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        return [{"schema": row[0], "procedure": row[1]} for row in cursor.fetchall()]

    def get_table_columns(self, schema: str, table: str) -> list[dict]:
        """Get columns of specific table."""
        query = """
        SELECT
            COLUMN_NAME as name,
            DATA_TYPE as type,
            IS_NULLABLE as nullable,
            COLUMN_DEFAULT as [default]
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """
        cursor = self.conn.cursor()
        cursor.execute(query, schema, table)
        return [
            {
                "name": row[0],
                "type": row[1],
                "nullable": row[2],
                "default": row[3],
            }
            for row in cursor.fetchall()
        ]

    def print_section(self, title: str):
        """Print section header."""
        print(f"\n{'=' * 80}")
        print(f"  {title}")
        print(f"{'=' * 80}")

    def print_tables(self):
        """Print all tables."""
        self.print_section("TABLES")
        tables = self.get_tables()
        if not tables:
            print("  (none found)")
            return

        for item in tables:
            print(f"  [{item['schema']}].[{item['table']}]  ({item['columns']} cols)")

    def print_views(self):
        """Print all views."""
        self.print_section("VIEWS")
        views = self.get_views()
        if not views:
            print("  (none found)")
            return

        for item in views:
            print(f"  [{item['schema']}].[{item['view']}]")

    def print_functions(self):
        """Print all functions."""
        self.print_section("FUNCTIONS & TABLE-VALUED FUNCTIONS")
        functions = self.get_functions()
        if not functions:
            print("  (none found)")
            return

        for item in functions:
            print(f"  [{item['schema']}].[{item['function']}]  ({item['type']})")

    def print_stored_procedures(self):
        """Print all stored procedures."""
        self.print_section("STORED PROCEDURES")
        procedures = self.get_stored_procedures()
        if not procedures:
            print("  (none found)")
            return

        for item in procedures:
            print(f"  [{item['schema']}].[{item['procedure']}]")

    def print_table_details(self, schema: str, table: str):
        """Print columns for specific table."""
        self.print_section(f"COLUMNS: [{schema}].[{table}]")
        columns = self.get_table_columns(schema, table)
        if not columns:
            print("  (no columns found)")
            return

        # Header
        print(f"  {'Name':<30} {'Type':<20} {'Nullable':<10} {'Default':<30}")
        print(f"  {'-'*30} {'-'*20} {'-'*10} {'-'*30}")

        for col in columns:
            null_str = col["nullable"] if col["nullable"] in ("YES", "NO") else str(col["nullable"])
            default = col["default"][:25] if col["default"] else "(none)"
            print(f"  {col['name']:<30} {col['type']:<20} {null_str:<10} {default:<30}")

    def run_interactive(self):
        """Interactive menu."""
        self.connect()

        while True:
            print("\n" + "=" * 80)
            print("  DATABASE SCHEMA INSPECTOR")
            print("=" * 80)
            print("  1. List all tables")
            print("  2. List all views")
            print("  3. List all functions")
            print("  4. List all stored procedures")
            print("  5. Show table columns (specify schema.table)")
            print("  6. Show all (tables, views, functions, procedures)")
            print("  0. Exit")

            choice = input("\nSelect option: ").strip()

            if choice == "1":
                self.print_tables()
            elif choice == "2":
                self.print_views()
            elif choice == "3":
                self.print_functions()
            elif choice == "4":
                self.print_stored_procedures()
            elif choice == "5":
                table_ref = input("Enter schema.table (e.g., dbo.Users): ").strip()
                if "." in table_ref:
                    schema, table = table_ref.split(".", 1)
                    self.print_table_details(schema, table)
                else:
                    print("  ✗ Invalid format. Use: schema.table")
            elif choice == "6":
                self.print_tables()
                self.print_views()
                self.print_functions()
                self.print_stored_procedures()
            elif choice == "0":
                break
            else:
                print("  ✗ Invalid option")

        self.disconnect()


def main():
    config = DBConfig.from_env()

    print(f"\nDatabase: {config.database}")
    print(f"Host: {config.host}:{config.port}")
    print(f"User: {config.user}\n")

    inspector = DatabaseInspector(config)
    inspector.run_interactive()


if __name__ == "__main__":
    main()

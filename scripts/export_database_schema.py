#!/usr/bin/env python3
"""
Export MSSQL Server database schema to CSV or JSON.
"""

import os
import sys
import json
import csv
from pathlib import Path
from datetime import datetime

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed. Run: pip install pyodbc")
    sys.exit(1)

from dotenv import load_dotenv

# Load .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


class SchemaExporter:
    def __init__(self):
        self.host = os.getenv("POS_DB_GROSIR_HOST", "localhost")
        self.port = int(os.getenv("POS_DB_GROSIR_PORT", 1433))
        self.database = os.getenv("POS_DB_GROSIR_NAME", "gs-pusat")
        self.user = os.getenv("POS_DB_GROSIR_USER", "sa")
        self.password = os.getenv("POS_DB_GROSIR_PASSWORD", "")
        self.conn = None

    def connect(self):
        """Connect to MSSQL."""
        try:
            connection_string = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={self.host},{self.port};"
                f"DATABASE={self.database};"
                f"UID={self.user};"
                f"PWD={self.password};"
            )
            self.conn = pyodbc.connect(connection_string)
            print(f"[OK] Connected to {self.database}")
        except pyodbc.Error as e:
            print(f"[ERROR] Connection failed: {e}")
            sys.exit(1)

    def disconnect(self):
        if self.conn:
            self.conn.close()

    def get_all_schema_data(self) -> dict:
        """Get all schema data: tables, views, functions, procedures."""
        data = {
            "database": self.database,
            "host": f"{self.host}:{self.port}",
            "exported_at": datetime.now().isoformat(),
            "tables": self._get_tables(),
            "views": self._get_views(),
            "functions": self._get_functions(),
            "stored_procedures": self._get_stored_procedures(),
        }
        return data

    def _get_tables(self) -> list[dict]:
        """Get all tables with column details."""
        query = """
        SELECT
            TABLE_SCHEMA as [schema],
            TABLE_NAME as [table]
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA != 'information_schema'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        tables = []

        for row in cursor.fetchall():
            schema, table_name = row
            columns = self._get_columns(schema, table_name)
            tables.append({
                "schema": schema,
                "name": table_name,
                "column_count": len(columns),
                "columns": columns,
            })

        return tables

    def _get_views(self) -> list[dict]:
        """Get all views."""
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
        return [{"schema": row[0], "name": row[1]} for row in cursor.fetchall()]

    def _get_functions(self) -> list[dict]:
        """Get all functions."""
        query = """
        SELECT
            ROUTINE_SCHEMA as [schema],
            ROUTINE_NAME as [function],
            ROUTINE_TYPE as type
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_SCHEMA NOT IN ('information_schema', 'sys')
            AND ROUTINE_TYPE != 'PROCEDURE'
        ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        return [
            {"schema": row[0], "name": row[1], "type": row[2]}
            for row in cursor.fetchall()
        ]

    def _get_stored_procedures(self) -> list[dict]:
        """Get all stored procedures."""
        query = """
        SELECT
            ROUTINE_SCHEMA as [schema],
            ROUTINE_NAME as [procedure]
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_TYPE = 'PROCEDURE'
            AND ROUTINE_SCHEMA NOT IN ('information_schema', 'sys')
        ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        return [{"schema": row[0], "name": row[1]} for row in cursor.fetchall()]

    def _get_columns(self, schema: str, table: str) -> list[dict]:
        """Get columns for specific table."""
        query = """
        SELECT
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            COLUMN_DEFAULT
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
                "nullable": row[2] == "YES",
                "default": row[3],
            }
            for row in cursor.fetchall()
        ]

    def export_json(self, output_file: str = None):
        """Export schema to JSON."""
        if output_file is None:
            output_file = f"schema_{self.database}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        data = self.get_all_schema_data()

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"[OK] Exported to {output_file}")

    def export_csv(self, output_dir: str = None):
        """Export schema to CSV files (one per object type)."""
        if output_dir is None:
            output_dir = f"schema_{self.database}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        Path(output_dir).mkdir(exist_ok=True)

        data = self.get_all_schema_data()

        # Tables
        tables_file = Path(output_dir) / "tables.csv"
        with open(tables_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Schema", "Table", "Columns"])
            for table in data["tables"]:
                writer.writerow([table["schema"], table["name"], table["column_count"]])
        print(f"[OK] {tables_file}")

        # Table Columns (detailed)
        columns_file = Path(output_dir) / "columns.csv"
        with open(columns_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Schema", "Table", "Column", "Type", "Nullable", "Default"])
            for table in data["tables"]:
                for col in table["columns"]:
                    writer.writerow([
                        table["schema"],
                        table["name"],
                        col["name"],
                        col["type"],
                        "Yes" if col["nullable"] else "No",
                        col["default"] or "",
                    ])
        print(f"[OK] {columns_file}")

        # Views
        views_file = Path(output_dir) / "views.csv"
        with open(views_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Schema", "View"])
            for view in data["views"]:
                writer.writerow([view["schema"], view["name"]])
        print(f"[OK] {views_file}")

        # Functions
        functions_file = Path(output_dir) / "functions.csv"
        with open(functions_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Schema", "Function", "Type"])
            for func in data["functions"]:
                writer.writerow([func["schema"], func["name"], func["type"]])
        print(f"[OK] {functions_file}")

        # Procedures
        procedures_file = Path(output_dir) / "stored_procedures.csv"
        with open(procedures_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Schema", "Procedure"])
            for proc in data["stored_procedures"]:
                writer.writerow([proc["schema"], proc["name"]])
        print(f"[OK] {procedures_file}")

        return output_dir


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Export MSSQL database schema")
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Export format (default: json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file/directory name",
    )

    args = parser.parse_args()

    print(f"\nExporting database schema...\n")

    exporter = SchemaExporter()
    exporter.connect()

    try:
        if args.format == "json":
            exporter.export_json(args.output)
        elif args.format == "csv":
            exporter.export_csv(args.output)
    finally:
        exporter.disconnect()


if __name__ == "__main__":
    main()

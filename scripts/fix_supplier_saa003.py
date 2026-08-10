"""Ubah kd_supplier SAA003 -> SAA000 (UMUM) di t_pembelian,
lalu hapus SAA003 dari m_supplier. Khusus PUSAT dan Testing.
"""
from __future__ import annotations
import argparse, os, sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from pathlib import Path
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import django; django.setup()
from apps.connections.models import ServerProfile
from core import mssql

TARGETS = ["PUSAT", "Testing"]
OLD_KD = "SAA003"
NEW_KD = "SAA000"  # UMUM


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    for name in TARGETS:
        profile = ServerProfile.objects.filter(name=name).first()
        if not profile:
            print(f"❌ Profil '{name}' tidak ditemukan"); continue

        print(f"\n{'═'*50}")
        print(f"  {name} [{profile.db_type}]")
        print(f"{'═'*50}")

        with mssql.cursor(profile, autocommit=False) as cur:
            try:
                # Cek semua tabel yang referensi SAA003
                cur.execute("""
                    SELECT tp.name AS tbl, cp.name AS col
                    FROM sys.foreign_keys fk
                    JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
                    JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
                    JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id
                        AND fkc.parent_column_id = cp.column_id
                    JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
                    WHERE tr.name = 'm_supplier'
                """)
                fk_tables = [(r[0], r[1]) for r in cur.fetchall()]
                print(f"  FK tables: {fk_tables}")

                # Untuk setiap FK table, cek & update/delete referensi SAA003
                for tbl, col in fk_tables:
                    cur.execute(f"SELECT COUNT(*) FROM [{tbl}] WHERE [{col}] = ?", OLD_KD)
                    cnt = cur.fetchone()[0]
                    if cnt == 0:
                        continue

                    if tbl.startswith("t_"):
                        # Tabel transaksi: UPDATE ke UMUM
                        print(f"  📝 {tbl}: {cnt} baris {OLD_KD} → {NEW_KD}")
                        if args.apply:
                            cur.execute(f"UPDATE [{tbl}] SET [{col}] = ? WHERE [{col}] = ?",
                                        NEW_KD, OLD_KD)
                            print(f"     ✅ Updated {cur.rowcount} baris")
                    else:
                        # Tabel master: DELETE
                        print(f"  🗑️  {tbl}: {cnt} baris akan dihapus")
                        if args.apply:
                            cur.execute(f"DELETE FROM [{tbl}] WHERE [{col}] = ?", OLD_KD)
                            print(f"     ✅ Deleted {cur.rowcount} baris")

                # Hapus SAA003 dari m_supplier
                cur.execute("SELECT nama FROM m_supplier WHERE kd_supplier = ?", OLD_KD)
                row = cur.fetchone()
                if row:
                    print(f"\n  🗑️  m_supplier: {OLD_KD} ({row[0]})")
                    if args.apply:
                        cur.execute("DELETE FROM m_supplier WHERE kd_supplier = ?", OLD_KD)
                        print(f"     ✅ Deleted")
                else:
                    print(f"\n  ℹ️  {OLD_KD} sudah tidak ada di m_supplier")

                if args.apply:
                    cur.connection.commit()
                    print(f"\n  ✅ COMMIT berhasil")

                    # Verifikasi
                    cur2 = cur.connection.cursor()
                    cur2.execute("SELECT kd_supplier, nama FROM m_supplier ORDER BY kd_supplier")
                    rows = cur2.fetchall()
                    print(f"\n  Supplier sekarang ({len(rows)}):")
                    for r in rows:
                        print(f"    {r[0]} | {r[1]}")
                else:
                    print(f"\n  ⏭️  DRY-RUN")

            except Exception as exc:
                cur.connection.rollback()
                print(f"\n  ❌ ROLLBACK — {exc}")

    if not args.apply:
        print(f"\nDRY-RUN — jalankan dengan --apply untuk eksekusi.")


if __name__ == "__main__":
    main()

"""Perbaikan: khusus RTL PUSAT yang gagal karena m_barang_supplier FK.
Hapus dulu baris di m_barang_supplier, baru hapus di m_supplier.

Jalankan:
  cd d:\Project\Arunika-SCT-POS
  venv\Scripts\python.exe -m scripts.restore_supplier_rtlpusat          # dry-run
  venv\Scripts\python.exe -m scripts.restore_supplier_rtlpusat --apply  # eksekusi
"""
from __future__ import annotations

import argparse
import os
import sys

# Force UTF-8 on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Django setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Load .env
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

import django
django.setup()

from apps.connections.models import ServerProfile
from core import mssql


REFERENSI_PROFIL = "PAGESANGAN"
TARGET_PROFIL = "RTL PUSAT"


def _dictify(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _st(v):
    return str(v).strip() if v is not None else ""


def baca_supplier(profile):
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT * FROM m_supplier ORDER BY kd_supplier")
        return _dictify(cur)


def kolom_supplier(profile):
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'm_supplier' ORDER BY ORDINAL_POSITION"
        )
        return [r[0] for r in cur.fetchall()]


def cari_fk_tables(profile):
    """Cari semua tabel yang punya FK ke m_supplier."""
    with mssql.cursor(profile) as cur:
        cur.execute("""
            SELECT 
                tp.name AS child_table,
                cp.name AS child_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
            JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
            JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
            JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
            WHERE tr.name = 'm_supplier'
        """)
        return _dictify(cur)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    ref_profile = ServerProfile.objects.filter(name=REFERENSI_PROFIL).first()
    tgt_profile = ServerProfile.objects.filter(name=TARGET_PROFIL).first()

    if not ref_profile or not tgt_profile:
        print(f"Profil tidak ditemukan: ref={ref_profile}, tgt={tgt_profile}")
        sys.exit(1)

    ref_rows = baca_supplier(ref_profile)
    ref_kolom = kolom_supplier(ref_profile)
    ref_kd = {_st(r["kd_supplier"]) for r in ref_rows}
    ref_map = {_st(r["kd_supplier"]): r for r in ref_rows}

    print(f"═══ REFERENSI: {REFERENSI_PROFIL} ({len(ref_rows)} supplier) ═══")
    for r in ref_rows:
        print(f"  {r['kd_supplier']} | {r['nama']}")

    # Cek FK constraints
    print(f"\n═══ FK constraints ke m_supplier di {TARGET_PROFIL} ═══")
    fk_info = cari_fk_tables(tgt_profile)
    for fk in fk_info:
        print(f"  {fk['child_table']}.{fk['child_column']}")

    current = baca_supplier(tgt_profile)
    dst_kolom = kolom_supplier(tgt_profile)
    cur_kd = {_st(r["kd_supplier"]) for r in current}
    cur_map = {_st(r["kd_supplier"]): r for r in current}

    common_cols = [c for c in ref_kolom if c in dst_kolom]
    non_key_cols = [c for c in common_cols if c != "kd_supplier"]

    to_delete = cur_kd - ref_kd
    to_insert = ref_kd - cur_kd
    to_update = ref_kd & cur_kd

    actually_update = set()
    for kd in to_update:
        for col in non_key_cols:
            if _st(ref_map[kd].get(col)) != _st(cur_map[kd].get(col)):
                actually_update.add(kd)
                break

    print(f"\n═══ {TARGET_PROFIL}: {len(current)} supplier sekarang ═══")
    print(f"  HAPUS  : {len(to_delete)} supplier")
    print(f"  INSERT : {len(to_insert)} supplier")
    print(f"  UPDATE : {len(actually_update)} supplier")
    print(f"  SAMA   : {len(to_update - actually_update)} supplier")

    if not args.apply:
        print(f"\n⏭️  DRY-RUN — jalankan dengan --apply untuk eksekusi.")
        return

    # Eksekusi
    with mssql.cursor(tgt_profile, autocommit=False) as cur:
        try:
            deleted = 0
            skipped = 0

            for kd in sorted(to_delete):
                # Hapus referensi di child tables dulu
                skip_this = False
                for fk in fk_info:
                    tbl = fk["child_table"]
                    col = fk["child_column"]

                    # Cek apakah ini tabel transaksi (t_*) — jangan hapus datanya
                    if tbl.startswith("t_"):
                        cur.execute(f"SELECT COUNT(*) FROM [{tbl}] WHERE [{col}] = ?", kd)
                        cnt = cur.fetchone()[0]
                        if cnt > 0:
                            print(f"  ⚠️  {kd} direferensi di {tbl} ({cnt} baris) — SKIP")
                            skip_this = True
                            break
                    else:
                        # Tabel master (m_barang_supplier dll) — hapus referensinya
                        cur.execute(f"DELETE FROM [{tbl}] WHERE [{col}] = ?", kd)
                        rc = cur.rowcount
                        if rc > 0:
                            print(f"    🔗 Hapus {rc} baris dari {tbl} untuk {kd}")

                if skip_this:
                    skipped += 1
                    continue

                cur.execute("DELETE FROM m_supplier WHERE kd_supplier = ?", kd)
                deleted += 1

            # INSERT
            inserted = 0
            for kd in sorted(to_insert):
                ref = ref_map[kd]
                vals = [ref.get(c) for c in common_cols]
                placeholders = ", ".join("?" * len(common_cols))
                col_list = ", ".join(common_cols)
                cur.execute(
                    f"INSERT INTO m_supplier ({col_list}) VALUES ({placeholders})", vals
                )
                inserted += 1

            # UPDATE
            updated = 0
            for kd in sorted(actually_update):
                ref = ref_map[kd]
                set_parts = ", ".join(f"{c} = ?" for c in non_key_cols)
                vals = [ref.get(c) for c in non_key_cols] + [kd]
                cur.execute(
                    f"UPDATE m_supplier SET {set_parts} WHERE kd_supplier = ?", vals
                )
                updated += 1

            cur.connection.commit()
            print(f"\n✅ COMMIT: deleted={deleted}, skipped={skipped}, inserted={inserted}, updated={updated}")

        except Exception as exc:
            cur.connection.rollback()
            print(f"\n❌ ROLLBACK — {exc}")

    # Verifikasi
    after = baca_supplier(tgt_profile)
    print(f"\n═══ {TARGET_PROFIL} SESUDAH: {len(after)} supplier ═══")
    for r in after:
        print(f"  {r['kd_supplier']} | {r['nama']}")


if __name__ == "__main__":
    main()

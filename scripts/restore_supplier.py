"""Kembalikan data m_supplier di semua server grosir & retail agar
SAMA PERSIS dengan PAGESANGAN (yang belum berubah, hanya 3 supplier).

Gudang TIDAK disentuh.

Langkah:
  1. Baca semua kolom m_supplier dari PAGESANGAN → 3 baris referensi.
  2. Untuk setiap server grosir & retail (kecuali gudang):
     a. Tampilkan supplier saat ini.
     b. Hapus supplier yang TIDAK ADA di referensi.
     c. Upsert (INSERT/UPDATE) supplier yang ADA di referensi.

Jalankan:
  cd d:\Project\Arunika-SCT-POS
  python -m scripts.restore_supplier          # dry-run (default)
  python -m scripts.restore_supplier --apply   # eksekusi sungguhan
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

# Load .env supaya POS_FERNET_KEY dll tersedia
from pathlib import Path  # noqa: E402
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import django  # noqa: E402
django.setup()

from apps.connections.models import ServerProfile  # noqa: E402
from core import mssql                              # noqa: E402


REFERENSI_PROFIL = "PAGESANGAN"
SKIP_DB_TYPES = {"gudang"}  # gudang tidak disentuh


def _dictify(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _st(v):
    return str(v).strip() if v is not None else ""


def baca_supplier(profile) -> list[dict]:
    """Baca semua kolom m_supplier dari sebuah profil."""
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT * FROM m_supplier ORDER BY kd_supplier")
        return _dictify(cur)


def kolom_supplier(profile) -> list[str]:
    """Daftar nama kolom m_supplier."""
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'm_supplier' ORDER BY ORDINAL_POSITION"
        )
        return [r[0] for r in cur.fetchall()]


def tampilkan(label, rows):
    print(f"\n  [{label}] {len(rows)} supplier:")
    for r in rows:
        print(f"    {r.get('kd_supplier', '?')} | {r.get('nama', '?')}")


def main():
    parser = argparse.ArgumentParser(description="Restore m_supplier ke data PAGESANGAN")
    parser.add_argument("--apply", action="store_true", help="Eksekusi sungguhan (tanpa ini = dry-run)")
    args = parser.parse_args()

    # ─── 1. Baca referensi dari PAGESANGAN ───────────────────────────────
    ref_profile = ServerProfile.objects.filter(name=REFERENSI_PROFIL).first()
    if not ref_profile:
        print(f"❌ Profil '{REFERENSI_PROFIL}' tidak ditemukan di database.")
        sys.exit(1)

    ref_rows = baca_supplier(ref_profile)
    ref_kolom = kolom_supplier(ref_profile)
    ref_kd = {_st(r["kd_supplier"]) for r in ref_rows}
    ref_map = {_st(r["kd_supplier"]): r for r in ref_rows}

    print(f"═══ REFERENSI: {REFERENSI_PROFIL} ═══")
    tampilkan(REFERENSI_PROFIL, ref_rows)
    print(f"\n  Kolom: {ref_kolom}")
    print(f"  Kunci referensi: {sorted(ref_kd)}")

    if not ref_rows:
        print("⚠️  Referensi kosong — tidak ada yang bisa dikerjakan.")
        sys.exit(1)

    # ─── 2. Proses semua server grosir & retail ──────────────────────────
    targets = ServerProfile.objects.exclude(
        name__in=[REFERENSI_PROFIL]
    ).exclude(db_type__in=list(SKIP_DB_TYPES))

    if not targets.exists():
        print("\n⚠️  Tidak ada profil target (grosir/retail selain PAGESANGAN).")
        return

    for profile in targets:
        print(f"\n{'═' * 60}")
        print(f"  TARGET: {profile.name} [{profile.db_type}]")
        print(f"{'═' * 60}")

        try:
            current = baca_supplier(profile)
            dst_kolom = kolom_supplier(profile)
        except Exception as exc:
            print(f"  ⚠️  Gagal membaca: {exc}")
            continue

        tampilkan(f"{profile.name} SEBELUM", current)

        cur_kd = {_st(r["kd_supplier"]) for r in current}
        cur_map = {_st(r["kd_supplier"]): r for r in current}

        # Kolom yang ada di KEDUA server (referensi & target)
        common_cols = [c for c in ref_kolom if c in dst_kolom]
        non_key_cols = [c for c in common_cols if c != "kd_supplier"]

        to_delete = cur_kd - ref_kd
        to_insert = ref_kd - cur_kd
        to_update = ref_kd & cur_kd  # cek per-kolom nanti

        # ─── Hitung baris yang benar-benar berubah ───────────────────
        actually_update = set()
        for kd in to_update:
            for col in non_key_cols:
                if _st(ref_map[kd].get(col)) != _st(cur_map[kd].get(col)):
                    actually_update.add(kd)
                    break

        print(f"\n  Rencana:")
        print(f"    HAPUS  : {sorted(to_delete) if to_delete else '(tidak ada)'}")
        print(f"    INSERT : {sorted(to_insert) if to_insert else '(tidak ada)'}")
        print(f"    UPDATE : {sorted(actually_update) if actually_update else '(tidak ada)'}")
        print(f"    SAMA   : {sorted(to_update - actually_update) if (to_update - actually_update) else '(tidak ada)'}")

        if not args.apply:
            print(f"  ⏭️  DRY-RUN — tidak ada perubahan.")
            continue

        # ─── Eksekusi ────────────────────────────────────────────────
        with mssql.cursor(profile, autocommit=False) as cur:
            try:
                # DELETE supplier yang tidak ada di referensi
                for kd in sorted(to_delete):
                    # Cek dulu apakah supplier ini dipakai di transaksi
                    cur.execute(
                        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_NAME = 't_pembelian'"
                    )
                    has_pembelian = cur.fetchone()[0] > 0

                    if has_pembelian:
                        cur.execute(
                            "SELECT COUNT(*) FROM t_pembelian WHERE kd_supplier = ?", kd
                        )
                        used = cur.fetchone()[0]
                        if used > 0:
                            print(f"    ⚠️  {kd} dipakai di {used} transaksi pembelian — SKIP DELETE")
                            continue

                    cur.execute("DELETE FROM m_supplier WHERE kd_supplier = ?", kd)
                    print(f"    ✅ DELETE {kd}")

                # INSERT supplier baru
                for kd in sorted(to_insert):
                    ref = ref_map[kd]
                    vals = [ref.get(c) for c in common_cols]
                    placeholders = ", ".join("?" * len(common_cols))
                    col_list = ", ".join(common_cols)
                    cur.execute(
                        f"INSERT INTO m_supplier ({col_list}) VALUES ({placeholders})",
                        vals
                    )
                    print(f"    ✅ INSERT {kd} ({ref.get('nama', '?')})")

                # UPDATE supplier yang berubah
                for kd in sorted(actually_update):
                    ref = ref_map[kd]
                    set_parts = ", ".join(f"{c} = ?" for c in non_key_cols)
                    vals = [ref.get(c) for c in non_key_cols] + [kd]
                    cur.execute(
                        f"UPDATE m_supplier SET {set_parts} WHERE kd_supplier = ?",
                        vals
                    )
                    print(f"    ✅ UPDATE {kd} ({ref.get('nama', '?')})")

                cur.connection.commit()
                print(f"\n  ✅ {profile.name}: COMMIT berhasil")

            except Exception as exc:
                cur.connection.rollback()
                print(f"\n  ❌ {profile.name}: ROLLBACK — {exc}")

        # Verifikasi
        try:
            after = baca_supplier(profile)
            tampilkan(f"{profile.name} SESUDAH", after)
        except Exception:
            pass

    print(f"\n{'═' * 60}")
    if args.apply:
        print("SELESAI — semua target sudah diproses.")
    else:
        print("DRY-RUN SELESAI — jalankan dengan --apply untuk eksekusi.")


if __name__ == "__main__":
    main()

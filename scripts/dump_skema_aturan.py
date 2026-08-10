"""Dump FK rules, triggers, PK/unique/check/default constraints for two MSSQL DBs."""
import os, sys, django
from dotenv import load_dotenv

load_dotenv(r"D:\Project\Arunika-SCT-POS\.env")
sys.path.insert(0, r"D:\Project\Arunika-SCT-POS")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.connections.models import ServerProfile
from core import mssql

Q_FK = """
SELECT fk.name, OBJECT_NAME(fk.parent_object_id), OBJECT_NAME(fk.referenced_object_id),
       fk.delete_referential_action_desc, fk.update_referential_action_desc,
       fk.is_disabled, fk.is_not_trusted
FROM sys.foreign_keys fk ORDER BY 2,1
"""
Q_FKCOL = """
SELECT fk.name, COL_NAME(fkc.parent_object_id, fkc.parent_column_id),
       COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id)
FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
ORDER BY fk.name, fkc.constraint_column_id
"""
Q_TRG = """
SELECT t.name, OBJECT_NAME(t.parent_id), t.is_disabled, t.is_instead_of_trigger,
       STUFF((SELECT ', ' + te.type_desc FROM sys.trigger_events te WHERE te.object_id = t.object_id FOR XML PATH('')),1,2,'')
FROM sys.triggers t WHERE t.parent_class = 1 ORDER BY 2,1
"""
Q_TRGDEF = "SELECT OBJECT_NAME(object_id), definition FROM sys.sql_modules WHERE object_id IN (SELECT object_id FROM sys.triggers WHERE parent_class=1)"
Q_KEYS = """
SELECT OBJECT_NAME(i.object_id), i.name, i.is_primary_key, i.is_unique_constraint,
       STUFF((SELECT ', ' + COL_NAME(ic.object_id, ic.column_id) FROM sys.index_columns ic
              WHERE ic.object_id=i.object_id AND ic.index_id=i.index_id AND ic.is_included_column=0
              ORDER BY ic.key_ordinal FOR XML PATH('')),1,2,'')
FROM sys.indexes i
WHERE (i.is_primary_key=1 OR i.is_unique_constraint=1 OR i.is_unique=1)
  AND OBJECTPROPERTY(i.object_id,'IsUserTable')=1
ORDER BY 1,3 DESC
"""
Q_CHK = """
SELECT OBJECT_NAME(parent_object_id), name, definition, is_disabled
FROM sys.check_constraints ORDER BY 1,2
"""
Q_DEF = """
SELECT OBJECT_NAME(parent_object_id), COL_NAME(parent_object_id, parent_column_id), definition
FROM sys.default_constraints ORDER BY 1,2
"""
Q_TBL = """
SELECT t.name, (SELECT COUNT(*) FROM sys.columns c WHERE c.object_id=t.object_id),
       SUM(CASE WHEN p.index_id IN (0,1) THEN p.rows ELSE 0 END)
FROM sys.tables t LEFT JOIN sys.partitions p ON p.object_id=t.object_id
GROUP BY t.name, t.object_id ORDER BY t.name
"""
Q_COLS = """
SELECT t.name, c.column_id, c.name, ty.name, c.max_length, c.precision, c.scale,
       c.is_nullable, c.is_identity, c.is_computed
FROM sys.tables t JOIN sys.columns c ON c.object_id=t.object_id
JOIN sys.types ty ON ty.user_type_id=c.user_type_id
ORDER BY t.name, c.column_id
"""


def run(profile_name, out):
    p = ServerProfile.objects.get(name=profile_name)
    with mssql.cursor(p) as cur:
        def q(sql):
            cur.execute(sql)
            return cur.fetchall()

        w = out.write
        w(f"\n{'='*100}\nDATABASE: {p.db_name}  (host {p.host}, profil '{p.name}')\n{'='*100}\n")

        tbl = q(Q_TBL)
        w(f"\n## TABEL ({len(tbl)})\n")
        for name, ncol, rows in tbl:
            w(f"  {name:45s} {ncol:3d} kolom  {rows or 0:>12,} baris\n")

        fks = q(Q_FK)
        fkcols = {}
        for n, pc, rc in q(Q_FKCOL):
            fkcols.setdefault(n, []).append(f"{pc}->{rc}")
        w(f"\n## FOREIGN KEY ({len(fks)})\n")
        if not fks:
            w("  (TIDAK ADA satu pun foreign key)\n")
        for n, parent, ref, dele, upd, dis, untrust in fks:
            w(f"  {parent}.{n}\n      -> {ref} [{', '.join(fkcols.get(n, []))}]\n"
              f"      ON DELETE {dele} | ON UPDATE {upd} | disabled={bool(dis)} not_trusted={bool(untrust)}\n")

        trg = q(Q_TRG)
        w(f"\n## TRIGGER ({len(trg)})\n")
        for n, parent, dis, instead, events in trg:
            kind = "INSTEAD OF" if instead else "AFTER"
            w(f"  {parent:35s} {n:45s} {kind} {events}{'  [DISABLED]' if dis else ''}\n")

        keys = q(Q_KEYS)
        w(f"\n## PRIMARY KEY / UNIQUE ({len(keys)})\n")
        for t, n, pk, uc, cols in keys:
            kind = "PK" if pk else ("UQ-constraint" if uc else "UQ-index")
            w(f"  {t:35s} {kind:14s} {n:40s} ({cols})\n")

        chk = q(Q_CHK)
        w(f"\n## CHECK CONSTRAINT ({len(chk)})\n")
        for t, n, d, dis in chk:
            w(f"  {t:35s} {n:35s} {d}{'  [DISABLED]' if dis else ''}\n")

        dfl = q(Q_DEF)
        w(f"\n## DEFAULT CONSTRAINT ({len(dfl)})\n")
        for t, c, d in dfl:
            w(f"  {t:35s} {c:30s} {d}\n")

        w(f"\n## KOLOM PER TABEL\n")
        cur_t = None
        for t, cid, c, ty, ml, pr, sc, nul, ident, comp in q(Q_COLS):
            if t != cur_t:
                w(f"\n  [{t}]\n")
                cur_t = t
            typ = ty
            if ty in ("varchar", "char", "nvarchar", "nchar", "varbinary", "binary"):
                typ = f"{ty}({'max' if ml == -1 else (ml // 2 if ty.startswith('n') else ml)})"
            elif ty in ("decimal", "numeric"):
                typ = f"{ty}({pr},{sc})"
            flags = []
            if ident: flags.append("IDENTITY")
            if comp: flags.append("COMPUTED")
            flags.append("NULL" if nul else "NOT NULL")
            w(f"    {cid:3d} {c:32s} {typ:18s} {' '.join(flags)}\n")

        w(f"\n## DEFINISI TRIGGER\n")
        for n, d in q(Q_TRGDEF):
            w(f"\n----- {n} -----\n{d}\n")


if __name__ == "__main__":
    for prof, path in [("testgudang", "testgudang_schema.txt"), ("Testing", "grosirpusat_schema.txt")]:
        full = os.path.join(os.path.dirname(__file__), path)
        with open(full, "w", encoding="utf-8") as f:
            run(prof, f)
        print("written", full)

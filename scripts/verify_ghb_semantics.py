#!/usr/bin/env python3
"""Verifikasi semantik diskon/pajak (_ghb) terhadap UDF legacy di DB.

Membuktikan tiga hal, semuanya lewat `assert`:

1. NOTA TERDAMPAK  -- untuk tiap nota dgn diskon header/pajak <> 0, total bersih
   versi _nota_net() harus cocok dgn dbo.GetTotalPenjualan (toleransi 0.01).
2. KONTROL         -- nota TANPA diskon header & pajak harus TETAP cocok. Ini
   penjaga regresi: 99,5% nota sudah benar sebelum perbaikan, jangan sampai
   ikut bergeser.
3. MODE DUAL       -- _ghb diuji dgn nilai sintetis (fraksi, rupiah flat,
   negatif, harga 0) lawan dbo.GetHargaBersih pada input yang sama. DB ini tak
   punya header diskon |d| >= 1, jadi cabang flat cuma bisa diuji begini.

UDF hanya dipakai DI SINI sebagai pembanding; kode produksi tetap table-level
(PRD SS5.3). Kredensial dari POS_DB_GROSIR_* di .env.

Catatan pembanding: GetTotalPenjualan sudah mengurangi voucher sedangkan
_nota_net sengaja tidak, jadi nominal voucher ditambahkan balik saat
membandingkan. UDF juga INNER JOIN ke m_voucher -- nota tanpa kd_voucher yang
cocok mengembalikan NULL dan dilewati (bukan kegagalan uji).

Pakai:
    python scripts/verify_ghb_semantics.py
    python scripts/verify_ghb_semantics.py --csv out.csv   # + daftar audit
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pyodbc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from apps.transactions.reports import _disk4, _ghb, _nota_net, _unit_net  # noqa: E402

_DRIVER_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)
_MODERN = {"ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"}
TOL = 0.01


def connect() -> pyodbc.Connection:
    cfg = {}
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    installed = set(pyodbc.drivers())
    driver = next((d for d in _DRIVER_PREFERENCE if d in installed), _DRIVER_PREFERENCE[1])
    enc = "Encrypt=yes;TrustServerCertificate=yes;" if driver in _MODERN else "Encrypt=no;"
    return pyodbc.connect(
        f"DRIVER={{{driver}}};SERVER={cfg['POS_DB_GROSIR_HOST']},{cfg['POS_DB_GROSIR_PORT']};"
        f"DATABASE={cfg['POS_DB_GROSIR_NAME']};UID={cfg['POS_DB_GROSIR_USER']};"
        f"PWD={cfg['POS_DB_GROSIR_PASSWORD']};{enc}Connection Timeout=10",
        timeout=600,
    )


def _cmp_sql(where: str, top: str = "") -> str:
    """Bandingkan _nota_net() vs GetTotalPenjualan utk nota yang cocok `where`."""
    return f"""
    SELECT {top} n.no_transaksi, n.tanggal, n.total_bersih AS total_baru,
           dbo.GetTotalPenjualan(n.no_transaksi) + COALESCE(v.nominal, 0) AS total_udf
    FROM ({_nota_net(where)}) n
    LEFT JOIN m_voucher v ON v.kd_voucher = n.kd_voucher
    WHERE dbo.GetTotalPenjualan(n.no_transaksi) IS NOT NULL
    """


HDR_NONZERO = (
    "(COALESCE(h.diskon1,0)<>0 OR COALESCE(h.diskon2,0)<>0 OR COALESCE(h.diskon3,0)<>0 "
    "OR COALESCE(h.diskon4,0)<>0 OR COALESCE(h.pajak,0)<>0)"
)
HDR_ZERO = (
    "COALESCE(h.diskon1,0)=0 AND COALESCE(h.diskon2,0)=0 AND COALESCE(h.diskon3,0)=0 "
    "AND COALESCE(h.diskon4,0)=0 AND COALESCE(h.pajak,0)=0 AND h.tanggal >= '2024-01-01'"
)


def check_notas(cur, label: str, where: str, top: str = "") -> int:
    print(f"\n[{label}] ...", flush=True)
    cur.execute(_cmp_sql(where, top))
    bad, n = [], 0
    for no, _tgl, baru, udf in cur.fetchall():
        n += 1
        if abs(float(baru) - float(udf)) > TOL:
            bad.append((no.strip(), float(baru), float(udf)))
    for no, baru, udf in bad[:10]:
        print(f"    MISMATCH {no}: kode={baru:,.2f} udf={udf:,.2f} selisih={baru - udf:,.2f}")
    assert not bad, f"[{label}] {len(bad)} dari {n} nota tidak cocok dgn GetTotalPenjualan"
    assert n > 0, f"[{label}] tidak ada nota terambil -- uji tidak bermakna"
    print(f"    OK: {n} nota cocok (toleransi {TOL})")
    return n


def check_dual_mode(cur) -> None:
    """_ghb vs GetHargaBersih pada nilai sintetis -- termasuk cabang |d| >= 1
    yang tidak ada di data live, dan guard harga <= 0."""
    cases = [
        # (harga, d1, d2, pajak, keterangan)
        (100000, 0.25, 0.0, 0.0, "fraksi 25%"),
        (100000, 0.05, 0.10, 0.0, "dua fraksi berurutan"),
        (100000, 5000.0, 0.0, 0.0, "rupiah flat >= 1"),
        (100000, -2.0, 0.0, 0.0, "rupiah flat negatif <= -1"),
        (100000, 0.0, 0.0, 0.05, "pajak fraksi 5%"),
        (100000, 0.10, 2500.0, 0.05, "campur fraksi + flat + pajak"),
        (0, 0.30, 0.0, 0.05, "guard harga = 0"),
        (-500, 0.30, 0.0, 0.0, "guard harga negatif"),
    ]
    print("\n[MODE DUAL] _ghb vs dbo.GetHargaBersih (nilai sintetis) ...", flush=True)
    expr = _ghb("t.harga", ["t.d1", "t.d2", "0", "0"], pajak="t.pajak")
    bad = []
    for harga, d1, d2, pajak, note in cases:
        cur.execute(
            f"SELECT {expr}, dbo.GetHargaBersih(t.harga, t.d1, t.d2, 0, 0, t.pajak, 0) "
            "FROM (SELECT CAST(? AS MONEY) AS harga, CAST(? AS FLOAT) AS d1, "
            "CAST(? AS FLOAT) AS d2, CAST(? AS FLOAT) AS pajak) t",
            [harga, d1, d2, pajak],
        )
        ours, udf = cur.fetchone()
        if abs(float(ours) - float(udf)) > TOL:
            bad.append((note, float(ours), float(udf)))
        else:
            print(f"    OK  {note:<32} -> {float(udf):,.2f}")
    for note, ours, udf in bad:
        print(f"    MISMATCH {note}: _ghb={ours:,.2f} udf={udf:,.2f}")
    assert not bad, f"[MODE DUAL] {len(bad)} kasus tidak cocok dgn GetHargaBersih"


def check_hpp_unchanged() -> None:
    """penjualan_hpp direfaktor jadi _unit_net/_disk4 -- ekspresinya harus sama
    persis dgn bentuk lama (beda spasi diabaikan), jadi angka Laba per Barang
    tidak boleh bergerak."""
    lama = _ghb("d.harga_jual",
                ["COALESCE(d.diskon1,0)", "COALESCE(d.diskon2,0)",
                 "COALESCE(d.diskon3,0)", "COALESCE(d.diskon4,0)"])
    baru = _unit_net("harga_jual")
    norm = lambda s: s.replace(" ", "")  # noqa: E731
    assert norm(lama) == norm(baru), "ekspresi item_net penjualan_hpp BERUBAH -- Laba per Barang akan bergeser"
    lama_h = _ghb("X", ["COALESCE(h.diskon1,0)", "COALESCE(h.diskon2,0)",
                        "COALESCE(h.diskon3,0)", "COALESCE(h.diskon4,0)"])
    assert norm(lama_h) == norm(_ghb("X", _disk4("h"))), "_disk4('h') tidak setara bentuk lama"
    print("\n[HPP] OK: ekspresi penjualan_hpp identik dgn sebelum refaktor")


def dump_csv(cur, path: str) -> None:
    """Daftar audit: nota terdampak, total lama (formula pra-perbaikan) vs baru."""
    lama_line = ("(d.qty * (d.harga_jual - COALESCE(d.diskon1,0) - COALESCE(d.diskon2,0) "
                 "- COALESCE(d.diskon3,0) - COALESCE(d.diskon4,0)))")
    lama_hdr = ("(COALESCE(h.diskon1,0) + COALESCE(h.diskon2,0) + COALESCE(h.diskon3,0) "
                "+ COALESCE(h.diskon4,0))")
    lama_net = f"(SUM({lama_line}) - {lama_hdr} - COALESCE(MIN(h.diskon_uang),0))"
    baru_net = (f"SUM({_ghb(_unit_net('harga_jual'), _disk4('h'))} * d.qty) "
                f"* (1 + COALESCE(MIN(h.pajak),0)) - COALESCE(MIN(h.diskon_uang),0)")
    cur.execute(f"""
        SELECT h.no_transaksi, MIN(h.tanggal) AS tanggal,
               MIN(h.diskon1) AS diskon1, MIN(h.diskon2) AS diskon2,
               MIN(h.diskon3) AS diskon3, MIN(h.diskon4) AS diskon4,
               MIN(h.pajak) AS pajak, MIN(h.diskon_uang) AS diskon_uang,
               ROUND(SUM(d.qty * d.harga_jual), 2) AS total_kotor,
               ROUND({lama_net} * (1 + COALESCE(MIN(h.pajak),0) / 100.0), 2) AS total_lama,
               ROUND({baru_net}, 2) AS total_baru,
               ROUND({lama_net} * (1 + COALESCE(MIN(h.pajak),0) / 100.0) - ({baru_net}), 2) AS selisih
        FROM t_penjualan h
        INNER JOIN t_penjualan_detail d ON h.no_transaksi = d.no_transaksi
        WHERE {HDR_NONZERO}
        GROUP BY h.no_transaksi, h.diskon1, h.diskon2, h.diskon3, h.diskon4,
                 h.diskon_uang, h.pajak
        ORDER BY ABS({lama_net} * (1 + COALESCE(MIN(h.pajak),0) / 100.0) - ({baru_net})) DESC
    """)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])
    total = sum(float(r[-1] or 0) for r in rows)
    print(f"\n[AUDIT] {len(rows)} nota -> {path}")
    print(f"         total selisih (lama - baru) = Rp{total:,.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", help="Tulis daftar audit nota terdampak ke file CSV.")
    args = ap.parse_args()

    check_hpp_unchanged()
    conn = connect()
    try:
        cur = conn.cursor()
        check_dual_mode(cur)
        check_notas(cur, "NOTA TERDAMPAK", HDR_NONZERO)
        check_notas(cur, "KONTROL (tanpa diskon header/pajak)", HDR_ZERO, top="TOP 500")
        if args.csv:
            dump_csv(cur, args.csv)
    finally:
        conn.close()
    print("\nSEMUA UJI LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

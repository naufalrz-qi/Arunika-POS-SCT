r"""Master data AMPHOREUS: satu katalog, ikut GUDANG saja.

Sebelumnya tiap cabang menulis masternya sendiri ke AMPHOREUS, jadi katalog yang
sama tersimpan sembilan kali dengan `kd_sumber` berbeda. Dua akibatnya:

- **Berganda tanpa guna.** Harga antar-server memang nyaris identik (174
  `m_barang_satuan` yang tersentuh pada uji fan-out semuanya sudah sama persis
  dengan gudang), jadi delapan salinan tambahan itu tidak membawa informasi apa
  pun — hanya ruang dan kebingungan soal baris mana yang benar.
- **Sebagiannya rusak.** Baris master yang datang lewat feed ditulis dari
  `formatted_data`, dan trigger legacy MEMOTONG kolom: baris `m_barang`
  ber-`kd_sumber=PRAYA` di AMPHOREUS mentok **30 karakter** untuk `nama` DAN
  `keterangan` padahal kedua kolomnya `varchar(50)` dan baris GUDANG mencapai 47.

Modul ini menulis master hanya dari GUDANG, membaca nilainya LANGSUNG dari tabel
asli (bukan dari payload, jadi tidak ada yang terpotong), dan menyediakan
pembersih untuk baris cabang lain yang terlanjur ada.

## Kenapa dibandingkan penuh, bukan diambil yang berubah

Master legacy tidak punya penanda perubahan sama sekali: `m_barang` hanya punya
`tanggal_daftar` (tanggal pendaftaran, tidak bergerak saat barang diedit) dan
`m_barang_satuan` tidak punya kolom waktu apa pun. Jadi satu-satunya cara jujur
adalah membaca kedua sisi dan membandingkannya. Katalognya ~55rb barang; sekali
sehari, dan hanya baris yang benar-benar beda yang ditulis.

## Skema tidak berubah

Kolom `kd_sumber` tetap ada dan tetap memimpin PK tiap tabel master. Yang berubah
hanya siapa yang mengisinya. `init_hub` memang tidak pernah ALTER/DROP tabel yang
sudah berisi data — menyesuaikan skema berisi data adalah keputusan manusia.
"""
from __future__ import annotations

import pyodbc

from apps.inventory.services import _k
from apps.transactions.feed_sync import _kolom_tujuan
from apps.transactions.hub_schema import KOL_SUMBER
from apps.transactions.hub_sync import HUB_TABLE_SPECS, SEED_TABLES
from core import mssql

# Satu-satunya `kd_sumber` yang boleh ada di tabel master AMPHOREUS.
SUMBER_MASTER = "GUDANG"


def _kunci(baris: dict, kunci_kol: list[str]) -> tuple:
    """Kunci ternormalisasi. `_k()` wajib: collation SQL Server mengabaikan huruf
    besar-kecil dan spasi ekor, tuple Python tidak. Tanpa ini 'LYG005 ' dan
    'lyg005' terbaca dua barang berbeda dan AMPHOREUS menumpuk kembar."""
    return tuple(_k(baris.get(k)) for k in kunci_kol)


def _muat(cur, tabel: str, kolom: list[str], where: str = "", params=None) -> dict:
    sql = f"SELECT {', '.join(f'[{k}]' for k in kolom)} FROM [{tabel}]"
    if where:
        sql += f" WHERE {where}"
    cur.execute(sql, params or [])
    return [dict(zip(kolom, r)) for r in cur.fetchall()]


def sync_tabel(src_cur, hub_cur, tabel: str, kd_sumber: str = SUMBER_MASTER) -> dict:
    """Satu tabel master: tulis yang beda, sisipkan yang belum ada, hapus yang lenyap."""
    spec = HUB_TABLE_SPECS[tabel]
    kunci_kol = spec["key_columns"]
    kol_hub = _kolom_tujuan(hub_cur, tabel)
    kol_src = set(_kolom_tujuan(src_cur, tabel))
    boleh = [k for k in kol_hub if k != KOL_SUMBER and k in kol_src]

    hilang = [k for k in kunci_kol if k not in boleh]
    if hilang:
        # Kunci yang menyempit harus jadi kegagalan terlihat, bukan WHERE yang
        # melebar: satu UPDATE berkunci separuh akan menimpa seluruh baris
        # sekerabat. Pelajaran yang sama sudah dibayar `feed_sync._kunci_lengkap`.
        raise RuntimeError(f"{tabel}: kolom kunci {hilang} tak ada di kedua sisi")

    sumber = _muat(src_cur, tabel, boleh)
    tujuan = _muat(hub_cur, tabel, boleh, f"[{KOL_SUMBER}] = ?", [kd_sumber])
    peta_tujuan = {_kunci(b, kunci_kol): b for b in tujuan}

    hasil = {"tabel": tabel, "baru": 0, "ubah": 0, "hapus": 0, "sama": 0}
    lain = [k for k in boleh if k not in kunci_kol]
    terlihat = set()

    # Baris baru dikumpulkan dulu, disisipkan sekali dengan `executemany`.
    # Menyisipkan per baris berarti satu round-trip per baris — 196.000 untuk
    # katalog penuh, dan lewat Tailscale yang me-relay ke Singapura itu belasan
    # menit untuk pekerjaan yang seharusnya di bawah satu menit. Pelajaran yang
    # sama sudah dibayar `hub_pull._salin_header`.
    #
    # UPDATE dan DELETE tetap per baris: jumlahnya kecil (pada sapuan penuh
    # pertama: 15 update, 0 hapus dari 196.000 baris) dan tiap barisnya punya
    # WHERE sendiri, jadi tidak ada yang bisa dibatch tanpa menebak.
    antre_baru = []
    for baris in sumber:
        kk = _kunci(baris, kunci_kol)
        terlihat.add(kk)
        lama = peta_tujuan.get(kk)
        if lama is None:
            antre_baru.append([kd_sumber] + [baris[k] for k in boleh])
            hasil["baru"] += 1
            continue
        if all(lama[k] == baris[k] for k in lain):
            hasil["sama"] += 1
            continue
        hub_cur.execute(
            f"UPDATE [{tabel}] SET {', '.join(f'[{k}] = ?' for k in lain)} "
            f"WHERE [{KOL_SUMBER}] = ? AND " + " AND ".join(f"[{k}] = ?" for k in kunci_kol),
            [baris[k] for k in lain] + [kd_sumber] + [baris[k] for k in kunci_kol],
        )
        hasil["ubah"] += 1

    if antre_baru:
        hub_cur.executemany(
            f"INSERT INTO [{tabel}] ([{KOL_SUMBER}], {', '.join(f'[{k}]' for k in boleh)}) "
            f"VALUES ({', '.join('?' * (len(boleh) + 1))})",
            antre_baru,
        )

    for kk, baris in peta_tujuan.items():
        if kk in terlihat:
            continue
        hub_cur.execute(
            f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] = ? AND "
            + " AND ".join(f"[{k}] = ?" for k in kunci_kol),
            [kd_sumber] + [baris[k] for k in kunci_kol],
        )
        hasil["hapus"] += 1
    return hasil


def sync_master(source, hub, tabel_saja=None, dry_run: bool = False) -> dict:
    """Seluruh katalog GUDANG -> AMPHOREUS. Satu transaksi; katalog setengah tertulis
    lebih buruk daripada katalog basi."""
    daftar = [t for t in SEED_TABLES if not tabel_saja or t in tabel_saja]
    hasil = {"source": source.name, "status": "ok", "tabel": [], "error": ""}
    try:
        with mssql.cursor(source) as src_cur, mssql.cursor(hub, autocommit=False) as hub_cur:
            for tabel in daftar:
                hasil["tabel"].append(sync_tabel(src_cur, hub_cur, tabel))
            if dry_run:
                hub_cur.connection.rollback()
                hasil["status"] = "dry_run"
            else:
                hub_cur.connection.commit()
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["status"] = "failed"
        hasil["error"] = str(exc.args[-1] if exc.args else exc)
    return hasil


def purge_lain(hub, dry_run: bool = True) -> dict:
    """Hapus baris master ber-`kd_sumber` selain GUDANG.

    Default `dry_run=True` — kebalikan dari fungsi lain di repo ini, dan disengaja.
    Ini satu-satunya fungsi di seluruh jalur sync yang menghapus data tanpa
    menyalin ulang penggantinya, dan yang dihapus mencakup baris `m_barang`
    delapan cabang. Yang memanggilnya harus MEMINTA penghapusan itu, bukan
    mendapatkannya karena lupa memberi flag.
    """
    hasil = {"status": "dry_run" if dry_run else "ok", "tabel": [], "error": ""}
    try:
        with mssql.cursor(hub, autocommit=False) as cur:
            for tabel in SEED_TABLES:
                cur.execute(
                    f"SELECT [{KOL_SUMBER}], COUNT(*) FROM [{tabel}] "
                    f"WHERE [{KOL_SUMBER}] <> ? GROUP BY [{KOL_SUMBER}]",
                    [SUMBER_MASTER],
                )
                per_sumber = {r[0]: int(r[1]) for r in cur.fetchall()}
                if per_sumber and not dry_run:
                    cur.execute(
                        f"DELETE FROM [{tabel}] WHERE [{KOL_SUMBER}] <> ?", [SUMBER_MASTER]
                    )
                hasil["tabel"].append({"tabel": tabel, "per_sumber": per_sumber,
                                       "total": sum(per_sumber.values())})
            if dry_run:
                cur.connection.rollback()
            else:
                cur.connection.commit()
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["status"] = "failed"
        hasil["error"] = str(exc.args[-1] if exc.args else exc)
    return hasil

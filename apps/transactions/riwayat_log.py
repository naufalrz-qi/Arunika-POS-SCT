"""Riwayat satu dokumen legacy, dibangun ulang dari tbl_log_transaksi.

Dipakai panel detail Nota Tanggal Mundur. Tabel dokumennya sendiri hanya
menyimpan versi TERAKHIR — dan versi itu menyesatkan: saat diedit, legacy
menimpa `tanggal_server` dan `kd_user` dengan waktu dan akun pengedit (lihat
catatan di `reports.nota_mundur`). Log trigger menyimpan setiap versi utuh,
jadi dari sanalah "siapa membuat, siapa mengubah apa, kapan" dijawab.

Bentuk jejak yang dipakai di sini, terbaca dari definisi trigger legacy:

- Header: `<tabel>__insert` (payload `val__…` seluruh kolom) dan
  `<tabel>__update` (`key__<no>__X;` lalu seluruh kolom versi baru).
- Detail: `<tabel_detail>__insert`, `<tabel_detail>__update`, dan untuk hapus
  `table_aksi` = nama tabel POLOS. Itu cacat di trigger legacy —
  `'t_penjualan_detail'__delete` dibaca SQL Server sebagai literal diikuti
  ALIAS kolom, jadi sufiksnya hilang. Baris hapus hanya membawa kolom kunci.
- Edit nota di legacy = UPDATE header, lalu hapus SEMUA baris barang dan
  insert ulang. Baris barang itu tercatat SESUDAH baris header-nya (id lebih
  besar), jadi tiap baris barang milik peristiwa header terakhir sebelum dia.

Butuh index `reports.LOG_INDEX`; tanpa index, setiap kueri di sini men-scan
seluruh tabel log (jutaan baris). Pemanggil wajib memeriksanya dulu.
"""
import datetime as dt

from apps.inventory.services import _k
from apps.transactions.feed_sync import parse_formatted_data
from core import mssql

# Kolom yang TIDAK dipajang sebagai "perubahan": `tanggal_server` dan `kd_user`
# SELALU berubah saat edit (itu justru inti masalahnya) dan sudah tampil
# sebagai "kapan" dan "oleh"; `divisi_id` adalah penanda asal milik trigger.
# `tanggal_setor` diisi ulang OLEH APLIKASI setiap nota disimpan (= tanggal
# nota − 1 hari, jam nota) — berubah di 227 dari 314 edit di grosirPusat 2025+,
# bukan karena ada yang mengetiknya. Memajangnya membuat tiap edit tampak
# mengubah sesuatu yang tak disentuh siapa pun.
_BUKAN_PERUBAHAN = {"tanggal_server", "kd_user", "divisi_id", "tanggal_setor"}

# Detail yang riwayat barangnya bisa diputar ulang: (tabel, kolom kunci baris).
# Kuncinya persis kolom `key__` di trigger hapus/update tabel itu — dengan kunci
# lain, baris hapus tak akan menemukan baris yang dihapusnya.
DETAIL = {
    "t_penjualan": ("t_penjualan_detail", ("kd_barang", "kd_satuan", "kd_pegawai", "jenis")),
}

# Jendela di sekitar satu peristiwa header tempat baris barangnya dicari.
# Terukur di PUSAT: baris barang menyusul header dalam hitungan detik.
_SEBELUM, _SESUDAH = dt.timedelta(minutes=1), dt.timedelta(minutes=10)


# Batas rantai nomor lama yang ditelusuri. Nomor berganti setiap kali tanggal
# diubah lewat edit; lebih dari sekali pun sudah jarang.
_MAKS_NOMOR = 5


def _log(cur, aksi: str, kunci: tuple, dari, sampai=None, berisi: str | None = None) -> list:
    """Baris log `aksi` milik dokumen ini: payload diawali salah satu `kunci`,
    atau (untuk update) memuat `berisi` — `;val__<no>__X;` letaknya sesudah
    nomor lama, jadi tak bisa dicocokkan sebagai awalan."""
    syarat = ["LEFT(formatted_data, ?) = ?" for _ in kunci]
    params = [aksi, dari]
    batas = ""
    if sampai is not None:
        batas = "AND waktu < ? "
        params.append(sampai)
    for k in kunci:
        params += [len(k), k]
    if berisi:
        syarat.append("CHARINDEX(?, formatted_data) > 0")
        params.append(berisi)
    mssql.execute_varchar(
        cur,
        "SELECT id, waktu, formatted_data FROM tbl_log_transaksi "
        f"WHERE table_aksi = ? AND waktu >= ? {batas}AND ({' OR '.join(syarat)}) ORDER BY id",
        params,
    )
    return cur.fetchall()


def tanggal_nomor(no: str):
    """Tanggal yang tersimpan di nomor dokumen (awalan + YYMMDD + urut 4), atau
    None. Kembaran Python dari `reports._tanggal_nomor`."""
    try:
        return dt.datetime.strptime("20" + no[-10:-4], "%Y%m%d")
    except (TypeError, ValueError):
        return None


def _baris(isi: dict, kunci: tuple) -> tuple:
    # `str()` dulu: `jenis` adalah tinyint di tabel tapi teks di payload log,
    # dan 1 != "1" akan membuat setiap baris sekarang tampak tak tercatat.
    return tuple(_k(str(isi.get(c, ""))) for c in kunci)


def _putar_barang(cur, tabel_detail: str, kunci: tuple, no_kol: str, peristiwa: list) -> list[dict]:
    """Isi barang SESUDAH tiap peristiwa header, hasil memutar ulang log detail.

    Nomor dicari PER PERISTIWA: nota yang tanggalnya dipindah lewat edit
    tercatat dengan nomor lama sebelum edit itu dan nomor baru sesudahnya.
    """
    baris = {}
    for p in peristiwa:
        nomor = {p["nomor"], p.get("nomor_lama") or p["nomor"]}
        # Bentuk kedua milik trigger insert detail di GUDANG, yang menulis
        # kolom nomor DUA kali dan yang pertama kosong: `val__no_transaksi__;
        # val__no_transaksi__GP…;`. Tanpa ini setiap nota GUDANG tampak tak
        # berbarang.
        ins = tuple(x for n in nomor for x in (f"val__{no_kol}__{n};", f"val__{no_kol}__;val__{no_kol}__{n};"))
        kun = tuple(f"key__{no_kol}__{n};" for n in nomor)
        dari, sampai = p["waktu"] - _SEBELUM, p["waktu"] + _SESUDAH
        for aksi, pola, jenis in ((f"{tabel_detail}__insert", ins, "insert"),
                                  (f"{tabel_detail}__update", kun, "update"),
                                  (tabel_detail, kun, "delete")):
            for id_, _w, fd in _log(cur, aksi, pola, dari, sampai):
                baris[id_] = (jenis, fd)

    ids = [p["id"] for p in peristiwa]
    isi, potret, i = {}, [], 0
    for id_ in sorted(baris):
        # Baris barang milik peristiwa header terakhir SEBELUM dia.
        while i + 1 < len(ids) and ids[i + 1] < id_:
            potret.append(dict(isi))
            i += 1
            # Nota yang dibuat ulang dengan nomor sama mulai dari kosong: hapus
            # header lamanya tak selalu tercatat (GUDANG tak punya trigger hapus
            # t_penjualan), jadi barang lamanya tak boleh terbawa.
            if peristiwa[i]["aksi"] != "Diedit":
                isi = {}
        jenis, fd = baris[id_]
        k, v = parse_formatted_data(fd)
        if jenis == "insert":
            isi[_baris(v, kunci)] = v
        elif jenis == "update":
            isi.pop(_baris(k, kunci), None)
            isi[_baris(v, kunci)] = v
        else:
            isi.pop(_baris(k, kunci), None)
    while len(potret) < len(ids):
        potret.append(dict(isi))
    return potret


def _angka(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ringkas(v: dict) -> dict:
    return {"kd_barang": (v.get("kd_barang") or "").strip(), "kd_satuan": (v.get("kd_satuan") or "").strip(),
            "qty": _angka(v.get("qty")), "harga_jual": _angka(v.get("harga_jual"))}


def _selisih_barang(sebelum: dict, sesudah: dict) -> dict:
    ditambah = [_ringkas(v) for k, v in sesudah.items() if k not in sebelum]
    dihapus = [_ringkas(v) for k, v in sebelum.items() if k not in sesudah]
    diubah = []
    for k in sebelum.keys() & sesudah.keys():
        a, b = _ringkas(sebelum[k]), _ringkas(sesudah[k])
        if (a["qty"], a["harga_jual"]) != (b["qty"], b["harga_jual"]):
            diubah.append({**b, "qty_dari": a["qty"], "harga_jual_dari": a["harga_jual"]})
    return {"ditambah": ditambah, "dihapus": dihapus, "diubah": diubah}


def riwayat(cur, tabel: str, no_kol: str, no: str, tanggal, tanggal_server) -> dict:
    """Seluruh versi dokumen `no` yang tercatat di log, terlama dulu.

    Insert dicari di dua jendela sempit — sekitar `tanggal` (jam PC saat dibuat)
    dan sekitar `tanggal_server` (untuk yang diinput mundur) — bukan di seluruh
    rentang di antaranya: nota yang diedit 200 hari kemudian akan menyeret 200
    hari baris insert. Update dicari sejak insert pertama sampai sekarang;
    update jarang (±300 setahun per tabel di PUSAT), jadi itu murah.

    Nomor yang berganti diikuti mundur: edit yang memindah tanggal menomori
    ulang dokumennya (`key__<no>__LAMA; val__<no>__BARU;`), dan seluruh riwayat
    sebelum edit itu — termasuk siapa yang membuatnya — tercatat dengan nomor
    LAMA, di sekitar tanggal yang tersimpan di nomor lama itu.

    `barang` per peristiwa hanya ada untuk tabel di `DETAIL`; selain itu None.
    """
    satu_hari = dt.timedelta(days=1)
    rows, antre, dilihat = {}, [(no, tanggal, tanggal_server)], set()
    while antre and len(dilihat) < _MAKS_NOMOR:
        nomor, jangkar, jangkar_simpan = antre.pop(0)
        if nomor in dilihat:
            continue
        dilihat.add(nomor)
        jendela = [(jangkar - satu_hari, jangkar + satu_hari)]
        if jangkar_simpan:
            jendela.append((jangkar_simpan - dt.timedelta(seconds=5), jangkar_simpan + satu_hari))
        sisipan = {}
        for dari, sampai in jendela:
            for r in _log(cur, f"{tabel}__insert", (f"val__{no_kol}__{nomor};",), dari, sampai):
                sisipan[r[0]] = r
        rows.update(sisipan)
        mulai = min([r[1] for r in sisipan.values()] + [jangkar - satu_hari])
        for r in _log(cur, f"{tabel}__update", (), mulai, berisi=f";val__{no_kol}__{nomor};"):
            rows[r[0]] = r
            k, _ = parse_formatted_data(r[2])
            lama = (k.get(no_kol) or "").strip()
            if lama and lama != nomor:
                antre.append((lama, tanggal_nomor(lama) or jangkar, None))

    peristiwa, sebelum = [], None
    for id_, waktu, fd in sorted(rows.values(), key=lambda r: r[0]):
        k, v = parse_formatted_data(fd)
        aksi = "Diedit" if fd.startswith("key__") else ("Dibuat ulang" if peristiwa else "Dibuat")
        perubahan = []
        if sebelum is not None and aksi == "Diedit":
            # Termasuk kolom nomor: nomor yang berganti adalah tanda tanggal
            # dipindah, dan tanggalnya sendiri ikut tampil sebagai perubahan.
            for kol, ke in v.items():
                if kol not in _BUKAN_PERUBAHAN and (sebelum.get(kol) or "").strip() != (ke or "").strip():
                    perubahan.append({"kolom": kol, "dari": (sebelum.get(kol) or "").strip(), "ke": (ke or "").strip()})
        nomor = (v.get(no_kol) or "").strip()
        peristiwa.append({"id": id_, "waktu": waktu, "aksi": aksi, "kd_user": (v.get("kd_user") or "").strip(),
                          "tanggal": (v.get("tanggal") or "").strip(), "perubahan": perubahan,
                          "nomor": nomor, "nomor_lama": (k.get(no_kol) or "").strip() or nomor})
        sebelum = v

    if tabel in DETAIL and peristiwa:
        tabel_detail, kunci = DETAIL[tabel]
        potret = _putar_barang(cur, tabel_detail, kunci, no_kol, peristiwa)
        for i, p in enumerate(peristiwa):
            if p["aksi"] != "Diedit":
                p["barang"] = {"isi": [_ringkas(v) for v in potret[i].values()]}
            elif i:
                p["barang"] = _selisih_barang(potret[i - 1], potret[i])
            # Edit tanpa insert tercatat sebelumnya (log dipangkas): isi
            # sebelumnya tak diketahui, jadi tak ada selisih yang jujur.
        akhir = {k: _angka(v.get("qty")) for k, v in potret[-1].items()}
    else:
        akhir = None
    for p in peristiwa:
        p.setdefault("barang", None)
        # `log_id` tetap dibawa: Jejak Audit mencocokkannya dengan rentang log
        # yang dicatat Edit Nota Arunika, supaya satu edit tak tampil dua kali.
        p["log_id"] = p.pop("id")
        del p["nomor_lama"]
    return {"peristiwa": peristiwa, "barang_akhir": akhir}


def cocok_dengan_sekarang(barang_akhir: dict | None, barang_sekarang: list[dict], kunci: tuple) -> bool | None:
    """Apakah hasil putar ulang log sama dengan isi nota sekarang?

    Kalau tidak, ada perubahan barang yang tak meninggalkan jejak di jendela
    peristiwa header (atau log sudah dipangkas) — panel harus mengatakannya,
    bukan memajang riwayat yang tak lengkap seolah utuh.
    """
    if barang_akhir is None:
        return None
    sekarang = {_baris(r, kunci): _angka(r.get("qty")) for r in barang_sekarang}
    return sekarang == barang_akhir

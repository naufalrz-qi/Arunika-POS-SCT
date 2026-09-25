"""Edit nota penjualan — bentuk tulisannya ke server legacy.

Tak ada server legacy di test, jadi yang dijaga BENTUK SQL-nya (pola
`test_pembelian_order.py`). Yang paling mahal kalau bergeser:

1. **Satu-satunya DELETE** adalah `DELETE TOP (1) FROM t_penjualan_detail`
   milik nota itu. DELETE ke tabel lain — terutama `t_penjualan`, yang merambat
   ke cicilan dan tagihan — tak boleh pernah muncul.
2. **Urutan legacy**: kepala di-UPDATE sebelum baris barang disentuh. Kalau
   terbalik, `riwayat_log` memasangkan baris barang ke peristiwa yang salah dan
   Nota Tanggal Mundur menampilkan riwayat yang keliru — tanpa galat.
3. **Satu baris per execute** untuk tabel bertrigger stok skalar.
4. `tanggal`, `kd_divisi`, `status`, dan nomor tak pernah ikut di-SET.
5. Setiap penghalang menolak SEBELUM satu tulisan pun terkirim.
"""
import datetime as dt
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import edit_nota as en
from apps.transactions import penjualan as pj

NO = "SC2609100001"
TGL = dt.datetime(2026, 9, 10, 10, 33, 0)


def _kepala(**kw):
    k = {"no_transaksi": NO, "kd_customer": "CAA000", "kd_divisi": "DAA000", "kd_jenis": "JAA000",
         "kd_kas": "KAA001", "kd_voucher": "VAA000", "no_bukti": "-", "tanggal": TGL,
         "tanggal_jatuh_tempo": dt.datetime(2026, 10, 10, 10, 33, 0), "status": 1,
         "diskon1": 0, "diskon2": 0, "diskon3": 0, "diskon4": 0, "diskon_uang": 0, "pajak": 0,
         "keterangan": "-", "kd_user": "UAA001", "tanggal_server": TGL}
    k.update(kw)
    return k


def _baris(kd_barang, qty, harga, kd_satuan="SAA000", jenis=1, point1=0.0, **kw):
    b = {"kd_barang": kd_barang, "kd_satuan": kd_satuan, "kd_pegawai": "PAA000", "jenis": jenis,
         "diskon1": 0, "diskon2": 0, "diskon3": 0, "diskon4": 0, "harga_jual": harga, "qty": qty,
         "point1": point1, "point2": 0.0}
    b.update(kw)
    return b


class FakeCur:
    """Cursor yang menjawab kueri edit_nota dari keadaan di memori."""

    def __init__(self, kepala=None, baris=None, *, tutup=dt.datetime(2025, 12, 31), base=None,
                 cicilan=0, tagihan=0, kepala_nota="SC", total=50000.0, berindex=True,
                 satuan=(("1001", "SAA000"), ("1002", "SAA000"), ("1002", "SAA001"))):
        self.kepala = kepala if kepala is not None else _kepala()
        self.baris = list(baris if baris is not None else
                          [_baris("1001", 2, 10000, jenis=3, point1=5.0), _baris("1002", 3, 10000)])
        self.tutup, self.base, self.cicilan, self.tagihan = tutup, base, cicilan, tagihan
        self.kepala_nota, self.total, self.satuan = kepala_nota, total, set(satuan)
        self.berindex = berindex
        self.log, self._hasil = [], []
        self.connection = None  # diisi _jalankan dengan _Conn

    # pyodbc
    def setinputsizes(self, _):
        pass

    def fetchone(self):
        return self._hasil[0] if self._hasil else None

    def fetchall(self):
        return list(self._hasil)

    def execute(self, sql, params=()):
        self.log.append((sql, list(params)))
        s = " ".join(sql.split())
        self._hasil = self._jawab(s, list(params))
        return self

    def _jawab(self, s, p):
        if s.startswith("SELECT no_transaksi, kd_customer"):
            return [tuple(self.kepala[c] for c in en._KEPALA)] if self.kepala else []
        if s.startswith("SELECT kd_barang, kd_satuan, kd_pegawai"):
            return [tuple(b[c] for c in en._BARIS) for b in self.baris]
        if "FROM sys.index_columns" in s:
            return [(1 if self.berindex else 0,)]
        if "FROM g_tutup_buku" in s:
            return [(self.tutup,)]
        if s.startswith("SELECT OBJECT_ID"):
            return [(1 if self.base else None,)]
        if "FROM pos_stok_snapshot_base" in s:
            return [(self.base,)]
        if "FROM t_piutang_cicilan" in s:
            return [(self.cicilan,)]
        if "FROM t_tagihan_detail" in s:
            return [(self.tagihan,)]
        if "kepala_nota FROM m_divisi" in s:
            return [(self.kepala_nota,)]
        if s.startswith("SELECT total FROM t_penjualan_total"):
            return [(self.total,)] if self.total is not None else []
        if "FROM tbl_log_transaksi" in s:
            return [(100 + len(self.log),)]
        if s.startswith("SELECT COUNT(*) FROM t_penjualan_detail"):
            return [(len(self.baris),)]
        if s.startswith("SELECT tanggal_server FROM t_penjualan"):
            return [(dt.datetime(2026, 9, 25, 9, 0, 0),)]
        if "FROM m_barang_satuan" in s:
            return sorted(self.satuan)
        if s.startswith("SELECT COUNT(*) FROM m_"):
            return [(1,)]
        if " IN (" in s and s.startswith("SELECT kd_"):
            return [(k, f"nama {k}") for k in p]
        if s.startswith("SELECT nama FROM"):
            return [("NAMA",)]
        if s.startswith("DELETE TOP (1) FROM t_penjualan_detail"):
            self.baris.pop(0)
            return []
        return []


class _Conn:
    def __init__(self, cur):
        self.cur = cur
        self.commits = 0

    def commit(self):
        self.commits += 1


def _jalankan(cur, perubahan=None, items=None, versi_layar=None, **kw):
    conn = _Conn(cur)
    cur.connection = conn

    @contextmanager
    def palsu(*a, **k):
        yield cur

    if versi_layar is None:
        versi_layar = en.versi(en._norm_kepala(cur.kepala), [en._norm_baris(b) for b in cur.baris])
    if items is None:
        items = [{"kd_barang": "1001", "kd_satuan": "SAA000", "qty": 5, "harga_jual": 10000},
                 {"kd_barang": "1002", "kd_satuan": "SAA000", "qty": 3, "harga_jual": 10000}]
    with patch("core.mssql.cursor", palsu):
        hasil = en.ubah_nota(object(), NO, kd_user="UAA009", perubahan=perubahan or {},
                             items=items, versi_layar=versi_layar, **kw)
    return hasil, conn


def _tulisan(cur):
    return [(" ".join(s.split()), p) for s, p in cur.log
            if s.lstrip().split()[0].upper() in ("INSERT", "UPDATE", "DELETE")]


class BentukTulisTests(SimpleTestCase):
    def test_urutan_legacy_kepala_dulu_lalu_hapus_lalu_insert_lalu_total(self):
        cur = FakeCur()
        _jalankan(cur)
        jenis = [s.split(" FROM ")[0].split(" (")[0] if s.startswith("DELETE") else " ".join(s.split()[:3])
                 for s, _ in _tulisan(cur)]
        self.assertEqual(jenis, [
            "UPDATE t_penjualan SET",
            "DELETE TOP", "DELETE TOP",
            "INSERT INTO t_penjualan_detail", "INSERT INTO t_penjualan_detail",
            "UPDATE t_penjualan_total SET",
        ])

    def test_satu_satunya_delete_adalah_baris_detail_nota_ini(self):
        cur = FakeCur()
        _jalankan(cur)
        hapus = [(s, p) for s, p in _tulisan(cur) if s.startswith("DELETE")]
        self.assertTrue(hapus)
        for s, p in hapus:
            self.assertEqual(s, "DELETE TOP (1) FROM t_penjualan_detail WHERE no_transaksi = ?")
            self.assertEqual(p, [NO])

    def test_satu_baris_per_insert(self):
        cur = FakeCur()
        _jalankan(cur)
        for s, p in _tulisan(cur):
            if s.startswith("INSERT INTO t_penjualan_detail"):
                self.assertEqual(s.count("VALUES ("), 1)
                self.assertEqual(len(p), len(pj._DETAIL))

    def test_kolom_terlarang_tak_pernah_diset(self):
        cur = FakeCur()
        _jalankan(cur, perubahan={"tanggal": "2020-01-01", "kd_divisi": "DXX", "status": 0,
                                  "no_transaksi": "XX"})
        upd = next(s for s, _ in _tulisan(cur) if s.startswith("UPDATE t_penjualan SET"))
        bagian_set = upd.split(" SET ")[1].split(" WHERE ")[0]
        bebas = (bagian_set.replace("tanggal_jatuh_tempo", "").replace("tanggal_server", "")
                 .replace("tanggal_setor", "").replace("DATEADD(day, -1, tanggal)", ""))
        for kol in ("tanggal =", "kd_divisi", "status", "no_transaksi", "diskon1"):
            self.assertNotIn(kol, bebas)

    def test_tanggal_setor_hanya_diisi_bila_kosong(self):
        # Trigger legacy merangkai tanggal_setor ke payload sync dengan `+`:
        # NULL di sana membuat seluruh payload NULL. Nilai yang ada tak disentuh.
        cur = FakeCur()
        _jalankan(cur)
        upd = next(s for s, _ in _tulisan(cur) if s.startswith("UPDATE t_penjualan SET"))
        self.assertIn("tanggal_setor = COALESCE(tanggal_setor, DATEADD(day, -1, tanggal))", upd)

    def test_pengedit_dan_jam_server_ditulis_seperti_legacy(self):
        cur = FakeCur()
        hasil, _ = _jalankan(cur)
        upd, p = next((s, p) for s, p in _tulisan(cur) if s.startswith("UPDATE t_penjualan SET"))
        self.assertIn("kd_user = ?, tanggal_server = GETDATE()", upd)
        self.assertEqual(p[-2:], ["UAA009", NO])
        self.assertEqual(hasil["sebelum"]["kepala"]["kd_user"], "UAA001")
        self.assertEqual(hasil["sesudah"]["kepala"]["kd_user"], "UAA009")

    def test_commit_sekali_sesudah_semua_tulisan(self):
        cur = FakeCur()
        _, conn = _jalankan(cur)
        self.assertGreaterEqual(conn.commits, 1)


class NilaiTests(SimpleTestCase):
    def test_total_memakai_rumus_nota(self):
        cur = FakeCur()
        items = [{"kd_barang": "1001", "kd_satuan": "SAA000", "qty": 2, "harga_jual": 12000,
                  "diskon1": 0.1}]
        hasil, _ = _jalankan(cur, items=items, perubahan={"diskon_uang": 500, "pajak": 0.1})
        self.assertAlmostEqual(hasil["sesudah"]["total"],
                               pj.total_nota([{"harga_jual": 12000, "qty": 2, "diskon1": 0.1}],
                                             (0, 0, 0, 0), 500, 0.1))
        upd = next(p for s, p in _tulisan(cur) if s.startswith("UPDATE t_penjualan_total"))
        self.assertAlmostEqual(upd[0], hasil["sesudah"]["total"])

    def test_nota_tanpa_baris_total_dibuatkan(self):
        cur = FakeCur(total=None)
        hasil, _ = _jalankan(cur)
        self.assertTrue(hasil["total_dibuat"])
        self.assertTrue(any(s.startswith("INSERT INTO t_penjualan_total") for s, _ in _tulisan(cur)))
        self.assertFalse(any(s.startswith("UPDATE t_penjualan_total") for s, _ in _tulisan(cur)))

    def test_jenis_dan_point_dibawa_dari_baris_lama(self):
        cur = FakeCur()
        items = [{"kd_barang": "1001", "kd_satuan": "SAA000", "qty": 9, "harga_jual": 10000},
                 {"kd_barang": "1002", "kd_satuan": "SAA001", "qty": 1, "harga_jual": 120000}]
        hasil, _ = _jalankan(cur, items=items)
        lama, baru = hasil["sesudah"]["baris"]
        self.assertEqual((lama["jenis"], lama["point1"]), (3, 5.0))
        self.assertEqual((baru["jenis"], baru["point1"]), (pj.JENIS_BARIS, 0.0))
        # Pegawai baris baru dari baris lama pertama, bukan kosong (NOT NULL).
        self.assertEqual(baru["kd_pegawai"], "PAA000")

    def test_jatuh_tempo_tanggal_sama_jam_lama_dipertahankan(self):
        cur = FakeCur()
        hasil, _ = _jalankan(cur, perubahan={"tanggal_jatuh_tempo": "2026-10-10"})
        kolom = {d["kolom"] for d in hasil["selisih"]["kepala"]}
        self.assertNotIn("tanggal_jatuh_tempo", kolom)

    def test_rentang_log_tercatat(self):
        hasil, _ = _jalankan(FakeCur())
        dari, sampai = hasil["log_id"]
        self.assertLess(dari, sampai)


class PenolakanTests(SimpleTestCase):
    def _ditolak(self, cur, pesan, **kw):
        with self.assertRaises(en.NotaDitolak) as e:
            _jalankan(cur, **kw)
        self.assertIn(pesan, str(e.exception))
        self.assertEqual(_tulisan(cur), [], "penolakan harus terjadi sebelum tulisan apa pun")

    def test_tanpa_index_detail(self):
        self._ditolak(FakeCur(berindex=False), "belum punya index nomor nota")

    def test_detail_tak_dikunci_rentang(self):
        # HOLDLOCK di detail tanpa index = seluruh tabel terkunci selama edit.
        cur = FakeCur()
        _jalankan(cur)
        for s, _ in cur.log:
            if "FROM t_penjualan_detail" in s and s.lstrip().upper().startswith("SELECT"):
                self.assertNotIn("HOLDLOCK", s)

    def test_sebelum_tutup_buku(self):
        self._ditolak(FakeCur(tutup=dt.datetime(2026, 9, 30)), "tutup buku")

    def test_sebelum_snapshot_dasar(self):
        self._ditolak(FakeCur(base=dt.datetime(2026, 9, 30)), "snapshot stok dasar")

    def test_punya_cicilan(self):
        self._ditolak(FakeCur(cicilan=1), "cicilan piutang")

    def test_masuk_tagihan(self):
        self._ditolak(FakeCur(tagihan=2), "tagihan")

    def test_salinan_server_lain(self):
        self._ditolak(FakeCur(kepala_nota="CT"), "bukan buatan divisi")

    def test_nota_tak_ada(self):
        cur = FakeCur(kepala={})
        with self.assertRaises(en.NotaDitolak):
            _jalankan(cur, versi_layar="x")
        self.assertEqual(_tulisan(cur), [])

    def test_versi_berubah(self):
        cur = FakeCur()
        with self.assertRaises(en.VersiBerubah):
            _jalankan(cur, versi_layar="versi-basi")
        self.assertEqual(_tulisan(cur), [])

    def test_tanpa_perubahan(self):
        items = [{"kd_barang": "1001", "kd_satuan": "SAA000", "qty": 2, "harga_jual": 10000},
                 {"kd_barang": "1002", "kd_satuan": "SAA000", "qty": 3, "harga_jual": 10000}]
        self._ditolak(FakeCur(), "Tidak ada yang berubah", items=items)

    def test_nota_dikosongkan(self):
        self._ditolak(FakeCur(), "dikosongkan", items=[])

    def test_qty_nol(self):
        self._ditolak(FakeCur(), "qty harus lebih dari nol",
                      items=[{"kd_barang": "1001", "kd_satuan": "SAA000", "qty": 0, "harga_jual": 1}])

    def test_satuan_tak_dikenal(self):
        self._ditolak(FakeCur(), "tidak punya satuan",
                      items=[{"kd_barang": "9999", "kd_satuan": "SAA000", "qty": 1, "harga_jual": 1}])

    def test_tanpa_tautan(self):
        cur = FakeCur()
        with self.assertRaises(en.NotaDitolak):
            en.ubah_nota(object(), NO, kd_user="", perubahan={}, items=[], versi_layar="x")
        self.assertEqual(cur.log, [])


class SelisihTests(SimpleTestCase):
    def test_ditambah_dihapus_diubah(self):
        k = en._norm_kepala(_kepala())
        lama = [_baris("A", 1, 100), _baris("B", 1, 100)]
        baru = [_baris("A", 2, 100), _baris("C", 1, 100)]
        s = en.selisih(k, k, lama, baru)
        self.assertEqual([b["kd_barang"] for b in s["barang"]["ditambah"]], ["C"])
        self.assertEqual([b["kd_barang"] for b in s["barang"]["dihapus"]], ["B"])
        self.assertEqual(s["barang"]["diubah"][0]["beda"], {"qty": {"dari": 1, "ke": 2}})

    def test_baris_kembar_tak_saling_menutupi(self):
        k = en._norm_kepala(_kepala())
        lama = [_baris("A", 1, 100), _baris("A", 1, 100)]
        baru = [_baris("A", 1, 100)]
        s = en.selisih(k, k, lama, baru)
        self.assertEqual(len(s["barang"]["dihapus"]), 1)

    def test_kepala_berubah(self):
        lama = en._norm_kepala(_kepala())
        baru = dict(lama, kd_customer="CAA123")
        s = en.selisih(lama, baru, [], [])
        self.assertEqual(s["kepala"], [{"kolom": "kd_customer", "dari": "CAA000", "ke": "CAA123"}])

    def test_versi_tak_bergantung_urutan_baris(self):
        k = en._norm_kepala(_kepala())
        a, b = en._norm_baris(_baris("A", 1, 1)), en._norm_baris(_baris("B", 1, 1))
        self.assertEqual(en.versi(k, [a, b]), en.versi(k, [b, a]))
        self.assertNotEqual(en.versi(k, [a]), en.versi(k, [a, b]))

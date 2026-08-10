"""Koreksi stok — bentuk tulisannya dipaksa oleh trigger legacy, bukan selera.

Yang paling mahal kalau salah dan paling tak terlihat kalau rusak:
`trig_update_stok_opname_stok` membaca `inserted` dengan assignment SKALAR, jadi
satu INSERT berisi banyak baris hanya menggeser stok untuk SATU baris. Barisnya
tetap tercatat, laporannya tetap benar, hanya stoknya yang diam — tak ada galat,
tak ada yang memberi tahu. Karena itu tes pertama di berkas ini menjaga
"satu execute, satu baris", dan ia yang paling penting di sini.

MS SQL tidak disentuh — cursor di-fake dan SQL yang dieksekusi direkam.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import opname as op

ITEMS = [
    {"kd_barang": "000-06", "kd_satuan": "SAA000", "qty": 2, "jenis": "lain_minus"},
    {"kd_barang": "1001", "kd_satuan": "SAA001", "qty": 5, "jenis": "lain_plus"},
    {"kd_barang": "3360C", "kd_satuan": "SAA000", "qty": 1, "jenis": "lain_minus"},
]


class FakeCursor:
    def __init__(self):
        self.sql = []
        self.params = []
        self.connection = self
        self.terakhir = None  # nomor MAX() terakhir, supaya urutannya menaik

    def setinputsizes(self, v):
        pass

    def commit(self):
        pass

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self.params.append(list(params or []))

    def fetchone(self):
        akhir = self.sql[-1]
        if "kepala_nota" in akhir:
            # Awalan mengikuti divisi yang diminta — di gudang tiap divisi punya
            # kepala_nota sendiri (GP/GO/UM), jadi memulangkan satu nilai tetap
            # akan menyembunyikan tepat bug yang dijaga di sini.
            return ("GP",) if self.params[-1] == ["DAA001"] else ("UM",)
        if "COUNT(*) FROM m_divisi" in akhir:
            return (1 if self.params[-1] and self.params[-1][0].startswith("DAA") else 0,)
        if "MAX(" in akhir:
            return (self.terakhir,)
        return (None,)

    # Nomor berikutnya dibaca dari MAX(); INSERT-lah yang memajukannya, persis
    # seperti di database sungguhan.
    def catat_insert(self, no):
        self.terakhir = no


@contextmanager
def _ctx(cur):
    yield cur


def _buat(cur, items=None, **kw):
    dasar = dict(kd_user="UAA002", kd_divisi="DAA001",
                 items=items if items is not None else ITEMS,
                 keterangan="BALANCE STOK RETUR")
    dasar.update(kw)
    asli = cur.execute

    def execute(sql, params=None):
        asli(sql, params)
        if sql.lstrip().upper().startswith("INSERT INTO T_OPNAME_STOK"):
            cur.catat_insert(params[cur_kolom_no()])

    def cur_kolom_no():
        return op.KOLOM.index("no_transaksi")

    cur.execute = execute
    with patch.object(op.mssql, "cursor", lambda *a, **k: _ctx(cur)):
        return op.buat_koreksi(object(), **dasar)


def _insert(cur):
    return [(q, p) for q, p in zip(cur.sql, cur.params)
            if q.startswith("INSERT INTO t_opname_stok")]


def _nilai(params, kolom):
    return params[op.KOLOM.index(kolom)]


class SatuBarisPerInsertTests(SimpleTestCase):
    def test_tiga_item_jadi_tiga_insert_satu_baris(self):
        """Trigger stoknya skalar: multi-baris berarti stok diam diam-diam."""
        cur = FakeCursor()
        hasil = _buat(cur)
        ins = _insert(cur)
        self.assertEqual(len(ins), 3, "tiap item wajib punya execute sendiri")
        for sql, _ in ins:
            self.assertEqual(sql.count("VALUES"), 1)
            # Satu tuple nilai saja — "VALUES (…), (…)" adalah bentuk yang
            # membuat trigger melewatkan baris.
            self.assertNotIn("), (", sql)
        self.assertEqual(hasil["baris"], 3)

    def test_tiap_baris_dapat_nomornya_sendiri_dan_menaik(self):
        cur = FakeCursor()
        hasil = _buat(cur)
        self.assertEqual(len(set(hasil["nomor"])), 3, "nomor tak boleh dipakai ulang")
        self.assertEqual(hasil["nomor"], sorted(hasil["nomor"]))
        for no in hasil["nomor"]:
            self.assertTrue(no.startswith("GP"), no)  # awalan divisi yang DIPILIH
            self.assertEqual(len(no), 12)             # GP + YYMMDD + NNNN


class BentukBarisTests(SimpleTestCase):
    def test_jenis_dipetakan_ke_status_menurut_view_legacy(self):
        """Angkanya bukan pilihan kita — view `mon_t_opname_stok` yang memberi
        nama: 0 Hilang, 1 Rusak, 2 Lain-Lain(+), 3 Lain-Lain(−)."""
        self.assertEqual(op.JENIS, {"hilang": 0, "rusak": 1,
                                    "lain_plus": 2, "lain_minus": 3})

    def test_hanya_lain_plus_yang_menambah_stok(self):
        """Trigger: `IF @status <> 2 SET @jumlah = @jumlah * -1`. Jadi Hilang,
        Rusak, dan Lain-Lain(−) sama-sama mengurangi — arah tak boleh jadi
        pilihan terpisah, atau "Rusak, stok bertambah" jadi mungkin."""
        self.assertEqual(op.JENIS[op.MENAMBAH], 2)
        for jenis in ("hilang", "rusak", "lain_minus"):
            self.assertNotEqual(op.JENIS[jenis], 2, jenis)

    def test_status_yang_ditulis_ikut_jenis_tiap_baris(self):
        cur = FakeCursor()
        _buat(cur)
        status = [_nilai(p, "status") for _, p in _insert(cur)]
        self.assertEqual(status, [op.LAIN_MINUS, op.LAIN_PLUS, op.LAIN_MINUS])

    def test_status_4_tak_pernah_ditulis(self):
        """Ia ada di data lama (1 baris di PAGESANGAN) tapi tak punya label di
        view legacy sama sekali — sampah, bukan jenis kelima."""
        self.assertNotIn(4, op.JENIS.values())

    def test_tanggal_server_ikut_ditulis(self):
        """Kolomnya tak punya default; 0 dari 4.917 baris lama bernilai NULL."""
        cur = FakeCursor()
        _buat(cur)
        for _, p in _insert(cur):
            self.assertIsNotNone(_nilai(p, "tanggal_server"))

    def test_divisi_yang_dipilih_yang_ditulis(self):
        cur = FakeCursor()
        _buat(cur, items=[{**ITEMS[0], "kd_divisi": "PALSU"}])
        # Divisi kepala yang berlaku, bukan yang diselipkan di baris item.
        self.assertEqual(_nilai(_insert(cur)[0][1], "kd_divisi"), "DAA001")

    def test_awalan_nomor_ikut_divisi_yang_dipilih(self):
        """Di gudang tiap divisi punya kepala_nota sendiri, dan opname-nya
        memang bernomor GP (PERGUDANGAN) — bukan UM milik divisi pertama."""
        cur = FakeCursor()
        self.assertTrue(_buat(cur, kd_divisi="DAA000")["nomor"][0].startswith("UM"))
        cur2 = FakeCursor()
        self.assertTrue(_buat(cur2, kd_divisi="DAA001")["nomor"][0].startswith("GP"))

    def test_qty_ditulis_positif_apa_pun_jenisnya(self):
        """Tandanya ada di `status`, bukan di qty — trigger yang membalik."""
        cur = FakeCursor()
        _buat(cur)
        for _, p in _insert(cur):
            self.assertGreater(_nilai(p, "qty"), 0)


class KeteranganTests(SimpleTestCase):
    def test_kosong_ditolak(self):
        cur = FakeCursor()
        with self.assertRaises(ValueError) as ctx:
            _buat(cur, keterangan="   ")
        self.assertIn("Keterangan", str(ctx.exception))

    def test_dipotong_di_50_bukan_ditolak_sql(self):
        cur = FakeCursor()
        _buat(cur, keterangan="B" * 80)
        self.assertEqual(len(_nilai(_insert(cur)[0][1], "keterangan")), 50)


class DivisiTests(SimpleTestCase):
    def test_kosong_ditolak_bukan_ditebak(self):
        cur = FakeCursor()
        with self.assertRaises(ValueError) as ctx:
            _buat(cur, kd_divisi="")
        self.assertIn("Divisi", str(ctx.exception))
        self.assertEqual(_insert(cur), [], "tak boleh ada baris yang terlanjur ditulis")

    def test_divisi_asing_ditolak(self):
        """kd_divisi satu-satunya nilai yang datang dari layar — ia diperiksa."""
        cur = FakeCursor()
        with self.assertRaises(ValueError):
            _buat(cur, kd_divisi="XXX999")
        self.assertEqual(_insert(cur), [])


class ValidasiTests(SimpleTestCase):
    def test_tanpa_tautan_akun_ditolak_dengan_arahan(self):
        with self.assertRaises(ValueError) as ctx:
            op._periksa(ITEMS, "")
        self.assertIn("Kelola Tautan User", str(ctx.exception))

    def test_tanpa_baris_ditolak(self):
        with self.assertRaises(ValueError):
            op._periksa([], "UAA002")

    def test_qty_nol_ditolak(self):
        with self.assertRaises(ValueError):
            op._periksa([{"kd_barang": "X", "kd_satuan": "SAA000", "qty": 0,
                          "jenis": "lain_plus"}], "UAA002")

    def test_qty_bukan_angka_ditolak_dengan_kalimat_yang_bisa_dibaca(self):
        """`float()` telanjang melempar pesan Python yang tak berarti apa-apa
        bagi orang yang sedang menghitung rak."""
        with self.assertRaises(ValueError) as ctx:
            op._periksa([{"kd_barang": "X", "kd_satuan": "SAA000", "qty": "dua",
                          "jenis": "lain_plus"}], "UAA002")
        self.assertIn("bukan angka", str(ctx.exception))
        self.assertNotIn("could not convert", str(ctx.exception))

    def test_koma_desimal_indonesia_dibaca(self):
        """Isian "1,5" jauh lebih mungkin diketik di sini daripada "1.5"."""
        self.assertEqual(op._qty({"qty": "1,5"}), 1.5)

    def test_satuan_kosong_ditolak(self):
        """kd_satuan menentukan BESAR pergeseran stok — 1 DUS bukan 1 PCS."""
        with self.assertRaises(ValueError):
            op._periksa([{"kd_barang": "X", "kd_satuan": "", "qty": 1,
                          "jenis": "lain_plus"}], "UAA002")

    def test_jenis_asing_ditolak(self):
        """Nilai `status` tak boleh datang mentah dari layar: 2 dan bukan-2
        adalah selisih antara stok bertambah dan stok berkurang. Angka "2"
        sebagai teks pun ditolak — layar mengirim nama jenis, bukan kodenya."""
        for jahat in ("2", "", "4", "lain-lain"):
            with self.assertRaises(ValueError, msg=jahat):
                op._periksa([{"kd_barang": "X", "kd_satuan": "SAA000", "qty": 1,
                              "jenis": jahat}], "UAA002")

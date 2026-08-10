"""Order Pembelian — layar tulis pertama yang tabelnya TIDAK punya data lama.

Semua jalur tulis sebelumnya bisa meniru baris yang sudah ada: penjualan order
punya 7.209 baris berawalan `OJ`, opname 6.698 baris di divisi DAA001, pembelian
12.605 baris. `t_pembelian_order` **kosong di setiap server yang terjangkau**
(testgudang 0, PUSAT 0). Jadi tak ada yang bisa dicocokkan — yang tersisa hanya
skema, view legacy, dan konvensi tabel kembarannya.

Karena itu tes ini menjaga bentuk SQL-nya, bukan angkanya: kalau salah satu dari
empat hal di bawah bergeser, kegagalannya di server sungguhan berupa galat SQL
saat kasir menekan Simpan — atau, lebih buruk, baris yang tersimpan diam-diam
salah dan langsung ikut terkirim ke pusat oleh trigger `insert_temp_m_*` yang
memang ada di tabel ini (`t_penjualan_order` tak punya satu pun).
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.transactions import transaksi as tx
from apps.transactions.penjualan import AWALAN_TETAP
from apps.transactions.penomoran import JENIS

ITEM = [{"kd_barang": "1001", "kd_satuan": "SAA000", "qty": 2, "harga": 5000}]


def _tulis(jenis, **kw):
    """Jalankan tx.buat dengan cursor palsu; kembalikan daftar (sql, params)."""
    cur = MagicMock()
    cur.fetchone.return_value = [None]
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    argumen = dict(kd_user="UAA002", kd_divisi="DAA001", kd_pihak="SUP001",
                   kd_jenis="JAA000", kd_kas="KAA001", items=ITEM)
    argumen.update(kw)
    with patch("core.mssql.cursor", return_value=ctx), \
         patch("apps.transactions.transaksi.awalan_untuk", return_value="GP"):
        hasil = tx.buat(object(), jenis, **argumen)
    return hasil, [c[0] for c in cur.execute.call_args_list]


class BentukSqlTests(SimpleTestCase):
    def test_terdaftar_di_penomoran(self):
        self.assertEqual(JENIS["pembelian_order"],
                         ("t_pembelian_order", "no_order"))

    def test_awalan_tetap_ob_tidak_dari_kepala_nota(self):
        """`awalan_untuk` di-patch memulangkan "GP"; kalau ia yang terpakai,
        nomornya jadi GP… dan penomoran order bercabang mengikuti divisi."""
        self.assertEqual(AWALAN_TETAP["pembelian_order"], "OB")
        hasil, panggilan = _tulis("pembelian_order")
        self.assertTrue(hasil["nomor"].startswith("OB"), hasil["nomor"])
        # Pembelian biasa TETAP dari kepala_nota — bedanya harus nyata.
        hasil2, _ = _tulis("pembelian")
        self.assertTrue(hasil2["nomor"].startswith("GP"), hasil2["nomor"])

    def test_order_terbuka_ditandai_no_transaksi_sama_dengan_no_order(self):
        """Konvensi t_penjualan_order, bukan kolom `status`.

        Di sana `status` justru yang gagal: 25 baris berstatus 1 padahal belum
        diambil, dan order salah-tanda lenyap dari daftar tanpa galat apa pun.
        """
        hasil, panggilan = _tulis("pembelian_order")
        sql, params = next(p for p in panggilan if "INSERT INTO t_pembelian_order " in p[0])
        kolom = sql.split("(")[1].split(")")[0].split(", ")
        self.assertEqual(params[kolom.index("no_transaksi")], hasil["nomor"])
        self.assertEqual(params[kolom.index("no_order")], hasil["nomor"])

    def test_kolom_pembayarannya_kd_jenis_bayar(self):
        """Satu-satunya tabel di SPEC yang mengejanya begitu. Menyebutnya
        `kd_jenis` membuat INSERT ditolak — kolomnya memang tak ada."""
        _, panggilan = _tulis("pembelian_order")
        sql, params = next(p for p in panggilan if "INSERT INTO t_pembelian_order " in p[0])
        kolom = sql.split("(")[1].split(")")[0].split(", ")
        self.assertIn("kd_jenis_bayar", kolom)
        self.assertNotIn("kd_jenis", kolom)
        self.assertEqual(params[kolom.index("kd_jenis_bayar")], "JAA000")

    def test_kolom_khususnya_terbawa(self):
        _, panggilan = _tulis("pembelian_order", no_pp_order="PP-9",
                              jaminan=250_000, tanggal_terima=None)
        sql, params = next(p for p in panggilan if "INSERT INTO t_pembelian_order " in p[0])
        kolom = sql.split("(")[1].split(")")[0].split(", ")
        self.assertEqual(params[kolom.index("no_pp_order")], "PP-9")
        self.assertEqual(params[kolom.index("jaminan")], 250_000.0)
        self.assertIsNotNone(params[kolom.index("tanggal_terima")])

    def test_detail_tanpa_point1_dan_tanpa_total(self):
        """`t_pembelian_detail` punya point1; order TIDAK. Dan `total` kolom
        terhitung di kedua tabel — menyebutnya membuat INSERT ditolak."""
        _, panggilan = _tulis("pembelian_order")
        sql, _ = next(p for p in panggilan
                      if "INSERT INTO t_pembelian_order_detail " in p[0])
        kolom = sql.split("(")[1].split(")")[0].split(", ")
        self.assertNotIn("point1", kolom)
        self.assertNotIn("total", kolom)
        self.assertEqual(kolom[0], "no_order")


class TidakMerusakJenisLainTests(SimpleTestCase):
    """Empat kolom baru di ctx tak boleh bocor ke tabel yang tak punya kolomnya."""

    def test_pembelian_biasa_tak_ikut_menulis_kolom_order(self):
        _, panggilan = _tulis("pembelian", no_pp_order="PP-9", jaminan=99)
        sql, _ = next(p for p in panggilan if "INSERT INTO t_pembelian " in p[0])
        kolom = sql.split("(")[1].split(")")[0].split(", ")
        for k in ("no_pp_order", "jaminan", "tanggal_terima", "kd_jenis_bayar"):
            self.assertNotIn(k, kolom)
        self.assertIn("kd_jenis", kolom)

    def test_retur_tak_ikut_menandai_order_terbuka(self):
        """Retur tak punya kolom no_transaksi sama sekali; penandanya
        disimpulkan dari header, jadi ia harus diam di sini."""
        for jenis in ("penjualan_retur", "pembelian_retur"):
            _, panggilan = _tulis(jenis)
            s = tx.spec(jenis)
            sql, _ = next(p for p in panggilan
                          if f"INSERT INTO {s['tabel']} " in p[0])
            self.assertNotIn("no_transaksi", sql.split("(")[1].split(")")[0])

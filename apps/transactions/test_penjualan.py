"""Uang di nota penjualan harus persis sama dengan hitungan aplikasi legacy.

Angka yang meleset di sini tidak menimbulkan galat apa pun — ia cuma jadi omzet
yang salah di laporan, dan baru ketahuan saat tutup buku.

Semantik yang ditiru ada di tiga UDF legacy, dan kembaran SQL-nya di
`_ghb`/`_nota_net` (apps/transactions/reports.py). Diperiksa terhadap 300 nota
SC nyata di server testing: 300 cocok, 0 beda.
"""
import datetime as dt
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import penjualan as pj


@contextmanager
def _ctx(cur):
    yield cur


class GhbTests(SimpleTestCase):
    def test_diskon_pecahan_dibaca_sebagai_persen(self):
        """Nilai di (-1, 1) berarti PERSEN. 82 dari 2.990.262 baris memakai mode
        ini; memperlakukannya sebagai rupiah berarti memotong Rp0,2."""
        self.assertAlmostEqual(pj.ghb(58400, [0.2]), 46720.0)

    def test_diskon_besar_dibaca_sebagai_rupiah(self):
        self.assertAlmostEqual(pj.ghb(58400, [400]), 58000.0)

    def test_diskon_berlapis_berurutan(self):
        self.assertAlmostEqual(pj.ghb(100000, [0.1, 0.5]), 45000.0)

    def test_harga_nol_atau_minus_dikembalikan_apa_adanya(self):
        """Guard UDF. Tanpanya baris berharga nol jadi subtotal negatif palsu."""
        self.assertEqual(pj.ghb(0, [0.5]), 0)
        self.assertEqual(pj.ghb(-500, [0.5]), -500)

    def test_diskon_kosong_tidak_mengubah_harga(self):
        self.assertAlmostEqual(pj.ghb(146000, [None, 0, None, 0]), 146000.0)


class TotalNotaTests(SimpleTestCase):
    def _item(self, **kw):
        dasar = {"kd_barang": "X", "kd_satuan": "S", "qty": 2, "harga_jual": 146000}
        dasar.update(kw)
        return dasar

    def test_kasus_yang_diverifikasi_ke_server(self):
        """Nota SC2608070001 yang benar-benar ditulis: 2 x 146.000 = 292.000,
        dan kolom terhitung di database mengembalikan angka yang sama."""
        self.assertAlmostEqual(pj.total_nota([self._item()]), 292000.0)

    def test_pajak_adalah_fraksi_bukan_angka_persen(self):
        """pajak 0,05 = 5%. Membaginya /100 membuat pajak jadi 0,05%."""
        self.assertAlmostEqual(pj.total_nota([self._item()], pajak=0.05), 306600.0)

    def test_diskon_uang_dikurangi_paling_akhir(self):
        """Setelah pajak, bukan sebelum — urutannya mengubah hasilnya."""
        self.assertAlmostEqual(
            pj.total_nota([self._item()], diskon_uang=2000, pajak=0.05), 304600.0)

    def test_diskon_header_berlaku_atas_harga_yang_sudah_didiskon_baris(self):
        hasil = pj.total_nota([self._item(diskon1=0.1)], diskon_header=[0.5, 0, 0, 0])
        self.assertAlmostEqual(hasil, 131400.0)


class ValidasiTests(SimpleTestCase):
    def test_tanpa_tautan_user_legacy_ditolak_dengan_arahan(self):
        """t_penjualan.kd_user NOT NULL. Ditahan di sini supaya kasir dapat
        kalimat yang bisa ditindaklanjuti, bukan galat ODBC."""
        with self.assertRaises(ValueError) as ctx:
            pj._periksa([{"kd_barang": "X", "qty": 1}], "")
        self.assertIn("Kelola Tautan User", str(ctx.exception))

    def test_nota_kosong_ditolak(self):
        with self.assertRaises(ValueError):
            pj._periksa([], "UAA002")

    def test_qty_nol_ditolak(self):
        with self.assertRaises(ValueError):
            pj._periksa([{"kd_barang": "X", "qty": 0}], "UAA002")

    def test_baris_tanpa_barang_ditolak(self):
        with self.assertRaises(ValueError):
            pj._periksa([{"kd_barang": "  ", "qty": 1}], "UAA002")


class FakeCursor:
    """Cursor palsu yang merekam SQL — MS SQL tak disentuh (lihat test_transaksi)."""

    def __init__(self):
        self.sql = []
        self.params = []
        self.connection = self

    def setinputsizes(self, v):
        pass

    def commit(self):
        pass

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self.params.append(list(params or []))

    def fetchone(self):
        return (None,)   # belum ada nomor untuk awalan ini


class NotaPalsu:
    """Cursor palsu yang menjawab tiga query `baca_nota` menurut urutannya.

    MS SQL tak disentuh: yang diuji di sini aritmetika struk dan pemetaan
    kolomnya, dan keduanya tak butuh server. Tes versi sebelumnya menembak
    koneksi `Testing` sungguhan lewat `core.mssql.get_profile` — fungsi yang
    tidak pernah ada — sehingga seluruh berkas ini gagal saat import.
    """

    def __init__(self, header, detail, profil):
        self._jawab = [[header], detail, [profil]]
        self.sql = []
        self.connection = self

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self._hasil = self._jawab.pop(0)

    def fetchone(self):
        return self._hasil[0] if self._hasil else None

    def fetchall(self):
        return self._hasil


PROFIL = ("SUKSES CROWN TOYS", "Jl. Selaparang 166", "0370-123")


def _baca(header, detail, profil=PROFIL):
    cur = NotaPalsu(header, detail, profil)
    with patch.object(pj.mssql, "cursor", lambda *a, **k: _ctx(cur)):
        return pj.baca_nota(object(), "SC2608140001"), cur


class BacaNotaTests(SimpleTestCase):
    """Header: no, tanggal, kd_customer, customer, kd_user, kasir, kd_jenis,
    jenis_bayar, kd_divisi, divisi, no_bukti, keterangan, jatuh_tempo,
    diskon1..4, diskon_uang, pajak, total."""

    HEADER = ("SC2608140001", dt.datetime(2026, 8, 14, 10, 0), "CAA000", "UMUM",
              "UAA034", "ADMIN6", "JAA000", "TUNAI", "DAA000", "GUDANG",
              "-", "-", dt.datetime(2026, 9, 13), 0, 0, 0, 0, 0.0, 0.0, 539500.0)
    # kd_barang, nama, kd_satuan, satuan, qty, harga, d1..d4, total, pegawai
    DETAIL = [("BOLALA", "PERMEN BOLALA", "SAA002", "RTG", 120.0, 5000.0,
               500.0, 0.0, 0.0, 0.0, 540000.0, "MAJDI")]

    def test_kasir_dibaca_dari_m_userx_bukan_m_pegawai(self):
        """`kd_user` dan `kd_pegawai` dua ruang kode berbeda: join m_pegawai
        lewat kd_user memulangkan NULL di SETIAP nota (terukur di server
        Testing), dan versi lama menambalnya dengan pegawai baris pertama —
        struk mencetak nama SPG di bawah label Kasir."""
        nota, cur = _baca(self.HEADER, self.DETAIL)
        self.assertEqual(nota["kasir"], "ADMIN6")
        self.assertEqual(nota["pegawai"], "MAJDI")
        self.assertIn("LEFT JOIN m_userx u ON u.kd_user = h.kd_user", cur.sql[0])
        self.assertNotIn("m_pegawai p ON p.kd_pegawai = h.kd_user", cur.sql[0])

    def test_divisi_diambil_dari_nota_bukan_baris_pertama_m_divisi(self):
        """Gudang punya lima divisi; `SELECT TOP 1 FROM m_divisi` mencetak kop
        divisi yang bukan penerbit notanya."""
        _, cur = _baca(self.HEADER, self.DETAIL)
        self.assertIn("LEFT JOIN m_divisi dv ON dv.kd_divisi = h.kd_divisi", cur.sql[0])
        self.assertNotIn("SELECT TOP 1 nama FROM m_divisi", " ".join(cur.sql))

    def test_g_info_profile_dibaca_berurutan(self):
        """Tabelnya heap tanpa kunci (16.581 baris di grosirPusat): TOP 1 tanpa
        ORDER BY tak menjanjikan baris yang sama dua kali."""
        _, cur = _baca(self.HEADER, self.DETAIL)
        self.assertIn("FROM g_info_profile ORDER BY", cur.sql[2])

    def test_ringkasan_uang_menjumlah(self):
        """Sub Total - Diskon + Pajak = Total. Ini yang dilihat pelanggan; kalau
        tak menjumlah, struknya terbaca sebagai salah hitung."""
        nota, _ = _baca(self.HEADER, self.DETAIL)
        self.assertAlmostEqual(nota["bruto"], 600000.0)
        self.assertAlmostEqual(
            nota["bruto"] - nota["diskon"] + nota["pajak_rp"], nota["total"], places=2)

    def test_diskon_gabungan_termasuk_diskon_uang(self):
        """diskon_uang dikurangi SETELAH pajak di total_nota, jadi ia tak bisa
        cuma dijumlahkan ke diskon baris — `diskon` diturunkan dari total."""
        h = list(self.HEADER)
        h[17] = 500.0          # diskon_uang
        nota, _ = _baca(tuple(h), self.DETAIL)
        self.assertAlmostEqual(nota["diskon"], 60500.0)

    def test_pajak_fraksi_jadi_rupiah(self):
        """`pajak` disimpan sebagai fraksi (0,05 = 5%); struk lama mencetak
        "0.05" apa adanya."""
        h = list(self.HEADER)
        h[18] = 0.05
        h[19] = None           # tanpa t_penjualan_total, hitung sendiri
        nota, _ = _baca(tuple(h), self.DETAIL)
        self.assertAlmostEqual(nota["pajak_rp"], 27000.0)
        self.assertAlmostEqual(nota["total"], 567000.0)
        self.assertAlmostEqual(
            nota["bruto"] - nota["diskon"] + nota["pajak_rp"], nota["total"], places=2)

    def test_sentinel_strip_jadi_kosong(self):
        """`keterangan`/`no_bukti` legacy berisi "-", bukan string kosong —
        mencetaknya apa adanya membuat struk berisi "Ket: -"."""
        nota, _ = _baca(self.HEADER, self.DETAIL)
        self.assertEqual(nota["keterangan"], "")
        self.assertEqual(nota["no_bukti"], "")

    def test_bayar_tak_pernah_datang_dari_baca_nota(self):
        """t_penjualan tak punya kolomnya; nilainya dioper dari layar kasir."""
        nota, _ = _baca(self.HEADER, self.DETAIL)
        self.assertNotIn("bayar", nota)
        self.assertNotIn("kembali", nota)

    def test_no_transaksi_kosong_tak_menyentuh_server(self):
        self.assertIsNone(pj.baca_nota(object(), "   "))


    def test_profil_contoh_installer_tak_pernah_jadi_kop(self):
        """`g_info_profile` di SERVER-TOYS (18.927 baris) dan SERVER-GUDANG
        (15.698) masih berisi teks contoh bawaan installer legacy. Mencetak
        "PERUSAHAAN ANDA / ALAMAT PERUSAHAAN / Telp : 0" di struk pelanggan
        lebih buruk daripada tak mencetak apa pun; nama divisi notanya dipakai
        sebagai gantinya, karena di server itu ia satu-satunya nama yang nyata."""
        nota, _ = _baca(self.HEADER, self.DETAIL,
                        ("PERUSAHAAN ANDA", "ALAMAT PERUSAHAAN", "0"))
        self.assertEqual(nota["toko"], "GUDANG")     # m_divisi.nama notanya
        self.assertEqual(nota["alamat"], "")
        self.assertEqual(nota["telepon"], "")

    def test_profil_terisi_menang_atas_nama_divisi(self):
        nota, _ = _baca(self.HEADER, self.DETAIL)
        self.assertEqual(nota["toko"], "SUKSES CROWN TOYS")
        self.assertEqual(nota["telepon"], "0370-123")

    def test_profil_kosong_jatuh_ke_divisi(self):
        nota, _ = _baca(self.HEADER, self.DETAIL, ("", "", ""))
        self.assertEqual(nota["toko"], "GUDANG")


class LabelDiskonTests(SimpleTestCase):
    def test_fraksi_jadi_persen(self):
        self.assertEqual(pj._label_diskon([0.1, 0, 0, 0]), "10%")

    def test_rupiah_diberi_satuan(self):
        """Angka kiri potongan PER UNIT, angka kanan potongan SELURUH baris.
        Tanpa "/PCS", "Disc 3.000 = 9.000" terbaca sebagai hitungan salah."""
        self.assertEqual(pj._label_diskon([3000, 0, 0, 0], "PCS"), "3.000/PCS")

    def test_diskon_nol_tak_muncul(self):
        self.assertEqual(pj._label_diskon([0, 0, 0, 0]), "")


class OrderTests(SimpleTestCase):
    """Order yang salah tanda tak bisa diambil jadi nota — dan tak ada galat
    apa pun yang memberi tahu; ia cuma hilang dari daftar order terbuka."""

    ITEM = [{"kd_barang": "000-06", "kd_satuan": "SAA000", "qty": 2,
             "harga_jual": 146000.0}]

    def _buat(self, **kw):
        cur = FakeCursor()
        dasar = dict(kd_user="UAA002", kd_divisi="DAA000", kd_customer="CAA000",
                     kd_jenis="JAA000", kd_kas="KAA001", kd_voucher="VAA000",
                     kd_pegawai="PAA000", items=self.ITEM)
        dasar.update(kw)
        with patch.object(pj.mssql, "cursor", lambda *a, **k: _ctx(cur)):
            return cur, pj.buat_order(object(), **dasar)

    def test_nomor_memakai_awalan_order_bukan_kepala_nota(self):
        """kepala_nota divisi ini `SC`, tapi seluruh 7.209 order legacy `OJ`."""
        cur, hasil = self._buat()
        self.assertTrue(hasil["no_order"].startswith("OJ"), hasil["no_order"])
        # kepala_nota tak dibaca sama sekali: layar order tetap jalan walau
        # kolomnya belum diisi.
        self.assertFalse(any("kepala_nota" in s for s in cur.sql))

    def test_ditandai_belum_diambil(self):
        """no_transaksi = no_order DAN status 0 — `daftar_order` menyaring pada
        yang pertama, jadi mengosongkannya membuat order langsung dianggap
        sudah jadi nota."""
        cur, hasil = self._buat()
        i = next(k for k, s in enumerate(cur.sql) if "INSERT INTO t_penjualan_order (" in s)
        nilai = dict(zip(pj._ORDER_HEADER, cur.params[i]))
        self.assertEqual(nilai["no_transaksi"], hasil["no_order"])
        self.assertEqual(nilai["status"], 0)

    def test_tanggal_server_diisi_jam_server(self):
        """Kolomnya NOT-NULL-able tanpa DEFAULT, beda dari t_penjualan; kalau
        tak disebut ia jadi NULL padahal 7.209 baris legacy semuanya terisi."""
        cur, _ = self._buat()
        insert = next(s for s in cur.sql if "INSERT INTO t_penjualan_order (" in s)
        self.assertIn("tanggal_server", insert)
        self.assertIn("GETDATE()", insert)

    def test_baris_ditulis_dengan_jenis_satu(self):
        cur, _ = self._buat()
        i = next(k for k, s in enumerate(cur.sql) if "t_penjualan_order_detail" in s)
        nilai = dict(zip(pj._ORDER_DETAIL, cur.params[i]))
        self.assertEqual(nilai["jenis"], pj.JENIS_BARIS)

    def test_order_kosong_ditolak_sebelum_menyentuh_database(self):
        with self.assertRaises(ValueError):
            self._buat(items=[])


class SatuanBarangTests(SimpleTestCase):
    """Ganti satuan harus ikut mengganti harga: 541 barang punya >1 satuan dan
    harganya beda per satuan (1001: PCS 4.800, LUSIN 57.600)."""

    class _Cur(FakeCursor):
        def fetchall(self):
            return [("SAA000", "PCS", 1.0, 4800.0, 1),
                    ("SAA001  ", " LUSIN ", 12.0, 57600.0, 1)]

    def _panggil(self, kode="1001"):
        cur = self._Cur()
        with patch.object(pj.mssql, "cursor", lambda *a, **k: _ctx(cur)):
            return cur, pj.satuan_barang(object(), kode)

    def test_mengembalikan_harga_per_satuan(self):
        _, rows = self._panggil()
        self.assertEqual(
            rows,
            [{"kd_satuan": "SAA000", "satuan": "PCS", "jumlah": 1.0,
              "harga_jual": 4800.0, "status": 1},
             {"kd_satuan": "SAA001", "satuan": "LUSIN", "jumlah": 12.0,
              "harga_jual": 57600.0, "status": 1}])

    def test_kode_kosong_tidak_menyentuh_database(self):
        cur, rows = self._panggil("   ")
        self.assertEqual(rows, [])
        self.assertEqual(cur.sql, [])


class BentukInsertTests(SimpleTestCase):
    def test_jenis_baris_mengikuti_data_legacy(self):
        """Legacy menulis 1 di SELURUH 2.990.259 baris t_penjualan_detail; 68
        baris ber-jenis 0 semuanya tulisan Arunika sendiri saat pengujian."""
        self.assertEqual(pj.JENIS_BARIS, 1)

    def test_kolom_order_menyebut_semua_kolom_wajib(self):
        """Seluruh kolom t_penjualan_order NOT NULL kecuali tanggal_server &
        no_transaksi — yang tak disebut membuat INSERT ditolak."""
        for k in ("no_order", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas",
                  "kd_voucher", "no_bukti", "tanggal", "tanggal_terima", "status",
                  "diskon_uang", "pajak", "keterangan", "jaminan", "kd_user"):
            self.assertIn(k, pj._ORDER_HEADER, f"{k} hilang — kolomnya NOT NULL")

    def test_kolom_terhitung_tidak_ikut_ditulis(self):
        """t_penjualan_detail.total kolom terhitung — menyebutnya membuat INSERT
        ditolak SQL Server, dan itu baru ketahuan saat menulis nota sungguhan."""
        self.assertNotIn("total", pj._DETAIL)

    def test_header_menyebut_semua_kolom_wajib(self):
        for k in ("no_transaksi", "kd_customer", "kd_divisi", "kd_jenis", "kd_kas",
                  "kd_voucher", "no_bukti", "tanggal", "tanggal_jatuh_tempo",
                  "status", "diskon_uang", "pajak", "keterangan", "kd_user"):
            self.assertIn(k, pj._HEADER, f"{k} hilang — kolomnya NOT NULL")

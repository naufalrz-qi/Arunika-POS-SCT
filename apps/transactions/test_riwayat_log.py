"""Riwayat dokumen dari tbl_log_transaksi (panel detail Nota Tanggal Mundur).

Dijalankan atas log palsu di memori yang meniru bentuk trigger legacy apa
adanya — termasuk cacat `table_aksi` baris hapus detail yang tanpa sufiks —
karena bentuk itulah yang paling mudah salah dibaca tanpa ada galat.
"""
import datetime as dt

from django.test import SimpleTestCase

from apps.transactions import riwayat_log as rl

T0 = dt.datetime(2026, 9, 20, 12, 28, 33)


def _hdr(aksi, no, kd_user, **kol):
    isi = ";".join(f"val__{k}__{v}" for k, v in {"no_transaksi": no, **kol, "kd_user": kd_user}.items())
    return f"key__no_transaksi__{no};{isi}" if aksi == "update" else isi


def _det_ins(no, kd_barang, qty, harga=1000):
    return (f"val__no_transaksi__{no};val__kd_barang__{kd_barang};val__kd_satuan__SAA000;"
            f"val__kd_pegawai__PAA000;val__jenis__1;val__harga_jual__{harga};val__qty__{qty}")


def _det_del(no, kd_barang):
    return (f"key__no_transaksi__{no};key__kd_barang__{kd_barang};key__kd_satuan__SAA000;"
            "key__kd_pegawai__PAA000;key__jenis__1")


class LogPalsu:
    """Cursor yang menjawab kueri `riwayat_log._log` dari daftar baris log."""

    def __init__(self, baris):
        # (id, waktu, table_aksi, formatted_data)
        self.baris = baris
        self._hasil = []

    def setinputsizes(self, _):
        pass

    def execute(self, sql, params):
        aksi, dari = params[0], params[1]
        pakai_sampai = "waktu < ?" in sql
        sampai = params[2] if pakai_sampai else None
        sisa = params[3:] if pakai_sampai else params[2:]
        awalan = [sisa[i + 1] for i in range(0, len(sisa), 2)]
        self._hasil = sorted(
            (i, w, fd) for i, w, ta, fd in self.baris
            if ta == aksi and w >= dari and (sampai is None or w < sampai)
            and any(fd.startswith(a) for a in awalan)
        )

    def fetchall(self):
        return self._hasil


def _log_edit():
    """Nota dibuat KASIR8, besoknya ADMIN5 mengedit: qty B jadi 3, C dibuang, D
    ditambah — lewat hapus-semua lalu insert-ulang, persis seperti legacy."""
    no = "SC1"
    edit = T0 + dt.timedelta(hours=21)
    return no, edit, [
        (100, T0, "t_penjualan__insert", _hdr("insert", no, "UAA009", tanggal="2026-9-20 12:28:33", kd_customer="CAA000")),
        (101, T0, "t_penjualan_detail__insert", _det_ins(no, "A", 1)),
        (102, T0, "t_penjualan_detail__insert", _det_ins(no, "B", 2)),
        (103, T0, "t_penjualan_detail__insert", _det_ins(no, "C", 1)),
        # nota lain di sela-sela — tak boleh ikut
        (104, T0, "t_penjualan_detail__insert", _det_ins("SC2", "Z", 9)),
        (200, edit, "t_penjualan__update", _hdr("update", no, "UAA032", tanggal="2026-9-20 12:28:33", kd_customer="CAA025")),
        (201, edit, "t_penjualan_detail", _det_del(no, "A")),
        (202, edit, "t_penjualan_detail", _det_del(no, "B")),
        (203, edit, "t_penjualan_detail", _det_del(no, "C")),
        (204, edit, "t_penjualan_detail__insert", _det_ins(no, "A", 1)),
        (205, edit, "t_penjualan_detail__insert", _det_ins(no, "B", 3)),
        (206, edit, "t_penjualan_detail__insert", _det_ins(no, "D", 5)),
    ]


class Riwayat(SimpleTestCase):
    def test_pembuat_dan_pengedit_terpisah(self):
        no, edit, log = _log_edit()
        r = rl.riwayat(LogPalsu(log), "t_penjualan", "no_transaksi", no, T0, edit)
        self.assertEqual([(p["aksi"], p["kd_user"]) for p in r["peristiwa"]],
                         [("Dibuat", "UAA009"), ("Diedit", "UAA032")])

    def test_perubahan_kolom_nota_tanpa_waktu_simpan_dan_kasir(self):
        """`tanggal_server`/`kd_user` SELALU berubah saat edit — itu sudah
        tampil sebagai "kapan" dan "oleh", bukan sebagai perubahan."""
        no, edit, log = _log_edit()
        r = rl.riwayat(LogPalsu(log), "t_penjualan", "no_transaksi", no, T0, edit)
        self.assertEqual(r["peristiwa"][1]["perubahan"],
                         [{"kolom": "kd_customer", "dari": "CAA000", "ke": "CAA025"}])

    def test_hapus_semua_insert_ulang_jadi_selisih_yang_sebenarnya(self):
        """Tanpa putar ulang, edit legacy tampak sebagai 'semua barang dihapus,
        semua ditambah'. Yang benar: B berubah qty, C hilang, D baru, A tetap."""
        no, edit, log = _log_edit()
        r = rl.riwayat(LogPalsu(log), "t_penjualan", "no_transaksi", no, T0, edit)
        awal, ubah = r["peristiwa"][0]["barang"], r["peristiwa"][1]["barang"]
        self.assertEqual(sorted(b["kd_barang"] for b in awal["isi"]), ["A", "B", "C"])
        self.assertEqual([b["kd_barang"] for b in ubah["ditambah"]], ["D"])
        self.assertEqual([b["kd_barang"] for b in ubah["dihapus"]], ["C"])
        self.assertEqual([(b["kd_barang"], b["qty_dari"], b["qty"]) for b in ubah["diubah"]], [("B", 2.0, 3.0)])

    def test_dibuat_ulang_tidak_mewarisi_barang_lama(self):
        """GUDANG tak punya trigger hapus t_penjualan: nota yang dihapus lalu
        dibuat ulang dengan nomor sama meninggalkan dua insert tanpa hapus di
        antaranya. Barang versi lama tak boleh terbawa."""
        no = "GP1"
        kedua = T0 + dt.timedelta(hours=6)
        log = [
            (10, T0, "t_penjualan__insert", _hdr("insert", no, "UAA010", tanggal="2026-9-20 12:28:33")),
            (11, T0, "t_penjualan_detail__insert", _det_ins(no, "LAMA", 1)),
            (20, kedua, "t_penjualan__insert", _hdr("insert", no, "UAA001", tanggal="2026-9-20 12:28:33")),
            (21, kedua, "t_penjualan_detail__insert", _det_ins(no, "BARU", 2)),
        ]
        r = rl.riwayat(LogPalsu(log), "t_penjualan", "no_transaksi", no, T0, kedua)
        self.assertEqual([p["aksi"] for p in r["peristiwa"]], ["Dibuat", "Dibuat ulang"])
        self.assertEqual([b["kd_barang"] for b in r["peristiwa"][1]["barang"]["isi"]], ["BARU"])
        self.assertEqual(list(r["barang_akhir"]), [("BARU", "SAA000", "PAA000", "1")])

    def test_payload_detail_gudang_berkolom_nomor_ganda(self):
        """Trigger detail GUDANG menulis `val__no_transaksi__;` kosong lebih
        dulu, lalu nomor sebenarnya. Terbaca di testGudang (GP2510250020)."""
        no = "GP2"
        log = [
            (1, T0, "t_penjualan__insert", _hdr("insert", no, "UAA006", tanggal="2025-10-25 10:15:00")),
            (2, T0, "t_penjualan_detail__insert", "val__no_transaksi__;" + _det_ins(no, "SBN024", 4)),
        ]
        r = rl.riwayat(LogPalsu(log), "t_penjualan", "no_transaksi", no, T0, T0)
        self.assertEqual([b["kd_barang"] for b in r["peristiwa"][0]["barang"]["isi"]], ["SBN024"])

    def test_tabel_tanpa_putar_ulang_barang(self):
        log = [(1, T0, "t_pembelian__insert", _hdr("insert", "PB1", "UAA001", tanggal="2026-9-20 12:28:33"))]
        r = rl.riwayat(LogPalsu(log), "t_pembelian", "no_transaksi", "PB1", T0, T0)
        self.assertIsNone(r["peristiwa"][0]["barang"])
        self.assertIsNone(r["barang_akhir"])


class CocokDenganSekarang(SimpleTestCase):
    KUNCI = rl.DETAIL["t_penjualan"][1]

    def test_jenis_tinyint_dari_tabel_cocok_dengan_teks_log(self):
        """`jenis` datang sebagai int dari tabel dan "1" dari log. Tanpa
        penyeragaman, SETIAP nota tampak punya riwayat barang tak lengkap."""
        akhir = {("A", "SAA000", "PAA000", "1"): 2.0}
        sekarang = [{"kd_barang": "A", "kd_satuan": "SAA000", "kd_pegawai": "PAA000", "jenis": 1, "qty": 2}]
        self.assertTrue(rl.cocok_dengan_sekarang(akhir, sekarang, self.KUNCI))

    def test_qty_berbeda_tidak_cocok(self):
        akhir = {("A", "SAA000", "PAA000", "1"): 2.0}
        sekarang = [{"kd_barang": "A", "kd_satuan": "SAA000", "kd_pegawai": "PAA000", "jenis": 1, "qty": 5}]
        self.assertFalse(rl.cocok_dengan_sekarang(akhir, sekarang, self.KUNCI))

    def test_tanpa_putar_ulang_tak_bisa_dijawab(self):
        self.assertIsNone(rl.cocok_dengan_sekarang(None, [], self.KUNCI))

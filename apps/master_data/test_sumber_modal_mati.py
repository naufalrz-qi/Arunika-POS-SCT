"""Sumber modal yang mati tidak boleh menghentikan pekerjaan di server aktif.

Sumber modal (cost_source) hanya REFERENSI: dari sana datang kolom Modal, hitungan
Margin, dan saran harga. Katalog barangnya sendiri milik server aktif. Kalau gudang
pusat mati atau jaringan antar-cabang putus, kasir di cabang tetap harus bisa
mencari barang dan mengubah harga — yang hilang cuma dua kolom dan daftar saran.

Kelas kegagalannya halus: pyodbc.Error dari server LAIN merambat ke atas lalu
ditangkap sebagai "Gagal membaca barang", dan layar menampilkan daftar KOSONG.
Tak ada yang menunjukkan bahwa server aktifnya sendiri baik-baik saja.
"""
from unittest import mock

import pyodbc
from django.test import TestCase

from apps.connections.models import DbType, ServerProfile
from apps.master_data import services as master


def _profil(nama, tipe, cost_source=None):
    return ServerProfile.objects.create(
        name=nama, db_type=tipe, host="localhost", port=1433,
        db_name="db", username="sa", cost_source=cost_source,
    )


class DaftarBarangTetapTerbaca(TestCase):
    def setUp(self):
        self.g = _profil("GUDANG", DbType.GUDANG)
        self.gr = _profil("GR", DbType.GROSIR, cost_source=self.g)

    def _list(self):
        """list_barang_edit dgn server AKTIF sehat tapi sumber modal mati."""
        cur = mock.MagicMock()
        cur.fetchall.return_value = []
        cur.description = [("kd_barang",), ("kd_kategori",), ("nama",),
                           ("keterangan",), ("status",)]
        ctx = mock.MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        # HANYA pembacaan sumber-modal yang gagal. Membuat seluruh _cached gagal
        # akan ikut menjatuhkan pembacaan server AKTIF, sehingga tes lulus karena
        # alasan yang salah — persis kebalikan dari yang sedang dijaga.
        def _cached_selektif(p, name, build, *a, **kw):
            if p.pk == self.g.pk:
                raise pyodbc.Error("08001", "gudang mati")
            return build()

        status: dict = {}
        with (
            mock.patch.object(master.mssql, "cursor", return_value=ctx),
            mock.patch.object(master, "_cached", side_effect=_cached_selektif),
        ):
            rows = master.list_barang_edit(self.gr, status=status)
        return rows, status

    def test_tidak_melempar_saat_sumber_modal_mati(self):
        rows, _status = self._list()
        self.assertEqual(rows, [])   # katalog kosong di fixture ini, bukan error

    def test_melaporkan_lewat_status_bukan_exception(self):
        _rows, status = self._list()
        self.assertIn("modal_error", status)
        self.assertIn("GUDANG", status["modal_error"])
        # Kalimatnya harus menenangkan: ini pemberitahuan, bukan kegagalan.
        self.assertIn("tetap berjalan", status["modal_error"])


class SimpanHargaTetapJalan(TestCase):
    """Harga milik server aktif — server referensi yang mati tak boleh memblokirnya."""

    def setUp(self):
        self.g = _profil("GUDANG", DbType.GUDANG)
        self.rtl = _profil("RTL", DbType.RETAIL, cost_source=self.g)

    def _simpan(self, modal_mati: bool):
        cur = mock.MagicMock()
        cur.description = [("kd_satuan",), ("harga_jual",)]
        cur.fetchall.return_value = [("PCS", 1000.0)]
        cur.rowcount = 1
        aktif = mock.MagicMock()
        aktif.__enter__.return_value = cur
        aktif.__exit__.return_value = False

        mati = mock.MagicMock()
        mati.__enter__.side_effect = pyodbc.Error("08001", "gudang mati")

        status: dict = {}
        # Panggilan pertama = sumber modal, sisanya = server aktif.
        sisi = [mati if modal_mati else aktif, aktif]
        with (
            mock.patch.object(master.mssql, "cursor", side_effect=sisi),
            mock.patch.object(master, "_invalidate_inventory_cache"),
        ):
            master.update_harga(self.rtl, "B1", {"PCS": 2000}, status=status)
        return cur, status

    def test_harga_tetap_tersimpan_walau_sumber_modal_mati(self):
        cur, _status = self._simpan(modal_mati=True)
        updates = [c for c in cur.execute.call_args_list if "UPDATE" in str(c[0][0])]
        self.assertEqual(len(updates), 1)

    def test_margin_TIDAK_disentuh_saat_sumber_modal_mati(self):
        # Menulis margin dari modal 0 akan MENGHAPUS margin tersimpan — kerusakan
        # yang persis dihindari cabang non-retail.
        cur, _status = self._simpan(modal_mati=True)
        sql = [str(c[0][0]) for c in cur.execute.call_args_list if "UPDATE" in str(c[0][0])]
        self.assertNotIn("margin", sql[0])

    def test_margin_ditulis_saat_sumber_modal_sehat(self):
        cur, status = self._simpan(modal_mati=False)
        sql = [str(c[0][0]) for c in cur.execute.call_args_list if "UPDATE" in str(c[0][0])]
        self.assertIn("margin", sql[0])
        self.assertNotIn("modal_error", status)

    def test_memberi_tahu_bahwa_margin_tak_dihitung_ulang(self):
        # Margin basi tanpa gejala adalah yang paling berbahaya dari ketiganya.
        _cur, status = self._simpan(modal_mati=True)
        self.assertIn("margin tidak dihitung ulang", status["modal_error"])

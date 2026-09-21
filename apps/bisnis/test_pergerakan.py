"""Buku besar stok harus menolak baris yang tak masuk akal, di DATABASE.

Aturan-aturan ini sengaja jadi CHECK constraint, bukan validasi Python. Alasannya
sama dengan alasan skema ini tidak memakai trigger sama sekali, hanya dari arah
sebaliknya: yang boleh ada di database adalah aturan yang MENOLAK, bukan yang
diam-diam mengubah. Penolakan terlihat; perubahan senyap tidak.

Baris bermuatan dua arah (`masuk` DAN `keluar` terisi) adalah contoh yang paling
berbahaya, karena ia tidak pernah tampak salah: tiap agregasi harus memutuskan
sendiri artinya, dan dua tempat yang memutuskan berbeda tidak menghasilkan galat
apa pun -- hanya dua angka stok yang berbeda.
"""
import datetime as dt

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.bisnis.models import (
    Barang, BarangSatuan, Divisi, JenisPergerakan, PergerakanStok, Satuan,
)


class BukuBesarMenolak(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.satuan = Satuan.objects.create(kode="PCS", nama="Pieces")
        cls.divisi = Divisi.objects.create(kode="DAA000", nama="Utama", awalan_nota="SC")
        cls.barang = Barang.objects.create(
            kode="049", nama="Mainan Uji", satuan_dasar=cls.satuan
        )

    def _gerak(self, **kw):
        data = dict(
            divisi=self.divisi, barang=self.barang, satuan=self.satuan,
            tanggal=dt.date(2026, 9, 7), jenis=JenisPergerakan.PEMBELIAN,
        )
        data.update(kw)
        return PergerakanStok.objects.create(**data)

    def test_satu_arah_diterima(self):
        self.assertIsNotNone(self._gerak(masuk=10).pk)
        self.assertIsNotNone(self._gerak(keluar=3).pk)

    def test_dua_arah_sekaligus_ditolak(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._gerak(masuk=10, keluar=3)

    def test_kuantitas_negatif_ditolak(self):
        """Pengurangan ditulis di kolom `keluar`, bukan sebagai `masuk` negatif.

        Dua cara menyatakan hal yang sama adalah dua cara menjumlahkannya salah.
        """
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._gerak(masuk=-5)

    def test_saldo_awal_adalah_baris_biasa(self):
        """Bukan tabel tersendiri -- itu yang membuatnya jadi blok UNION kesembilan
        dengan aturan tanggal berbeda di skema legacy."""
        b = self._gerak(masuk=100, jenis=JenisPergerakan.SALDO_AWAL)
        self.assertEqual(b.jenis, "saldo_awal")


class KonversiSatuan(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pcs = Satuan.objects.create(kode="PCS", nama="Pieces")
        cls.lusin = Satuan.objects.create(kode="LSN", nama="Lusin")
        cls.barang = Barang.objects.create(kode="049", nama="Uji", satuan_dasar=cls.pcs)

    def test_isi_harus_positif(self):
        """`isi` = berapa satuan dasar dalam satu satuan ini. Nol membagi stok jadi tak hingga."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            BarangSatuan.objects.create(barang=self.barang, satuan=self.lusin, isi=0)

    def test_satu_satuan_sekali_per_barang(self):
        BarangSatuan.objects.create(barang=self.barang, satuan=self.lusin, isi=12)
        with self.assertRaises(IntegrityError), transaction.atomic():
            BarangSatuan.objects.create(barang=self.barang, satuan=self.lusin, isi=6)

"""Acuan modal (`cost_source`) boleh diisi grosir, bukan cuma retail.

Semula backend memaksa `cost_source = None` untuk semua tipe selain retail, jadi
pilihan pada profil grosir dibuang diam-diam saat disimpan — tanpa pesan galat,
tampak seperti "tidak bisa disimpan". Grosir membutuhkannya untuk Audit Harga
Beli, yang membandingkan pembelian toko dengan pembelian gudang.
"""
from django.test import SimpleTestCase

from apps.connections.models import ServerProfile
from apps.connections.views import _apply_form


def _form(db_type, cost_source=None):
    return {
        "name": "Uji", "db_type": db_type, "host": "localhost",
        "port": 1433, "db_name": "db", "username": "sa",
        "cost_source": cost_source,
    }


class CostSourcePerTipeTest(SimpleTestCase):
    def _simpan(self, db_type, cost_source):
        p = ServerProfile()
        _apply_form(p, _form(db_type, cost_source))
        return p.cost_source_id

    def test_grosir_menyimpan_acuan_modal(self):
        # Inti perbaikannya: dulu nilai ini dibuang jadi None.
        self.assertEqual(self._simpan("grosir", 3), 3)

    def test_retail_tetap_menyimpan(self):
        self.assertEqual(self._simpan("retail", 3), 3)

    def test_gudang_tak_punya_acuan_di_atasnya(self):
        self.assertIsNone(self._simpan("gudang", 3))

    def test_kosong_tetap_kosong(self):
        # Opsional untuk grosir — tak memilih apa pun bukan galat.
        self.assertIsNone(self._simpan("grosir", None))
        self.assertIsNone(self._simpan("grosir", ""))

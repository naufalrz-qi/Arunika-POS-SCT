"""SQL yang ditulis update_harga per tipe profil.

Kolom `margin` hanya boleh ikut ter-UPDATE di profil retail. Non-retail tidak
punya sumber-modal untuk menghitungnya dan UI menampilkannya read-only, jadi
menimpanya dengan 0 sama saja menghapus data. MS SQL tidak disentuh — cursor
di-fake dan SQL yang dieksekusi direkam.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.master_data import services


class FakeProfile:
    def __init__(self, db_type):
        self.db_type = db_type
        self.name = f"TEST {db_type}"


class FakeCursor:
    """Cukup untuk update_harga: SELECT harga lama sekali, lalu UPDATE per satuan."""

    def __init__(self, sink):
        self.sink = sink
        self.rowcount = 1
        self.description = [("kd_satuan",), ("harga_jual",)]
        self._rows = []

    def execute(self, sql, params=None):
        self.sink.append((sql, list(params or [])))
        self._rows = [("PCS", 1000.0)] if sql.lstrip().upper().startswith("SELECT") else []
        return self

    def fetchall(self):
        return self._rows

    @property
    def connection(self):
        return self

    def commit(self):
        pass


class UpdateHargaMarginTest(SimpleTestCase):
    def _jalankan(self, db_type):
        sql_terekam = []

        @contextmanager
        def fake_cursor(profile, autocommit=True):
            yield FakeCursor(sql_terekam)

        with patch.object(services.mssql, "cursor", fake_cursor), \
             patch.object(services.mssql, "get_cost_source", return_value=None), \
             patch.object(services, "_invalidate_inventory_cache"):
            services.update_harga(FakeProfile(db_type), "A1", {"PCS": 3000})

        return [sql for sql, _ in sql_terekam if sql.lstrip().upper().startswith("UPDATE")]

    def test_retail_menulis_margin(self):
        updates = self._jalankan("retail")
        self.assertEqual(len(updates), 1)
        self.assertIn("margin", updates[0])

    def test_grosir_tidak_menyentuh_margin(self):
        updates = self._jalankan("grosir")
        self.assertEqual(len(updates), 1)
        self.assertNotIn("margin", updates[0])

    def test_gudang_tidak_menyentuh_margin(self):
        updates = self._jalankan("gudang")
        self.assertEqual(len(updates), 1)
        self.assertNotIn("margin", updates[0])

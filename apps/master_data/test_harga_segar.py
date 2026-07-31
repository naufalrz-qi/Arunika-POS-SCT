"""Halaman Update Barang wajib menampilkan harga TERKINI.

Harga di m_barang_satuan sering diubah dari luar Arunika (aplikasi POS lama,
SSMS). Penulisan dari luar tidak memanggil invalidate_master_cache(), jadi harga
yang di-cache per profil akan basi sampai TTL habis (default 600 detik) — di
halaman yang justru dipakai untuk mengedit harga. Baris satuan/divisi karena itu
dibaca ulang tiap permintaan, dibatasi pada barang yang benar-benar tampil.

Peta nama (m_satuan/m_kategori/m_divisi) tetap boleh di-cache: isinya label, dan
basi 10 menit di sana tak menyesatkan siapa pun.

MS SQL tidak disentuh — cursor di-fake dan SQL yang dieksekusi direkam.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.master_data import services
from core import cache as corecache


class FakeProfile:
    def __init__(self, pk=1, db_type="grosir"):
        self.pk = pk
        self.db_type = db_type
        self.name = f"TEST {db_type}"


class FakeCursor:
    """Menjawab tiap SELECT di list_barang_edit dari `db` yang bisa diubah tes."""

    def __init__(self, db, sink):
        self.db = db
        self.sink = sink
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        self.sink.append((" ".join(sql.split()), list(params or [])))
        low = sql.lower()
        if "from m_barang_satuan" in low:
            self.description = [("kd_barang",), ("kd_satuan",), ("jumlah",),
                                ("harga_jual",), ("margin",), ("status",)]
            self._rows = [(kb, ks, 1, h, 0, "1") for (kb, ks), h in self.db["harga"].items()]
        elif "from m_barang_divisi" in low:
            self.description = [("kd_barang",), ("kd_divisi",), ("status",)]
            self._rows = [("A1", "D1", "1")]
        elif "from m_barang" in low:
            self.description = [("kd_barang",), ("kd_kategori",), ("nama",),
                                ("keterangan",), ("status",)]
            self._rows = [("A1", "K1", "BARANG SATU", "", "1")]
        elif "from m_satuan" in low:
            self.description = [("kd_satuan",), ("nama",)]
            self._rows = [("PCS", "Pieces")]
        elif "from m_kategori" in low:
            self.description = [("kd_kategori",), ("nama",)]
            self._rows = [("K1", "Kategori Satu")]
        elif "from m_divisi" in low:
            self.description = [("kd_divisi",), ("nama",)]
            self._rows = [("D1", "Divisi Satu")]
        else:  # pragma: no cover — penjaga, bukan jalur yang diuji
            raise AssertionError(f"SQL tak terduga: {sql}")
        return self

    def fetchall(self):
        return self._rows


class HargaSegarTest(SimpleTestCase):
    def setUp(self):
        corecache._master_cache.clear()
        self.addCleanup(corecache._master_cache.clear)
        self.db = {"harga": {("A1", "PCS"): 1000.0}}
        self.sql = []

    @contextmanager
    def _cursor(self, profile, autocommit=True, query_timeout=None):
        yield FakeCursor(self.db, self.sql)

    def _panggil(self, profile=None, cost=None):
        with patch.object(services.mssql, "cursor", self._cursor), \
             patch.object(services.mssql, "get_cost_source", return_value=cost):
            return services.list_barang_edit(profile or FakeProfile(), "BARANG")

    def _harga(self, rows):
        return rows[0]["satuan"][0]["harga_jual"]

    def test_harga_diubah_dari_luar_langsung_terlihat(self):
        self.assertEqual(self._harga(self._panggil()), 1000.0)
        # Aplikasi POS lama menulis harga baru — tanpa lewat Arunika, jadi tidak
        # ada invalidate_master_cache() yang terpanggil.
        self.db["harga"][("A1", "PCS")] = 2500.0
        self.assertEqual(self._harga(self._panggil()), 2500.0)

    def test_modal_dari_server_sumber_juga_segar(self):
        cost = FakeProfile(pk=99, db_type="gudang")
        rows = self._panggil(profile=FakeProfile(db_type="retail"), cost=cost)
        self.assertEqual(rows[0]["satuan"][0]["modal"], 1000.0)

        self.db["harga"][("A1", "PCS")] = 4000.0
        rows = self._panggil(profile=FakeProfile(db_type="retail"), cost=cost)
        self.assertEqual(rows[0]["satuan"][0]["modal"], 4000.0)

    def test_baca_satuan_dibatasi_barang_yang_tampil(self):
        """Bukan lagi scan penuh 55rb baris m_barang_satuan tiap permintaan."""
        self._panggil()
        satuan = [(sql, p) for sql, p in self.sql if "from m_barang_satuan" in sql.lower()]
        self.assertTrue(satuan, "m_barang_satuan tidak pernah dibaca")
        for sql, params in satuan:
            self.assertIn("kd_barang IN (SELECT TOP", sql)
            self.assertEqual(params, ["%BARANG%", "%BARANG%"])

    def test_penyaring_satuan_sama_dengan_penyaring_barang(self):
        """Kalau predikatnya menyimpang, satuan yang terbaca bukan milik barang
        yang tampil — dan itu tak akan terlihat sebagai error, cuma harga salah."""
        self._panggil()
        pakai = {}
        for sql, params in self.sql:
            low = sql.lower()
            for tabel in ("m_barang_satuan", "m_barang_divisi"):
                if f"from {tabel}" in low:
                    pakai[tabel] = (sql.split("WHERE", 1)[1], tuple(params))
        induk = next(
            (sql, tuple(p)) for sql, p in self.sql
            if "from m_barang " in sql.lower() and "top" in sql.lower()
        )
        induk_where = induk[0].split("WHERE", 1)[1].split("ORDER BY")[0].strip()
        for tabel, (where, params) in pakai.items():
            self.assertIn(induk_where, where, f"{tabel} menyaring dengan predikat lain")
            self.assertEqual(params, induk[1], f"{tabel} memakai parameter lain")

    def test_peta_nama_tetap_di_cache(self):
        self._panggil()
        awal = len([s for s, _ in self.sql if "from m_satuan" in s.lower()])
        self._panggil()
        ulang = len([s for s, _ in self.sql if "from m_satuan" in s.lower()])
        self.assertEqual(awal, 1)
        self.assertEqual(ulang, 1, "m_satuan seharusnya dilayani cache")

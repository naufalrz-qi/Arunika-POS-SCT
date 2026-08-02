"""Pusat data AMPHOREUS: invarian yang kalau rusak tidak memunculkan error.

Tiga di antaranya adalah bug yang benar-benar terjadi saat membangun ini, dan
ketiganya punya bentuk kegagalan yang sama: laporan tetap jalan, tidak ada
exception, angkanya saja yang salah.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.connections.models import ServerProfile
from apps.transactions import hub_schema, hub_sync


class SpecTests(SimpleTestCase):
    def test_tiap_spec_punya_kunci_atau_induk(self):
        for tabel, spec in hub_sync.HUB_TABLE_SPECS.items():
            self.assertTrue(
                bool(spec.get("key_columns")) ^ bool(spec.get("parent_key")),
                f"{tabel}: harus salah satu, bukan keduanya/tak satu pun",
            )

    def test_tiap_header_transaksi_menarik_detailnya(self):
        """Cabang bisa TIDAK mencatat feed detail sama sekali — terukur di PRAYA:
        285 t_penjualan__insert, nol t_penjualan_detail__insert. Kalau header tak
        menyeret detailnya, pusat berisi nota tanpa baris dan omzetnya nol tanpa
        satu pun error."""
        for header, detail in [
            ("t_penjualan", "t_penjualan_detail"),
            ("t_penjualan_retur", "t_penjualan_retur_detail"),
            ("t_pembelian", "t_pembelian_detail"),
            ("t_pembelian_retur", "t_pembelian_retur_detail"),
            ("t_mutasi_stok", "t_mutasi_stok_detail"),
            ("t_penjualan_order", "t_penjualan_order_detail"),
        ]:
            self.assertIn(detail, hub_sync.HUB_TABLE_SPECS[header].get("details", []), header)
            self.assertIn("parent_key", hub_sync.HUB_TABLE_SPECS[detail], detail)

    def test_tabel_detail_tidak_dapat_primary_key(self):
        """Satu nota sah punya dua baris untuk kd_barang yang sama (dua harga).
        PK (kd_sumber, no_transaksi, kd_barang) akan menolak nota yang benar."""
        kolom = [
            {"nama": "no_transaksi", "tipe": "varchar", "max_length": 20, "precision": 0, "scale": 0, "nullable": False},
            {"nama": "kd_barang", "tipe": "varchar", "max_length": 30, "precision": 0, "scale": 0, "nullable": True},
        ]
        ddl = hub_schema.ddl_tabel_detail("t_penjualan_detail", kolom, "no_transaksi")
        self.assertNotIn("PRIMARY KEY", ddl)
        self.assertIn("CREATE CLUSTERED INDEX", ddl)
        self.assertIn("[kd_sumber], [no_transaksi]", ddl)

    def test_kunci_pusat_selalu_diawali_kd_sumber(self):
        """no_transaksi bisa sama antar-cabang (RUMAK & RTL RUMAK sama-sama punya
        TR2608010005). PK tanpa kd_sumber membuat nota dua cabang saling menimpa
        — omzet hilang tanpa satu pun error."""
        kolom = [
            {"nama": "no_transaksi", "tipe": "varchar", "max_length": 20, "precision": 0, "scale": 0, "nullable": False},
            {"nama": "tanggal", "tipe": "datetime", "max_length": 8, "precision": 0, "scale": 0, "nullable": True},
        ]
        ddl = hub_schema.ddl_tabel("t_penjualan", kolom, ["no_transaksi"])
        self.assertIn("PRIMARY KEY CLUSTERED ([kd_sumber], [no_transaksi])", ddl)

    def test_kolom_kunci_dipaksa_not_null(self):
        """PK tidak bisa dibangun dari kolom nullable, dan baris berkunci NULL
        tak akan pernah bisa dicocokkan ulang di sync berikutnya."""
        kolom = [{"nama": "no_transaksi", "tipe": "varchar", "max_length": 20,
                  "precision": 0, "scale": 0, "nullable": True}]
        ddl = hub_schema.ddl_tabel("t_penjualan", kolom, ["no_transaksi"])
        self.assertIn("[no_transaksi] varchar(20) NOT NULL", ddl)

    def test_render_tipe(self):
        r = hub_schema._render_tipe
        self.assertEqual(r({"tipe": "varchar", "max_length": 30, "precision": 0, "scale": 0}), "varchar(30)")
        self.assertEqual(r({"tipe": "nvarchar", "max_length": 200, "precision": 0, "scale": 0}), "nvarchar(100)")
        self.assertEqual(r({"tipe": "varchar", "max_length": -1, "precision": 0, "scale": 0}), "varchar(max)")
        self.assertEqual(r({"tipe": "decimal", "max_length": 9, "precision": 19, "scale": 4}), "decimal(19,4)")
        self.assertEqual(r({"tipe": "datetime", "max_length": 8, "precision": 0, "scale": 0}), "datetime")


class TerapkanHeaderTests(SimpleTestCase):
    def _cur(self, ada=True, rowcount=1):
        cur = MagicMock()
        cur.rowcount = rowcount
        cur.fetchone.return_value = (1,) if ada else None
        return cur

    def test_kd_sumber_selalu_ikut_di_where_dan_insert(self):
        cur = self._cur(ada=False)
        hub_sync._terapkan_header(
            cur, "t_penjualan", hub_sync.HUB_TABLE_SPECS["t_penjualan"], "PRAYA",
            {"no_transaksi": "SP1"}, {"kd_customer": "C1"},
            ["kd_sumber", "no_transaksi", "kd_customer"],
        )
        cek_sql, cek_args = cur.execute.call_args_list[0][0]
        insert_sql, insert_args = cur.execute.call_args_list[1][0]
        self.assertIn("[kd_sumber] = ?", cek_sql)
        self.assertIn("PRAYA", cek_args)
        self.assertIn("[kd_sumber]", insert_sql)
        self.assertEqual(insert_args[0], "PRAYA")

    def test_rowcount_tidak_pernah_menentukan_ada_tidaknya_baris(self):
        """Bentuknya disamakan dengan `feed_sync` supaya bug trigger/rowcount
        tidak bisa kembali lewat pintu pusat. Lihat catatan lengkapnya di
        `test_feed_parse.test_rowcount_tidak_pernah_menentukan_ada_tidaknya_baris`."""
        cur = self._cur(ada=False, rowcount=1)
        hub_sync._terapkan_header(
            cur, "t_penjualan", hub_sync.HUB_TABLE_SPECS["t_penjualan"], "PRAYA",
            {"no_transaksi": "SP1"}, {"kd_customer": "C1"},
            ["kd_sumber", "no_transaksi", "kd_customer"],
        )
        perintah = [c[0][0].split()[0] for c in cur.execute.call_args_list]
        self.assertIn("INSERT", perintah)

    def test_kd_sumber_tidak_pernah_masuk_klausa_set(self):
        """Kalau payload kebetulan membawa kd_sumber, itu tidak boleh menimpa
        penanda cabang yang kita tetapkan sendiri."""
        cur = self._cur(ada=True)
        hub_sync._terapkan_header(
            cur, "t_penjualan", hub_sync.HUB_TABLE_SPECS["t_penjualan"], "PRAYA",
            {"no_transaksi": "SP1"}, {"kd_sumber": "PALSU", "kd_customer": "C1"},
            ["kd_sumber", "no_transaksi", "kd_customer"],
        )
        sql, args = cur.execute.call_args[0]
        self.assertNotIn("SET [kd_sumber]", sql)
        self.assertNotIn("PALSU", args)

    def test_nilai_selalu_lewat_parameter(self):
        """Pembeda satu-satunya dari `exec (@query)` di job legacy."""
        cur = self._cur(rowcount=1)
        jahat = "'; DROP TABLE t_penjualan; --"
        hub_sync._terapkan_header(
            cur, "t_penjualan", hub_sync.HUB_TABLE_SPECS["t_penjualan"], "PRAYA",
            {"no_transaksi": "SP1"}, {"kd_customer": jahat},
            ["kd_sumber", "no_transaksi", "kd_customer"],
        )
        sql, args = cur.execute.call_args[0]
        self.assertNotIn("DROP", sql)
        self.assertIn(jahat, args)

    def test_kunci_tak_lengkap_ditolak(self):
        cur = self._cur()
        with self.assertRaises(ValueError):
            hub_sync._terapkan_header(
                cur, "m_barang_satuan", hub_sync.HUB_TABLE_SPECS["m_barang_satuan"], "PRAYA",
                {"kd_barang": "X1"}, {"harga_jual": "1"},  # kd_satuan hilang
                ["kd_sumber", "kd_barang", "kd_satuan", "harga_jual"],
            )


class AmbilUlangDetailTests(SimpleTestCase):
    def test_hapus_per_nota_selalu_menyertakan_kd_sumber(self):
        """DELETE tanpa kd_sumber menghapus nota bernomor sama milik cabang lain."""
        src, hub = MagicMock(), MagicMock()
        src.fetchall.return_value = [("B1", "S1", 2.0)]
        hub_sync._ambil_ulang_detail(
            src, hub, "t_penjualan_detail", "no_transaksi", "PRAYA",
            {"SP1"}, ["kd_sumber", "kd_barang", "kd_satuan", "qty"],
        )
        sql, args = hub.execute.call_args[0]
        self.assertIn("[kd_sumber] = ?", sql)
        self.assertEqual(args, ["PRAYA", "SP1"])

    def test_nota_kosong_di_sumber_meninggalkan_nol_baris(self):
        """Nota yang dikosongkan di cabang harus jadi nol baris di pusat, bukan
        baris lama yang tertinggal."""
        src, hub = MagicMock(), MagicMock()
        src.fetchall.return_value = []
        hub_sync._ambil_ulang_detail(
            src, hub, "t_penjualan_detail", "no_transaksi", "PRAYA",
            {"SP1"}, ["kd_sumber", "kd_barang"],
        )
        hub.execute.assert_called_once()  # DELETE saja
        hub.executemany.assert_not_called()


class SyncSourceTests(TestCase):
    def setUp(self):
        self.src = ServerProfile.objects.create(
            name="CABANG", host="h1", db_name="D", username="sa", kode_sumber="CABANG"
        )
        self.hub = ServerProfile.objects.create(name="HUB", host="h2", db_name="AMPHOREUS", username="sa")

    @contextmanager
    def _cursor_palsu(self, *a, **kw):
        cur = MagicMock()
        cur.rowcount = 1
        cur.fetchone.return_value = [1]
        cur.fetchall.return_value = [("kd_barang",), ("no_transaksi",)]
        yield cur

    def _jalankan(self, feed, **kw):
        with patch.object(hub_sync.mssql, "cursor", self._cursor_palsu), \
                patch.object(hub_sync, "ambil_perubahan", return_value=feed), \
                patch.object(hub_sync, "_terapkan_header"), \
                patch.object(hub_sync, "_ambil_ulang_detail", return_value=1):
            return hub_sync.sync_source(self.src, self.hub, from_id=0, **kw)

    def test_cabang_tanpa_kode_sumber_dilewati(self):
        """Tanpa kode, barisnya tak bisa dibedakan dari cabang lain di pusat.
        Dilewati, bukan ditebak dari nama profil."""
        self.src.kode_sumber = ""
        self.src.save()
        hasil = hub_sync.sync_source(self.src, self.hub)
        self.assertEqual(hasil["status"], "tanpa_kode")
        self.assertEqual(hasil["diterapkan"], 0)

    def test_detail_tanpa_sufiks_aksi_tetap_diproses(self):
        """133 dari 2.000 baris feed PRAYA berupa detail tanpa sufiks aksi. Untuk
        tabel detail aksinya memang tak dipakai — selalu ambil ulang seluruh
        nota. Menolaknya berarti membuang perubahan yang sungguhan."""
        hasil = self._jalankan([
            {"id": 1, "table_aksi": "t_penjualan_detail", "formatted_data": "val__no_transaksi__SP1"},
        ])
        self.assertEqual(hasil["dilewati"], 0)
        self.assertEqual(hasil["diterapkan"], 1)

    def test_header_tanpa_sufiks_aksi_tetap_diproses(self):
        """Regresi: 42 baris `t_pembelian` ANDARIA tanpa sufiks aksi masuk
        dead-letter, padahal tak ada yang salah dengannya. Kelonggaran untuk
        aksi kosong dulu hanya diberikan ke tabel detail — padahal
        `_terapkan_header` juga tidak pernah peduli insert atau update: ia
        SELECT dulu, lalu UPDATE atau INSERT. Aksi kosong tidak ambigu."""
        hasil = self._jalankan([
            {"id": 4, "table_aksi": "t_pembelian", "formatted_data": "val__no_transaksi__GP1"},
        ])
        self.assertEqual(hasil["dilewati"], 0)
        self.assertEqual(hasil["diterapkan"], 1)

    def test_aksi_asing_pada_tabel_berkunci_tetap_ditolak(self):
        """Beda dari aksi kosong: bentuk yang sungguh-sungguh di luar dugaan
        harus terlihat, bukan ditebak jadi tulisan."""
        hasil = self._jalankan([
            {"id": 2, "table_aksi": "t_penjualan__entahlah", "formatted_data": "val__no_transaksi__SP1"},
        ])
        self.assertEqual(hasil["dilewati"], 1)

    def test_tabel_di_luar_izin_disaring_bukan_dead_letter(self):
        from apps.core.models import SyncDeadLetter

        hasil = self._jalankan([
            {"id": 3, "table_aksi": "t_biaya_operasional__insert", "formatted_data": "val__x__1"},
        ])
        self.assertEqual(hasil["disaring"], 1)
        self.assertEqual(hasil["dilewati"], 0)
        self.assertEqual(SyncDeadLetter.objects.count(), 0)

    def test_dry_run_tidak_memajukan_cursor(self):
        from apps.core.models import FeedSyncCursor

        self._jalankan(
            [{"id": 9, "table_aksi": "t_penjualan__insert", "formatted_data": "val__no_transaksi__SP1"}],
            dry_run=True,
        )
        self.assertEqual(FeedSyncCursor.objects.get().last_id, 0)

    def test_run_pertama_hanya_menetapkan_posisi(self):
        """Pusat sengaja mulai kosong: run pertama tidak boleh menarik jutaan
        baris riwayat sejak 2020."""
        from apps.core.models import FeedSyncCursor

        with patch.object(hub_sync, "posisi_awal", return_value=2763912):
            hasil = hub_sync.sync_source(self.src, self.hub)
        self.assertEqual(hasil["status"], "posisi_awal")
        self.assertEqual(FeedSyncCursor.objects.get().last_id, 2763912)

    def test_cabang_mati_saat_penetapan_posisi_tidak_menjatuhkan_run(self):
        """Regresi: ANDARIA mati (08001) pernah menjatuhkan SELURUH perintah,
        sehingga 8 cabang sehat tidak pernah jalan — hanya karena cabang itu
        pertama menurut abjad dan belum punya cursor. Penetapan posisi awal
        menyentuh jaringan, jadi harus ikut terlindung."""
        import pyodbc

        from apps.core.models import FeedSyncCursor

        with patch.object(hub_sync, "posisi_awal", side_effect=pyodbc.Error("08001", "timeout")):
            hasil = hub_sync.sync_source(self.src, self.hub)
        self.assertEqual(hasil["status"], "failed")
        self.assertIn("timeout", hasil["error"])
        # Cursor tercatat gagal, dan TIDAK maju.
        row = FeedSyncCursor.objects.get()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.last_id, 0)

    def test_satu_cabang_mati_tidak_menahan_yang_lain(self):
        import pyodbc

        sehat = ServerProfile.objects.create(
            name="SEHAT", host="h3", db_name="D", username="sa", kode_sumber="SEHAT"
        )
        with patch.object(hub_sync, "posisi_awal", side_effect=[pyodbc.Error("08001", "mati"), 500]):
            hasil = hub_sync.sync_all(self.hub, [self.src, sehat])
        self.assertEqual([r["status"] for r in hasil], ["failed", "posisi_awal"])

    def test_cursor_tidak_maju_saat_gagal_di_tengah(self):
        """Cursor yang maju melewati perubahan yang belum sempat ditulis
        meninggalkan lubang yang tidak akan pernah terisi sendiri. Mengulang
        batch yang sama aman — apply-nya idempoten."""
        import pyodbc

        from apps.core.models import FeedSyncCursor

        FeedSyncCursor.objects.create(
            source_profile=self.src, target_profile=self.hub, last_id=100
        )
        with patch.object(hub_sync.mssql, "cursor", side_effect=pyodbc.Error("08S01", "putus")):
            hasil = hub_sync.sync_source(self.src, self.hub)
        self.assertEqual(hasil["status"], "failed")
        self.assertEqual(FeedSyncCursor.objects.get().last_id, 100)

    def test_dry_run_tidak_menetapkan_posisi_awal(self):
        from apps.core.models import FeedSyncCursor

        with patch.object(hub_sync, "posisi_awal", return_value=2763912):
            hub_sync.sync_source(self.src, self.hub, dry_run=True)
        self.assertEqual(FeedSyncCursor.objects.get().last_id, 0)

"""Parser feed + daftar-izin `feed_sync`.

Yang diuji di sini adalah dua hal yang membuat jalur ini lebih aman daripada
sync legacy: nilai yang mengandung karakter pemisah tidak rusak (legacy merusaknya
lewat ~20 REPLACE berantai tanpa jaminan bolak-balik), dan tabel di luar
daftar-izin tidak pernah tersentuh (legacy menjalankan apa pun yang dikirim).

Contoh `formatted_data` di bawah disalin dari feed GUDANG yang sebenarnya.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.transactions import feed_sync as fs


class ParseTableAksiTests(SimpleTestCase):
    def test_bentuk_biasa(self):
        self.assertEqual(fs.parse_table_aksi("m_barang__update"), ("m_barang", "update"))
        self.assertEqual(fs.parse_table_aksi("m_barang_satuan__insert"), ("m_barang_satuan", "insert"))

    def test_tanpa_sufiks_aksi_tidak_ditebak(self):
        """Ada 5.010 baris `t_pembelian_detail` polos di feed nyata. Menebaknya
        sebagai insert adalah cara paling rapi merusak data diam-diam."""
        self.assertEqual(fs.parse_table_aksi("t_pembelian_detail"), ("t_pembelian_detail", ""))
        self.assertEqual(fs.parse_table_aksi(""), ("", ""))

    def test_nama_tabel_bergaris_bawah_ganda_tetap_utuh(self):
        """rpartition, bukan partition: `m_barang_satuan__update` harus jadi
        tabel `m_barang_satuan`, bukan `m_barang_satuan__update` dipotong di
        pemisah pertama yang salah."""
        tabel, aksi = fs.parse_table_aksi("t_penjualan_retur_detail__insert")
        self.assertEqual(tabel, "t_penjualan_retur_detail")
        self.assertEqual(aksi, "insert")


class ParseFormattedDataTests(SimpleTestCase):
    def test_insert_semua_val_tanpa_key(self):
        kunci, nilai = fs.parse_formatted_data(
            "val__kd_merk__MAB482;val__nama__YOU;val__keterangan__-;val__status__1;val__divisi_id__DAA000"
        )
        self.assertEqual(kunci, {})
        self.assertEqual(nilai["kd_merk"], "MAB482")
        self.assertEqual(nilai["nama"], "YOU")
        self.assertEqual(nilai["divisi_id"], "DAA000")

    def test_update_memisahkan_key_dari_val(self):
        """Baris `__update` menandai kolom kuncinya dengan prefiks `key__`.
        Kalau itu tidak dibedakan, kunci ikut masuk klausa SET dan barisnya
        menimpa dirinya sendiri dengan kunci yang sama — atau lebih buruk,
        tidak ada kunci sama sekali untuk WHERE."""
        kunci, nilai = fs.parse_formatted_data(
            "key__kd_barang__SSRPCS005;key__kd_satuan__SAA000;"
            "val__jumlah__1;val__harga_jual__3000.00;val__status__1"
        )
        self.assertEqual(kunci, {"kd_barang": "SSRPCS005", "kd_satuan": "SAA000"})
        self.assertEqual(set(nilai), {"jumlah", "harga_jual", "status"})

    def test_nilai_boleh_mengandung_titik_koma(self):
        """Pemisahan record memakai batas `;(?=key|val__)`, bukan split(';').
        Nama barang yang mengandung `;` akan terpotong jadi field palsu kalau
        tidak."""
        _, nilai = fs.parse_formatted_data(
            "val__kd_barang__X1;val__nama__BOX A; B; C;val__status__1"
        )
        self.assertEqual(nilai["nama"], "BOX A; B; C")
        self.assertEqual(nilai["status"], "1")

    def test_nilai_boleh_mengandung_garis_bawah_ganda(self):
        """Dipotong di `__` PERTAMA sesudah prefiks; sisanya utuh jadi nilai."""
        _, nilai = fs.parse_formatted_data("val__nama__SISIR__GAGANG__BIJIAN")
        self.assertEqual(nilai["nama"], "SISIR__GAGANG__BIJIAN")

    def test_nilai_kosong_jadi_string_kosong(self):
        _, nilai = fs.parse_formatted_data("val__kd_barang__X1;val__keterangan__")
        self.assertEqual(nilai["keterangan"], "")

    def test_potongan_tak_berprefiks_dilewati(self):
        _, nilai = fs.parse_formatted_data("sampah;val__kd_barang__X1")
        self.assertEqual(nilai, {"kd_barang": "X1"})

    def test_kosong_aman(self):
        self.assertEqual(fs.parse_formatted_data(""), ({}, {}))
        self.assertEqual(fs.parse_formatted_data(None), ({}, {}))

    def test_baris_nyata_m_barang_update_utuh(self):
        """Payload sungguhan dari GUDANG: 1 key + 12 val = 13 kolom, sama dengan
        jumlah kolom m_barang. Update di feed ini membawa baris utuh."""
        kunci, nilai = fs.parse_formatted_data(
            "key__kd_barang__SSRPCS005;val__kd_kategori__KAA022;val__kd_jenis_bahan__JAA004;"
            "val__kd_model__MAA003;val__kd_merk__MAA705;val__kd_warna__WAA481;val__ukuran__4;"
            "val__nama__SISIR KEPALA GAGANG BIJIAN;val__keterangan__-;val__status__1;"
            "val__point__0;val__kd_satuan__SAA000;val__divisi_id__DAA000"
        )
        self.assertEqual(len(kunci) + len(nilai), 13)
        self.assertEqual(nilai["nama"], "SISIR KEPALA GAGANG BIJIAN")


class DaftarIzinTests(SimpleTestCase):
    def test_tabel_transaksi_tidak_didaftarkan(self):
        """Transaksi milik server yang membuatnya. Kalau ini pernah masuk
        daftar, penjualan gudang akan tersalin jadi penjualan tiap toko."""
        for tabel in ("t_penjualan", "t_penjualan_detail", "t_pembelian", "t_opname_stok"):
            self.assertNotIn(tabel, fs.FEED_TABLE_SPECS)

    def test_m_barang_divisi_tidak_didaftarkan(self):
        """Membawa stok_awal / stok_min / harga_beli_awal yang milik tiap toko.
        Kalau nanti dibutuhkan, daftarkan dengan `columns` eksplisit — bukan None."""
        self.assertNotIn("m_barang_divisi", fs.FEED_TABLE_SPECS)

    def test_setiap_spec_punya_kolom_kunci(self):
        for tabel, spec in fs.FEED_TABLE_SPECS.items():
            self.assertTrue(spec.get("key_columns"), tabel)


class TerapkanBarisTests(SimpleTestCase):
    """`_terapkan_baris` dengan cursor tiruan — yang diperiksa SQL yang disusun."""

    def _cur(self, ada=True, rowcount=1):
        """Cursor tiruan. `ada` = apakah SELECT keberadaan menemukan barisnya.

        `rowcount` sengaja bisa diatur terpisah dari `ada`: itulah yang
        membedakan kode benar dari kode lama — yang benar tidak boleh menoleh ke
        rowcount sama sekali.
        """
        cur = MagicMock()
        cur.rowcount = rowcount
        cur.fetchone.return_value = (1,) if ada else None
        return cur

    def test_divisi_id_dibuang_karena_bukan_kolom_tabel(self):
        """Trigger menambahkan val__divisi_id ke hampir semua payload, padahal
        m_barang_satuan tidak punya kolom itu. Tanpa irisan dengan katalog
        tujuan, setiap INSERT gagal."""
        cur = self._cur(ada=True)
        fs._terapkan_baris(
            cur, "m_barang_satuan", fs.FEED_TABLE_SPECS["m_barang_satuan"],
            {"kd_barang": "X1", "kd_satuan": "SAA000"},
            {"harga_jual": "3000.00", "divisi_id": "DAA000"},
            ["kd_barang", "kd_satuan", "harga_jual", "jumlah", "status", "margin"],
        )
        sql = cur.execute.call_args[0][0]
        self.assertNotIn("divisi_id", sql)
        self.assertIn("harga_jual", sql)

    def test_baris_baru_di_insert(self):
        cur = self._cur(ada=False)
        fs._terapkan_baris(
            cur, "m_merk", fs.FEED_TABLE_SPECS["m_merk"],
            {}, {"kd_merk": "MAB482", "nama": "YOU"},
            ["kd_merk", "nama", "status"],
        )
        perintah = [c[0][0].split()[0] for c in cur.execute.call_args_list]
        self.assertEqual(perintah, ["SELECT", "INSERT"])

    def test_baris_yang_sudah_ada_di_update_bukan_di_insert(self):
        cur = self._cur(ada=True)
        fs._terapkan_baris(
            cur, "m_merk", fs.FEED_TABLE_SPECS["m_merk"],
            {}, {"kd_merk": "MAB482", "nama": "YOU"},
            ["kd_merk", "nama", "status"],
        )
        perintah = [c[0][0].split()[0] for c in cur.execute.call_args_list]
        self.assertEqual(perintah, ["SELECT", "UPDATE"])

    def test_rowcount_tidak_pernah_menentukan_ada_tidaknya_baris(self):
        """Regresi, dan bug ini terukur di testgudang.

        Tabel di server toko punya trigger legacy. Trigger AFTER UPDATE tetap
        menyala walau UPDATE mengenai NOL baris, dan `INSERT INTO tbl_tmp_post`
        di dalamnya membuat `cur.rowcount` terbaca 1. Kode lama menyimpulkan
        "sudah ter-update" lalu melewatkan INSERT — barang baru tidak pernah
        sampai ke toko, tanpa error, tanpa dead-letter, dan tetap terhitung
        "diterapkan".

        Di sini barisnya TIDAK ada (`ada=False`) tapi rowcount berbohong 1.
        INSERT tetap wajib terjadi.
        """
        cur = self._cur(ada=False, rowcount=1)
        fs._terapkan_baris(
            cur, "m_barang", fs.FEED_TABLE_SPECS["m_barang"],
            {}, {"kd_barang": "GTK315", "nama": "GITAR KAYU"},
            ["kd_barang", "nama"],
        )
        perintah = [c[0][0].split()[0] for c in cur.execute.call_args_list]
        self.assertIn("INSERT", perintah)

    def test_kunci_tidak_ikut_klausa_set(self):
        cur = self._cur(ada=True)
        fs._terapkan_baris(
            cur, "m_barang", fs.FEED_TABLE_SPECS["m_barang"],
            {"kd_barang": "X1"}, {"nama": "A"}, ["kd_barang", "nama"],
        )
        sql = cur.execute.call_args[0][0]
        self.assertEqual(sql.count("kd_barang"), 1)  # hanya di WHERE
        self.assertIn("WHERE kd_barang = ?", sql)

    def test_nilai_selalu_lewat_parameter(self):
        """Tidak ada isi feed yang pernah masuk ke teks SQL. Inilah satu-satunya
        hal yang membedakan modul ini dari `exec (@query)` di job legacy."""
        cur = self._cur(ada=True)
        jahat = "'; DROP TABLE m_barang; --"
        fs._terapkan_baris(
            cur, "m_barang", fs.FEED_TABLE_SPECS["m_barang"],
            {"kd_barang": "X1"}, {"nama": jahat}, ["kd_barang", "nama"],
        )
        sql, params = cur.execute.call_args[0]
        self.assertNotIn("DROP", sql)
        self.assertIn(jahat, params)

    def test_kunci_tak_lengkap_ditolak(self):
        """Kunci menurut spec, bukan menurut prefiks `key__` di payload.

        Kalau payload yang menentukan, baris ini menghasilkan
        `WHERE kd_barang = ?` tanpa `kd_satuan` — dan satu perubahan harga
        menimpa SELURUH satuan barang itu. Harus gagal terlihat, bukan melebar
        diam-diam.
        """
        cur = self._cur()
        with self.assertRaises(ValueError):
            fs._terapkan_baris(
                cur, "m_barang_satuan", fs.FEED_TABLE_SPECS["m_barang_satuan"],
                {"kd_barang": "X1"}, {"harga_jual": "1"},  # kd_satuan hilang
                ["kd_barang", "kd_satuan", "harga_jual"],
            )


class DisaringVsDeadLetterTests(TestCase):
    """Baris yang tabelnya di luar daftar-izin DISARING, tidak di-dead-letter.

    Pada uji nyata 2.566 dari 3.000 baris feed berada di luar daftar-izin — itu
    penyaringan yang disengaja, bukan kerusakan. Mencatat tiap satunya menimbun
    ribuan baris tiap tick dan menenggelamkan kegagalan yang sungguhan, sehingga
    tabel dead-letter berhenti berarti apa-apa.
    """

    def setUp(self):
        from apps.connections.models import ServerProfile

        self.src = ServerProfile.objects.create(name="SUM", host="h1", db_name="D", username="sa")
        self.dst = ServerProfile.objects.create(name="TUJ", host="h2", db_name="D", username="sa")

    @contextmanager
    def _cursor_palsu(self, *a, **kw):
        cur = MagicMock()
        cur.rowcount = 1
        cur.fetchone.return_value = [1]
        cur.fetchall.return_value = [("kd_merk",), ("nama",)]
        yield cur

    def test_tabel_di_luar_izin_tidak_menulis_dead_letter(self):
        from apps.core.models import SyncDeadLetter

        feed = [
            {"id": 10, "table_aksi": "t_penjualan_detail__insert", "formatted_data": "val__x__1"},
            {"id": 11, "table_aksi": "m_barang_divisi__update", "formatted_data": "val__x__1"},
            {"id": 12, "table_aksi": "m_merk__insert", "formatted_data": "val__kd_merk__M1;val__nama__A"},
        ]
        with patch.object(fs.mssql, "cursor", self._cursor_palsu), \
                patch.object(fs, "ambil_perubahan", return_value=feed):
            hasil = fs.sync_pair(self.src, self.dst, from_id=0)

        self.assertEqual(hasil["disaring"], 2)
        self.assertEqual(hasil["dilewati"], 0)
        self.assertEqual(hasil["diterapkan"], 1)
        self.assertEqual(SyncDeadLetter.objects.count(), 0)
        self.assertIn("tabel 't_penjualan_detail' di luar daftar-izin", hasil["alasan"])

    def test_aksi_tak_dikenal_pada_tabel_terdaftar_masuk_dead_letter(self):
        """Beda kasus: tabelnya MEMANG difan-out tapi bentuk barisnya tak terduga.
        Itu layak disimpan — feed nyata punya baris tanpa sufiks aksi."""
        from apps.core.models import SyncDeadLetter

        feed = [{"id": 20, "table_aksi": "m_merk", "formatted_data": "val__kd_merk__M1"}]
        with patch.object(fs.mssql, "cursor", self._cursor_palsu), \
                patch.object(fs, "ambil_perubahan", return_value=feed):
            hasil = fs.sync_pair(self.src, self.dst, from_id=0)

        self.assertEqual(hasil["dilewati"], 1)
        self.assertEqual(SyncDeadLetter.objects.count(), 1)

    def test_nilai_diambil_dari_sumber_bukan_dari_payload(self):
        """Trigger legacy MEMOTONG sebagian kolom saat menyusun payload:
        `m_barang.keterangan` di feed tidak pernah lebih dari 30 karakter,
        padahal kolomnya varchar(50) dan tabelnya menyimpan 45. Menulis dari
        payload akan memendekkan keterangan yang sudah benar di toko.

        Di sini payload membawa nilai terpotong, sumber membawa nilai utuh. Yang
        ditulis harus yang utuh.
        """
        terpotong = "1KOTAK 88.800(24PC)BELI PERKOL"
        utuh = "1KOTAK 88.800(24PC)BELI PERKOLIAN HRG 525.600"
        feed = [{
            "id": 40, "table_aksi": "m_barang__update",
            "formatted_data": f"key__kd_barang__SBN336;val__keterangan__{terpotong}",
        }]
        ditulis = {}

        def rekam(cur, tabel, spec, kunci, nilai, kolom_ada):
            ditulis.update(nilai)

        with patch.object(fs.mssql, "cursor", self._cursor_palsu), \
                patch.object(fs, "ambil_perubahan", return_value=feed), \
                patch.object(fs, "_kolom_sumber", return_value=["kd_barang", "keterangan"]), \
                patch.object(fs, "_baca_dari_sumber",
                             return_value={"kd_barang": "SBN336", "keterangan": utuh}), \
                patch.object(fs, "_terapkan_baris", side_effect=rekam):
            fs.sync_pair(self.src, self.dst, from_id=0)

        self.assertEqual(ditulis["keterangan"], utuh)
        self.assertNotEqual(ditulis["keterangan"], terpotong)

    def test_baris_yang_hilang_di_sumber_tidak_dihapus_di_tujuan(self):
        """Feed master tidak pernah membawa aksi delete, jadi "tak ketemu di
        sumber" lebih mungkin berarti kita salah baca daripada perintah
        menghapus. Dihitung, tidak ditindak."""
        feed = [{
            "id": 41, "table_aksi": "m_merk__update",
            "formatted_data": "key__kd_merk__MAB999",
        }]
        with patch.object(fs.mssql, "cursor", self._cursor_palsu), \
                patch.object(fs, "ambil_perubahan", return_value=feed), \
                patch.object(fs, "_kolom_sumber", return_value=["kd_merk"]), \
                patch.object(fs, "_baca_dari_sumber", return_value=None), \
                patch.object(fs, "_terapkan_baris") as tulis:
            hasil = fs.sync_pair(self.src, self.dst, from_id=0)
        tulis.assert_not_called()
        self.assertEqual(hasil["dilewati_hilang"], 1)
        self.assertEqual(hasil["dilewati"], 0)

    def test_edit_berulang_pada_kunci_sama_jadi_satu_tulisan(self):
        """Tiga edit pada barang yang sama dalam satu batch cukup satu tulisan —
        keadaan terkini dibaca sekali dari sumber."""
        feed = [
            {"id": 50 + i, "table_aksi": "m_merk__update", "formatted_data": "key__kd_merk__M1"}
            for i in range(3)
        ]
        with patch.object(fs.mssql, "cursor", self._cursor_palsu), \
                patch.object(fs, "ambil_perubahan", return_value=feed), \
                patch.object(fs, "_kolom_sumber", return_value=["kd_merk"]), \
                patch.object(fs, "_baca_dari_sumber", return_value={"kd_merk": "M1"}), \
                patch.object(fs, "_terapkan_baris") as tulis:
            hasil = fs.sync_pair(self.src, self.dst, from_id=0)
        self.assertEqual(tulis.call_count, 1)
        self.assertEqual(hasil["diterapkan"], 1)

    def test_dry_run_tidak_memajukan_cursor(self):
        from apps.core.models import FeedSyncCursor

        feed = [{"id": 30, "table_aksi": "m_merk__insert", "formatted_data": "val__kd_merk__M1;val__nama__A"}]
        with patch.object(fs.mssql, "cursor", self._cursor_palsu), \
                patch.object(fs, "ambil_perubahan", return_value=feed):
            fs.sync_pair(self.src, self.dst, from_id=0, dry_run=True)
        self.assertEqual(FeedSyncCursor.objects.get().last_id, 0)

    def test_dry_run_tidak_menetapkan_posisi_awal(self):
        """Pratinjau tidak boleh diam-diam meng-arm pasangan ini: run sungguhan
        berikutnya harus mulai dari keputusan sadar, bukan dari titik yang
        kebetulan dipilih sebuah dry run."""
        from apps.core.models import FeedSyncCursor

        with patch.object(fs, "posisi_awal", return_value=999):
            hasil = fs.sync_pair(self.src, self.dst, dry_run=True)
        self.assertEqual(hasil["status"], "posisi_awal")
        self.assertEqual(FeedSyncCursor.objects.get().last_id, 0)

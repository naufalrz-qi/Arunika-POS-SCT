"""Tarik-langsung ke AMPHOREUS: invarian yang kalau rusak tidak memunculkan error.

Semuanya berbentuk sama seperti bug-bug yang sudah pernah terjadi di jalur sync
ini: tidak ada exception, laporan tetap jalan, angkanya saja yang salah.
"""
import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import hub_master, hub_pull, hub_sync


class KursorPalsu:
    """Kursor yang mencatat SQL dan mengembalikan hasil yang sudah diantrekan."""

    def __init__(self, hasil=None):
        self.sql = []
        self.params = []
        self._antre = list(hasil or [])
        self.rowcount = 0
        self.inputsizes = None

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(list(params or []))

    def fetchall(self):
        return self._antre.pop(0) if self._antre else []

    def fetchone(self):
        baris = self._antre.pop(0) if self._antre else None
        return baris[0] if isinstance(baris, list) and baris else baris

    def executemany(self, sql, seq):
        self.sql.append(sql)
        self.params.append(list(seq))

    def setinputsizes(self, ukuran):
        # Dicatat, bukan diabaikan: ikatan VARCHAR inilah yang membuat daftar
        # `IN` panjang tetap seek — tanpanya satu batch 500 nota memakan 60 detik
        # di ANDARIA dan seluruh sync cabang itu gagal.
        self.inputsizes = ukuran


class DaftarTabelTests(SimpleTestCase):
    def test_daftar_diturunkan_dari_spec_bukan_ditulis_ulang(self):
        """Daftar kedua adalah cara paling pasti agar skema pusat dan isi sync
        berbeda tanpa ada yang tahu."""
        self.assertIn("t_penjualan", hub_pull.TABEL_HEADER)
        self.assertTrue(set(hub_pull.TABEL_HEADER) <= set(hub_sync.HUB_TABLE_SPECS))

    def test_detail_milik_header_tidak_disapu_sendiri(self):
        """`t_penjualan_detail` diseret headernya. Menyapunya lagi sebagai rentang
        berarti menghapus-dan-menyalin tiap nota dua kali."""
        self.assertNotIn("t_penjualan_detail", hub_pull.TABEL_RENTANG)

    def test_opname_disapu_sendiri(self):
        """`t_opname_stok` berbentuk detail tapi tidak dimiliki header mana pun.
        Kalau ia tidak masuk daftar rentang, opname tidak pernah sampai ke pusat."""
        self.assertIn("t_opname_stok", hub_pull.TABEL_RENTANG)

    def test_master_tidak_ikut_tersapu_per_tanggal(self):
        semua = set(hub_pull.TABEL_HEADER) | set(hub_pull.TABEL_RENTANG)
        self.assertFalse([t for t in semua if t.startswith("m_")])


class RentangTests(SimpleTestCase):
    def test_memakai_kedua_kolom_waktu_dengan_or(self):
        """Terukur: 13 dari 927 baris GUDANG dan 13 dari 8.742 baris PUSAT punya
        `tanggal_server` beda HARI dari `tanggal` — nota bertanggal mundur yang
        diinput belakangan. Menyaring `tanggal` saja melewatkannya tanpa suara."""
        sql, params = hub_pull._where_rentang(
            ["tanggal", "tanggal_server"], dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1)
        )
        self.assertIn(" OR ", sql)
        self.assertIn("[tanggal]", sql)
        self.assertIn("[tanggal_server]", sql)
        self.assertEqual(len(params), 4)

    def test_tidak_pernah_and(self):
        """AND akan menuntut kedua kolom masuk rentang sekaligus — justru
        kebalikan dari yang dibutuhkan."""
        sql, _ = hub_pull._where_rentang(
            ["tanggal", "tanggal_server"], dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1)
        )
        self.assertNotIn(" AND ", sql.replace(">= ? AND [", ">= ? & ["))

    def test_batas_atas_dipagari(self):
        """ANDARIA punya nota bertanggal 7252-01-09. Tanpa pagar, satu typo tahun
        menyeret agregat harian jadi ribuan hari kosong."""
        _, params = hub_pull._where_rentang(
            ["tanggal"], dt.datetime(2026, 1, 1), dt.datetime(9999, 1, 1)
        )
        self.assertEqual(params[1], hub_pull.TANGGAL_MAKS)

    def test_tabel_tanpa_kolom_tanggal_ditolak(self):
        with self.assertRaises(RuntimeError):
            hub_pull._where_rentang([], dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1))


class JendelaTests(SimpleTestCase):
    def test_dihitung_dari_jam_server_bukan_max_tanggal(self):
        """`MAX(tanggal)` di ANDARIA bernilai tahun 7252; jendela yang dihitung
        dari situ berhenti menyapu apa pun selamanya."""
        cur = KursorPalsu([[(dt.date(2026, 7, 29),)]])
        hub_pull._awal_jendela(cur, 7)
        self.assertIn("GETDATE()", cur.sql[0])
        self.assertNotIn("MAX(", cur.sql[0])

    def test_selalu_datetime_bukan_date(self):
        """`CAST(... AS date)` kembali sebagai `datetime.date`; mencampurnya dengan
        `datetime` melempar TypeError di `min()` — di jalur yang hanya jalan saat
        scheduler menyala, jadi tak terlihat sampai produksi."""
        cur = KursorPalsu([[(dt.date(2026, 7, 29),)]])
        hasil = hub_pull._awal_jendela(cur, 7)
        self.assertIsInstance(hasil, dt.datetime)
        # Terbukti bisa dipakai berdampingan dengan batas atas datetime.
        self.assertLess(hasil, hub_pull.TANGGAL_MAKS)


class PotonganTests(SimpleTestCase):
    def test_hari_bersambung_digabung(self):
        hari = [dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3), dt.date(2026, 1, 9)]
        self.assertEqual(
            hub_pull._gabung_hari(hari),
            [(dt.date(2026, 1, 1), dt.date(2026, 1, 3)), (dt.date(2026, 1, 9), dt.date(2026, 1, 9))],
        )

    def test_arsip_dipotong_per_bulan(self):
        """Satu TAHUN PUSAT = ~90.000 header + ~600.000 detail dalam satu
        transaksi lewat WAN. Satu error di menit ke-40 membuang seluruhnya.
        Per bulan, yang hilang cuma sebulan."""
        potongan = hub_pull._per_bulan(dt.datetime(2024, 11, 1), dt.datetime(2025, 2, 1))
        self.assertEqual(len(potongan), 3)
        self.assertEqual(potongan[0], (dt.datetime(2024, 11, 1), dt.datetime(2024, 12, 1)))
        # Pergantian tahun tidak boleh menghasilkan bulan ke-13.
        self.assertEqual(potongan[-1], (dt.datetime(2025, 1, 1), dt.datetime(2025, 2, 1)))

    def test_potongan_bulanan_menutup_seluruh_rentang_tanpa_celah(self):
        potongan = hub_pull._per_bulan(dt.datetime(2024, 1, 1), dt.datetime(2024, 6, 15))
        for a, b in zip(potongan, potongan[1:]):
            self.assertEqual(a[1], b[0], "ada celah/tumpang tindih antar potongan")
        self.assertEqual(potongan[-1][1], dt.datetime(2024, 6, 15))

    def test_arsip_dipotong_per_tahun(self):
        """445.167 nota PUSAT dalam satu transaksi lewat WAN adalah cara paling
        pasti kehilangan seluruh pekerjaan di menit ke-40."""
        potongan = hub_pull._per_tahun(dt.datetime(2022, 6, 1), dt.datetime(2024, 3, 1))
        self.assertEqual(len(potongan), 3)
        self.assertEqual(potongan[0][0], dt.datetime(2022, 6, 1))
        self.assertEqual(potongan[-1][1], dt.datetime(2024, 3, 1))


class CobaUlangTests(SimpleTestCase):
    def test_gagal_sesaat_diulang(self):
        """PRAYA gagal `[08001] wait operation timed out` lalu konek 0,7 detik
        kemudian tanpa ada yang berubah — dan blip sesaat itu membuang seluruh
        cabang. Aman diulang karena tiap mode idempoten dan hanya mengerjakan
        sisanya."""
        hasil = [
            {**hub_pull._hasil_kosong(type("P", (), {"name": "PRAYA", "kode_sumber": "PRAYA"})()),
             "status": "failed", "error": "blip"},
            hub_pull._hasil_kosong(type("P", (), {"name": "PRAYA", "kode_sumber": "PRAYA"})()),
        ]
        with patch.object(hub_pull, "pull_segar", side_effect=hasil) as m, \
             patch.object(hub_pull, "JEDA_ULANG", 0):
            akhir = hub_pull.pull_source(object(), object(), mode="segar", dry_run=True)
        self.assertEqual(m.call_count, 2)
        self.assertEqual(akhir["status"], "ok")

    def test_berhenti_sesudah_batas(self):
        """Server yang benar-benar mati tidak boleh diulang selamanya."""
        gagal = {**hub_pull._hasil_kosong(type("P", (), {"name": "X", "kode_sumber": "X"})()),
                 "status": "failed", "error": "mati"}
        with patch.object(hub_pull, "pull_segar", return_value=gagal) as m, \
             patch.object(hub_pull, "JEDA_ULANG", 0):
            akhir = hub_pull.pull_source(object(), object(), mode="segar", dry_run=True, coba=3)
        self.assertEqual(m.call_count, 3)
        self.assertEqual(akhir["status"], "failed")


class TitikLanjutTests(SimpleTestCase):
    """Run pertama kehilangan 285.809 header PUSAT karena jaringan putus di
    potongan 32 dari 48 dan tidak ada penanda 31 potongan sebelumnya selesai."""

    def test_dibaca_sebagai_jam_lokal_bukan_utc(self):
        """USE_TZ=True menyimpan UTC; batas potongan naif jam lokal. Selisih 8 jam
        membuat potongan yang BELUM selesai bisa terbaca sudah, lalu dilewati
        diam-diam — lubang data tanpa satu pun error."""
        import datetime as _dt

        from django.utils import timezone as tz

        lokal = tz.make_aware(_dt.datetime(2024, 8, 1, 0, 0))
        with patch.object(hub_pull.HubPullState.objects, "filter") as f:
            f.return_value.first.return_value = type("R", (), {"arsip_sampai": lokal})()
            hasil = hub_pull._titik_lanjut(object(), object())
        self.assertEqual(hasil, _dt.datetime(2024, 8, 1, 0, 0))
        self.assertIsNone(hasil.tzinfo)


class NotaLenyapTests(SimpleTestCase):
    """Feed hanya memuat __insert/__update, jadi nota yang DIBATALKAN di cabang
    tertinggal jadi hantu di pusat: jumlah nota benar, omzetnya salah. Ini
    satu-satunya jalur yang bisa memperbaikinya."""

    def _jalankan(self, kunci_pusat):
        """-> (hub_cursor, mock _ambil_ulang_detail, hasil).

        Diuji lewat PERILAKU, bukan bentuk SQL-nya: header nota lenyap ikut
        terhapus oleh DELETE rentang, sementara DETAIL-nya harus dibersihkan
        terpisah — dan yang terakhir itulah yang mudah hilang saat kodenya
        dioptimalkan.
        """
        src = KursorPalsu([[("TR001",)]])          # cabang: hanya TR001 tersisa
        hub = KursorPalsu([[(k,) for k in kunci_pusat]])
        with patch.object(hub_pull, "_kolom_tujuan", return_value=["kd_sumber", "no_transaksi"]), \
             patch.object(hub_pull, "_kolom_waktu", return_value=["tanggal"]), \
             patch.object(hub_pull, "_ambil_ulang_detail", return_value=0) as detail:
            hasil = hub_pull._salin_header(
                src, hub, "t_penjualan", "PRAYA",
                dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1),
            )
        return hub, detail, hasil

    def _parent_dibersihkan(self, detail):
        """Nota yang detailnya dihapus = panggilan _ambil_ulang_detail SESUDAH
        panggilan untuk nota yang masih hidup."""
        return [p for c in detail.call_args_list for p in c[0][5]]

    def test_nota_yang_hilang_di_cabang_dihapus_di_pusat(self):
        _, detail, hasil = self._jalankan(["TR001", "TR999"])
        self.assertEqual(hasil["dihapus"], 1)
        self.assertIn("TR999", self._parent_dibersihkan(detail))

    def test_nota_yang_masih_ada_tidak_ikut_dibersihkan(self):
        _, detail, hasil = self._jalankan(["TR001"])
        self.assertEqual(hasil["dihapus"], 0)
        # TR001 tetap boleh muncul (detailnya disalin ulang), yang penting tak
        # ada nota yang dihitung lenyap.
        self.assertEqual(hasil["header"], 1)

    def test_beda_huruf_besar_dan_spasi_ekor_bukan_nota_hilang(self):
        """Collation SQL Server mengabaikan huruf besar-kecil dan spasi ekor, set
        Python tidak. Tanpa `_k()`, nota yang sama terbaca hilang lalu detailnya
        dihapus dan ditulis ulang tiap run selamanya."""
        _, _, hasil = self._jalankan(["tr001  "])
        self.assertEqual(hasil["dihapus"], 0)

    def test_rentang_diganti_bukan_diperiksa_per_baris(self):
        """Bentuk cek-lalu-UPDATE/INSERT mengirim DUA round-trip per baris —
        1.000 untuk 500 nota, lewat Tailscale yang me-relay ke Singapura. Aman
        diganti di sini HANYA karena modul ini membaca baris penuh dari tabel
        asli; di `feed_sync` nilainya datang dari payload yang terpotong."""
        hub, _, _ = self._jalankan(["TR001"])
        self.assertEqual(len([s for s in hub.sql if s.startswith("DELETE")]), 1)
        self.assertEqual(len([s for s in hub.sql if s.startswith("INSERT")]), 1)
        self.assertFalse([s for s in hub.sql if s.startswith("UPDATE")])


class IkatanVarcharTests(SimpleTestCase):
    """pyodbc mengikat `str` sebagai NVARCHAR; kolom kunci legacy `varchar`.
    Konversi implisit di sisi kolom membatalkan index seek, dan SQL Server
    memindai tabel sekali untuk TIAP nilai di daftar `IN`.

    Terukur di ANDARIA (t_penjualan_detail, 1.462.929 baris): IN(50) 6,23 dtk
    apa adanya vs 0,01 dtk sesudah diikat; IN(500) 60 dtk timeout vs 0,18 dtk.
    Regresi di sini tidak memunculkan error — cuma sync yang gagal lewat WAN,
    di jalur yang tak pernah terlihat saat menguji ke server lokal.
    """

    def test_bind_varchar_memakai_sql_varchar(self):
        import pyodbc

        cur = KursorPalsu()
        hub_sync.bind_varchar(cur, 3, panjang=20)
        self.assertEqual(cur.inputsizes, [(pyodbc.SQL_VARCHAR, 20, 0)] * 3)

    def test_hapus_nota_mengikat_seluruh_parameter(self):
        """Termasuk `kd_sumber` di depan daftar — hitungannya harus len+1, kalau
        tidak pyodbc mengeluh jumlah parameter tak cocok."""
        src = KursorPalsu([[("TR001",)]])
        hub = KursorPalsu([[("TR001",), ("TR999",)]])
        with patch.object(hub_pull, "_kolom_tujuan", return_value=["kd_sumber", "no_transaksi"]), \
             patch.object(hub_pull, "_kolom_waktu", return_value=["tanggal"]), \
             patch.object(hub_pull, "_terapkan_header"), \
             patch.object(hub_pull, "_ambil_ulang_detail", return_value=0):
            hub_pull._salin_header(
                src, hub, "t_penjualan", "PRAYA",
                dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1),
            )
        # Direset sesudah dipakai: ikatan menempel di cursor dan execute
        # berikutnya dengan jumlah parameter berbeda akan salah.
        self.assertIsNone(hub.inputsizes)


class KunciMenyempitTests(SimpleTestCase):
    def test_master_menolak_kunci_tak_lengkap(self):
        """Kunci yang menyempit harus jadi kegagalan terlihat, bukan WHERE yang
        melebar: satu UPDATE berkunci separuh menimpa seluruh baris sekerabat.
        `m_barang_satuan` berkunci (kd_barang, kd_satuan) — kalau `kd_satuan`
        hilang, satu perubahan harga menimpa SEMUA satuan barang itu."""
        cur = KursorPalsu()
        with patch.object(hub_master, "_kolom_tujuan", return_value=["kd_sumber", "kd_barang"]):
            with self.assertRaises(RuntimeError) as ctx:
                hub_master.sync_tabel(cur, cur, "m_barang_satuan")
        self.assertIn("kd_satuan", str(ctx.exception))


class MasterTests(SimpleTestCase):
    def test_hanya_gudang_yang_jadi_sumber_master(self):
        """Baris m_barang ber-kd_sumber=PRAYA di pusat mentok 30 karakter untuk
        `nama` DAN `keterangan` padahal kolomnya varchar(50) — trigger legacy
        memotongnya. Master ikut satu sumber saja, dan sumbernya GUDANG."""
        self.assertEqual(hub_master.SUMBER_MASTER, "GUDANG")

    def test_purge_default_dry_run(self):
        """Satu-satunya fungsi di jalur sync yang menghapus tanpa menyalin ulang
        penggantinya. Yang memanggilnya harus MEMINTA penghapusan itu."""
        import inspect

        tanda = inspect.signature(hub_master.purge_lain).parameters["dry_run"]
        self.assertIs(tanda.default, True)

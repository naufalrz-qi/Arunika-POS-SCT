"""Kontrak adapter master: pemetaan yang salah di sini TIDAK memunculkan galat.

View yang salah petakan tetap valid secara SQL. Yang terjadi cuma daftar
pelanggan yang kurang, atau layar biaya yang tampak "belum ada datanya" —
gejala yang akan dikira masalah data, bukan masalah kode.

Dua jebakan yang sudah terbukti nyata di server dijaga secara khusus di bawah,
dan keduanya SUDAH nyaris terjadi saat modul ini ditulis:

  * `m_biaya` memakai **status = 2** untuk aktif, bukan 1 seperti tabel
    referensi lain. Seluruh 38 barisnya bernilai 2, jadi `status = 1` akan
    memulangkan NOL baris aktif.
  * Kunci legacy bertipe `char(6)` dan dipadatkan spasi. Kode pemasok yang
    sebenarnya `'01'` terbaca `'01    '`; SQL Server menganggapnya sama, kunci
    dict Python tidak.

Tak butuh server: yang diuji teks DDL-nya. Pembuktian bahwa barisnya identik
dengan legacy dilakukan terhadap server sungguhan (8 entitas, isi baris cocok
persis — lihat docstring `master_src`).
"""
import re

from django.test import SimpleTestCase

from apps.bisnis import master_src


class DdlDasar(SimpleTestCase):
    def test_semua_entitas_punya_kedua_mode(self):
        for nama in master_src.daftar():
            for mode in master_src.MODE:
                ddl = master_src.ddl(nama, mode, db_legacy="LEGACY")
                self.assertIn(f"[{master_src.SKEMA}].[{nama}]", ddl)

    def test_selalu_di_schema_sendiri_tak_pernah_dbo(self):
        """View kita tak boleh mendarat di `dbo` — di mode legacy `dbo` milik vendor."""
        for nama in master_src.daftar():
            ddl = master_src.ddl(nama, "legacy", db_legacy="LEGACY")
            self.assertNotIn("CREATE VIEW [dbo]", ddl)
            self.assertIn(f"CREATE VIEW [{master_src.SKEMA}]", ddl)

    def test_kolom_bentuk_ditulis_eksplisit(self):
        """Daftar kolom di header VIEW yang menentukan bentuk, bukan alias di
        dalam badan SELECT — satu tempat saja yang memutuskan."""
        for nama in master_src.daftar():
            kolom = master_src._MASTER[nama]["kolom"]
            ddl = master_src.ddl(nama, "arunika")
            header = ddl.split(" AS\n")[0]
            for k in kolom:
                self.assertIn(f"[{k}]", header)

    def test_kedua_mode_menyajikan_kolom_yang_sama(self):
        """Bentuknya satu; kalau tidak, kode pembaca harus tahu sedang di mode apa
        — dan itu persis yang dihindari seluruh rancangan ini."""
        for nama in master_src.daftar():
            a = master_src.ddl(nama, "legacy", db_legacy="X").split(" AS\n")[0]
            b = master_src.ddl(nama, "arunika").split(" AS\n")[0]
            self.assertEqual(a, b)


class ModeLegacy(SimpleTestCase):
    def test_butuh_nama_database(self):
        with self.assertRaises(ValueError):
            master_src.ddl("kota", "legacy")

    def test_nama_database_nakal_ditolak(self):
        """Nama database tak bisa jadi parameter; ia disisipkan ke teks SQL."""
        with self.assertRaises(ValueError):
            master_src.ddl("kota", "legacy", db_legacy="X]; DROP DATABASE y --")

    def test_sumber_berkualifikasi_database(self):
        """Tanpa kualifikasi, view akan mencari tabel legacy di database kita sendiri."""
        ddl = master_src.ddl("pelanggan", "legacy", db_legacy="SOLID_SIM")
        self.assertIn("[SOLID_SIM].dbo.m_customer", ddl)

    def test_mode_asing_ditolak(self):
        with self.assertRaises(ValueError):
            master_src.ddl("kota", "sqlite")


class JebakanYangSudahTerbukti(SimpleTestCase):
    def test_kategori_biaya_aktif_adalah_dua(self):
        """38 dari 38 baris `m_biaya` bernilai 2. `status = 1` memulangkan NOL
        baris aktif — tanpa galat, dan layar kas akan tampak kosong."""
        ddl = master_src.ddl("kategori_biaya", "legacy", db_legacy="X")
        self.assertIn("status = 2", ddl)
        self.assertNotIn("status = 1", ddl)

    def test_entitas_lain_tetap_satu(self):
        """Nilai 2 itu khusus m_biaya; menyeragamkannya akan mematikan yang lain."""
        for nama in ("negara", "kota", "bank", "pelanggan", "kas", "voucher"):
            ddl = master_src.ddl(nama, "legacy", db_legacy="X")
            self.assertIn("status = 1", ddl, nama)

    def test_pemasok_tak_punya_status_sama_sekali(self):
        """`m_supplier` 13 kolom, nol di antaranya status. Mengarang `status = 1`
        di sini akan membuat SELURUH 517 pemasok lenyap dari daftar."""
        ddl = master_src.ddl("pemasok", "legacy", db_legacy="X")
        self.assertNotIn("status", ddl.lower())

    def test_setiap_kolom_kode_dirtrim(self):
        """`char(6)` dipadatkan spasi: kode pemasok '01' terbaca '01    '.
        SQL Server menganggapnya sama; kunci dict Python tidak, dan barisnya
        hilang tanpa suara.

        Yang dijaga adalah kolom KELUARAN, bukan setiap kemunculan `kd_*`.
        Predikat join (`WHERE bs.kd_barang = b.kd_barang`) tidak butuh RTRIM --
        perbandingan `char` di SQL Server sudah mengabaikan spasi ekor. Yang
        berbahaya hanyalah nilai yang KELUAR lalu dipakai sebagai kunci di
        Python.
        """
        for nama in master_src.daftar():
            spec = master_src._MASTER[nama]
            kolom_kode = [k for k in spec["kolom"]
                          if k == "kode" or k.endswith("_kode") or k.endswith("nomor")]
            n = master_src.badan_legacy(nama, "X").count("RTRIM(")
            self.assertGreaterEqual(
                n, len(kolom_kode),
                f"{nama}: {len(kolom_kode)} kolom kode tapi hanya {n} RTRIM",
            )


class ModeArunika(SimpleTestCase):
    def test_menunjuk_tabel_yang_benar_benar_ada(self):
        """Salah ketik nama tabel di sini baru ketahuan saat CREATE VIEW gagal
        di server pelanggan."""
        from django.apps import apps

        nyata = {m._meta.db_table for m in apps.get_app_config("bisnis").get_models()}
        for nama in master_src.daftar():
            badan = master_src._MASTER[nama]["arunika"]
            for tabel in re.findall(r"\bdbo\.(\w+)", badan):
                self.assertIn(tabel, nyata, f"{nama}: dbo.{tabel} bukan tabel model")

    def test_tak_menyentuh_database_lain(self):
        """Mode mandiri harus mandiri; rujukan lintas-database di sini berarti
        pemasangan tanpa legacy akan gagal."""
        for nama in master_src.daftar():
            self.assertNotIn("{db}", master_src._MASTER[nama]["arunika"])


class NilaiUangPenjualan(SimpleTestCase):
    """Nilai uang nota dibangkitkan dari `reports._nota_net()`, satu sumber.

    Versi pertama view ini memanggil fungsi skalar legacy (`GetTotalPenjualan`
    dkk). Itu benar secara nilai — 200/200 cocok dengan `t_penjualan_total` —
    tapi dua hal membatalkannya, keduanya terukur di grosirPusat:

      * **Lambat untuk agregat.** Fungsi itu `is_inlineable` tapi compatibility
        level database legacy 100 (butuh >= 150), jadi baris-per-baris.
        2025 setahun: 36,2 dtk. 2024-2026: 79,6 dtk.
      * **Angkanya berbeda dari laporan yang sudah berjalan.** `_nota_net()`
        tidak memotong nominal voucher; fungsi legacy memotongnya —
        Rp 73.700.000 pada 1.396 nota.

    Sesudah dibangkitkan dari `_nota_net()`: 6,59 dan 9,97 dtk, dan angkanya
    IDENTIK dengan jalur lama.
    """

    def _badan(self):
        return master_src.badan_legacy("penjualan", "LEGACYDB")

    def test_nol_panggilan_fungsi_skalar(self):
        """Satu panggilan saja mengembalikan ongkos baris-per-baris itu."""
        badan = self._badan()
        for fn in ("GetTotalPenjualan", "GetTotalDiskonPenjualan", "GetTotalPajakPenjualan"):
            self.assertNotIn(fn, badan, f"{fn} masih dipanggil")

    def test_dibangkitkan_dari_nota_net(self):
        """Bukan disalin: satu formula uang, dipakai kedua jalur.

        Kalau ini putus, perbedaan voucher (dan setiap perbedaan formula
        berikutnya) akan diam-diam hidup lagi sebagai dua angka omzet untuk
        data yang sama.
        """
        from apps.transactions import reports

        inti = reports._nota_net("1=1")
        # Sepotong khas dari _nota_net yang tak mungkin muncul kebetulan.
        petik = "net_lines"
        self.assertIn(petik, inti)
        self.assertIn(petik, self._badan())

    def test_sumber_berkualifikasi_database(self):
        """View hidup di database Arunika; tabelnya tidak."""
        badan = master_src.badan_legacy("penjualan", "SOLID_SIM")
        self.assertIn("[SOLID_SIM].dbo.t_penjualan", badan)
        self.assertNotIn("FROM t_penjualan_detail", badan)

    def test_diskon_diturunkan_bukan_ditebak(self):
        """`_nota_net()` tak punya kolom diskon. Identitas
        `total_kotor - (total_bersih - pajak)` sudah dipakai `penjualan_periode`
        sejak lama dan terbukti 50/50 pada nota berdiskon."""
        self.assertIn("n.total_kotor - (n.total_bersih - n.pajak)", self._badan())

    def test_mode_arunika_tak_menyentuh_fungsi_legacy(self):
        """Pemasangan mandiri tak punya fungsi vendor sama sekali."""
        self.assertNotIn("GetTotal", master_src._MASTER["penjualan"]["arunika"])


class SumberUtama(SimpleTestCase):
    """Daftar tabel sumber ditulis terpisah dari badan view, jadi ia bisa
    menyimpang. Test ini yang menahannya.

    Menurunkannya otomatis sudah dicoba dan gagal: rujukan `{db}.dbo.X` PERTAMA
    di badan `barang` adalah `m_barang_satuan` (subquery satuan dasar), bukan
    `m_barang` — pemeriksa jadi membandingkan 53.865 dengan 54.232 dan
    melaporkan selisih yang tidak ada. Yang TERAKHIR sama tak bisa dipercaya:
    di `penjualan` itu sebuah fungsi.
    """

    def test_setiap_entitas_punya_sumber(self):
        self.assertEqual(set(master_src.SUMBER_UTAMA), set(master_src.daftar()))

    def test_sumber_benar_benar_dirujuk_badannya(self):
        for nama, tabel in master_src.SUMBER_UTAMA.items():
            self.assertIn(
                f"[X].dbo.{tabel}",
                master_src.badan_legacy(nama, "X"),
                f"{nama}: SUMBER_UTAMA menyebut {tabel} tapi badan view tak merujuknya",
            )


class StatusBukanPenandaBatal(SimpleTestCase):
    """`t_penjualan.status` adalah JENIS PEMBAYARAN, bukan penanda batal.

    0=Kredit, 1=Tunai, 2=Lunas — lihat `reports.STATUS_PENJUALAN_CASE`. Versi
    pertama view `penjualan` memetakan `status = 0` ke 'batal', yang akan
    melabeli setiap penjualan kredit sebagai nota batal. Hanya 8 baris di
    grosirPusat, dan justru kecilnya yang membuatnya berbahaya: salah seperti
    itu tidak terlihat di angka ringkasan mana pun.

    Kepala nota legacy tak punya kolom pembatalan, jadi tak ada yang bisa
    dipetakan. Test ini menahan kesalahan yang sama terulang.
    """

    def test_tak_menurunkan_batal_dari_kolom_status(self):
        badan = master_src.badan_legacy("penjualan", "LEGACYDB")
        # `h.status` MEMANG muncul di badan (`_nota_net` memulangkannya sebagai
        # `status_raw` untuk jenis pembayaran). Yang tak boleh adalah
        # menurunkan 'batal' darinya.
        self.assertNotIn("'batal'", badan)

    def test_status_konstan_aktif_di_mode_legacy(self):
        self.assertIn("'aktif'", master_src.badan_legacy("penjualan", "LEGACYDB"))

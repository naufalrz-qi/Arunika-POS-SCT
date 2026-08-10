"""Kelola Barang — buat dan sunting m_barang + satuan + divisi.

MS SQL tidak disentuh: cursor di-fake dan SQL yang dieksekusi direkam.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.master_data import barang as bb
from apps.master_data.services import BukanServerGudang


class Profil:
    def __init__(self, db_type="gudang", pk=1, name="GUDANG"):
        self.db_type = db_type
        self.pk = pk
        self.id = pk
        self.name = name


class FakeCursor:
    def __init__(self, ada_kode=1, sudah_dipakai=False):
        self.ada_kode = ada_kode
        self.sudah_dipakai = sudah_dipakai
        self.sql = []
        self.params = []
        self._row = None
        self.connection = self

    def setinputsizes(self, v):
        pass

    def commit(self):
        self.sql.append("COMMIT")

    def execute(self, sql, params=None):
        rapi = " ".join(sql.split())
        self.sql.append(rapi)
        self.params.append(list(params or []))
        if rapi.startswith("SELECT 1 FROM m_barang"):
            self._row = (1,) if self.sudah_dipakai else None
        elif rapi.startswith("SELECT COUNT"):
            self._row = (self.ada_kode,)
        else:
            self._row = None

    def fetchone(self):
        return self._row


@contextmanager
def _fake(cur):
    @contextmanager
    def ganti(profile, autocommit=True, query_timeout=None):
        yield cur

    with patch.object(bb.mssql, "cursor", ganti), \
            patch.object(bb, "_invalidate_inventory_cache", lambda p: None):
        yield


LENGKAP = {
    "kd_barang": "oct6555",
    "nama": "MOBIL DRIFT RACING",
    "keterangan": "",
    "ukuran": "1",
    "kd_kategori": "KAA000", "kd_merk": "MAA000", "kd_model": "MAA000",
    "kd_warna": "WAA000", "kd_jenis_bahan": "JAA000",
    "satuan": [{"kd_satuan": "SAA000", "jumlah": "1", "harga_jual": "15000"}],
    "divisi": [],
}


def _buat(cur, **ubah):
    isi = {**LENGKAP, **ubah}
    with _fake(cur):
        return bb.buat_barang(Profil(), isi)


def _insert(cur, tabel):
    return [(i, s) for i, s in enumerate(cur.sql)
            if s.startswith(f"INSERT INTO {tabel} ")]


class GerbangGudangTests(SimpleTestCase):
    def test_server_toko_ditolak(self):
        """Katalog disebarkan gudang → toko; barang buatan toko akan tertimpa."""
        with self.assertRaises(BukanServerGudang):
            with _fake(FakeCursor()):
                bb.buat_barang(Profil(db_type="grosir"), LENGKAP)

    def test_server_retail_juga_ditolak(self):
        with self.assertRaises(BukanServerGudang):
            with _fake(FakeCursor()):
                bb.buat_barang(Profil(db_type="retail"), LENGKAP)

    def test_ditolak_sebelum_menyentuh_database(self):
        cur = FakeCursor()
        with self.assertRaises(BukanServerGudang):
            with _fake(cur):
                bb.buat_barang(Profil(db_type="grosir"), LENGKAP)
        self.assertEqual(cur.sql, [])


class KodeTests(SimpleTestCase):
    def test_kode_dinaikkan_ke_huruf_besar(self):
        cur = FakeCursor()
        self.assertEqual(_buat(cur)["kd_barang"], "OCT6555")

    def test_kode_kosong_ditolak(self):
        with self.assertRaises(ValueError):
            _buat(FakeCursor(), kd_barang="  ")

    def test_kode_yang_sudah_dipakai_ditolak_dengan_jelas(self):
        with self.assertRaises(ValueError) as ctx:
            _buat(FakeCursor(sudah_dipakai=True))
        self.assertIn("sudah dipakai", str(ctx.exception))

    def test_bentrok_diperiksa_sebelum_insert(self):
        cur = FakeCursor()
        _buat(cur)
        cek = next(i for i, s in enumerate(cur.sql) if s.startswith("SELECT 1 FROM m_barang"))
        sisip = _insert(cur, "m_barang")[0][0]
        self.assertLess(cek, sisip)

    def test_kode_tak_pernah_di_UPDATE(self):
        """ON UPDATE CASCADE ada di 128 dari 129 FK — mengubah kd_barang
        merambat ke belasan tabel transaksi sekaligus."""
        cur = FakeCursor()
        _buat(cur)
        self.assertFalse([s for s in cur.sql if s.startswith("UPDATE")])


class KolomTests(SimpleTestCase):
    def test_ketiga_tabel_tertulis_dalam_satu_transaksi(self):
        cur = FakeCursor()
        _buat(cur, divisi=[{"kd_divisi": "DAA001", "stok_awal": "5",
                            "harga_beli_awal": "9000", "stok_min": "2"}])
        for tabel in ("m_barang", "m_barang_satuan", "m_barang_divisi"):
            self.assertEqual(len(_insert(cur, tabel)), 1, tabel)
        self.assertEqual(cur.sql[-1], "COMMIT")

    def test_insert_menyebut_kolom_eksplisit(self):
        """m_barang_divisi melewati column_id 6 — VALUES posisional salah kolom."""
        cur = FakeCursor()
        _buat(cur, divisi=[{"kd_divisi": "DAA001"}])
        for tabel, kolom in (("m_barang", bb.KOLOM_BARANG),
                             ("m_barang_satuan", bb.KOLOM_SATUAN),
                             ("m_barang_divisi", bb.KOLOM_DIVISI)):
            sql = _insert(cur, tabel)[0][1]
            for k in kolom:
                self.assertIn(k, sql, f"{tabel}.{k}")

    def test_satu_baris_per_execute(self):
        cur = FakeCursor()
        _buat(cur, satuan=[{"kd_satuan": "SAA000"}, {"kd_satuan": "SAA001"}])
        self.assertEqual(len(_insert(cur, "m_barang_satuan")), 2)
        for _, sql in _insert(cur, "m_barang_satuan"):
            self.assertEqual(sql.count("VALUES"), 1)

    def test_tanggal_daftar_ditulis(self):
        """Terisi di SELURUH 53.865 baris dan tak punya default constraint."""
        cur = FakeCursor()
        _buat(cur)
        i, _ = _insert(cur, "m_barang")[0]
        self.assertIsNotNone(cur.params[i][bb.KOLOM_BARANG.index("tanggal_daftar")])

    def test_bawaan_status_diambil_dari_data_server(self):
        cur = FakeCursor()
        _buat(cur)
        i, _ = _insert(cur, "m_barang")[0]
        nilai = cur.params[i]
        self.assertEqual(nilai[bb.KOLOM_BARANG.index("status")], 1)
        # Nol di seluruh 53.865 baris — bukan pilihan.
        self.assertEqual(nilai[bb.KOLOM_BARANG.index("status_pinjam")], 0)
        self.assertEqual(nilai[bb.KOLOM_BARANG.index("pabrik")], 0)

    def test_keterangan_kosong_jadi_strip(self):
        cur = FakeCursor()
        _buat(cur)
        i, _ = _insert(cur, "m_barang")[0]
        self.assertEqual(cur.params[i][bb.KOLOM_BARANG.index("keterangan")],
                         bb.KETERANGAN_KOSONG)

    def test_tak_ada_delete(self):
        cur = FakeCursor()
        _buat(cur, divisi=[{"kd_divisi": "DAA001"}])
        self.assertNotIn("DELETE", " ".join(cur.sql).upper())


class SatuanDivisiTests(SimpleTestCase):
    def test_tanpa_satuan_ditolak(self):
        with self.assertRaises(ValueError) as ctx:
            _buat(FakeCursor(), satuan=[])
        self.assertIn("tak bisa dijual", str(ctx.exception))

    def test_satuan_ganda_ditolak(self):
        """PK-nya (kd_barang, kd_satuan) — baris keduanya pasti ditolak DB."""
        with self.assertRaises(ValueError) as ctx:
            _buat(FakeCursor(), satuan=[{"kd_satuan": "SAA000"},
                                        {"kd_satuan": "SAA000"}])
        self.assertIn("dua kali", str(ctx.exception))

    def test_isi_satuan_bawaan_satu(self):
        cur = FakeCursor()
        _buat(cur, satuan=[{"kd_satuan": "SAA000"}])
        i, _ = _insert(cur, "m_barang_satuan")[0]
        self.assertEqual(cur.params[i][bb.KOLOM_SATUAN.index("jumlah")], 1)

    def test_margin_nol_bukan_null(self):
        """Terisi di SELURUH baris; dihitung ulang oleh services.update_harga."""
        cur = FakeCursor()
        _buat(cur)
        i, _ = _insert(cur, "m_barang_satuan")[0]
        self.assertEqual(cur.params[i][bb.KOLOM_SATUAN.index("margin")], 0)

    def test_divisi_boleh_kosong(self):
        """22.927 dari 53.865 barang memang tak punya baris divisi."""
        cur = FakeCursor()
        _buat(cur, divisi=[])
        self.assertEqual(_insert(cur, "m_barang_divisi"), [])

    def test_divisi_ganda_ditolak(self):
        with self.assertRaises(ValueError):
            _buat(FakeCursor(), divisi=[{"kd_divisi": "DAA001"},
                                        {"kd_divisi": "DAA001"}])


class ValidasiKodeTests(SimpleTestCase):
    def test_kode_lookup_tak_dikenal_ditolak_di_aplikasi(self):
        """FK tak bisa jadi sandaran: 116 dari 129 FK `not_trusted`."""
        with self.assertRaises(ValueError) as ctx:
            _buat(FakeCursor(ada_kode=0))
        self.assertIn("tidak ada atau tidak aktif", str(ctx.exception))

    def test_pemeriksaan_menolak_yang_nonaktif(self):
        cur = FakeCursor()
        _buat(cur)
        cek = [s for s in cur.sql if s.startswith("SELECT COUNT")]
        self.assertEqual(len(cek), len(bb.LOOKUP_BARANG) + 1)  # + satuan
        for s in cek:
            self.assertIn("status <> 0", s)

    def test_kategori_kosong_ditolak(self):
        with self.assertRaises(ValueError) as ctx:
            _buat(FakeCursor(), kd_kategori="")
        self.assertIn("belum dipilih", str(ctx.exception))

    def test_nama_wajib(self):
        with self.assertRaises(ValueError):
            _buat(FakeCursor(), nama="   ")

    def test_nama_dipotong_ke_lima_puluh(self):
        cur = FakeCursor()
        _buat(cur, nama="N" * 120)
        i, _ = _insert(cur, "m_barang")[0]
        self.assertEqual(len(cur.params[i][bb.KOLOM_BARANG.index("nama")]), 50)

    def test_ukuran_bukan_angka_dijelaskan(self):
        with self.assertRaises(ValueError) as ctx:
            _buat(FakeCursor(), ukuran="besar")
        self.assertIn("Tulis angkanya saja", str(ctx.exception))


# --- Sunting barang yang sudah ada ----------------------------------------


class UbahCursor(FakeCursor):
    """FakeCursor + jawaban untuk "baris mana yang sudah ada".

    `satuan_ada` / `divisi_ada` menjawab dua SELECT di `_upsert_*`, yang
    memutuskan sebuah baris di-INSERT atau di-UPDATE.
    """

    def __init__(self, satuan_ada=(), divisi_ada=(), barang_ada=True, **kw):
        super().__init__(**kw)
        self.satuan_ada = list(satuan_ada)
        self.divisi_ada = list(divisi_ada)
        self.barang_ada = barang_ada
        self._rows = []

    def execute(self, sql, params=None):
        rapi = " ".join(sql.split())
        self.sql.append(rapi)
        self.params.append(list(params or []))
        if rapi.startswith("SELECT 1 FROM m_barang"):
            self._row = (1,) if self.barang_ada else None
        elif rapi.startswith("SELECT kd_satuan FROM m_barang_satuan"):
            self._rows = [(k,) for k in self.satuan_ada]
        elif rapi.startswith("SELECT kd_divisi FROM m_barang_divisi"):
            self._rows = [(k,) for k in self.divisi_ada]
        elif rapi.startswith("SELECT COUNT"):
            self._row = (self.ada_kode,)
        else:
            self._row = None

    def fetchall(self):
        return self._rows


def _ubah(cur, **ubah):
    isi = {**LENGKAP, **ubah}
    with _fake(cur):
        return bb.ubah_barang(Profil(), "OCT6555", isi)


def _upd(cur, tabel):
    return [(i, s) for i, s in enumerate(cur.sql)
            if s.startswith(f"UPDATE {tabel} ")]


class UbahGerbangTests(SimpleTestCase):
    def test_server_toko_ditolak_sebelum_menyentuh_database(self):
        cur = UbahCursor()
        with self.assertRaises(BukanServerGudang):
            with _fake(cur):
                bb.ubah_barang(Profil(db_type="grosir"), "OCT6555", LENGKAP)
        self.assertEqual(cur.sql, [])

    def test_barang_yang_tak_ada_ditolak(self):
        with self.assertRaises(ValueError) as ctx:
            _ubah(UbahCursor(barang_ada=False))
        self.assertIn("tidak ada di server ini", str(ctx.exception))


class UbahKunciTests(SimpleTestCase):
    def test_kunci_tak_pernah_masuk_SET(self):
        """ON UPDATE CASCADE di 128 dari 129 FK — mengubah kd_* merambat ke
        belasan tabel transaksi dan membangunkan trigger feed di tiap baris."""
        cur = UbahCursor(satuan_ada=["SAA000"], divisi_ada=["DAA001"])
        _ubah(cur, divisi=[{"kd_divisi": "DAA001", "stok_min": "3"}])
        for s in cur.sql:
            if s.startswith("UPDATE "):
                bagian_set = s.split(" SET ", 1)[1].split(" WHERE ")[0]
                for kunci in ("kd_barang", "kd_satuan", "kd_divisi"):
                    self.assertNotIn(f"{kunci} =", bagian_set, s)

    def test_status_m_barang_bukan_urusan_layar_ini(self):
        """Dikelola Update Harga lewat master.update_status. Dua jalur tulis
        untuk satu kolom akan menyimpang diam-diam."""
        self.assertNotIn("status", bb.UBAH_BARANG)

    def test_tak_ada_delete(self):
        cur = UbahCursor(satuan_ada=["SAA000"], divisi_ada=["DAA001"])
        _ubah(cur, divisi=[{"kd_divisi": "DAA001"}])
        self.assertNotIn("DELETE", " ".join(cur.sql).upper())


class UbahHargaTests(SimpleTestCase):
    def test_harga_baris_lama_tak_pernah_ditulis(self):
        """Inti pembagian kerja: struktur di sini, harga di Update Harga.

        Menulis harga dari sini melewati validasi harga bulat, hitung ulang
        margin, pembatalan cache, pencatatan riwayat, dan sebar ke 8 toko.
        """
        self.assertNotIn("harga_jual", bb.UBAH_SATUAN)
        self.assertNotIn("margin", bb.UBAH_SATUAN)
        cur = UbahCursor(satuan_ada=["SAA000"])
        _ubah(cur, satuan=[{"kd_satuan": "SAA000", "jumlah": "1",
                            "harga_jual": "999999"}])
        upd = _upd(cur, "m_barang_satuan")[0][1]
        self.assertNotIn("harga_jual", upd)
        self.assertNotIn("999999", " ".join(str(p) for p in cur.params))

    def test_satuan_baru_tetap_membawa_harganya(self):
        """Belum ada harga lama yang perlu dirawat — sama seperti buat_barang."""
        cur = UbahCursor(satuan_ada=[])
        _ubah(cur, satuan=[{"kd_satuan": "SAA001", "jumlah": "12",
                            "harga_jual": "150000"}])
        i, _ = _insert(cur, "m_barang_satuan")[0]
        self.assertEqual(cur.params[i][bb.KOLOM_SATUAN.index("harga_jual")], 150000)


class UpsertTests(SimpleTestCase):
    def test_satuan_yang_sudah_ada_di_UPDATE_bukan_INSERT(self):
        cur = UbahCursor(satuan_ada=["SAA000"])
        hasil = _ubah(cur, satuan=[{"kd_satuan": "SAA000", "jumlah": "1"}])
        self.assertEqual(_insert(cur, "m_barang_satuan"), [])
        upd = _upd(cur, "m_barang_satuan")[0][1]
        self.assertTrue(upd.endswith("WHERE kd_barang = ? AND kd_satuan = ?"))
        self.assertEqual(hasil["satuan_baru"], 0)

    def test_satuan_baru_di_INSERT(self):
        cur = UbahCursor(satuan_ada=["SAA000"])
        hasil = _ubah(cur, satuan=[{"kd_satuan": "SAA000", "jumlah": "1"},
                                   {"kd_satuan": "SAA001", "jumlah": "12"}])
        self.assertEqual(len(_insert(cur, "m_barang_satuan")), 1)
        self.assertEqual(len(_upd(cur, "m_barang_satuan")), 1)
        self.assertEqual(hasil["satuan_baru"], 1)

    def test_divisi_yang_sudah_ada_di_UPDATE_dengan_kunci_gandanya(self):
        cur = UbahCursor(satuan_ada=["SAA000"], divisi_ada=["DAA001"])
        _ubah(cur, divisi=[{"kd_divisi": "DAA001", "stok_min": "5"}])
        upd = _upd(cur, "m_barang_divisi")[0][1]
        self.assertTrue(upd.endswith("WHERE kd_barang = ? AND kd_divisi = ?"))

    def test_divisi_baru_di_INSERT(self):
        cur = UbahCursor(satuan_ada=["SAA000"], divisi_ada=[])
        hasil = _ubah(cur, divisi=[{"kd_divisi": "DAA002", "stok_awal": "7"}])
        self.assertEqual(len(_insert(cur, "m_barang_divisi")), 1)
        self.assertEqual(hasil["divisi_baru"], 1)

    def test_satu_baris_per_execute(self):
        cur = UbahCursor(satuan_ada=[])
        _ubah(cur, satuan=[{"kd_satuan": "SAA000"}, {"kd_satuan": "SAA001"}])
        self.assertEqual(len(_insert(cur, "m_barang_satuan")), 2)


class UbahStatusTests(SimpleTestCase):
    def test_nonaktif_per_baris_tersimpan(self):
        """Satu-satunya pembatalan yang ada — tak ada DELETE di modul ini."""
        cur = UbahCursor(satuan_ada=["SAA000"])
        _ubah(cur, satuan=[{"kd_satuan": "SAA000", "jumlah": "1", "status": "0"}])
        i, _ = _upd(cur, "m_barang_satuan")[0]
        self.assertEqual(cur.params[i][bb.UBAH_SATUAN.index("status")], 0)

    def test_bawaan_baris_adalah_aktif(self):
        cur = UbahCursor(satuan_ada=["SAA000"])
        _ubah(cur, satuan=[{"kd_satuan": "SAA000", "jumlah": "1"}])
        i, _ = _upd(cur, "m_barang_satuan")[0]
        self.assertEqual(cur.params[i][bb.UBAH_SATUAN.index("status")], bb.AKTIF)

"""Jalur tulis kas: biaya operasional, penambahan kas, mutasi kas.

MS SQL tidak disentuh — cursor di-fake dan SQL yang dieksekusi direkam. Bentuknya
mengikuti test_opname_koreksi.py, karena jalur tulisnya memang sekeluarga.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.transactions import kas


class FakeCursor:
    """Cursor palsu. `ada` menjawab setiap COUNT(*) pemeriksaan kode."""

    def __init__(self, ada=1, kepala="SC", maks=None):
        self.ada = ada
        self.kepala = kepala
        self.maks = maks
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
        if rapi.startswith("SELECT kepala_nota"):
            self._row = (self.kepala,)
        elif rapi.startswith("SELECT MAX"):
            self._row = (self.maks,)
        elif rapi.startswith("SELECT COUNT"):
            self._row = (self.ada,)
        else:
            self._row = None

    def fetchone(self):
        return self._row


@contextmanager
def _fake(cur):
    @contextmanager
    def ganti(profile, autocommit=True, query_timeout=None):
        yield cur

    with patch.object(kas.mssql, "cursor", ganti):
        yield


LENGKAP = {
    "biaya": {"kd_divisi": "DAA000", "kd_biaya": "BAA001", "kd_jenis": "JAA000",
              "kd_kas": "KAA000", "nominal": "230000", "no_bukti": "",
              "keterangan": "lampu 30 watt"},
    "penambahan": {"kd_divisi": "DAA000", "kd_kas": "KAA000", "nominal": "500000",
                   "keterangan": "setor modal"},
    "mutasi": {"kd_divisi": "DAA000", "kd_kas_sumber": "KAA000",
               "kd_kas_tujuan": "KAA001", "nominal": "1000000",
               "no_bukti_sumber": "", "no_bukti_tujuan": "",
               "keterangan": "pindah ke rek B"},
}


def _simpan(jenis, cur, **ubah):
    isi = dict(LENGKAP[jenis])
    isi.update(ubah)
    with _fake(cur):
        return kas.simpan(object(), jenis, kd_user="UAA013", data=isi)


class NomorTests(SimpleTestCase):
    def test_nomor_memakai_kepala_nota_divisi(self):
        """SC2603200006 — bentuk yang benar-benar ada di 9.563 baris grosirPusat."""
        cur = FakeCursor(kepala="SC", maks=None)
        hasil = _simpan("biaya", cur)
        self.assertTrue(hasil["nomor"].startswith("SC"))
        self.assertEqual(len(hasil["nomor"]), 12)

    def test_awalan_diambil_dari_divisi_yang_dipilih(self):
        """Gudang punya lima divisi: UM/GP/GO/KN/FR. "Yang pertama" salah."""
        cur = FakeCursor(kepala="GP")
        _simpan("biaya", cur, kd_divisi="DAA001")
        tanya = next(s for s in cur.sql if s.startswith("SELECT kepala_nota"))
        self.assertIn("WHERE kd_divisi = ?", tanya)
        self.assertIn(["DAA001"], cur.params)

    def test_nomor_melanjutkan_yang_sudah_ada(self):
        # Tanggalnya SELALU hari ini — yang dilanjutkan hanya urutannya, dan
        # MAX() memang sudah disaring ke awalan+tanggal hari ini di dalam
        # `urut_berikutnya`. Karena itu yang diperiksa ekornya, bukan nomor utuh.
        import datetime as dt

        cur = FakeCursor(kepala="SC", maks="SC2603200005")
        nomor = _simpan("biaya", cur)["nomor"]
        self.assertEqual(nomor, f"SC{dt.date.today():%y%m%d}0006")


class KolomTests(SimpleTestCase):
    def test_insert_menyebut_kolom_eksplisit(self):
        """`t_biaya_operasional` melewati column_id 7 — VALUES posisional salah kolom."""
        for jenis in kas.SPEC:
            cur = FakeCursor()
            _simpan(jenis, cur)
            ins = next(s for s in cur.sql if s.startswith("INSERT"))
            for k in kas.SPEC[jenis]["kolom"]:
                self.assertIn(k, ins, f"{jenis}: {k} tak disebut")

    def test_satu_baris_satu_execute(self):
        for jenis in kas.SPEC:
            cur = FakeCursor()
            _simpan(jenis, cur)
            self.assertEqual(len([s for s in cur.sql if s.startswith("INSERT")]), 1)

    def test_tanggal_server_ditulis_di_yang_punya(self):
        """Tak ada default constraint; aplikasi lama menulisnya sendiri."""
        for jenis in ("biaya", "mutasi"):
            cur = FakeCursor()
            _simpan(jenis, cur)
            ins = next(i for i, s in enumerate(cur.sql) if s.startswith("INSERT"))
            kolom = kas.SPEC[jenis]["kolom"]
            self.assertIn("tanggal_server", kolom)
            self.assertIsNotNone(cur.params[ins][kolom.index("tanggal_server")])

    def test_penambahan_kas_tak_punya_tanggal_server(self):
        self.assertNotIn("tanggal_server", kas.SPEC["penambahan"]["kolom"])

    def test_no_bukti_kosong_jadi_strip(self):
        """9.563 dari 9.563 baris biaya berbunyi "-", bukan string kosong."""
        cur = FakeCursor()
        _simpan("biaya", cur)
        kolom = kas.SPEC["biaya"]["kolom"]
        ins = next(i for i, s in enumerate(cur.sql) if s.startswith("INSERT"))
        self.assertEqual(cur.params[ins][kolom.index("no_bukti")], kas.BUKTI_KOSONG)

    def test_tak_ada_delete(self):
        for jenis in kas.SPEC:
            cur = FakeCursor()
            _simpan(jenis, cur)
            self.assertNotIn("DELETE", " ".join(cur.sql).upper())


class ValidasiTests(SimpleTestCase):
    def test_tanpa_tautan_ditolak_dan_menyebut_tempat_memperbaikinya(self):
        with self.assertRaises(ValueError) as ctx:
            with _fake(FakeCursor()):
                kas.simpan(object(), "biaya", kd_user="", data=LENGKAP["biaya"])
        self.assertIn("Kelola Tautan User", str(ctx.exception))

    def test_kode_tak_dikenal_ditolak_di_aplikasi(self):
        """FK tak bisa diandalkan: kd_kas tak punya FK sama sekali di tabel ini."""
        with self.assertRaises(ValueError) as ctx:
            _simpan("biaya", FakeCursor(ada=0))
        self.assertIn("tidak ada atau tidak aktif", str(ctx.exception))

    def test_pemeriksaan_kode_menolak_yang_nonaktif(self):
        cur = FakeCursor()
        _simpan("biaya", cur)
        cek = [s for s in cur.sql if s.startswith("SELECT COUNT")]
        self.assertTrue(cek)
        for s in cek:
            self.assertIn("status <> 0", s)

    def test_nominal_nol_ditolak(self):
        with self.assertRaises(ValueError):
            _simpan("biaya", FakeCursor(), nominal="0")

    def test_nominal_negatif_ditolak(self):
        with self.assertRaises(ValueError):
            _simpan("biaya", FakeCursor(), nominal="-5000")

    def test_nominal_berpemisah_ribuan_indonesia_diterima(self):
        cur = FakeCursor()
        _simpan("biaya", cur, nominal="1.250.000")
        kolom = kas.SPEC["biaya"]["kolom"]
        ins = next(i for i, s in enumerate(cur.sql) if s.startswith("INSERT"))
        self.assertEqual(cur.params[ins][kolom.index("nominal")], 1250000.0)

    def test_nominal_bukan_angka_dijelaskan(self):
        with self.assertRaises(ValueError) as ctx:
            _simpan("biaya", FakeCursor(), nominal="dua ratus")
        self.assertIn("Tulis angkanya saja", str(ctx.exception))

    def test_keterangan_wajib(self):
        with self.assertRaises(ValueError):
            _simpan("biaya", FakeCursor(), keterangan="   ")

    def test_keterangan_dipotong_ke_lima_puluh(self):
        cur = FakeCursor()
        _simpan("biaya", cur, keterangan="X" * 200)
        kolom = kas.SPEC["biaya"]["kolom"]
        ins = next(i for i, s in enumerate(cur.sql) if s.startswith("INSERT"))
        self.assertEqual(len(cur.params[ins][kolom.index("keterangan")]), 50)

    def test_divisi_kosong_ditolak_untuk_biaya(self):
        with self.assertRaises(ValueError) as ctx:
            _simpan("biaya", FakeCursor(), kd_divisi="")
        self.assertIn("Divisi belum dipilih", str(ctx.exception))


class SpecTests(SimpleTestCase):
    def test_form_hanya_menyebut_kolom_yang_ditulis(self):
        """Kotak isian yang kolomnya tak ada di INSERT hilang tanpa jejak."""
        for jenis, medan in kas.FORM.items():
            kolom = set(kas.SPEC[jenis]["kolom"])
            for f in medan:
                self.assertIn(f["name"], kolom, f"{jenis}.{f['name']}")

    def test_setiap_jenis_punya_entri_penomoran(self):
        from apps.transactions import penomoran

        for jenis, s in kas.SPEC.items():
            self.assertIn(s["jenis_nomor"], penomoran.JENIS, jenis)
            self.assertEqual(penomoran.JENIS[s["jenis_nomor"]][0], s["tabel"])

    def test_kas_tujuan_menunjuk_m_kas(self):
        """Tipenya varchar(10)/JR_KODE_ACCOUNT, tapi tiga VIEW legacy
        (v_t_mutasi_kas, mon_t_mutasi_kas, v_g_kas_histori_detail) sama-sama
        join ke m_kas.kd_kas. Tipe kolomnya yang tak rapi, bukan artinya."""
        self.assertEqual(kas.SPEC["mutasi"]["kode"]["kd_kas_tujuan"][0], "m_kas")
        opsi = {f["opsi"] for f in kas.FORM["mutasi"] if f["tipe"] == "pilih"}
        self.assertEqual(opsi, {"kas"})

"""Payload kolumnar Stok Akhir harus bisa dibongkar balik jadi baris semula.

Bentuk ini menukar keterbacaan dengan ukuran: kolom teks yang berulang diganti
indeks ke tabel kamus. Kalau ambang kamusnya salah, kerugiannya senyap — payload
tetap sah dan layar tetap terisi, cuma ukurannya kembali membengkak (atau malah
lebih besar dari bentuk asalnya, karena tabel kamus ikut terkirim tanpa ada yang
dihemat). Tes ini menjaga dua hal: isinya utuh, dan kamusnya dipakai hanya di
tempat yang memang menghemat.
"""
from django.test import SimpleTestCase

from apps.inventory.services import _kolumnar

COLS = ["kd_barang", "barang", "kategori", "stok_akhir"]


def _rows(n):
    """n baris: kd_barang unik, kategori cuma 2 nilai (kandidat kamus)."""
    return [
        {
            "kd_barang": f"SKU{i:05d}",
            "barang": f"Barang {i}",
            "kategori": "BATERAI" if i % 2 else "YOYO",
            "stok_akhir": float(i % 7) - 3.0,
        }
        for i in range(n)
    ]


def _decode(payload):
    """Bongkar balik jadi list of dict — kebalikan _kolumnar."""
    out = []
    for i in range(payload["n"]):
        row = {}
        for c in payload["cols"]:
            v = payload["data"][c][i]
            row[c] = payload["dict"][c][v] if c in payload["dict"] else v
        out.append(row)
    return out


class Kolumnar(SimpleTestCase):
    def test_bolak_balik_utuh(self):
        rows = _rows(200)
        self.assertEqual(_decode(_kolumnar(rows, COLS)), rows)

    def test_kolom_berulang_dikamuskan(self):
        p = _kolumnar(_rows(200), COLS)
        self.assertEqual(p["types"]["kategori"], "dict")
        self.assertEqual(p["dict"]["kategori"], ["BATERAI", "YOYO"])
        self.assertEqual(p["data"]["kategori"][:4], [1, 0, 1, 0])

    def test_kolom_hampir_unik_tidak_dikamuskan(self):
        # Inti tesnya: memberi kamus pada kolom unik MENAMBAH byte, bukan
        # mengurangi — satu tabel penuh plus satu indeks per baris.
        p = _kolumnar(_rows(200), COLS)
        self.assertEqual(p["types"]["kd_barang"], "str")
        self.assertEqual(p["types"]["barang"], "str")
        self.assertNotIn("kd_barang", p["dict"])
        self.assertEqual(p["data"]["kd_barang"][0], "SKU00000")

    def test_kolom_angka_apa_adanya(self):
        p = _kolumnar(_rows(200), COLS)
        self.assertEqual(p["types"]["stok_akhir"], "num")
        self.assertNotIn("stok_akhir", p["dict"])
        self.assertEqual(p["data"]["stok_akhir"][:4], [-3.0, -2.0, -1.0, 0.0])

    def test_angka_bercampur_null_bukan_num(self):
        # Kolom angka yang memuat satu None TIDAK boleh dilabeli "num": klien
        # akan membangun Float64Array darinya, null jadi NaN, dan layar
        # mencetak "NaN" alih-alih "-". Sebelum `types` ada, klien menebak
        # tipe dari elemen pertama dan tepat jatuh ke jebakan ini.
        rows = [{"x": 1.0}, {"x": None}, {"x": 3.0}]
        p = _kolumnar(rows, ["x"])
        self.assertEqual(p["types"]["x"], "raw")
        self.assertEqual(p["data"]["x"], [1.0, None, 3.0])

    def test_bool_bukan_num(self):
        # bool adalah subclass int di Python; tanpa penjagaan ia lolos sebagai
        # "num" dan berubah jadi 1/0 di layar.
        p = _kolumnar([{"x": True}, {"x": False}], ["x"])
        self.assertEqual(p["types"]["x"], "raw")

    def test_setiap_kolom_punya_tipe(self):
        p = _kolumnar(_rows(50), COLS)
        self.assertEqual(sorted(p["types"]), sorted(COLS))
        self.assertLessEqual(set(p["types"].values()), {"dict", "num", "str", "raw"})

    def test_kamus_terurut(self):
        # Klien mengurut kolom berkamus dengan MEMBANDINGKAN INDEKS, bukan teks
        # (lihat useColumnarTable.js). Itu hanya benar bila tabel kamusnya
        # terurut — kalau tidak, kolom Kategori terurut acak tanpa gejala lain.
        p = _kolumnar(_rows(200), COLS)
        for name, tabel in p["dict"].items():
            with self.subTest(kolom=name):
                self.assertEqual(tabel, sorted(tabel))

    def test_tanpa_baris(self):
        p = _kolumnar([], [])
        self.assertEqual((p["n"], p["cols"], p["dict"], p["data"]), (0, [], {}, {}))

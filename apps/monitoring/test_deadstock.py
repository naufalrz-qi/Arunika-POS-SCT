"""Deadstock: aturan penyaringnya (fungsi murni) dan panel detailnya.

Angka dari server nyata diverifikasi terpisah di kedua profil lokal; yang
dijaga di sini aturan mana yang memasukkan/mengeluarkan barang dari daftar.
"""
import datetime as dt
import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.auth_app.models import Role, User
from apps.monitoring import views as v

HARI_INI = dt.date(2026, 9, 26)


def _lv(kd, stok, divisi="D1", harga_jual=1000.0, nominal=None):
    return {"kd_barang": kd, "barang": f"Barang {kd}", "kategori": "K", "divisi": divisi,
            "stok_akhir": stok, "harga_jual": harga_jual,
            "nominal": stok * 10 if nominal is None else nominal}


def _t(hari_lalu):
    d = HARI_INI - dt.timedelta(days=hari_lalu)
    return dt.datetime(d.year, d.month, d.day, 10, 0)


def _saring(levels, jual=None, beli=None, hari=90, cari=""):
    rows = v._saring_deadstock(levels, jual or {}, beli or {}, HARI_INI, hari, cari)
    return {r["kd_barang"]: r for r in rows}


class SaringDeadstock(SimpleTestCase):
    def test_laku_dalam_jendela_keluar(self):
        self.assertEqual(_saring([_lv("A", 5)], jual={"A": _t(10)}), {})

    def test_laku_lama_masuk_dengan_hari_tak_laku(self):
        r = _saring([_lv("A", 5)], jual={"A": _t(200)}, beli={"A": (_t(400), _t(5))})["A"]
        self.assertEqual(r["hari_tak_laku"], 200)
        self.assertEqual(r["jual_terakhir"], _t(200).date().isoformat())
        # Restock barang mati tetap masuk — justru itu yang perlu terlihat.
        self.assertEqual(r["beli_terakhir"], _t(5).date().isoformat())

    def test_tepat_di_batas_masuk(self):
        self.assertIn("A", _saring([_lv("A", 5)], jual={"A": _t(90)}))
        self.assertEqual(_saring([_lv("A", 5)], jual={"A": _t(89)}), {})

    def test_tak_pernah_laku_dan_beli_pertama_lama_masuk(self):
        r = _saring([_lv("A", 5)], beli={"A": (_t(300), _t(300))})["A"]
        self.assertIsNone(r["hari_tak_laku"])
        self.assertIsNone(r["jual_terakhir"])

    def test_tak_pernah_laku_tanpa_pembelian_masuk(self):
        self.assertIn("A", _saring([_lv("A", 5)]))

    def test_barang_baru_belum_sempat_laku_keluar(self):
        self.assertEqual(_saring([_lv("A", 5)], beli={"A": (_t(20), _t(20))}), {})

    def test_stok_habis_atau_minus_keluar(self):
        self.assertEqual(_saring([_lv("A", 0), _lv("B", -3)]), {})

    def test_barang_non_jual_keluar(self):
        self.assertEqual(_saring([_lv("A", 5, harga_jual=0)]), {})

    def test_divisi_dijumlah_jadi_satu_baris(self):
        r = _saring([_lv("A", 5, "D1"), _lv("A", 3, "D2"), _lv("A", 0, "D3")])["A"]
        self.assertEqual(r["qty_stok"], 8)
        self.assertEqual(r["nilai_stok"], 80)
        self.assertEqual(r["per_divisi"], [{"divisi": "D1", "stok": 5}, {"divisi": "D2", "stok": 3}])

    def test_kunci_dinormalisasi(self):
        """Kunci stok dan kunci penjualan bisa beda spasi ujung/huruf — `_k`."""
        self.assertEqual(_saring([_lv("abc ", 5)], jual={"ABC": _t(1)}), {})

    def test_cari(self):
        rows = _saring([_lv("A1", 5), _lv("B2", 5)], cari="b2")
        self.assertEqual(list(rows), ["B2"])


class DetailDeadstock(TestCase):
    GERAKAN = [{"tanggal": f"2026-01-{i:02d} 10:00", "transaksi": "Penjualan",
                "harga": 1000.0, "saldo": 1.0} for i in range(1, 41)]

    def _get(self, **kw):
        u = User.objects.create_user(
            f"ds{User.objects.count()}", password="rahasia-kuat-123",
            role=Role.ADMIN, allowed_menu_keys=["deadstock"], **kw)
        self.client.force_login(u)
        with patch.object(v, "_active", lambda: object()), \
             patch.object(v.inv, "barang_histori", lambda *a, **k: [dict(g) for g in self.GERAKAN]):
            return self.client.get("/admin-panel/analitik/deadstock/detail?kd_barang=A")

    def test_tiga_puluh_terbaru_dulu(self):
        d = json.loads(self._get().content)
        self.assertEqual(d["jml_gerakan"], 40)
        self.assertEqual(len(d["gerakan"]), 30)
        self.assertEqual(d["gerakan"][0]["tanggal"], "2026-01-40 10:00")
        self.assertIn("harga", d["gerakan"][0])

    def test_harga_butuh_kedua_izin(self):
        for kunci in ("harga_jual", "harga_beli"):
            d = json.loads(self._get(hidden_data_keys=[kunci]).content)
            self.assertNotIn("harga", d["gerakan"][0], kunci)

    def test_tanpa_kd_barang_400(self):
        u = User.objects.create_user("ds_x", password="rahasia-kuat-123",
                                     role=Role.ADMIN, allowed_menu_keys=["deadstock"])
        self.client.force_login(u)
        self.assertEqual(self.client.get("/admin-panel/analitik/deadstock/detail").status_code, 400)

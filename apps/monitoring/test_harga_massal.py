"""Jalur tulis Terapkan Massal: bentuk payload JSON -> panggilan update_harga.

Tidak menyentuh MS SQL — `master.update_harga` di-patch dan panggilannya direkam.
Yang diuji justru bagian yang paling gampang salah diam-diam: parsing body JSON,
pengelompokan per barang, dan penanganan baris yang ditolak validasi.
"""
import json
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.master_data.services import HargaTidakBulat
from apps.monitoring import views


class FakeProfile:
    name = "RTL TEST"
    db_type = "retail"


def _post(payload):
    request = RequestFactory().post(
        "/admin-panel/master/update-barang/harga-massal",
        data=json.dumps(payload),
        content_type="application/json",
    )
    request.session = {}
    return request


class TerapkanMassalTest(SimpleTestCase):
    def setUp(self):
        patcher_active = patch.object(views, "_active", return_value=FakeProfile())
        patcher_log_rows = patch.object(views, "log_barang_updates")
        patcher_log_act = patch.object(views, "log_activity")
        for p in (patcher_active, patcher_log_rows, patcher_log_act):
            p.start()
            self.addCleanup(p.stop)

    def test_payload_dikelompokkan_per_barang(self):
        calls = []

        def fake_update(profile, kd_barang, prices):
            calls.append((kd_barang, dict(prices)))
            return [{"kd_satuan": k, "harga_lama": 0.0, "harga_baru": v} for k, v in prices.items()]

        with patch.object(views.master, "update_harga", side_effect=fake_update):
            request = _post({"items": [
                {"kd_barang": "A1", "kd_satuan": "PCS", "harga": 3000, "nama": "Barang A"},
                {"kd_barang": "A1", "kd_satuan": "BOX", "harga": 45000, "nama": "Barang A"},
                {"kd_barang": "B2", "kd_satuan": "PCS", "harga": 12000, "nama": "Barang B"},
            ]})
            views.update_barang_harga_massal(request)

        # Dua barang -> dua panggilan; satuan milik barang yang sama digabung.
        self.assertEqual(len(calls), 2)
        self.assertEqual(dict(calls)["A1"], {"PCS": 3000, "BOX": 45000})
        self.assertEqual(dict(calls)["B2"], {"PCS": 12000})
        self.assertIn("3 satuan", request.session["flash_success"])

    def test_barang_ditolak_tidak_menggagalkan_sisanya(self):
        def fake_update(profile, kd_barang, prices):
            if kd_barang == "BAD":
                raise HargaTidakBulat("PCS: 3000.001")
            return [{"kd_satuan": "PCS", "harga_lama": 0.0, "harga_baru": 3000}]

        with patch.object(views.master, "update_harga", side_effect=fake_update):
            request = _post({"items": [
                {"kd_barang": "BAD", "kd_satuan": "PCS", "harga": 3000.001},
                {"kd_barang": "OK", "kd_satuan": "PCS", "harga": 3000},
            ]})
            views.update_barang_harga_massal(request)

        pesan = request.session["flash_error"]
        self.assertIn("1 satuan diperbarui", pesan)
        self.assertIn("BAD", pesan)

    def test_seleksi_kosong_tidak_menulis(self):
        with patch.object(views.master, "update_harga") as m:
            request = _post({"items": []})
            views.update_barang_harga_massal(request)
        m.assert_not_called()
        self.assertIn("Tidak ada baris", request.session["flash_error"])

    def test_baris_cacat_dilewati_bukan_crash(self):
        calls = []

        def fake_update(profile, kd_barang, prices):
            calls.append(kd_barang)
            return []

        with patch.object(views.master, "update_harga", side_effect=fake_update):
            request = _post({"items": [
                "bukan objek",
                {"kd_satuan": "PCS", "harga": 3000},          # kd_barang hilang
                {"kd_barang": "C3", "harga": 3000},           # kd_satuan hilang
                {"kd_barang": "OK", "kd_satuan": "PCS", "harga": 3000},
            ]})
            views.update_barang_harga_massal(request)

        self.assertEqual(calls, ["OK"])

    def test_items_bukan_list_ditolak(self):
        with patch.object(views.master, "update_harga") as m:
            request = _post({"items": "PCS"})
            views.update_barang_harga_massal(request)
        m.assert_not_called()

    def test_harga_hilang_diteruskan_apa_adanya_untuk_divalidasi_backend(self):
        # View tidak boleh diam-diam menormalkan harga yang hilang jadi 0 —
        # None harus sampai ke update_harga supaya _cek_harga_bulat menolaknya.
        captured = {}

        def fake_update(profile, kd_barang, prices):
            captured.update(prices)
            return []

        with patch.object(views.master, "update_harga", side_effect=fake_update):
            views.update_barang_harga_massal(_post({"items": [
                {"kd_barang": "A1", "kd_satuan": "PCS"},  # tanpa field harga
            ]}))

        self.assertIsNone(captured["PCS"])

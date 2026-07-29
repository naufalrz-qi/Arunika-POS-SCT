"""Jam yang tampil di layar = zona waktu situs, bukan UTC.

USE_TZ=True menyimpan semua datetime ORM dalam UTC. `value.strftime(...)`
langsung mencetak UTC apa adanya — Log Aktivitas jam 10:34 WIB terbaca
03:34. Konversinya ada di `_local()`; ini yang menjaganya.
"""
import datetime as dt

from django.test import SimpleTestCase, override_settings

from apps.monitoring.views import _local

UTC_SIANG = dt.datetime(2026, 7, 28, 3, 34, 56, tzinfo=dt.timezone.utc)


class LocalTimeFormat(SimpleTestCase):
    # Zona dipatok eksplisit, tidak diwarisi dari .env: tanpa ini test gagal di
    # mesin siapa pun yang TIME_ZONE-nya bukan Asia/Jakarta (mis. Asia/Makassar
    # → "11:34:56"), padahal yang diuji konversinya, bukan setelan zonanya.
    @override_settings(TIME_ZONE="Asia/Jakarta")  # UTC+7
    def test_utc_digeser_ke_zona_situs(self):
        self.assertEqual(_local(UTC_SIANG), "2026-07-28 10:34:56")

    @override_settings(TIME_ZONE="Asia/Jayapura")  # UTC+9
    def test_zona_bisa_diatur(self):
        self.assertEqual(_local(UTC_SIANG), "2026-07-28 12:34:56")

    def test_pergantian_hari_ikut_bergeser(self):
        # 20:00 UTC = 03:00 WIB keesokan harinya; format tanggal-saja pun
        # harus ikut, kalau tidak Log Aktivitas mengelompokkannya salah hari.
        malam = dt.datetime(2026, 7, 27, 20, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(_local(malam, "%Y-%m-%d"), "2026-07-28")

    def test_datetime_naif_dibiarkan(self):
        # Tanggal dari MS SQL legacy sudah waktu lokal — menggesernya lagi
        # justru membuatnya salah.
        naif = dt.datetime(2026, 7, 28, 10, 34, 56)
        self.assertEqual(_local(naif), "2026-07-28 10:34:56")

    def test_kosong_jadi_string_kosong(self):
        self.assertEqual(_local(None), "")

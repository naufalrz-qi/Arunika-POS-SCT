"""Nilai uang yang dicabut tak boleh IKUT TERKIRIM, bukan sekadar tak tampil.

Menyembunyikan kolom di Vue tidak membatasi apa pun: payload-nya tetap sampai
ke peramban dan terbaca di tab Network. Stok Akhir bahkan mengirim seluruh
katalog dalam satu payload kolumnar, jadi satu permintaan memuat harga ~55rb
barang sekaligus. Karena itu yang diuji di sini isi RESPONS, bukan layarnya.
"""
from django.test import SimpleTestCase, TestCase

from apps.auth_app.models import DATA_KEY_SET, Role, User
from apps.monitoring.views import (
    _KLASIFIKASI_UANG,
    _UANG_INFO_KASIR,
    _hidden_fields,
    _tanpa_kolom,
)

# Kolom uang milik Klasifikasi Pelanggan. Diambil dari sumbernya, bukan ditulis
# ulang: daftar yang dijiplak akan tetap hijau justru ketika seseorang menambah
# kolom uang baru dan lupa mendaftarkannya.
_UANG_KLASIFIKASI = set(_KLASIFIKASI_UANG)


def _payload():
    """Payload kolumnar mini dengan bentuk yang sama seperti _kolumnar()."""
    return {
        "cols": ["kd_barang", "divisi", "harga_jual", "harga_average", "nominal"],
        "types": {
            "kd_barang": "str", "divisi": "dict", "harga_jual": "num",
            "harga_average": "num", "nominal": "num",
        },
        "dict": {"divisi": ["A", "B"]},
        "data": {
            "kd_barang": ["X1", "X2"], "divisi": [0, 1], "harga_jual": [10.0, 20.0],
            "harga_average": [7.0, 8.0], "nominal": [70.0, 160.0],
        },
        "n": 2,
    }


class TanpaKolom(SimpleTestCase):
    def test_kolom_dibuang_dari_ketiga_map(self):
        p = _tanpa_kolom(_payload(), {"nominal", "harga_average"})
        self.assertEqual(p["cols"], ["kd_barang", "divisi", "harga_jual"])
        self.assertNotIn("nominal", p["types"])
        self.assertNotIn("nominal", p["data"])
        self.assertNotIn("harga_average", p["data"])
        self.assertEqual(p["n"], 2)

    def test_kamus_kolom_yang_bertahan_ikut_terbawa(self):
        p = _tanpa_kolom(_payload(), {"nominal"})
        self.assertEqual(p["dict"]["divisi"], ["A", "B"])

    def test_objek_asal_TIDAK_diubah(self):
        """Inti tes ini. Payload kolumnar dicache PER PROFIL, bukan per user
        (`stok_kolumnar:<tanggal>` di apps/inventory/services.py). Kalau
        _tanpa_kolom mengedit objeknya, kolom itu lenyap untuk SEMUA user
        sampai pemanas menimpanya — dan bug itu hanya muncul kalau user
        terbatas kebetulan membuka halaman lebih dulu."""
        asal = _payload()
        _tanpa_kolom(asal, {"nominal", "harga_jual", "harga_average"})
        self.assertEqual(asal["cols"], _payload()["cols"])
        self.assertEqual(sorted(asal["data"]), sorted(_payload()["data"]))
        self.assertIn("nominal", asal["types"])

    def test_larik_kolom_dipakai_bersama_bukan_disalin(self):
        # Salinan larik akan menggandakan 55rb entri per permintaan.
        asal = _payload()
        p = _tanpa_kolom(asal, {"nominal"})
        self.assertIs(p["data"]["harga_jual"], asal["data"]["harga_jual"])

    def test_tanpa_larangan_objek_yang_sama_dikembalikan(self):
        asal = _payload()
        self.assertIs(_tanpa_kolom(asal, set()), asal)


class HiddenFields(TestCase):
    def test_satu_izin_menutup_beberapa_field(self):
        u = User.objects.create_user("u1", role=Role.ADMIN, hidden_data_keys=["harga_beli"])
        self.assertEqual(
            _hidden_fields(_Req(u)), {"harga_average", "harga_beli_akhir"})

    def test_nominal_ikut_menutup_omset_dan_nilai_fast_moving(self):
        # `nilai` sempat terlewat: omset di kartu ringkasan sudah hilang, tapi
        # rupiah per barang di tabel Fast Moving di bawahnya masih tampil —
        # cukup untuk menjumlahkan sendiri apa yang baru saja disembunyikan.
        u = User.objects.create_user("u2", role=Role.ADMIN, hidden_data_keys=["nominal"])
        self.assertEqual(
            _hidden_fields(_Req(u)),
            {"nominal", "revenue", "nilai"}
            | _UANG_KLASIFIKASI | _UANG_INFO_KASIR,
        )

    def test_nominal_menutup_kolom_uang_panel_info_kasir(self):
        # Panel info kasir berdiri di luar /admin-panel, jadi ia tak lewat satu
        # pun spec laporan: kalau namanya tak ada di sini, piutang dan batas
        # kredit tetap terkirim ke akun yang rupiahnya sudah dicabut.
        u = User.objects.create_user("u5", role=Role.ADMIN, hidden_data_keys=["nominal"])
        self.assertTrue(_UANG_INFO_KASIR <= _hidden_fields(_Req(u)))

    def test_nominal_menutup_seluruh_kolom_uang_klasifikasi_pelanggan(self):
        # Diuji terpisah dari daftar di atas supaya jelas apa yang dijaga: halaman
        # Klasifikasi Pelanggan menyajikan belanja per ORANG di tiga rute berbeda
        # (laporan, panel detail, dua sheet export). Kolom yang lupa didaftarkan
        # di sini akan lolos di salah satu rute tanpa gejala apa pun di layar.
        u = User.objects.create_user("u4", role=Role.ADMIN, hidden_data_keys=["nominal"])
        self.assertTrue(_UANG_KLASIFIKASI <= _hidden_fields(_Req(u)))

    def test_superadmin_tak_pernah_dibatasi(self):
        u = User.objects.create_user("boss", role=Role.SUPERADMIN,
                                     hidden_data_keys=sorted(DATA_KEY_SET))
        self.assertEqual(_hidden_fields(_Req(u)), set())

    def test_kunci_asing_diabaikan(self):
        # Nilai basi di JSONField (mis. sisa rilis lama) tak boleh menutup apa pun.
        u = User.objects.create_user("u3", role=Role.ADMIN, hidden_data_keys=["ngawur"])
        self.assertEqual(_hidden_fields(_Req(u)), set())

    def test_user_lama_tak_kehilangan_apa_pun(self):
        """Default field = [] → migrasi pada basis data berjalan tak mencabut
        akses siapa pun."""
        u = User.objects.create_user("u4", role=Role.ADMIN)
        self.assertEqual(u.hidden_data_keys, [])
        self.assertEqual(_hidden_fields(_Req(u)), set())


class _Req:
    """request tiruan — _hidden_fields hanya membaca request.user."""

    def __init__(self, user):
        self.user = user


class MenusSaveDataKeys(TestCase):
    """Layar mengirim yang BOLEH dilihat; yang disimpan kebalikannya."""

    def setUp(self):
        self.boss = User.objects.create_user(
            "boss", password="rahasia-kuat-123", role=Role.SUPERADMIN)
        self.staf = User.objects.create_user("staf", role=Role.ADMIN)
        self.client.force_login(self.boss)

    def _save(self, data_keys):
        return self.client.post(
            "/admin-panel/menus/save",
            {"user_id": self.staf.id, "menu_keys": ["dashboard"], "data_keys": data_keys},
            content_type="application/json",
        )

    def test_sebagian_dicentang(self):
        self._save(["harga_jual"])
        self.staf.refresh_from_db()
        self.assertEqual(set(self.staf.hidden_data_keys), {"harga_beli", "nominal"})

    def test_kosong_berarti_semua_disembunyikan(self):
        """Justru kasus yang membuat daftar-izin berbahaya: dengan konvensi
        `allowed_menu_keys` ("kosong = akses penuh"), mematikan semua centang
        akan memberi akses penuh — kebalikan dari maksud si penyetel."""
        self._save([])
        self.staf.refresh_from_db()
        self.assertEqual(set(self.staf.hidden_data_keys), DATA_KEY_SET)

    def test_semua_dicentang_berarti_tak_ada_yang_disembunyikan(self):
        self._save(sorted(DATA_KEY_SET))
        self.staf.refresh_from_db()
        self.assertEqual(self.staf.hidden_data_keys, [])

    def test_kunci_asing_ditolak(self):
        self._save(["harga_jual", "ngawur"])
        self.staf.refresh_from_db()
        self.assertNotIn("ngawur", self.staf.hidden_data_keys)

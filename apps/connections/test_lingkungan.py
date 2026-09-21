"""Penanda produksi vs uji coba.

Yang dijaga di sini bukan fiturnya melainkan ARAH kegagalannya: sebuah profil
yang tak jelas lingkungannya harus diperlakukan sebagai SUNGGUHAN. Bawaan yang
terbalik akan membuat server produksi yang lupa ditandai tampil berlencana
"Uji coba" — tepat kebalikan dari gunanya penanda ini.
"""
from django.test import SimpleTestCase, TestCase

from apps.connections import views
from apps.connections.models import Lingkungan, ServerProfile


class BawaanAman(TestCase):
    def test_profil_baru_dianggap_produksi(self):
        p = ServerProfile.objects.create(name="x", host="h", db_name="d", username="u")
        self.assertEqual(p.lingkungan, Lingkungan.PRODUKSI)

    def test_navbar_menerima_lingkungan(self):
        """`as_dict` adalah prop bersama yang dipakai lencana navbar. Kalau
        kolomnya tak ikut, lencananya diam-diam tak pernah muncul."""
        p = ServerProfile.objects.create(
            name="x", host="h", db_name="d", username="u", lingkungan=Lingkungan.UJI,
        )
        self.assertEqual(p.as_dict()["lingkungan"], "uji")

    def test_bukan_alamat_server(self):
        """Prop umum tetap tak boleh membawa alamat — penanda ini label, dan
        penambahannya tak boleh jadi celah masuk bagi host/port/db_name."""
        p = ServerProfile.objects.create(name="x", host="rahasia", db_name="d", username="u")
        d = p.as_dict()
        for bocor in ("host", "port", "db_name", "username", "password_encrypted"):
            self.assertNotIn(bocor, d)


class FormJatuhKeProduksi(SimpleTestCase):
    def _terap(self, nilai):
        p = ServerProfile(name="x", host="h", db_name="d", username="u")
        views._apply_form(p, {"name": "x", "host": "h", "db_name": "d",
                              "username": "u", "lingkungan": nilai})
        return p.lingkungan

    def test_nilai_sah_diterima(self):
        self.assertEqual(self._terap("uji"), Lingkungan.UJI)
        self.assertEqual(self._terap("produksi"), Lingkungan.PRODUKSI)

    def test_nilai_asing_jadi_produksi(self):
        """Termasuk yang kosong dan yang tak ada sama sekali. Menyimpan nilai
        asing apa adanya akan membuat lencananya menampilkan slug mentah, dan
        lebih buruk: profil itu tak terbaca sebagai produksi MAUPUN uji."""
        for nilai in ("", None, "UJI", "staging", "uji "):
            self.assertEqual(self._terap(nilai), Lingkungan.PRODUKSI, f"nilai {nilai!r}")

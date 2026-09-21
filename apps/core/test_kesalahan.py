"""`handler500` harus membedakan pangkal mati dari kesalahan biasa.

Jalur yang diuji adalah jalur yang sebenarnya dipakai Django: view melempar, lalu
`response_for_exception` memanggil `handler500`. Bukan memanggil `server_error()`
langsung — test yang memanggil helper-nya sendiri akan tetap hijau seandainya
`handler500` lupa dipasang di `config/urls.py`.

Path uji sengaja berawalan `/login` supaya lolos `auth_required`: itu juga skenario
yang paling mungkin terjadi sungguhan, karena halaman login justru yang pertama
dibuka orang saat pangkalnya mati.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
import pyodbc
from django.db import InterfaceError, OperationalError
from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings
from django.urls import path


def _pangkal_mati(request):
    raise OperationalError("[08001] TCP Provider: tak terjangkau")


def _antarmuka_putus(request):
    raise InterfaceError("koneksi tertutup di tengah jalan")


def _legacy_mati(request):
    # Yang dilempar core/mssql.py saat server legacy tak terjangkau: pyodbc mentah,
    # BUKAN turunan kelas django.db.
    raise pyodbc.OperationalError("08001", "server legacy tak terjangkau")


def _salah_biasa(request):
    raise ValueError("bug biasa")


def _sehat(request):
    return HttpResponse("ok")


urlpatterns = [
    path("login-uji/pangkal", _pangkal_mati),
    path("login-uji/antarmuka", _antarmuka_putus),
    path("login-uji/legacy", _legacy_mati),
    path("login-uji/lain", _salah_biasa),
    path("login-uji/sehat", _sehat),
]
handler500 = "apps.core.kesalahan.server_error"


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
class Handler500(SimpleTestCase):
    def setUp(self):
        # Tanpa ini klien test melempar ulang exception-nya alih-alih
        # mengembalikan respons yang dihasilkan handler.
        self.client.raise_request_exception = False

    def test_pangkal_mati_dijelaskan(self):
        r = self.client.get("/login-uji/pangkal")
        isi = r.content.decode()
        self.assertEqual(r.status_code, 503)
        self.assertIn("Basis data pangkal tidak terjangkau", isi)
        # Dua hal yang membuat halaman ini ada: ke mana orang harus melihat, dan
        # penegasan bahwa data transaksi tak ikut terdampak.
        self.assertIn("SQL Server", isi)
        self.assertIn("tidak terdampak", isi)

    def test_antarmuka_putus_diperlakukan_sama(self):
        self.assertEqual(self.client.get("/login-uji/antarmuka").status_code, 503)

    def test_galat_legacy_bukan_urusan_halaman_ini(self):
        """pyodbc mentah = server legacy, bukan pangkal.

        Kalau ini ikut tertangkap, halaman yang sebenarnya masih bisa dipakai akan
        diganti layar penuh 'pangkal mati' yang menuduh mesin yang salah.
        """
        r = self.client.get("/login-uji/legacy")
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("Basis data pangkal", r.content.decode())

    def test_kesalahan_biasa_tetap_500(self):
        r = self.client.get("/login-uji/lain")
        isi = r.content.decode()
        self.assertEqual(r.status_code, 500)
        self.assertIn("Terjadi kesalahan di server", isi)
        self.assertNotIn("Basis data pangkal", isi)
        # Jejak Python tak boleh bocor ke pengguna saat DEBUG mati.
        self.assertNotIn("Traceback", isi)

    def test_permintaan_sehat_tak_terganggu(self):
        self.assertEqual(self.client.get("/login-uji/sehat").status_code, 200)

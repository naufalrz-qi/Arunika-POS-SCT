"""Halaman 500, dengan satu perkecualian: pangkal yang tak terjangkau.

## Kenapa ini ada

Sejak pangkal pindah ke MS SQL, matinya layanan basis data di mesin ini membuat
SELURUH aplikasi tak bisa dibuka — termasuk halaman login, karena sesi disimpan di
DB. Itu harga yang memang dipilih (lihat `context.md` § "Kenapa login user di MS SQL,
bukan SQLite"), tapi sebelumnya pengguna cuma melihat "Terjadi kesalahan di server",
yang tak memberi petunjuk apa pun ke orang yang bisa memperbaikinya.

## Kenapa `handler500`, bukan middleware

Middleware tak bisa menangkapnya. Django membungkus SETIAP lapisan middleware dengan
`convert_exception_to_response`, jadi galat yang dilempar lapisan dalam sudah berubah
jadi respons 500 sebelum sampai ke lapisan luar — middleware di atasnya tak pernah
melihat exception-nya. `handler500` dipanggil dari `response_for_exception`, satu
tempat yang dilewati keduanya: galat dari view maupun dari middleware.

## Yang sengaja TIDAK ditangkap

Hanya `django.db.OperationalError` / `InterfaceError`, yaitu koneksi `default`.
Galat dari server legacy adalah `pyodbc.*` mentah (lihat `core/mssql.py`) dan bukan
turunan kelas Django ini — itu sudah punya jalurnya sendiri lewat
`mssql.friendly_error()`, yang menampilkan banner di halaman yang bersangkutan alih-alih
membuang seluruh layar. Menyeret keduanya ke sini akan menyembunyikan halaman yang
sebenarnya masih bisa dipakai.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
import sys

from django.db import InterfaceError, OperationalError
from django.http import HttpResponse
from django.template import loader


def server_error(request, template_name="500.html"):
    """`handler500` — ganti halaman kalau yang mati adalah pangkal."""
    galat = sys.exc_info()[1]
    if isinstance(galat, (OperationalError, InterfaceError)):
        # 503, bukan 500: ini keadaan sementara yang hilang begitu layanannya hidup.
        # Dirender TANPA request supaya tak ada context processor yang jalan —
        # `auth` akan menyentuh DB yang baru saja terbukti mati.
        return HttpResponse(loader.render_to_string("pangkal_mati.html"), status=503)
    return HttpResponse(loader.render_to_string(template_name), status=500)

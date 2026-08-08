"""Membaca tautan user legacy untuk koneksi yang sedang aktif.

Dipisah dari model supaya satu aturan berdiri di satu tempat: **tidak ada
fallback**. Kalau akun ini belum ditautkan untuk koneksi yang sedang dipakai,
jalur tulis menolak — ia TIDAK meminjam tautan koneksi lain.

Meminjam adalah kegagalan yang paling mahal di sini, dan yang paling tak
terlihat. `kd_user` dibuat berurutan oleh tiap server sendiri-sendiri, jadi
`UAA002` milik orang lain di server lain (terukur: 10 dari 11 kode bersama
menunjuk orang berbeda). Nota yang ditulis dengan kode pinjaman akan tersimpan
tanpa galat, lolos foreign key, dan langsung terkirim ke pusat oleh trigger —
atas nama orang yang tak pernah menyentuhnya.

Resolusinya juga sengaja EKSPLISIT (profil dioper sebagai argumen), bukan
properti yang diam-diam membaca profil aktif dari thread-local. Di perintah
`manage.py` dan thread penjadwal tak ada profil request, dan properti ajaib
akan jatuh ke profil `is_default` — persis peminjaman yang dilarang di atas,
cuma lebih sulit dilihat.
"""
from apps.auth_app.models import TautanUser

# Dipakai layar yang cuma MENAMPILKAN kode; kosong bukan galat di sana.
KOSONG = TautanUser(kd_user="", kd_divisi="", kd_pegawai="")


def tautan_untuk(user, profile):
    """Tautan user ini untuk `profile`, atau `KOSONG` kalau belum ada.

    Untuk MENAMPILKAN saja. Jalur tulis pakai `tautan_wajib`.
    """
    if not (user and getattr(user, "is_authenticated", False) and profile):
        return KOSONG
    return (TautanUser.objects.filter(user=user, profile=profile).first()
            or KOSONG)


def tautan_wajib(user, profile):
    """Tautan yang lengkap, atau `ValueError` berisi apa yang harus dilakukan.

    `kd_user` DAN `kd_divisi` sama-sama wajib: yang pertama menentukan transaksi
    tercatat atas nama siapa, yang kedua menentukan awalan nomornya dan divisi
    mana yang stoknya bergeser. `kd_pegawai` tidak wajib — ia cuma nilai bawaan
    di form nota dan bisa dipilih di layar.
    """
    if not profile:
        raise ValueError(
            "Tidak ada koneksi aktif. Pilih koneksi di navbar sebelum menyimpan.")
    t = tautan_untuk(user, profile)
    kurang = [nama for nama, nilai in
              (("user legacy", t.kd_user), ("divisi", t.kd_divisi)) if not nilai]
    if kurang:
        raise ValueError(
            f"Akun Anda belum ditautkan ({' dan '.join(kurang)} belum diisi) untuk "
            f"koneksi {profile.name}. Tautan dibuat per koneksi karena kode user "
            f"legacy berbeda artinya di tiap server. Minta pengelola aplikasi "
            f"mengisinya di Kelola Tautan User."
        )
    return t

"""App-local user model (SQLite). PRD §4 — RBAC with 4 roles."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    KASIR = "kasir", "Kasir"
    SUPERVISOR = "supervisor", "Supervisor"
    ADMIN = "admin", "Admin"
    SUPERADMIN = "superadmin", "Superadmin"


# Kelompok nilai uang yang bisa dicabut per user. Bukan nama kolom database:
# satu kunci menutup beberapa field sekaligus (lihat _hidden_fields di
# apps/monitoring/views.py untuk pemetaannya).
DATA_KEYS = [
    {"key": "harga_jual", "label": "Harga jual"},
    {"key": "harga_beli", "label": "Harga beli / modal"},
    {"key": "nominal", "label": "Nominal & omset"},
]
DATA_KEY_SET = {d["key"] for d in DATA_KEYS}


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.KASIR)
    # PRD §4.3 — Superadmin controls which menus an Admin may access.
    # Empty/null => use defaults; superadmin always sees everything.
    allowed_menu_keys = models.JSONField(default=list, blank=True)

    # Daftar LARANGAN, bukan daftar izin — dan itu disengaja.
    #
    # `allowed_menu_keys` di atas memakai konvensi "kosong = akses penuh"
    # (lihat menus_for()). Konvensi itu berbahaya untuk field yang menahan data:
    # superadmin yang mematikan SEMUA centang menghasilkan list kosong, yang
    # justru berarti akses penuh — persis kebalikan dari maksudnya. Sebagai
    # daftar larangan, kosong berarti tak ada yang disembunyikan (yaitu
    # perilaku hari ini, jadi tak ada user yang kehilangan akses saat deploy)
    # dan mematikan semua centang mengisi ketiga kunci.
    hidden_data_keys = models.JSONField(default=list, blank=True)

    # Tautan ke user legacy di MS SQL (m_userx.kd_user) dan divisi tempat ia
    # bekerja (m_divisi.kd_divisi). Transaksi menyimpan kd_user, bukan id user
    # Arunika, jadi tanpa tautan ini nota yang kita tulis tak bisa dikenali
    # laporan "Penjualan per User" — di Arunika MAUPUN di aplikasi POS lama.
    #
    # Hanya TAUTAN, bukan salinan akun — skema m_userx memang jauh berbeda dari
    # AbstractUser, jadi memetakan kolomnya satu per satu tak akan pernah rapi.
    # Yang dipinjam cuma kd_user-nya.
    #
    # Kata sandi tetap milik Arunika. Arunika TIDAK PERNAH membaca maupun
    # menulis dua kolom sandi di m_userx:
    #   passwd  — menyimpan sandi apa adanya (terukur 4-9 karakter, bukan hash);
    #             menyalinnya ke sini berarti menyebarkan sandi terbuka ke
    #             sistem kedua.
    #   passweb — peninggalan pengembang sebelumnya dan sudah diketahui
    #             mengganggu aplikasi legacy. Menulisinya berarti mengulang
    #             kerusakan yang sudah ada, bukan memperbaikinya.
    kd_user = models.CharField(max_length=6, blank=True, default="")
    kd_divisi = models.CharField(max_length=6, blank=True, default="")

    @property
    def is_admin_tier(self) -> bool:
        return self.role in (Role.ADMIN, Role.SUPERADMIN)

    def hidden_data(self) -> set[str]:
        """Kunci nilai uang yang TIDAK boleh dilihat user ini.

        Superadmin tak pernah dibatasi, sejalan dengan menus_for()."""
        if self.role == Role.SUPERADMIN:
            return set()
        return {k for k in (self.hidden_data_keys or []) if k in DATA_KEY_SET}

    def can_see(self, key: str) -> bool:
        return key not in self.hidden_data()

    def __str__(self) -> str:
        return f"{self.get_full_name() or self.username} ({self.role})"

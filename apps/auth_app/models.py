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

    # Tautan ke user legacy TIDAK ada di sini — ia per koneksi, lihat TautanUser
    # di bawah berkas ini.

    # Server yang boleh dipakai akun ini. Kasir/supervisor DIKUNCI ke sini dan
    # tak bisa berpindah: koneksi menentukan ke server toko MANA sebuah nota
    # tertulis, dan nota yang masuk ke cabang yang salah tak bisa ditarik —
    # ia langsung ikut terkirim ke pusat oleh trigger legacy.
    # Kosong berarti belum ditentukan; jalur tulis menolak, bukan menebak.
    server_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pengguna",
    )

    @property
    def koneksi_terkunci(self) -> bool:
        """Peran toko tak memilih koneksi; peran kantor memilih sendiri."""
        return self.role in (Role.KASIR, Role.SUPERVISOR)

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


class TautanUser(models.Model):
    """Tautan akun Arunika → user legacy `m_userx`, SATU PER KONEKSI.

    Kenapa per koneksi dan bukan satu field di User: `kd_user` dibuat berurutan
    (`UAA000`, `UAA001`, …) oleh tiap server SENDIRI-SENDIRI, jadi kode yang sama
    menunjuk orang yang berbeda di server yang berbeda. Terukur antara dua server:
    dari 11 kode yang ada di keduanya, 10 milik orang lain — `UAA002` adalah
    KASIR01 di satu server dan YIQ di server lain.

    Akibatnya satu `kd_user` di akun admin sudah salah sejak admin berpindah
    koneksi (dan admin memang berpindah — 14 profil). Nota atau koreksi stoknya
    akan tercatat atas nama orang lain di server tujuan, tanpa galat apa pun:
    kodenya valid di sana, cuma bukan miliknya.

    Kasir/supervisor tidak jadi kasus khusus — mereka terkunci ke satu server,
    jadi tautannya kebetulan cuma satu baris. Satu mekanisme, bukan dua.

    Ini TAUTAN, bukan salinan akun. Kata sandi tetap milik Arunika; Arunika tak
    pernah membaca maupun menulis `m_userx.passwd` (menyimpan sandi apa adanya,
    4-9 karakter) maupun `passweb` (peninggalan yang sudah diketahui mengganggu
    aplikasi legacy).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tautan")
    # Koneksi ikut terhapus bersama tautannya: tautan ke server yang sudah tak
    # ada tidak berarti apa-apa, dan menyimpannya cuma membuat layar menampilkan
    # baris hantu.
    profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="tautan")
    kd_user = models.CharField(max_length=6, blank=True, default="")
    kd_divisi = models.CharField(max_length=6, blank=True, default="")
    # Pegawai yang melayani, terisi otomatis di form nota. Tak bisa disimpulkan
    # dari kd_user: m_pegawai menyebutnya "KASIR9" sedangkan m_userx "KASIR01",
    # dan mencocokkan lewat nama akan menautkan orang yang salah tanpa satu pun
    # galat — nota lalu tercatat atas nama pegawai lain.
    kd_pegawai = models.CharField(max_length=6, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "profile"], name="tautan_unik_per_koneksi"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.profile_id} → {self.kd_user or '-'}"

"""MS SQL connection profiles (SQLite, PRD §5.1 / §7.2).

Passwords are stored Fernet-encrypted; the plaintext is never serialized to the
frontend (see `as_dict`). One profile may be the default per db_type.
"""
from django.db import models

from core.encryption import encrypt


class DbType(models.TextChoices):
    GUDANG = "gudang", "Gudang"
    GROSIR = "grosir", "Grosir"
    RETAIL = "retail", "Retail"


class ConnStatus(models.TextChoices):
    UNKNOWN = "unknown", "Belum dites"
    ONLINE = "online", "Online"
    OFFLINE = "offline", "Offline"


class ServerProfile(models.Model):
    name = models.CharField(max_length=100)
    db_type = models.CharField(max_length=10, choices=DbType.choices, default=DbType.GROSIR)
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=1433)
    db_name = models.CharField(max_length=128)
    username = models.CharField(max_length=128)
    password_encrypted = models.TextField(blank=True)
    # Retail pakai server grosir/gudang ini sebagai acuan modal (harga_jual grosir).
    cost_source = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="retail_children"
    )
    # Opsional: server kedua (replica laporan, disinkron via CDC — lihat
    # apps/transactions/cdc_sync.py) yang dipakai untuk query laporan berat,
    # supaya SELECT laporan tidak bersaing lock dengan transaksi kasir di
    # server legacy ini. Kosong => laporan tetap baca langsung dari server ini.
    report_source = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="report_children"
    )
    # Kode cabang untuk pusat data AMPHOREUS (apps/transactions/hub_sync.py).
    #
    # Wajib ditetapkan manual, dan sengaja TIDAK diturunkan dari `name`: tidak ada
    # satu pun kolom di data legacy yang menandai server asal — `divisi_id` di feed
    # bernilai DAA000/DAA004 di SEMUA server, dan `m_divisi.kd_divisi` juga DAA000
    # di semua server. Nilai inilah satu-satunya asal-usul kolom `kd_sumber` di
    # pusat, dan `no_transaksi` bisa sama antar-server (RUMAK & RTL RUMAK sama-sama
    # punya TR2608010005), jadi salah isi berarti nota dua cabang saling menimpa.
    #
    # Kosong = profil ini bukan sumber pusat. `sync_hub` melewatinya, bukan menebak.
    kode_sumber = models.CharField(max_length=20, blank=True, default="")
    is_default = models.BooleanField(default=False)
    last_status = models.CharField(max_length=10, choices=ConnStatus.choices, default=ConnStatus.UNKNOWN)
    last_checked = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["db_type", "name"]
        constraints = [
            # Unik hanya di antara yang terisi: dua cabang berbagi kode berarti
            # transaksi keduanya bertumpuk di baris pusat yang sama.
            models.UniqueConstraint(
                fields=["kode_sumber"],
                condition=models.Q(kode_sumber__gt=""),
                name="unique_kode_sumber_terisi",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.db_type}]"

    def set_password(self, plaintext: str) -> None:
        """Encrypt and store a plaintext MS SQL password."""
        self.password_encrypted = encrypt(plaintext)

    def make_default(self) -> None:
        """Jadikan ini satu-satunya koneksi aktif (global, lintas semua tipe)."""
        ServerProfile.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        if not self.is_default:
            self.is_default = True
            self.save(update_fields=["is_default"])

    def as_dict(self) -> dict:
        """Representasi untuk prop Inertia UMUM — tanpa password, DAN tanpa
        alamat server.

        `inertia_share` mengirim daftar koneksi sebagai prop bersama di SETIAP
        render, termasuk halaman `/kasir/*` yang sengaja tidak dijaga penjaga
        Tailscale. Selama `host`/`port`/`db_name`/`username` ikut di sini, setiap
        kasir menerima alamat server tokonya beserta nama user databasenya di
        dalam HTML tiap halaman, dan setiap admin menerima peta keempat belas
        server sekaligus — walau menu Koneksi Server tak diberikan kepadanya.

        Alasannya sama persis dengan yang sudah dipakai kartu status server di
        dashboard (`_boleh_lihat_server` di apps/monitoring/views.py): peta
        infrastruktur tak dibutuhkan siapa pun untuk MEMAKAI aplikasi. Yang
        membutuhkannya cuma satu layar, dan layar itu memanggil `as_dict_admin`.

        Yang tersisa di sini adalah yang benar-benar dipakai navbar & pemilih
        koneksi: nama, jenis, status, dan relasinya.
        """
        return {
            "id": self.pk,
            "name": self.name,
            "db_type": self.db_type,
            "cost_source": self.cost_source_id,
            "report_source": self.report_source_id,
            "is_default": self.is_default,
            "status": self.last_status,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
        }

    def as_dict_admin(self) -> dict:
        """`as_dict` + alamat server. HANYA untuk layar Kelola Koneksi Server,
        yang memang menampilkan dan menyunting kolom-kolom ini. Jangan dipakai
        di prop bersama — lihat alasannya di `as_dict`."""
        return self.as_dict() | {
            "host": self.host,
            "port": self.port,
            "db_name": self.db_name,
            "username": self.username,
        }

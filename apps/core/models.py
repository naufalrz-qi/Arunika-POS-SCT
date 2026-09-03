"""Audit trail (SQLite). PRD §5.1 / §7.6."""
import json

from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    # Denormalized username so logs survive user deletion.
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=50)
    detail = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.username} {self.action}"


def log_untuk(user):
    """Jejak yang boleh dilihat `user`: miliknya sendiri, kecuali superadmin.

    Satu aturan untuk TIGA layar — kartu Aktivitas Terbaru di dashboard, kotak
    notif di navbar, dan halaman Log Aktivitas. Sebelumnya hanya dashboard yang
    menyaring, dan halaman log memperlihatkan jejak semua orang kepada admin
    mana pun; dua aturan untuk data yang sama adalah cara paling rapi supaya
    satu di antaranya diam-diam tertinggal saat yang lain diperbaiki.

    Disaring lewat `username` (salinan teks di baris log), bukan relasi ke User:
    kolom itu didenormalisasi supaya jejak tetap terbaca setelah akunnya dihapus,
    dan menyaring lewat FK akan menyembunyikan baris-baris itu dari superadmin.
    """
    from apps.auth_app.models import Role

    qs = ActivityLog.objects.all()
    if not (user and getattr(user, "is_authenticated", False)):
        return qs.none()
    if user.role == Role.SUPERADMIN:
        return qs
    return qs.filter(username=user.username)


def log_activity(request, action, detail=""):
    """Convenience helper to record an audit entry from a request."""
    from apps.core.http import client_ip

    user = getattr(request, "user", None)
    # Lewat helper, bukan REMOTE_ADDR mentah: di belakang proxy setiap baris
    # audit akan mencatat alamat proxy-nya, dan pertanyaan "dari mana" — satu-
    # satunya alasan kolom ini ada — berhenti bisa dijawab untuk semua orang
    # sekaligus, tanpa ada yang menyadarinya sampai dibutuhkan.
    ip = client_ip(request) if request else None
    ActivityLog.objects.create(
        user=user if (user and user.is_authenticated) else None,
        username=(user.username if (user and user.is_authenticated) else ""),
        action=action,
        detail=detail,
        ip_address=ip,
    )


class SyncLog(models.Model):
    """Riwayat sinkronisasi antar-server (harga, m_barang, m_customer, m_supplier).

    Menggantikan ActivityLog (terlalu generik: tidak ada field src/dst/mode/
    jumlah) sebagai sumber data untuk halaman Riwayat Sinkronisasi.
    """

    class Status(models.TextChoices):
        OK = "ok", "Berhasil"
        PARTIAL = "partial", "Sebagian"
        FAILED = "failed", "Gagal"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_logs",
    )
    # Denormalized so logs survive user/profile deletion, same pattern as ActivityLog.username.
    username = models.CharField(max_length=150, blank=True)
    feature = models.CharField(max_length=30)  # "harga" | "m_barang" | "m_customer" | "m_supplier"
    mode = models.CharField(max_length=30, blank=True)
    src_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="sync_logs_src"
    )
    src_name = models.CharField(max_length=100, blank=True)
    dst_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="sync_logs_dst"
    )
    dst_name = models.CharField(max_length=100, blank=True)
    compared_count = models.PositiveIntegerField(default=0)
    applied_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK)
    detail = models.TextField(blank=True)  # JSON-serialized list of changed-item dicts
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.feature} {self.src_name}->{self.dst_name}"

    def items(self) -> list:
        return json.loads(self.detail) if self.detail else []


class BarangUpdateLog(models.Model):
    """Riwayat perubahan per-barang dari halaman Update Barang (harga & status).

    Satu baris per field yang benar-benar berubah (bukan per klik simpan), supaya
    "Riwayat" pada kartu barang bisa langsung menampilkan nilai lama -> baru.
    """

    class Field(models.TextChoices):
        HARGA = "harga", "Harga Jual"
        STATUS_BARANG = "status_barang", "Status Barang"
        STATUS_DIVISI = "status_divisi", "Status Divisi"
        STATUS_SATUAN = "status_satuan", "Status Satuan"
        # Identitas barang — hanya bisa diubah dari server gudang. Dicatat di
        # riwayat yang sama supaya satu tempat menjawab "apa yang berubah pada
        # barang ini"; nama yang berubah tanpa jejak adalah perubahan yang paling
        # menyulitkan, karena ia menyebar ke seluruh cabang lewat sinkronisasi.
        NAMA = "nama", "Nama Barang"
        KETERANGAN = "keterangan", "Keterangan"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barang_update_logs",
    )
    # Denormalized so logs survive user/profile deletion, same pattern as ActivityLog.username.
    username = models.CharField(max_length=150, blank=True)
    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="barang_update_logs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    kd_barang = models.CharField(max_length=30)
    nama_barang = models.CharField(max_length=150, blank=True)
    field = models.CharField(max_length=20, choices=Field.choices)
    kd_ref = models.CharField(max_length=30, blank=True)  # kd_satuan / kd_divisi, kosong utk level m_barang
    nilai_lama = models.CharField(max_length=100, blank=True)
    nilai_baru = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["profile", "kd_barang", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.kd_barang} {self.field}: {self.nilai_lama} -> {self.nilai_baru}"


def log_barang_updates(request, profile, kd_barang, nama_barang, entries):
    """Catat satu atau lebih perubahan field untuk satu barang (harga/status).

    `entries`: list of (field, kd_ref, nilai_lama, nilai_baru). Entri dengan
    nilai_lama == nilai_baru dilewati (bukan perubahan nyata).
    """
    user = getattr(request, "user", None)
    username = user.username if (user and user.is_authenticated) else ""
    rows = [
        BarangUpdateLog(
            user=user if (user and user.is_authenticated) else None,
            username=username,
            profile=profile,
            profile_name=profile.name if profile else "",
            kd_barang=kd_barang,
            nama_barang=nama_barang,
            field=field,
            kd_ref=kd_ref or "",
            nilai_lama="" if nilai_lama is None else str(nilai_lama),
            nilai_baru="" if nilai_baru is None else str(nilai_baru),
        )
        for field, kd_ref, nilai_lama, nilai_baru in entries
        if str(nilai_lama) != str(nilai_baru)
    ]
    if rows:
        BarangUpdateLog.objects.bulk_create(rows)


class CdcSyncCursor(models.Model):
    """Resume point for one CDC-synced table (apps/transactions/cdc_sync.py).

    `last_lsn` is the SQL Server LSN (varbinary(10)) up to which changes for
    this table have already been applied to the report_source replica, stored
    as a hex string (bytes.hex()) since Django/SQLite has no native varbinary.
    One row per (profile, table_name) — the sync job reads it to know where to
    resume, and writes it after each successful batch.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="cdc_cursors"
    )
    table_name = models.CharField(max_length=64)
    last_lsn = models.CharField(max_length=20, blank=True)  # hex(varbinary(10)) = 20 chars
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_rows_applied = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, default="ok")  # "ok" | "failed"
    error_message = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "table_name"], name="unique_cdc_cursor_per_table")
        ]

    def __str__(self) -> str:
        return f"{self.profile_id}:{self.table_name} @ {self.last_lsn or '(belum sync)'}"


def log_sync(request, feature, mode, src, dst, compared, applied, status="ok", items=None, error=""):
    """Catat satu proses sinkronisasi (harga atau master data) untuk halaman Riwayat Sinkronisasi."""
    user = getattr(request, "user", None)
    SyncLog.objects.create(
        user=user if (user and user.is_authenticated) else None,
        username=(user.username if (user and user.is_authenticated) else ""),
        feature=feature,
        mode=mode,
        src_profile=src,
        src_name=src.name if src else "",
        dst_profile=dst,
        dst_name=dst.name if dst else "",
        compared_count=compared,
        applied_count=applied,
        status=status,
        detail=json.dumps(items or []),
        error_message=error,
    )


class BarangHargaState(models.Model):
    """Harga terkini per SKU per koneksi — baseline untuk deteksi perubahan harga
    harian (management command `snapshot_harga`). Di-update di tempat, jadi
    ukurannya tetap (satu baris per SKU per server), bukan bertambah tiap hari.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="harga_states"
    )
    kd_barang = models.CharField(max_length=30)
    kd_satuan = models.CharField(max_length=30)
    harga_jual = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    margin = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "kd_barang", "kd_satuan"], name="unique_harga_state_sku")
        ]
        indexes = [models.Index(fields=["profile", "kd_barang", "kd_satuan"])]

    def __str__(self) -> str:
        return f"{self.profile_id}:{self.kd_barang}/{self.kd_satuan} = {self.harga_jual}"


class BarangHargaChange(models.Model):
    """Log perubahan harga yang terdeteksi job harian (append-only). Menangkap
    perubahan dari sumber APA PUN (termasuk edit langsung di POS), beda dari
    `BarangUpdateLog` yang hanya mencatat perubahan lewat aplikasi ini.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="harga_changes"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    kd_barang = models.CharField(max_length=30)
    nama_barang = models.CharField(max_length=150, blank=True)
    kd_satuan = models.CharField(max_length=30)
    harga_lama = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    harga_baru = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["profile", "-detected_at"]),
            models.Index(fields=["kd_barang", "-detected_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.detected_at:%Y-%m-%d} {self.kd_barang}/{self.kd_satuan} {self.harga_lama}->{self.harga_baru}"


class HargaSnapshotRun(models.Model):
    """Penanda satu kali jalan snapshot harga per (profile, tanggal). Dipakai
    scheduler in-process (config/wsgi.py + apps.core.scheduler) supaya cukup jalan
    sekali/hari selama server hidup, sekaligus info "terakhir dijalankan".
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="harga_snapshot_runs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    run_date = models.DateField()
    ran_at = models.DateTimeField(auto_now_add=True)
    changes = models.PositiveIntegerField(default=0)
    seeded = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-ran_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "run_date"], name="unique_harga_snapshot_run_per_day")
        ]

    def __str__(self) -> str:
        return f"{self.run_date} {self.profile_name}: {self.changes} perubahan"


class StokSnapshotRun(models.Model):
    """Penanda satu kali jalan snapshot stok per (profile, tanggal). Sama pola
    dengan HargaSnapshotRun: dipakai scheduler in-process supaya rebuild penuh
    (berat) cukup sekali/hari, sekaligus info "terakhir dijalankan".
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="stok_snapshot_runs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    run_date = models.DateField()
    ran_at = models.DateTimeField(auto_now_add=True)
    rows = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-ran_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "run_date"], name="unique_stok_snapshot_run_per_day")
        ]

    def __str__(self) -> str:
        return f"{self.run_date} {self.profile_name}: {self.rows} baris"


class StokSnapshotBaseRun(models.Model):
    """Penanda rebuild BASE snapshot (beku ~13 bln) per (profile, bulan-base).
    Base cukup dibangun sekali per bulan kalender base — marker ini mencegah
    rebuild penuh (berat, scan sejak tutup buku) berulang di bulan yang sama.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="stok_snapshot_base_runs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    base_month = models.CharField(max_length=7)  # "YYYY-MM" dari base_date
    ran_at = models.DateTimeField(auto_now_add=True)
    rows = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-ran_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "base_month"], name="unique_stok_snapshot_base_per_month")
        ]

    def __str__(self) -> str:
        return f"{self.base_month} {self.profile_name}: {self.rows} baris"


class SyncHealthSample(models.Model):
    """Satu pengukuran kesehatan sync legacy untuk satu server, satu waktu.

    Halaman Kesehatan Sync membaca angka LANGSUNG dari server tiap kali dibuka;
    tabel ini yang membuatnya jadi riwayat. Tanpa riwayat, "antre 8.000" tak bisa
    dibedakan dari "antre 8.000 dan naik terus sejak Mei" — dan justru pembedaan
    itulah yang tak ada selama empat tahun sementara RTL PUSAT menumpuk sejuta
    baris tanpa seorang pun tahu.

    Ditulis tiap tick scheduler (bukan harian): sync yang mati perlu ketahuan
    dalam hitungan menit, bukan besok.
    """

    class Status(models.TextChoices):
        OK = "ok", "Sehat"
        LAMBAT = "lambat", "Lambat"
        MATI = "mati", "Mati"
        OFFLINE = "offline", "Tak terhubung"

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sync_health_samples",
    )
    profile_name = models.CharField(max_length=100, blank=True)
    # Kedalaman antrean keluar (tbl_tmp_post) + umur baris tertuanya.
    antre = models.BigIntegerField(default=0)
    antre_tertua = models.DateTimeField(null=True, blank=True)
    antre_terbaru = models.DateTimeField(null=True, blank=True)
    # Watermark arah masuk (tbl_waktu_get) — kapan server ini terakhir menarik data.
    watermark_get = models.DateTimeField(null=True, blank=True)
    # Ujung feed (tbl_log_transaksi) — dipakai feed_sync/hub_sync sbg cursor.
    # Tidak dihapus job legacy, tapi BISA dipangkas pemeliharaan DB; nilai yang
    # turun antar-sampel dibaca `services_sync._stuck()` sebagai feed di-reset.
    feed_id = models.BigIntegerField(null=True, blank=True)
    feed_waktu = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK)
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["profile", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.profile_name}: {self.status} (antre {self.antre})"


class FeedSyncCursor(models.Model):
    """Titik lanjut satu pasangan (sumber → tujuan) untuk apps/transactions/feed_sync.py.

    `last_id` adalah tbl_log_transaksi.id terakhir yang SUDAH diterapkan ke
    server tujuan. Kolom itu IDENTITY + clustered PK di sumber, jadi `WHERE id > ?`
    adalah seek, bukan scan — itulah sebabnya feed ini dipakai sebagai sumber
    perubahan alih-alih tbl_tmp_post (yang dihapus job legacy).

    Satu baris per (source_profile, target_profile): tiap toko punya posisi
    sendiri, jadi satu toko yang mati tidak menahan yang lain.
    """

    source_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="feed_cursors_out"
    )
    target_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="feed_cursors_in"
    )
    last_id = models.BigIntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_rows_applied = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, default="ok")  # "ok" | "failed"
    error_message = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_profile", "target_profile"], name="unique_feed_cursor_per_pair"
            )
        ]

    def __str__(self) -> str:
        # ASCII, bukan panah: __str__ ini muncul di log dan konsol Windows
        # (cp1252) yang tak bisa mengencode U+2192 dan melempar UnicodeEncodeError
        # justru saat seseorang sedang menelusuri kegagalan.
        return f"{self.source_profile_id}->{self.target_profile_id} @ id {self.last_id}"


class SyncDeadLetter(models.Model):
    """Satu baris feed yang TIDAK diterapkan, beserta alasannya.

    Ada supaya kegagalan tidak punya dua jalan keluar yang sama-sama buruk:
    menghentikan seluruh run (pola `goto hell` di job legacy, yang membuat sisa
    antrean terlewat sesiklus) atau ditelan diam-diam. Baris masuk sini, cursor
    tetap maju, dan kegagalannya bisa dibaca manusia.

    Yang TIDAK masuk sini: baris yang tabelnya di luar daftar-izin. Itu
    penyaringan yang disengaja, bukan kerusakan, dan jumlahnya mayoritas isi feed
    (2.566 dari 3.000 pada uji nyata) — mencatatnya akan menimbun ribuan baris
    tiap tick dan menenggelamkan kegagalan yang sungguhan. Jumlahnya dilaporkan
    per run sebagai `disaring`, tidak disimpan.

    Jadi tabel ini idealnya KOSONG. Isinya berarti ada yang perlu dilihat.
    """

    source_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dead_letters_out",
    )
    target_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dead_letters_in",
    )
    feed_id = models.BigIntegerField(default=0)
    table_aksi = models.CharField(max_length=255, blank=True)
    formatted_data = models.TextField(blank=True)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["source_profile", "-created_at"])]

    def __str__(self) -> str:
        return f"id {self.feed_id} {self.table_aksi}: {self.reason}"


class HubPullState(models.Model):
    """Posisi tarik-langsung satu cabang ke pusat (apps/transactions/hub_pull.py).

    BUKAN `FeedSyncCursor`. Cursor itu menyimpan `last_id` feed dan seluruh
    halaman Kesehatan Sync menafsirkannya sebagai "ketinggalan" — jarak ke ujung
    feed. `hub_pull` tidak punya konsep itu sama sekali: ia menyapu rentang
    tanggal, jadi tidak ada yang bisa tertinggal, dan angka yang bisa basi
    hanyalah KAPAN sapuan terakhir terjadi. Menumpangkan dua arti pada satu
    kolom adalah cara paling rapi untuk membuat halaman monitoring berbohong.

    Tiga tingkat, tiga stempel waktu:

    - `arsip_selesai_at` — sekali seumur hidup, untuk `tanggal <= tutup_buku`.
      Tutup buku adalah lantai keras; di bawahnya data tidak berubah lagi.
    - `cocok_terakhir_at` — sekali sehari, membandingkan agregat per hari antara
      tutup buku dan jendela segar. `hari_beda` = berapa hari yang tidak cocok
      dan karena itu disalin ulang; idealnya 0, dan angka yang bukan 0 adalah
      temuan, bukan derau.
    - `segar_terakhir_at` — tiap tick, N hari terakhir disalin ulang tanpa
      dibandingkan.

    `tutup_buku` disimpan hanya untuk ditampilkan. Yang dipakai saat menyapu
    selalu dibaca ulang dari cabang: kalau klien menjalankan tutup buku lagi,
    batasnya maju, dan batas yang di-cache akan diam-diam menyapu ulang rentang
    yang sudah jadi arsip.
    """

    source_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="hub_pull_out"
    )
    target_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="hub_pull_in"
    )
    tutup_buku = models.DateTimeField(null=True, blank=True)
    arsip_selesai_at = models.DateTimeField(null=True, blank=True)
    # Ujung atas potongan arsip terakhir yang BERHASIL di-commit. Titik lanjut,
    # bukan hiasan: run pertama kehilangan 285.809 header PUSAT karena jaringan
    # putus di potongan ke-32 dari 48 dan tidak ada yang menandai 31 potongan
    # sebelumnya sudah selesai. Menjalankan ulang dari nol tetap BENAR (semuanya
    # idempoten) — yang hilang cuma jam kerjanya, dan justru itu yang mahal.
    arsip_sampai = models.DateTimeField(null=True, blank=True)
    cocok_terakhir_at = models.DateTimeField(null=True, blank=True)
    segar_terakhir_at = models.DateTimeField(null=True, blank=True)
    hari_beda = models.IntegerField(default=0)
    rows_header = models.BigIntegerField(default=0)
    rows_detail = models.BigIntegerField(default=0)
    rows_deleted = models.BigIntegerField(default=0)
    status = models.CharField(max_length=10, default="ok")  # "ok" | "failed"
    error_message = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_profile", "target_profile"], name="unique_hub_pull_per_pair"
            )
        ]

    def __str__(self) -> str:
        # ASCII, bukan panah: ini muncul di konsol Windows (cp1252), yang tak bisa
        # mengencode U+2192 dan melempar justru saat seseorang menelusuri kegagalan.
        return f"{self.source_profile_id}->{self.target_profile_id} arsip={bool(self.arsip_selesai_at)}"


class InfoPerusahaan(models.Model):
    """Identitas perusahaan untuk kop struk — SATU baris per koneksi.

    Disimpan di SQLite, bukan di `g_info_profile` pada server legacy, dan itu
    keputusan yang dibeli dengan pengukuran. Tabel legacy itu bukan tabel master:
    16.581 baris di grosirPusat / 18.927 di SERVER-TOYS / 14.867 di testGudang,
    `COUNT(DISTINCT)` = 1 pada SETIAP kolom (seluruhnya duplikat identik), dan
    `sys.indexes` cuma memulangkan satu baris HEAP — tanpa primary key, tanpa
    kolom identity, tanpa index. Tak ada `WHERE` yang bisa menunjuk satu baris di
    sana, sehingga satu-satunya tulis yang benar adalah mengganti SELURUH isinya.
    Menulis belasan ribu baris tiap klik Simpan, ke tabel milik aplikasi lama
    yang masih membacanya, bukan harga yang pantas dibayar untuk tiga baris kop.

    Di sini identitasnya milik Arunika sendiri: satu baris, punya kunci, dan
    tidak menyentuh satu pun tabel legacy.

    Per KONEKSI, bukan global — alasan yang sama seperti `TautanUser`: satu
    Arunika melayani gudang dan delapan grosir, dan tiap server punya alamat dan
    telepon sendiri.
    """

    profile = models.OneToOneField(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="info_perusahaan")
    perusahaan = models.CharField(max_length=200, blank=True, default="")
    alamat = models.CharField(max_length=300, blank=True, default="")
    kota = models.CharField(max_length=100, blank=True, default="")
    telp = models.CharField(max_length=60, blank=True, default="")
    hp = models.CharField(max_length=60, blank=True, default="")
    email = models.CharField(max_length=120, blank=True, default="")
    website = models.CharField(max_length=120, blank=True, default="")
    nama_kontak = models.CharField(max_length=120, blank=True, default="")
    diperbarui_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.profile_id}: {self.perusahaan or '(belum diisi)'}"

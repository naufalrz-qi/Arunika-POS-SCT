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


def log_activity(request, action, detail=""):
    """Convenience helper to record an audit entry from a request."""
    user = getattr(request, "user", None)
    ip = request.META.get("REMOTE_ADDR") if request else None
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

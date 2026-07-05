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

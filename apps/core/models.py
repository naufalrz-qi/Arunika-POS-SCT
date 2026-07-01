"""Audit trail (SQLite). PRD §5.1 / §7.6."""
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

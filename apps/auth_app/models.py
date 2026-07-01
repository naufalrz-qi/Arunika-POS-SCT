"""App-local user model (SQLite). PRD §4 — RBAC with 4 roles."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    KASIR = "kasir", "Kasir"
    SUPERVISOR = "supervisor", "Supervisor"
    ADMIN = "admin", "Admin"
    SUPERADMIN = "superadmin", "Superadmin"


# Menu keys must match those in apps/core/menus.py.
ADMIN_DEFAULT_MENUS = ["dashboard", "users", "connections", "products", "customers", "logs"]


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.KASIR)
    # PRD §4.3 — Superadmin controls which menus an Admin may access.
    # Empty/null => use defaults; superadmin always sees everything.
    allowed_menu_keys = models.JSONField(default=list, blank=True)

    @property
    def is_admin_tier(self) -> bool:
        return self.role in (Role.ADMIN, Role.SUPERADMIN)

    def __str__(self) -> str:
        return f"{self.get_full_name() or self.username} ({self.role})"

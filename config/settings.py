"""
Django settings for the POS Multi-Server app (Frontend / Admin phase).

This phase wires Django + Inertia + Vite with MOCK data only.
No MS SQL connection and no custom auth models yet — see the project plan.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name, default=False):
    return os.environ.get(name, str(int(default))).lower() in ("1", "true", "yes", "on")

# SECURITY: dev-only key. Replace via env var in production.
SECRET_KEY = "django-insecure-dev-key-frontend-phase-change-me"

DEBUG = True

# PRD §3.3 — dual access (LAN lokal + Tailscale). Adjust IPs per deployment.
ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "192.168.1.10",   # IP LAN lokal mesin kasir (contoh)
    "100.64.0.1",     # Tailscale IP mesin kasir (contoh, range 100.x.x.x)
]

# Display name shared to the frontend via inertia_share.
APP_NAME = "Sukses Crown Toys"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "inertia",
    "django_vite",
    # Local apps
    "apps.core",
    "apps.auth_app",
    "apps.monitoring",
    "apps.connections",
    "apps.transactions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Inertia
    "inertia.middleware.InertiaMiddleware",
    "apps.core.middleware.inertia_share",
    # App access control (order matters: after auth, before views)
    "apps.core.middleware.auth_required",
    "apps.core.middleware.admin_network_guard",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Local app DB (PRD §5: SQLite for auth/config). Default unused in this phase.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# --- Auth (PRD §4, §8.1) ---------------------------------------------------
AUTH_USER_MODEL = "auth_app.User"
LOGIN_URL = "/login"

# bcrypt first (PRD §8.1), Django defaults as fallback.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = []

# Idle session expiry (PRD §8.1) — slide expiry on each request.
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_IDLE_SECONDS", 60 * 60 * 4))  # 4h
SESSION_SAVE_EVERY_REQUEST = True

# --- Network access control (PRD §3.4 / §7.6) ------------------------------
# When enabled, /admin-panel/* is reachable only from the Tailscale CGNAT range.
ENFORCE_TAILSCALE = _env_bool("ENFORCE_TAILSCALE", default=not DEBUG)
TAILSCALE_CIDR = os.environ.get("TAILSCALE_CIDR", "100.64.0.0/10")
# Always-allowed IPs (loopback for local dev).
ADMIN_IP_ALLOWLIST = ["127.0.0.1", "::1"]

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True

# --- Inertia ---------------------------------------------------------------
INERTIA_LAYOUT = "base.html"

# --- Static / Vite ---------------------------------------------------------
STATIC_URL = "/static/"

DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "dev_server_host": "localhost",
        "dev_server_port": 5173,
        "manifest_path": BASE_DIR / "frontend" / "dist" / "manifest.json",
    }
}

# Where Vite build output lives (collected as static in production).
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

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

# SECURITY: production must set via env var (no default in prod).
_DEV_SECRET_KEY = "django-insecure-dev-key-frontend-phase-change-me"
SECRET_KEY = os.environ.get("SECRET_KEY", _DEV_SECRET_KEY)

DEBUG = _env_bool("DEBUG", default=False)

if not DEBUG and SECRET_KEY == _DEV_SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "SECRET_KEY masih memakai nilai default dev. Set SECRET_KEY di .env "
        "sebelum menjalankan dengan DEBUG=0."
    )

# PRD §3.3 — dual access (LAN lokal + Tailscale). Set real hosts in .env
# (ALLOWED_HOSTS=host1,host2,...). Default is loopback-only for a fresh clone.
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

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
    "django.middleware.gzip.GZipMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware" if not DEBUG else "django.middleware.security.SecurityMiddleware",
    "django.middleware.security.SecurityMiddleware" if DEBUG else "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "inertia.middleware.InertiaMiddleware",
    "apps.core.middleware.inertia_share",
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

# Minimal hardening for a flat trusted LAN: block trivially guessable passwords.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Idle session expiry (PRD §8.1) — do NOT save every request (kills SQLite concurrency).
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_IDLE_SECONDS", 60 * 60 * 4))  # 4h
SESSION_SAVE_EVERY_REQUEST = False

# Cookie hardening. SameSite=Lax explicit (CSRF defense-in-depth). The Secure /
# HSTS flags stay behind env because the app also serves plain-HTTP LAN/Tailscale
# — turn them ON only when fronted by HTTPS, else the cookies never get sent and
# login breaks.
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", default=False)
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)

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
STATIC_ROOT = BASE_DIR / "staticfiles"  # For collectstatic; whitenoise serves from here in prod.

DJANGO_VITE = {
    "default": {
        "dev_mode": _env_bool("DJANGO_VITE_DEV", default=DEBUG),
        "dev_server_host": "localhost",
        "dev_server_port": 5173,
        "manifest_path": BASE_DIR / "frontend" / "dist" / "manifest.json",
    }
}

STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage" if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- SQLite WAL mode (multi-reader/single-writer) ----
# Enabled so SELECT doesn't stall on WRITE; readers see last committed state while
# a writer prepares the next. Readers don't block each other.
def _enable_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL")

from django.db.backends.signals import connection_created
connection_created.connect(_enable_sqlite_wal)

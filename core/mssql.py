"""Dynamic MS SQL access layer (raw pyodbc).

PRD §5.3: table-level access only — NO stored procedures/functions/views, joins and
calculations happen in Python. Connections are opened per active ServerProfile so one
install can talk to many servers/branches (gudang / grosir / retail).

Security: passwords are stored Fernet-encrypted and only decrypted here, in-process,
to build the connection string. Modern drivers (17/18) connect with
Encrypt=yes;TrustServerCertificate=yes. The legacy "SQL Server" driver (the one
built into Windows when no separate ODBC driver is installed) honors Encrypt=yes
literally and fails the TLS handshake against most SQL Server setups, so it
connects unencrypted instead — acceptable here since MS SQL traffic stays on
the same trusted LAN as the app server.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

import pyodbc

from core.encryption import EncryptionKeyMissing, PasswordDecryptError, decrypt_checked, safe_decrypt

# Preferred newest-first; picks whichever is actually registered on this
# machine instead of hard-failing when only an older/legacy driver is present.
_DRIVER_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)


def _detect_driver() -> str:
    installed = set(pyodbc.drivers())
    for name in _DRIVER_PREFERENCE:
        if name in installed:
            return name
    # None registered — keep the documented default so the resulting pyodbc
    # error still names a real, googleable driver to install.
    return _DRIVER_PREFERENCE[1]


ODBC_DRIVER = _detect_driver()
_MODERN_DRIVERS = {"ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"}
CONNECT_TIMEOUT = 5  # seconds

# Enable driver-manager connection pooling (reuses handles across requests).
pyodbc.pooling = True


def build_conn_str(host, port, db_name, username, password) -> str:
    # Only the 17/18 drivers implement TrustServerCertificate correctly; older
    # drivers either fail the TLS handshake outright or silently ignore it.
    encrypt_clause = "Encrypt=yes;TrustServerCertificate=yes;" if ODBC_DRIVER in _MODERN_DRIVERS else "Encrypt=no;"
    return (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={host},{port};"
        f"DATABASE={db_name};"
        f"UID={username};"
        f"PWD={password};"
        f"{encrypt_clause}"
        f"Connection Timeout={CONNECT_TIMEOUT}"
    )


def _connect(host, port, db_name, username, password, autocommit=True):
    conn_str = build_conn_str(host, port, db_name, username, password)
    conn = pyodbc.connect(conn_str, timeout=CONNECT_TIMEOUT, autocommit=autocommit)
    conn.timeout = 60  # Query timeout (seconds); slow queries don't pin the worker indefinitely.
    return conn


def test_connection(host, port, db_name, username, password) -> dict:
    """Ping a server with SELECT 1. Returns {ok, message, latency_ms}."""
    start = time.perf_counter()
    try:
        with _connect(host, port, db_name, username, password) as conn:
            conn.cursor().execute("SELECT 1").fetchone()
        latency = round((time.perf_counter() - start) * 1000)
        return {"ok": True, "message": f"Koneksi berhasil (~{latency} ms)", "latency_ms": latency}
    except pyodbc.Error as exc:
        # exc.args[0] is the SQLSTATE; args[1] the driver message.
        detail = exc.args[1] if len(exc.args) > 1 else str(exc)
        return {"ok": False, "message": f"Gagal terhubung: {detail}", "latency_ms": None}


def test_profile(profile) -> dict:
    """Test a saved ServerProfile (decrypts its password).

    Decryption is checked explicitly first: a corrupt/mismatched
    POS_FERNET_KEY would otherwise silently degrade to a blank password and
    surface as a confusing SQL Server login error instead of the real cause.
    """
    try:
        password = decrypt_checked(profile.password_encrypted)
    except PasswordDecryptError as exc:
        return {"ok": False, "message": str(exc), "latency_ms": None}
    except EncryptionKeyMissing as exc:
        return {"ok": False, "message": str(exc), "latency_ms": None}
    return test_connection(profile.host, profile.port, profile.db_name, profile.username, password)


@contextmanager
def cursor(profile, autocommit=True):
    """Context manager yielding a cursor for the given ServerProfile.

    Use autocommit=False for write transactions, then call conn.commit() yourself.
    """
    conn = _connect(
        profile.host,
        profile.port,
        profile.db_name,
        profile.username,
        safe_decrypt(profile.password_encrypted),
        autocommit=autocommit,
    )
    try:
        yield conn.cursor()
    finally:
        conn.close()


def get_active_profile(db_type: str | None = None):
    """Return the single active ServerProfile (global), or None.

    Satu koneksi aktif untuk seluruh aplikasi — tipe (gudang/grosir/retail) hanya
    menentukan perilaku, bukan koneksi mana. `db_type` opsional untuk menyaring.
    """
    from apps.connections.models import ServerProfile

    qs = ServerProfile.objects.filter(db_type=db_type) if db_type else ServerProfile.objects.all()
    profile = qs.filter(is_default=True).first() or qs.first()
    if profile:
        # Auto-build the report/stock indexes once per profile per process, in
        # the background — new connections get them without a manual command.
        from apps.transactions.indexes import ensure_indexes_async

        ensure_indexes_async(profile)
    return profile


def get_cost_source(retail_profile):
    """Server grosir/gudang acuan modal untuk sebuah profil retail, atau None."""
    return getattr(retail_profile, "cost_source", None)

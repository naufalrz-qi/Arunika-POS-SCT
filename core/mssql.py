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

import os
import re
import threading
import time
from contextlib import contextmanager

import pyodbc

from core.encryption import EncryptionKeyMissing, PasswordDecryptError, decrypt_checked


class ProfileAuthError(pyodbc.Error):
    """Masalah POS_FERNET_KEY dilempar sebagai pyodbc.Error supaya SEMUA
    `except pyodbc.Error` di views menangkapnya jadi banner Indonesia, bukan 500.

    PasswordDecryptError/EncryptionKeyMissing adalah RuntimeError, jadi tanpa
    pembungkus ini sebuah key yang dirotasi/rusak menembus ~28 handler di
    apps/monitoring/views.py dan menghasilkan 500 di hampir tiap halaman data.
    Format args = (SQLSTATE, pesan) seperti pyodbc, jadi `exc.args[-1]` yang
    sudah dipakai di puluhan f-string langsung menghasilkan kalimat Indonesia."""


# Prefiks driver ODBC ("[Microsoft][ODBC Driver 17 for SQL Server]") tak berarti
# apa-apa bagi admin toko — dibuang dari pesan yang tampil ke pengguna.
_ODBC_NOISE = re.compile(r"\[Microsoft\]\[[^\]]+\]")


def friendly_error(exc, prefix: str = "Gagal membaca data") -> str:
    """Pesan bahasa Indonesia untuk pengguna akhir dari sebuah pyodbc.Error.

    Dipakai di semua view sebagai ganti f"...: {exc.args[-1]}", yang membocorkan
    SQLSTATE + teks driver bahasa Inggris ke banner berbahasa Indonesia."""
    args = getattr(exc, "args", ()) or ()
    raw = str(args[-1] if args else exc)
    state = args[0] if args else ""
    if isinstance(exc, ProfileAuthError):
        return raw  # sudah kalimat Indonesia dari core/encryption.py
    if state in ("08001", "08S01", "HYT00") or "timeout" in raw.lower():
        return f"{prefix}: server tidak dapat dihubungi. Periksa jaringan/koneksi."
    if state == "28000":
        return f"{prefix}: username atau password server salah."
    if state == "42S02":
        return f"{prefix}: tabel yang dibutuhkan tidak ada di server ini."
    # ponytail: sisanya apa adanya minus prefiks driver. Menambah pemetaan
    # SQLSTATE baru hanya kalau ada yang benar-benar muncul di lapangan.
    return f"{prefix}: {_ODBC_NOISE.sub('', raw).strip()}"

# Per-request active connection. Each HTTP request may target a different
# ServerProfile chosen by THAT user (stored in their session, stamped here by
# apps.core.middleware.inertia_share for the life of the request). Thread-local
# so concurrent users on the waitress thread-pool don't clobber each other; the
# middleware clears it in a finally so a pooled thread never leaks a choice into
# the next request. Background code with no request (scheduler, manage.py
# commands) leaves it unset → get_active_profile falls back to the global
# is_default. This replaces the old single global active connection.
_request_local = threading.local()


def set_request_profile_id(profile_id) -> None:
    _request_local.profile_id = profile_id


def clear_request_profile() -> None:
    _request_local.profile_id = None


def _request_profile_id():
    return getattr(_request_local, "profile_id", None)

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

# Batas waktu query. 60 detik pas untuk halaman interaktif — query lambat tak
# boleh menahan worker selamanya. Tapi pembangun snapshot (snapshot_stok_base)
# adalah query terberat di aplikasi dan jalan di latar, jadi punya plafonnya
# sendiri: kalau ia kena timeout, scheduler gagal tanpa mencatat marker,
# mengulang tiap 30 menit, dan server itu TAK PERNAH punya snapshot — artinya
# jalur lambat permanen. Naikkan POS_SNAPSHOT_TIMEOUT untuk server jauh/lambat.
QUERY_TIMEOUT = int(os.environ.get("POS_QUERY_TIMEOUT", 60))
SNAPSHOT_TIMEOUT = int(os.environ.get("POS_SNAPSHOT_TIMEOUT", 900))

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


def _connect(host, port, db_name, username, password, autocommit=True, query_timeout=None):
    conn_str = build_conn_str(host, port, db_name, username, password)
    conn = pyodbc.connect(conn_str, timeout=CONNECT_TIMEOUT, autocommit=autocommit)
    conn.timeout = query_timeout or QUERY_TIMEOUT
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
        return {"ok": False, "message": friendly_error(exc, "Gagal terhubung"), "latency_ms": None}


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
def cursor(profile, autocommit=True, query_timeout=None):
    """Context manager yielding a cursor for the given ServerProfile.

    Use autocommit=False for write transactions, then call conn.commit() yourself.

    Password decrypt is CHECKED (fail loud): a corrupt/rotated POS_FERNET_KEY
    raises here instead of silently connecting with a blank password and
    surfacing as a confusing SQL Server login error. `safe_decrypt` stays for
    display-only paths that must never raise.

    Re-raised as ProfileAuthError (a pyodbc.Error) so the ~28 `except
    pyodbc.Error` handlers in the views turn it into a banner instead of a 500.
    """
    try:
        password = decrypt_checked(profile.password_encrypted)
    except (PasswordDecryptError, EncryptionKeyMissing) as exc:
        raise ProfileAuthError("HY000", str(exc)) from exc
    conn = _connect(
        profile.host,
        profile.port,
        profile.db_name,
        profile.username,
        password,
        autocommit=autocommit,
        query_timeout=query_timeout,
    )
    cur = conn.cursor()
    # `executemany` polos mengirim SATU round-trip PER BARIS. Dengan
    # `fast_executemany` pyodbc mengemas seluruh array parameter jadi satu
    # perintah TDS. Terukur di jalur arsip: menyalin riwayat lewat Tailscale
    # yang me-relay ke Singapura, ribuan baris detail per nota-batch berarti
    # ribuan perjalanan bolak-balik yang masing-masing berbiaya milidetik.
    #
    # Hanya berpengaruh pada `executemany`; `execute` biasa tidak tersentuh.
    # Aman untuk seluruh aplikasi: semua pemanggil sudah mengirim parameter
    # bertipe seragam per kolom (dibaca dari kolom sumber yang sama).
    try:
        cur.fast_executemany = True
    except AttributeError:  # pragma: no cover — driver lawas
        pass
    try:
        yield cur
    finally:
        conn.close()


@contextmanager
def report_cursor(profile, query_timeout=None):
    """Cursor READ-ONLY untuk report: READ UNCOMMITTED (NOLOCK) supaya SELECT
    berat tak mengambil shared lock yang memblok tulis POS live. Aman untuk
    laporan (data historis tak sedang ditulis); JANGAN dipakai jalur write."""
    with cursor(profile, query_timeout=query_timeout) as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        yield cur


def get_active_profile(db_type: str | None = None):
    """Return the ServerProfile active for the current request, or None.

    Per-user: resolves the profile the current user picked (their session, via
    the request-local set by middleware). Falls back to the global `is_default`
    when there is no request-scoped choice (background jobs) or the chosen
    profile no longer exists / doesn't match `db_type`. `db_type` optional filter.
    """
    from apps.connections.models import ServerProfile

    profile = None
    pid = _request_profile_id()
    if pid is not None:
        profile = ServerProfile.objects.filter(pk=pid).first()
        if profile and db_type and profile.db_type != db_type:
            profile = None  # session choice doesn't match requested type → fall back
    if profile is None:
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


def get_gudang_source(profile):
    """Profil bertipe `gudang` acuan bagi `profile`, ditelusuri lewat rantai
    cost_source. None bila rantainya tak pernah sampai ke gudang.

    Rantai yang ada di lapangan: retail -> grosir -> gudang (RTL PUSAT -> PUSAT
    -> GUDANG). Karena itu cost_source ditelusuri BERULANG, bukan sekali:
    cost_source milik profil retail biasanya grosir, jadi satu langkah tak akan
    pernah menemukan gudang.

    Bisa mengembalikan `profile` itu sendiri kalau ia memang gudang — caller
    yang memutuskan artinya (untuk saran harga: gudang adalah sumber acuan, jadi
    ia tak punya apa pun untuk diikuti).

    Penjaga siklus disengaja: cost_source adalah FK ke tabel yang sama, jadi
    A->B->A bisa terbentuk dari layar Koneksi tanpa ada yang melarangnya, dan
    tanpa penjaga ini satu profil salah-konfigurasi menggantung request selamanya.
    """
    seen = set()
    p = profile
    while p is not None and p.pk not in seen:
        seen.add(p.pk)
        if p.db_type == "gudang":
            return p
        p = getattr(p, "cost_source", None)
    return None


def get_report_source(profile):
    """Replica server (disinkron via CDC) untuk baca laporan, atau None.

    Dipakai di jalur baca laporan berat (apps/monitoring/views.py _report_view)
    supaya SELECT laporan mengenai replica ini, bukan server legacy yang juga
    melayani transaksi kasir live. Jalur WRITE (update_harga, sync_entity, dst.)
    TIDAK boleh pakai ini — selalu tulis ke `profile` (server legacy) langsung.
    """
    return getattr(profile, "report_source", None)


def report_read_profiles(profile) -> list:
    """Ordered candidate profiles for report READS: the CDC replica first (so
    heavy SELECTs offload off the live POS server), then the primary `profile`
    as a fallback. Callers try each in order until one connects — a replica
    outage then degrades to slower direct reads instead of breaking every
    report page. READS ONLY; write paths must always target `profile` directly.
    """
    replica = get_report_source(profile)
    return [replica, profile] if replica else [profile]

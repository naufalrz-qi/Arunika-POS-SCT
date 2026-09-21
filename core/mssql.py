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

import datetime as dt
import os
import re
import struct
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


def set_request_profile_id(profile_id, strict: bool = False) -> None:
    """Profil untuk permintaan ini. `strict` mematikan jatuh-tempo ke default.

    Dipakai untuk akun yang DIKUNCI ke satu server (kasir/supervisor): kalau
    servernya belum ditetapkan, jawabannya harus "tidak ada", bukan diam-diam
    memakai koneksi default. Menebak berarti nota tertulis ke server toko yang
    salah, dan trigger legacy langsung mengirimkannya ke pusat.
    """
    _request_local.profile_id = profile_id
    _request_local.strict = strict


def clear_request_profile() -> None:
    _request_local.profile_id = None
    _request_local.strict = False


def _request_profile_id():
    return getattr(_request_local, "profile_id", None)


def _request_strict() -> bool:
    return getattr(_request_local, "strict", False)

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


# SQL_SS_TIMESTAMPOFFSET. pyodbc tak mengenalnya sendiri dan melempar
# "ODBC SQL type -155 is not yet supported" -- bukan nilai kosong, melainkan
# galat yang menjatuhkan seluruh kueri.
_TIPE_DATETIMEOFFSET = -155


def _baca_datetimeoffset(nilai: bytes) -> dt.datetime:
    """Ubah 20 byte `datetimeoffset` jadi datetime ber-zona.

    Dibutuhkan sejak database Arunika berisi tabel NYATA: `mssql-django`
    memetakan `DateTimeField` ke `datetimeoffset` saat `USE_TZ` aktif, sementara
    seluruh jalur baca laporan memakai pyodbc mentah lewat `arunika_cursor`.
    Tanpa konverter ini setiap laporan di profil mode-Arunika gagal -- dan itu
    baru ketahuan sesudah tabelnya benar-benar diisi, sebab di mode legacy
    kolomnya `datetime` biasa milik vendor.
    """
    th, bl, hr, jam, mnt, dtk, nano, oj, om = struct.unpack("<6hI2h", nilai)
    return dt.datetime(
        th, bl, hr, jam, mnt, dtk, nano // 1000,
        dt.timezone(dt.timedelta(hours=oj, minutes=om)),
    )


def _connect(host, port, db_name, username, password, autocommit=True, query_timeout=None):
    conn_str = build_conn_str(host, port, db_name, username, password)
    conn = pyodbc.connect(conn_str, timeout=CONNECT_TIMEOUT, autocommit=autocommit)
    conn.timeout = query_timeout or QUERY_TIMEOUT
    conn.add_output_converter(_TIPE_DATETIMEOFFSET, _baca_datetimeoffset)
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
        # Akun terkunci tak boleh jatuh ke koneksi default — lihat
        # set_request_profile_id(strict=True).
        if _request_strict():
            return None
        qs = ServerProfile.objects.filter(db_type=db_type) if db_type else ServerProfile.objects.all()
        profile = qs.filter(is_default=True).first() or qs.first()
    # SENGAJA tidak membangun index di sini. Dulu fungsi ini menyalakan thread
    # `ensure_indexes_async` setiap kali profil aktif diresolusi — artinya
    # sekadar MEMBACA koneksi aktif menulis DDL ke database legacy milik
    # bersama, tanpa ada yang memintanya, dan gagalnya cuma muncul di log
    # server ("ensure_indexes gagal untuk RTL PUSAT"). Pembangunan index kini
    # manual sepenuhnya: tombol Cek Index per koneksi di layar Koneksi Server,
    # atau `manage.py ensure_indexes`.
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


def execute_varchar(cur, sql, params, panjang_min: int = 10):
    """`cur.execute` dengan parameter string diikat VARCHAR **per posisi**.

    pyodbc mengikat `str` Python sebagai NVARCHAR, sedangkan seluruh kolom kunci
    legacy bertipe `varchar`/`char`. Konversi implisit di sisi KOLOM membatalkan
    index seek, dan SQL Server memindai tabelnya. Terukur di server uji lokal
    pada kueri pergerakan stok (`t_penjualan_detail` 569.831 baris, difilter
    satu `kd_barang`): **0,1309 dtk -> 0,0070 dtk, 18,6x.** Di server jauh
    ongkosnya akan jauh lebih besar lagi.

    ## Kenapa bukan `hub_sync.bind_varchar`

    Helper itu menyetel SELURUH posisi jadi VARCHAR, yang benar untuk kasus yang
    melahirkannya -- satu daftar `IN (...)` berisi string semua. Daftar parameter
    di sini CAMPURAN: kueri pergerakan stok mengirim 38 parameter, 22 di
    antaranya `datetime`. Memaksa datetime jadi VARCHAR berarti menyerahkan
    penafsiran tanggalnya ke setelan bahasa server, dan itu **terbukti pecah**:

        SET LANGUAGE us_english  -> lolos, hasil identik
        SET LANGUAGE british     -> DataError 22007 (gagal konversi tanggal)
        SET LANGUAGE deutsch     -> DataError 22007

    Lolosnya di mesin pengembang hanya karena bahasa sesinya kebetulan
    `us_english`. Kegagalan seperti itu tidak akan pernah terlihat saat menguji
    ke server lokal -- ia muncul di server pelanggan.

    Karena itu di sini hanya posisi bertipe `str` yang diikat; sisanya `None`,
    yang berarti "biarkan pyodbc memutuskan". pyodbc menerima `None` per posisi,
    dan hasilnya terbukti identik di ketiga bahasa di atas.

    ## Panjang deklarasi

    Diturunkan dari nilai terpanjang yang benar-benar dikirim, bukan konstanta.
    Deklarasi yang lebih PENDEK dari nilainya akan memotongnya diam-diam, dan
    baris yang hilang karena kunci terpotong tidak memunculkan galat apa pun.

    Ikatan `setinputsizes` menempel di cursor, jadi ia selalu direset di
    `finally` -- execute berikutnya dengan jumlah parameter berbeda akan salah
    kalau tidak.
    """
    def _varchar_aman(v) -> bool:
        """Hanya string ASCII yang diikat VARCHAR.

        Kolom legacy memang `varchar`, jadi ia tak pernah bisa menyimpan
        karakter di luar codepage-nya -- tapi NILAI yang dikirim tidak selalu
        datang dari sana. Kata kunci pencarian diketik pengguna dan bisa memuat
        apa saja. Memaksa string non-ASCII lewat VARCHAR menyerahkannya ke
        konversi codepage server, yang bisa memetakan dua karakter berbeda ke
        byte yang sama dan memunculkan kecocokan yang salah -- tanpa galat.

        Dibiarkan NVARCHAR, string seperti itu sekadar tidak cocok dengan apa
        pun, yang memang jawaban yang benar. Ongkosnya nol: nilai non-ASCII
        tidak akan pernah menemukan baris di kolom `varchar` bagaimanapun
        caranya, jadi seek yang hilang tidak merugikan siapa pun.
        """
        return isinstance(v, str) and v.isascii()

    if not any(_varchar_aman(v) for v in params):
        cur.execute(sql, params)
        return cur
    panjang = max(panjang_min, max(len(v) for v in params if _varchar_aman(v)))
    try:
        cur.setinputsizes(
            [(pyodbc.SQL_VARCHAR, panjang, 0) if _varchar_aman(v) else None for v in params]
        )
        cur.execute(sql, params)
    finally:
        cur.setinputsizes(None)
    return cur


def punya_arunika(profile) -> bool:
    """Apakah profil ini punya database Arunika pendamping."""
    return bool((getattr(profile, "db_arunika", "") or "").strip())


@contextmanager
def arunika_cursor(profile, query_timeout=None):
    """Cursor READ-ONLY ke database ARUNIKA pendamping, bukan ke database legacy.

    Kembaran `report_cursor` untuk sisi yang lain. Keduanya menunjuk instans SQL
    Server yang SAMA; yang berbeda hanya databasenya -- `profile.db_name` untuk
    legacy, `profile.db_arunika` untuk milik kita. Di situlah tabel skema Arunika
    dan view adapter `arunika_src.*` tinggal, dan dari sanalah legacy dibaca
    lintas-database.

    READ UNCOMMITTED dengan alasan yang sama seperti `report_cursor`: laporan
    memindai banyak baris dan tak boleh mengambil shared lock yang memblok tulis
    POS live. Di mode legacy isolasi itu ikut berlaku ke tabel legacy yang dibaca
    view -- justru yang diinginkan.

    Menolak dengan galat kalau `db_arunika` kosong, bukan diam-diam jatuh ke
    database legacy: jatuh diam-diam berarti kueri bentuk-baru dijalankan di
    database yang tak punya bentuk itu, dan pesannya akan menyebut nama objek
    yang "tidak ada" alih-alih menyebut sebab sebenarnya.
    """
    db = (getattr(profile, "db_arunika", "") or "").strip()
    if not db:
        raise ProfileAuthError(
            "HY000",
            f"Profil '{profile.name}' belum punya database Arunika (db_arunika kosong). "
            "Jalankan `manage.py init_arunika --profile <nama>` lebih dulu.",
        )
    try:
        password = decrypt_checked(profile.password_encrypted)
    except (PasswordDecryptError, EncryptionKeyMissing) as exc:
        raise ProfileAuthError("HY000", str(exc)) from exc
    conn = _connect(
        profile.host, profile.port, db, profile.username, password,
        autocommit=True, query_timeout=query_timeout,
    )
    cur = conn.cursor()
    try:
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        yield cur
    finally:
        cur.close()
        conn.close()

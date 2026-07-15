"""Scheduler in-process untuk snapshot harian (tanpa cron/Task Scheduler eksternal).

Menjalankan job harian sekali per hari kalender untuk koneksi AKTIF, selama proses
server HTTP hidup. Dimulai dari `config/wsgi.py`, jadi hanya jalan saat serving
(runserver/waitress) — bukan saat `migrate`/`shell`/dll.

Dua job:
- snapshot HARGA (deteksi perubahan harga_jual per SKU) — HARGA_SNAPSHOT_*.
- snapshot STOK (rebuild saldo stok pos_stok_snapshot) — STOK_SNAPSHOT_*.

Idempotent: penanda per (profile, tanggal) mencegah lebih dari satu run berat/hari.
Kalau server mati seharian, hari itu dilewati (trade-off diterima: "saat server
berjalan saja"). Nonaktifkan per job dengan *_SNAPSHOT_ENABLED=0.

Env:
- HARGA_SNAPSHOT_ENABLED / STOK_SNAPSHOT_ENABLED (default 1)
- HARGA_SNAPSHOT_HOUR (default 0) / STOK_SNAPSHOT_HOUR (default 3) — jam lokal minimum
  sebelum boleh jalan. Beda jam supaya kedua job berat tak tabrakan.
- HARGA_SNAPSHOT_INTERVAL_SECONDS (default 1800) — jeda cek antar-iterasi (dipakai bersama).
"""
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() not in ("0", "false", "no", "off")


def _hour(name: str, default: int) -> int:
    try:
        return max(0, min(23, int(os.environ.get(name, str(default)))))
    except ValueError:
        return default


def _harga_enabled() -> bool:
    return _flag("HARGA_SNAPSHOT_ENABLED")


def _stok_enabled() -> bool:
    return _flag("STOK_SNAPSHOT_ENABLED")


def _interval() -> int:
    try:
        return max(60, int(os.environ.get("HARGA_SNAPSHOT_INTERVAL_SECONDS", "1800")))
    except ValueError:
        return 1800


def _run_due_harga(now, profile) -> None:
    """Snapshot harga bila hari ini belum & sudah lewat jam minimum."""
    from apps.core.models import HargaSnapshotRun
    from apps.master_data.services import snapshot_harga_changes

    if now.hour < _hour("HARGA_SNAPSHOT_HOUR", 0):
        return
    today = now.date()
    if HargaSnapshotRun.objects.filter(profile=profile, run_date=today).exists():
        return
    try:
        res = snapshot_harga_changes(profile)
    except Exception as exc:  # pyodbc.Error dll — jangan matikan loop
        log.warning("snapshot_harga terjadwal gagal (%s): %s", profile.name, exc)
        return
    HargaSnapshotRun.objects.create(
        profile=profile, profile_name=profile.name, run_date=today,
        changes=res["changes"], seeded=res["seeded"], total=res["total"],
    )
    log.info("snapshot_harga %s: %s perubahan, %s seed, %s SKU",
             profile.name, res["changes"], res["seeded"], res["total"])


def _run_due_stok(now, profile) -> None:
    """Rebuild snapshot stok untuk `profile`: base beku (bulanan) lalu live (harian).

    Opportunistic — jam minimum default 0, jadi jalan di kesempatan pertama saat
    server hidup (server user cuma nyala jam kerja, bukan dini hari)."""
    from apps.core.models import StokSnapshotBaseRun, StokSnapshotRun
    from apps.inventory.services import _base_date, snapshot_stok, snapshot_stok_base

    if now.hour < _hour("STOK_SNAPSHOT_HOUR", 0):
        return

    # (a) BASE beku: cukup sekali per bulan-base (berat, scan sejak tutup buku).
    base_month = _base_date(now).strftime("%Y-%m")
    if not StokSnapshotBaseRun.objects.filter(profile=profile, base_month=base_month).exists():
        try:
            res = snapshot_stok_base(profile)
        except Exception as exc:  # server mati / pyodbc — hentikan profil ini, retry tick berikutnya
            log.warning("snapshot_stok_base terjadwal gagal (%s): %s", profile.name, exc)
            return
        StokSnapshotBaseRun.objects.create(
            profile=profile, profile_name=profile.name, base_month=base_month, rows=res["rows"],
        )
        log.info("snapshot_stok_base %s (%s): %s baris", profile.name, base_month, res["rows"])

    # (b) LIVE: sekali per hari (ringan — hanya delta sejak base).
    today = now.date()
    if StokSnapshotRun.objects.filter(profile=profile, run_date=today).exists():
        return
    try:
        res = snapshot_stok(profile)
    except Exception as exc:  # pyodbc.Error dll — jangan matikan loop
        log.warning("snapshot_stok terjadwal gagal (%s): %s", profile.name, exc)
        return
    StokSnapshotRun.objects.create(
        profile=profile, profile_name=profile.name, run_date=today, rows=res["rows"],
    )
    log.info("snapshot_stok %s: %s baris saldo", profile.name, res["rows"])


def _run_due_jobs() -> None:
    """Jalankan snapshot untuk SEMUA profil (bukan hanya koneksi aktif) — tiap
    server/database butuh snapshotnya sendiri. Berurutan, per-profil terisolasi:
    satu server mati/gagal tak menghentikan yang lain."""
    from django.utils import timezone

    from apps.connections.models import ServerProfile

    now = timezone.localtime()
    stok_on = _stok_enabled()
    harga_on = _harga_enabled()
    for profile in ServerProfile.objects.all():
        try:
            if stok_on:
                _run_due_stok(now, profile)
            if harga_on:
                _run_due_harga(now, profile)
        except Exception:  # pragma: no cover — profil gagal tak hentikan lainnya
            log.exception("scheduler snapshot gagal untuk profil %s", getattr(profile, "name", "?"))


def _loop() -> None:
    time.sleep(60)  # beri boot server selesai dulu
    interval = _interval()
    while True:
        try:
            _run_due_jobs()
        except Exception:  # pragma: no cover — loop harus tetap hidup
            log.exception("scheduler snapshot error")
        time.sleep(interval)


def start_scheduler() -> None:
    """Idempotent: mulai satu daemon thread. Dipanggil dari config/wsgi.py."""
    global _started
    if not (_harga_enabled() or _stok_enabled()):
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="snapshot-scheduler", daemon=True).start()
    log.info(
        "Scheduler snapshot aktif (interval %ss, semua profil; harga=%s jam≥%s, stok=%s jam≥%s).",
        _interval(), _harga_enabled(), _hour("HARGA_SNAPSHOT_HOUR", 0),
        _stok_enabled(), _hour("STOK_SNAPSHOT_HOUR", 0),
    )

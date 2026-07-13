"""Scheduler in-process untuk snapshot harga harian (tanpa cron/Task Scheduler eksternal).

Menjalankan `snapshot_harga_changes` sekali per hari kalender untuk koneksi AKTIF,
selama proses server HTTP hidup. Dimulai dari `config/wsgi.py`, jadi hanya jalan saat
serving (runserver/waitress) — bukan saat `migrate`/`shell`/dll.

Idempotent: penanda `HargaSnapshotRun` per (profile, tanggal) mencegah lebih dari satu
run berat/hari; diff-nya sendiri juga idempotent. Kalau server mati seharian, hari itu
dilewati (trade-off yang diterima user: "saat server berjalan saja"). Nonaktifkan
dengan HARGA_SNAPSHOT_ENABLED=0.

Env:
- HARGA_SNAPSHOT_ENABLED (default 1)
- HARGA_SNAPSHOT_HOUR (default 0) — jam minimum sebelum boleh jalan (jam lokal
  `TIME_ZONE`). 0 = jalan di kesempatan pertama tiap hari saat server hidup.
- HARGA_SNAPSHOT_INTERVAL_SECONDS (default 1800) — jeda cek antar-iterasi.
"""
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _enabled() -> bool:
    return os.environ.get("HARGA_SNAPSHOT_ENABLED", "1").lower() not in ("0", "false", "no", "off")


def _min_hour() -> int:
    try:
        return max(0, min(23, int(os.environ.get("HARGA_SNAPSHOT_HOUR", "0"))))
    except ValueError:
        return 0


def _interval() -> int:
    try:
        return max(60, int(os.environ.get("HARGA_SNAPSHOT_INTERVAL_SECONDS", "1800")))
    except ValueError:
        return 1800


def _run_due_snapshot() -> None:
    """Jalankan snapshot bila hari ini belum & sudah lewat jam minimum."""
    from django.utils import timezone

    from apps.core.models import HargaSnapshotRun
    from apps.master_data.services import snapshot_harga_changes
    from core import mssql

    now = timezone.localtime()
    if now.hour < _min_hour():
        return
    profile = mssql.get_active_profile()
    if not profile:
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
    log.info(
        "snapshot_harga %s: %s perubahan, %s seed, %s SKU",
        profile.name, res["changes"], res["seeded"], res["total"],
    )


def _loop() -> None:
    time.sleep(60)  # beri boot server selesai dulu
    interval = _interval()
    while True:
        try:
            _run_due_snapshot()
        except Exception:  # pragma: no cover — loop harus tetap hidup
            log.exception("scheduler snapshot_harga error")
        time.sleep(interval)


def start_scheduler() -> None:
    """Idempotent: mulai satu daemon thread. Dipanggil dari config/wsgi.py."""
    global _started
    if not _enabled():
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="harga-snapshot-scheduler", daemon=True).start()
    log.info("Scheduler snapshot harga aktif (interval %ss, jam min %s).", _interval(), _min_hour())

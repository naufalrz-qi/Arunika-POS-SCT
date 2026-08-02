"""Scheduler in-process untuk snapshot harian (tanpa cron/Task Scheduler eksternal).

Menjalankan job harian sekali per hari kalender untuk koneksi AKTIF, selama proses
server HTTP hidup. Dimulai dari `config/wsgi.py`, jadi hanya jalan saat serving
(runserver/waitress) — bukan saat `migrate`/`shell`/dll.

Tiga job:
- pemanas CACHE master data — MASTER_WARM_ENABLED. Tiap tick, bukan harian:
  ongkos cache dingin di server WAN ~30 detik, dan tanpa pemanas ongkos itu
  selalu ditanggung pengguna pertama setelah TTL habis / server restart.
- snapshot HARGA (deteksi perubahan harga_jual per SKU) — HARGA_SNAPSHOT_*.
- snapshot STOK (rebuild saldo stok pos_stok_snapshot) — STOK_SNAPSHOT_*.

Idempotent: penanda per (profile, tanggal) mencegah lebih dari satu run berat/hari.
Kalau server mati seharian, hari itu dilewati (trade-off diterima: "saat server
berjalan saja"). Nonaktifkan per job dengan *_SNAPSHOT_ENABLED=0.

Env:
- MASTER_WARM_ENABLED (default 1) — pemanas cache master data tiap tick.
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


def _warm_enabled() -> bool:
    return _flag("MASTER_WARM_ENABLED")


def _warm_ttl() -> int:
    """Umur entri cache yang ditulis pemanas: 3x jeda tick.

    Harus lebih panjang dari jeda tick, kalau tidak entri kedaluwarsa di antara
    dua pemanasan dan pengguna yang membuka halaman pada celah itu tetap
    menanggung cache dingin — persis masalah yang mau dihapus. Faktor 3 memberi
    ruang untuk satu-dua tick yang gagal (server legacy sempat mati) tanpa
    langsung membuka celah."""
    return _interval() * 3


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
            # Tanpa base, fase live di bawah tak bisa jalan (live = delta sejak
            # base), jadi profil ini TAK PUNYA snapshot sama sekali dan setiap
            # halaman stoknya jatuh ke jalur lambat. Diulang tiap tick, jadi
            # kalau penyebabnya timeout ia akan gagal terus tanpa henti —
            # naikkan POS_SNAPSHOT_TIMEOUT (default 900 detik) untuk server jauh.
            log.error(
                "snapshot_stok_base gagal (%s): %s — profil ini akan memakai jalur "
                "lambat sampai berhasil. Bila ini timeout, naikkan POS_SNAPSHOT_TIMEOUT.",
                profile.name, exc,
            )
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


def _warm_master(profile, include_stok=False) -> None:
    """Panasi cache master data profil ini. Tiap tick, bukan sekali sehari:
    tujuannya menjaga cache TETAP hangat, bukan mengisinya sekali.

    `include_stok` hanya untuk profil AKTIF — lihat alasannya di
    warm_master_cache()."""
    from apps.inventory.services import warm_master_cache

    t0 = time.monotonic()
    try:
        n = warm_master_cache(profile, ttl=_warm_ttl(), include_stok=include_stok)
    except Exception as exc:  # pyodbc.Error dll — server jauh mati, coba tick berikutnya
        log.warning("pemanasan cache master gagal (%s): %s", profile.name, exc)
        return
    log.info("cache master %s: %s key%s, %.2fs", profile.name, n,
             " (+stok kolumnar)" if include_stok else "", time.monotonic() - t0)


def _run_due_sync_health(profile) -> None:
    """Rekam satu sampel kesehatan sync untuk `profile`. Tiap tick, bukan harian.

    Sync yang mati perlu ketahuan dalam hitungan menit. Halaman Kesehatan Sync
    membaca angka langsung saat dibuka; yang ditulis di sini adalah RIWAYATnya —
    tanpa itu "antre 8.000" tak bisa dibedakan dari "antre 8.000 dan naik terus
    sejak Mei". Murah: semua kuerinya seek/metadata, bukan scan.
    """
    from apps.monitoring import services_sync

    try:
        hasil = services_sync.sync_health(profile)
        services_sync.simpan_sample(hasil)
    except Exception as exc:  # pragma: no cover — pemantauan tak boleh menjatuhkan tick
        log.warning("sampel kesehatan sync gagal (%s): %s", profile.name, exc)


def _run_due_feed_sync() -> None:
    """Fan-out master data dari server sumber ke semua toko. Tiap tick.

    Default MATI (FEED_SYNC_ENABLED=0): deploy tidak boleh langsung mulai
    memindahkan data antar-server produksi. Dinyalakan sadar-sadar lewat .env
    sesudah `manage.py sync_feed --dry-run` diperiksa.

    Env:
    - FEED_SYNC_ENABLED (default 0)
    - FEED_SYNC_SOURCE (default "GUDANG") — nama ServerProfile sumber.
    - FEED_SYNC_TARGETS — CSV nama profil tujuan. Kosong = semua kecuali sumber.
    - FEED_SYNC_LIMIT (default 2000) — baris feed per tujuan per tick.
    """
    from apps.connections.models import ServerProfile
    from apps.transactions import feed_sync

    nama_sumber = os.environ.get("FEED_SYNC_SOURCE", "GUDANG")
    source = ServerProfile.objects.filter(name=nama_sumber).first()
    if not source:
        log.warning("feed_sync: profil sumber '%s' tidak ada — dilewati.", nama_sumber)
        return

    csv = os.environ.get("FEED_SYNC_TARGETS", "").strip()
    qs = ServerProfile.objects.exclude(pk=source.pk)
    if csv:
        qs = qs.filter(name__in=[n.strip() for n in csv.split(",") if n.strip()])
    targets = list(qs.order_by("name"))
    if not targets:
        return

    try:
        limit = max(1, int(os.environ.get("FEED_SYNC_LIMIT", "2000")))
    except ValueError:
        limit = 2000

    for hasil in feed_sync.sync_all(source, targets, limit=limit):
        if hasil["status"] == "failed":
            log.warning("feed_sync %s -> %s GAGAL: %s", hasil["source"], hasil["target"], hasil["error"])
        elif hasil["diterapkan"] or hasil["dilewati"]:
            log.info(
                "feed_sync %s -> %s: %s diterapkan, %s dead-letter, sampai id %s",
                hasil["source"], hasil["target"], hasil["diterapkan"], hasil["dilewati"], hasil["sampai_id"],
            )


def _run_due_hub_sync() -> None:
    """Tarik perubahan tiap cabang ke pusat AMPHOREUS. Tiap tick.

    Default MATI (HUB_SYNC_ENABLED=0). Cabang tanpa `kode_sumber` dilewati, bukan
    ditebak — tanpa kode, barisnya tak bisa dibedakan dari cabang lain di pusat.

    Env: HUB_SYNC_ENABLED (0), HUB_NAME (AMPHOREUS), HUB_SYNC_LIMIT (2000).
    """
    from apps.connections.models import ServerProfile
    from apps.transactions import hub_sync

    nama_hub = os.environ.get("HUB_NAME", "AMPHOREUS")
    hub = ServerProfile.objects.filter(name=nama_hub).first()
    if not hub:
        log.warning("hub_sync: profil pusat '%s' tidak ada — dilewati.", nama_hub)
        return
    sumber = hub_sync.sumber_profiles()
    if not sumber:
        log.warning("hub_sync: tidak ada cabang ber-kode_sumber — dilewati.")
        return
    try:
        limit = max(1, int(os.environ.get("HUB_SYNC_LIMIT", "2000")))
    except ValueError:
        limit = 2000

    for hasil in hub_sync.sync_all(hub, sumber, limit=limit):
        if hasil["status"] == "failed":
            log.warning("hub_sync %s GAGAL: %s", hasil["source"], hasil["error"])
        elif hasil["diterapkan"] or hasil["dilewati"]:
            log.info(
                "hub_sync %s [%s]: %s diterapkan, %s nota, %s dead-letter, sampai id %s",
                hasil["source"], hasil["kd_sumber"], hasil["diterapkan"],
                hasil["nota"], hasil["dilewati"], hasil["sampai_id"],
            )


def _run_due_jobs() -> None:
    """Jalankan snapshot untuk SEMUA profil (bukan hanya koneksi aktif) — tiap
    server/database butuh snapshotnya sendiri. Berurutan, per-profil terisolasi:
    satu server mati/gagal tak menghentikan yang lain."""
    from django.utils import timezone

    from apps.connections.models import ServerProfile

    now = timezone.localtime()
    stok_on = _stok_enabled()
    harga_on = _harga_enabled()
    warm_on = _warm_enabled()
    health_on = _flag("SYNC_HEALTH_ENABLED")
    # Payload kolumnar Stok Akhir (~5 MB) hanya dibangun untuk profil DEFAULT.
    # Koneksi aktif sebenarnya per-pengguna (sesi), jadi thread latar ini tak
    # punya "yang aktif" — get_active_profile() pun jatuh ke is_default saat
    # tak ada request. Memanaskan ke-13 profil berarti menahan 13 × 5 MB di
    # memori proses demi halaman yang cuma menampilkan satu server. Pengguna
    # yang memilih koneksi lain menanggung sekali cache dingin; itu diterima.
    default_pk = ServerProfile.objects.filter(is_default=True).values_list("pk", flat=True).first()
    for profile in ServerProfile.objects.all():
        try:
            if health_on:
                _run_due_sync_health(profile)
            if warm_on:
                _warm_master(profile, include_stok=profile.pk == default_pk)
            if stok_on:
                _run_due_stok(now, profile)
            if harga_on:
                _run_due_harga(now, profile)
        except Exception:  # pragma: no cover — profil gagal tak hentikan lainnya
            log.exception("scheduler snapshot gagal untuk profil %s", getattr(profile, "name", "?"))

    # Di luar loop per-profil: fan-out punya sumbernya sendiri, bukan sesuatu
    # yang dikerjakan sekali untuk tiap profil yang lewat.
    if _flag("FEED_SYNC_ENABLED", "0"):
        try:
            _run_due_feed_sync()
        except Exception:  # pragma: no cover — tick harus tetap hidup
            log.exception("feed_sync gagal")
    if _flag("HUB_SYNC_ENABLED", "0"):
        try:
            _run_due_hub_sync()
        except Exception:  # pragma: no cover — tick harus tetap hidup
            log.exception("hub_sync gagal")


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
    if not (
        _harga_enabled() or _stok_enabled() or _warm_enabled()
        or _flag("SYNC_HEALTH_ENABLED") or _flag("FEED_SYNC_ENABLED", "0")
        or _flag("HUB_SYNC_ENABLED", "0")
    ):
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="snapshot-scheduler", daemon=True).start()
    log.info(
        "Scheduler snapshot aktif (interval %ss, semua profil; harga=%s jam≥%s, stok=%s jam≥%s, "
        "pemanas cache=%s ttl=%ss).",
        _interval(), _harga_enabled(), _hour("HARGA_SNAPSHOT_HOUR", 0),
        _stok_enabled(), _hour("STOK_SNAPSHOT_HOUR", 0),
        _warm_enabled(), _warm_ttl(),
    )

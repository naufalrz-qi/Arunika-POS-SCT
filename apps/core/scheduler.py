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


def _run_due_hub_pull(now) -> None:
    """Tarik transaksi cabang ke pusat langsung dari tabel aslinya.

    Dua tingkat dijadwalkan di sini, satu tidak:

    - **segar** tiap tick — N hari terakhir disalin ulang tanpa dibandingkan.
    - **cocok** sekali sehari — agregat per hari dibandingkan antara tutup buku
      dan jendela segar; hanya hari yang beda yang disalin ulang. Penjaganya
      `HubPullState.cocok_terakhir_at`, bukan tabel penanda baru: barisnya sudah
      ada dan sudah menyimpan tanggal itu.
    - **arsip** TIDAK PERNAH otomatis. Ia menyapu seluruh riwayat di bawah tutup
      buku (445.167 nota di PUSAT) dan itu keputusan manusia, bukan sesuatu yang
      boleh terjadi karena seseorang menyalakan scheduler.

    Master ikut di slot harian yang sama dan hanya dari GUDANG — katalognya satu
    untuk seluruh pusat, jadi tak ada gunanya diulang per cabang.

    Env: HUB_PULL_ENABLED (0), HUB_PULL_DAYS (7), HUB_MATCH_ENABLED (0),
    HUB_MATCH_HOUR (2), HUB_MASTER_ENABLED (0).
    """
    from django.utils import timezone

    from apps.connections.models import ServerProfile
    from apps.core.models import HubPullState
    from apps.transactions import hub_master, hub_pull

    nama_hub = os.environ.get("HUB_NAME", "AMPHOREUS")
    hub = ServerProfile.objects.filter(name=nama_hub).first()
    if not hub:
        log.warning("hub_pull: profil pusat '%s' tidak ada — dilewati.", nama_hub)
        return
    sumber = hub_pull.sumber_profiles()
    if not sumber:
        log.warning("hub_pull: tidak ada cabang ber-kode_sumber — dilewati.")
        return

    try:
        hari = max(1, int(os.environ.get("HUB_PULL_DAYS", "7")))
    except ValueError:
        hari = hub_pull.JENDELA_SEGAR_HARI

    # Satu slot harian, dua penghuni yang saling bebas. `cocok_terakhir_at`
    # menandai SLOT-nya, bukan pekerjaan cocok — kalau ia hanya ditulis oleh
    # `mode="cocok"`, mematikan HUB_MATCH_ENABLED membuat penandanya tak pernah
    # maju dan master ikut tak pernah jalan (atau jalan tiap tick).
    boleh_harian = now.hour >= _hour("HUB_MATCH_HOUR", 2)
    sudah = {
        s.source_profile_id: s.cocok_terakhir_at
        for s in HubPullState.objects.filter(target_profile=hub)
    }
    nama_master = os.environ.get("FEED_SYNC_SOURCE", "GUDANG")

    for s in sumber:
        try:
            hasil = hub_pull.pull_source(s, hub, mode="segar", hari=hari)
            if hasil["status"] == "failed":
                log.warning("hub_pull segar %s GAGAL: %s", hasil["source"], hasil["error"])
            elif hasil["header"] or hasil["dihapus"]:
                log.info(
                    "hub_pull segar %s: %s header, %s detail, %s hapus",
                    hasil["source"], hasil["header"], hasil["detail"], hasil["dihapus"],
                )
            if hasil["anomali_tanggal"]:
                log.warning(
                    "hub_pull %s: %s baris bertanggal di luar akal DILEWATI — perbaiki di cabang",
                    hasil["source"], hasil["anomali_tanggal"],
                )

            terakhir = sudah.get(s.pk)
            jatuh_tempo = boleh_harian and (
                terakhir is None or timezone.localtime(terakhir).date() < now.date()
            )
            if not jatuh_tempo:
                continue

            if _flag("HUB_MATCH_ENABLED", "0"):
                cocok = hub_pull.pull_source(s, hub, mode="cocok")
                if cocok["hari_beda"]:
                    # Hari yang tidak cocok adalah TEMUAN, bukan derau: catat
                    # jumlahnya supaya tren "selalu ada 3 hari beda" terlihat.
                    log.warning(
                        "hub_pull cocok %s: %s hari berbeda, disalin ulang",
                        cocok["source"], cocok["hari_beda"],
                    )
            if s.name == nama_master and _flag("HUB_MASTER_ENABLED", "0"):
                m = hub_master.sync_master(s, hub)
                if m["status"] == "failed":
                    log.warning("hub_master GAGAL: %s", m["error"])
            # Slot harian ditandai selesai apa pun yang jalan di dalamnya.
            HubPullState.objects.filter(source_profile=s, target_profile=hub).update(
                cocok_terakhir_at=timezone.now()
            )
        except Exception:  # pragma: no cover — satu cabang tak menjatuhkan sisanya
            log.exception("hub_pull gagal untuk cabang %s", getattr(s, "name", "?"))


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
    # `hub_sync` (feed `tbl_log_transaksi`) DIGANTI `hub_pull` (tarik langsung
    # dari tabel asli). Pemanggilannya sengaja ditinggal di sini di belakang flag
    # yang defaultnya 0: kodenya belum dihapus supaya angka jalur lama masih bisa
    # dibandingkan kalau `hub_pull` ternyata meleset. Jangan menyalakan keduanya
    # sekaligus — keduanya menulis tabel yang sama, dan yang belakangan menang.
    if _flag("HUB_SYNC_ENABLED", "0"):
        try:
            _run_due_hub_sync()
        except Exception:  # pragma: no cover — tick harus tetap hidup
            log.exception("hub_sync gagal")
    if _flag("HUB_PULL_ENABLED", "0"):
        try:
            _run_due_hub_pull(now)
        except Exception:  # pragma: no cover — tick harus tetap hidup
            log.exception("hub_pull gagal")


def _loop() -> None:
    time.sleep(60)  # beri boot server selesai dulu
    interval = _interval()
    while True:
        try:
            _run_due_jobs()
        except Exception:  # pragma: no cover — loop harus tetap hidup
            log.exception("scheduler snapshot error")
        time.sleep(interval)


def _harga_sync_interval() -> int:
    try:
        return max(15, int(os.environ.get("HARGA_SYNC_INTERVAL_SECONDS", "60")))
    except ValueError:
        return 60


def _loop_harga() -> None:
    """Sebar harga GUDANG -> toko. THREAD SENDIRI, bukan menumpang tick utama.

    Tick utama 30 menit karena isinya snapshot berat yang memang harian; harga
    butuh hitungan menit. Menurunkan interval bersama akan membuat pemanas cache
    master dan sapuan kesehatan sync ikut jalan tiap menit — semuanya menyentuh
    sebelas server.

    Sapuan penuh (membaca keadaan nyata tiap toko) dijalankan berkala, dan yang
    PERTAMA selalu penuh karena salinan harga di memori masih kosong. Lihat
    `harga_sync.sapu` untuk kenapa mode cepat sendirian tidak cukup.
    """
    from apps.transactions import harga_sync

    time.sleep(90)  # sesudah loop utama; jangan dua sapuan besar barengan saat boot
    interval = _harga_sync_interval()
    try:
        tiap_penuh = max(1, int(os.environ.get("HARGA_SYNC_FULL_MINUTES", "60")))
    except ValueError:
        tiap_penuh = 60
    detik_sejak_penuh = 10**9  # paksa sapuan pertama jadi penuh
    # Kegagalan dilaporkan saat BERUBAH, bukan tiap tick. Toko dimatikan tiap
    # malam saat tutup; tanpa ini, delapan toko mati x 60 detik = ribuan baris
    # peringatan identik sampai pagi, dan kegagalan yang sungguhan tenggelam di
    # dalamnya. Yang perlu terlihat adalah PERUBAHAN keadaan.
    gagal_terakhir: set = set()
    while True:
        try:
            source, targets = harga_sync.profil_fanout()
            if source and targets:
                penuh = detik_sejak_penuh >= tiap_penuh * 60
                hasil = harga_sync.sapu(source, targets, penuh=penuh)
                if penuh:
                    detik_sejak_penuh = 0
                if hasil["sku"]:
                    log.info(
                        "harga_sync %s: %s SKU disebar (%s) %s",
                        hasil["mode"], hasil["sku"], source.name, hasil["per_toko"],
                    )
                # Toko yang gagal BUKAN sekadar catatan: sampai sapuan penuh
                # berikutnya, harga di sana basi tanpa gejala apa pun. Tapi yang
                # dilaporkan PERUBAHANNYA, bukan keadaannya tiap menit.
                gagal = set(hasil["gagal"]) | ({"(sumber)"} if hasil["error"] else set())
                if gagal != gagal_terakhir:
                    if gagal - gagal_terakhir:
                        log.warning(
                            "harga_sync mulai gagal ke: %s", sorted(gagal - gagal_terakhir)
                        )
                    if gagal_terakhir - gagal:
                        log.info("harga_sync pulih ke: %s", sorted(gagal_terakhir - gagal))
                    gagal_terakhir = gagal
        except Exception:  # pragma: no cover — loop harus tetap hidup
            log.exception("harga_sync error")
        time.sleep(interval)
        detik_sejak_penuh += interval


def start_scheduler() -> None:
    """Idempotent: mulai daemon thread. Dipanggil dari config/wsgi.py."""
    global _started
    harga_sync_on = _flag("HARGA_SYNC_ENABLED", "0")
    if not (
        _harga_enabled() or _stok_enabled() or _warm_enabled()
        or _flag("SYNC_HEALTH_ENABLED") or _flag("FEED_SYNC_ENABLED", "0")
        or _flag("HUB_SYNC_ENABLED", "0") or _flag("HUB_PULL_ENABLED", "0")
        or harga_sync_on
    ):
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="snapshot-scheduler", daemon=True).start()
    if harga_sync_on:
        threading.Thread(target=_loop_harga, name="harga-sync", daemon=True).start()
        log.info("Sebar harga GUDANG -> toko aktif (tiap %ss).", _harga_sync_interval())
    log.info(
        "Scheduler snapshot aktif (interval %ss, semua profil; harga=%s jam≥%s, stok=%s jam≥%s, "
        "pemanas cache=%s ttl=%ss).",
        _interval(), _harga_enabled(), _hour("HARGA_SNAPSHOT_HOUR", 0),
        _stok_enabled(), _hour("STOK_SNAPSHOT_HOUR", 0),
        _warm_enabled(), _warm_ttl(),
    )

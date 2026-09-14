"""Transfer ke Arunika: satu tombol untuk legacy -> salinan lokal -> DB Arunika baru.

Menjalankan urutan yang sebelumnya tiga perintah terminal, dari layar superadmin
(`/admin-panel/master/transfer-arunika`), di thread latar, dengan progres di
`apps.core.models.TransferArunika`.

## Satu transfer = dua profil baru + tiga database baru

Nama `N` (slug `s`), sumber `S`, jendela `dari..sampai`:

1. **Salin legacy**     profil `N (legacy)`, db `legacy_s`: tabel legacy `S` mentah
                        dalam jendela tanggal. `S` hanya DIBACA.
2. **Sumber adapter**   db `arunika_s_sumber` untuk profil (1): view mode legacy.
3. **Tujuan**           profil `N`, db `arunika_s`: skema Arunika + view mode arunika.
4. **Isi**              tabel nyata (3) dari view (2).

Semua database dibuat di instans LOKAL yang kredensialnya diambil dari profil
ber-lingkungan uji yang dipilih -- server produksi tak pernah menerima objek apa
pun. Tiap transfer membuat nama baru; tak ada yang ditimpa, dan nama yang sudah
dipakai (profil maupun database) ditolak di depan.

## Yang sengaja tak ada

Tombol batal: thread tak bisa dihentikan dengan aman di tengah INSERT beruntun,
dan setengah transfer tak berguna. Hapus transfer lama juga belum ada.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import threading

import pyodbc
from django.db import connections
from django.utils import timezone

from apps.bisnis import muat, salin_legacy
from apps.bisnis.siapkan import Ditolak, database_ada, siapkan_arunika
from core import mssql

log = logging.getLogger(__name__)

# `db_name` profil Arunika-murni. Menunjuk database yang memang TIDAK ADA: jalur
# yang diam-diam mencoba membaca legacy lewat profil ini gagal seketika dengan
# "Cannot open database", bukan menemukan data server lain.
TANPA_LEGACY = "TIDAK_ADA_LEGACY"

TAHAP = ("Salin legacy", "Sumber adapter", "Tujuan", "Isi")

PANJANG_SLUG = 40

_kunci = threading.Lock()
_thread: dict[int, threading.Thread] = {}


def slug(nama: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (nama or "").strip().lower()).strip("_")
    return s[:PANJANG_SLUG].strip("_")


def nama_database(s: str) -> dict[str, str]:
    return {"legacy": f"legacy_{s}", "sumber": f"arunika_{s}_sumber", "tujuan": f"arunika_{s}"}


def nama_profil(nama: str) -> dict[str, str]:
    return {"legacy": f"{nama} (legacy)", "tujuan": nama}


def pilihan_sumber():
    """Profil yang boleh jadi sumber: database POS legacy, produksi maupun uji.

    Dikeluarkan: profil Arunika-murni (tak punya legacy sama sekali) dan hub
    AMPHOREUS (skema berbeda, ber-`kd_sumber`).
    """
    from apps.connections.models import ServerProfile

    hub = os.environ.get("HUB_NAME", "AMPHOREUS")
    return ServerProfile.objects.exclude(db_name=TANPA_LEGACY).exclude(name=hub).order_by("name")


def pilihan_instans():
    """Satu profil uji per (host, port, username): sumber kredensial instans lokal."""
    from apps.connections.models import Lingkungan, ServerProfile

    dilihat, hasil = set(), []
    for p in ServerProfile.objects.filter(lingkungan=Lingkungan.UJI).order_by("name"):
        k = (p.host.lower(), p.port, p.username.lower())
        if k not in dilihat:
            dilihat.add(k)
            hasil.append(p)
    return hasil


def tutup_buku_terakhir(sumber):
    """Tanggal tutup buku terakhir `sumber` (sadar-zona), atau None. Hanya dibaca."""
    with mssql.report_cursor(sumber) as cur:
        cur.execute("SELECT MAX(tanggal) FROM g_tutup_buku")
        tgl = cur.fetchone()[0]
    if tgl is None:
        return None
    return timezone.make_aware(tgl, timezone.get_current_timezone()) if timezone.is_naive(tgl) else tgl


def validasi(nama, sumber_id, dari, sampai, instans_id) -> dict:
    """Periksa input form. Pulangkan objek siap pakai, atau `Ditolak`."""
    from apps.connections.models import Lingkungan, ServerProfile

    nama = (nama or "").strip()
    s = slug(nama)
    if not nama or not s:
        raise Ditolak("Nama transfer wajib diisi, minimal satu huruf atau angka.")
    try:
        dari = dt.date.fromisoformat(str(dari))
        sampai = dt.date.fromisoformat(str(sampai))
    except ValueError:
        raise Ditolak("Tanggal harus berformat YYYY-MM-DD.")
    if dari > sampai:
        raise Ditolak("Tanggal awal lewat dari tanggal akhir.")

    sumber = pilihan_sumber().filter(pk=sumber_id).first()
    if not sumber:
        raise Ditolak("Server sumber tak dikenal atau bukan database legacy.")
    instans = ServerProfile.objects.filter(pk=instans_id, lingkungan=Lingkungan.UJI).first()
    if not instans:
        raise Ditolak("Instans lokal harus dipilih dari profil ber-lingkungan uji.")

    profil = nama_profil(nama)
    bentrok = sorted(ServerProfile.objects.filter(name__in=profil.values())
                     .values_list("name", flat=True))
    if bentrok:
        raise Ditolak(f"Nama profil sudah dipakai: {', '.join(bentrok)}. Pilih nama lain.")
    db = nama_database(s)
    try:
        ada = [n for n in db.values() if database_ada(instans, n)]
    except pyodbc.Error as exc:
        raise Ditolak(mssql.friendly_error(exc, f"Gagal menghubungi instans {instans.host}"))
    if ada:
        raise Ditolak(f"Database sudah ada di {instans.host}: {', '.join(ada)}. Pilih nama lain.")
    # Dibaca di depan, bukan di tengah jalan: sumber yang tak terjangkau ketahuan
    # sebelum satu profil atau database pun dibuat.
    try:
        tutup_buku = tutup_buku_terakhir(sumber)
    except pyodbc.Error as exc:
        raise Ditolak(mssql.friendly_error(exc, f"Gagal membaca server sumber {sumber.name}"))
    return {"nama": nama, "slug": s, "sumber": sumber, "instans": instans,
            "dari": dari, "sampai": sampai, "tutup_buku": tutup_buku}


def sedang_berjalan() -> bool:
    return any(t.is_alive() for t in _thread.values())


def rapikan_yatim() -> int:
    """Baris `berjalan` yang thread-nya tak hidup lagi (server berhenti) -> `terputus`."""
    from apps.core.models import TransferArunika

    hidup = [i for i, t in _thread.items() if t.is_alive()]
    return (TransferArunika.objects.filter(status=TransferArunika.BERJALAN)
            .exclude(pk__in=hidup)
            .update(status=TransferArunika.TERPUTUS, selesai_pada=timezone.now(),
                    pesan_galat="Server berhenti saat transfer berjalan. Hasilnya setengah jadi."))


def mulai(data: dict, username: str, sinkron: bool = False):
    """Buat baris jalan dan jalankan transfernya. `data` hasil `validasi`.

    Satu transfer sekaligus: dua pemuatan sejuta baris bersamaan ke instans yang
    sama hanya membuat keduanya lambat, dan pemeriksaan nama di `validasi` tak
    melihat transfer lain yang belum sempat membuat databasenya.
    """
    from apps.core.models import TransferArunika

    with _kunci:
        if sedang_berjalan():
            raise Ditolak("Masih ada transfer yang berjalan. Tunggu sampai selesai.")
        rapikan_yatim()
        run = TransferArunika.objects.create(
            nama=data["nama"], sumber=data["sumber"], sumber_nama=data["sumber"].name,
            dari=data["dari"], sampai=data["sampai"], tutup_buku=data.get("tutup_buku"),
            dibuat_oleh=username or "",
            tahap=TAHAP[0],
        )
        if sinkron:
            _jalankan(run.pk, data["instans"].pk)
            return run
        t = threading.Thread(target=_jalankan, args=(run.pk, data["instans"].pk),
                             name=f"transfer-arunika-{run.pk}", daemon=True)
        _thread[run.pk] = t
        t.start()
    return run


def _pencatat(run, tahap: str):
    """`lapor` yang menulis progres ke baris jalan."""
    def lapor(p: dict) -> None:
        if p.get("jenis") == "langkah":
            run.langkah = [*run.langkah, {
                "tahap": tahap, "nama": p["nama"], "baris": p.get("baris", 0),
                "detik": p.get("detik", 0), "dilewati": p.get("dilewati", 0),
                "alasan": p.get("alasan") or {},
            }]
            if tahap == TAHAP[3]:
                run.total_baris += p.get("baris", 0)
                run.total_dilewati += p.get("dilewati", 0)
            run.tahap = f"{tahap}: {p['nama']}"
            run.save(update_fields=["langkah", "tahap", "total_baris", "total_dilewati"])
        else:
            run.tahap = f"{tahap}: {p.get('pesan', '')}"[:100]
            run.save(update_fields=["tahap"])
    return lapor


def _profil_baru(nama, db_name, instans, sumber):
    from apps.connections.models import Lingkungan, ServerProfile

    return ServerProfile.objects.create(
        name=nama, db_type=sumber.db_type, host=instans.host, port=instans.port,
        db_name=db_name, username=instans.username,
        password_encrypted=instans.password_encrypted, lingkungan=Lingkungan.UJI,
    )


def _jalankan(run_id: int, instans_id: int) -> None:
    from apps.connections.models import ServerProfile
    from apps.core.models import ActivityLog, TransferArunika

    run = TransferArunika.objects.get(pk=run_id)
    try:
        instans = ServerProfile.objects.get(pk=instans_id)
        sumber = run.sumber
        if sumber is None:
            raise Ditolak("Profil sumber sudah dihapus.")
        db, profil = nama_database(slug(run.nama)), nama_profil(run.nama)

        run.tahap = TAHAP[0]
        run.save(update_fields=["tahap"])
        legacy = _profil_baru(profil["legacy"], db["legacy"], instans, sumber)
        run.profil_legacy = legacy
        run.save(update_fields=["profil_legacy"])
        salin_legacy.salin(sumber, legacy, run.dari, run.sampai, lapor=_pencatat(run, TAHAP[0]))

        siapkan_arunika(legacy, db=db["sumber"], mode="legacy", lapor=_pencatat(run, TAHAP[1]))

        tujuan = _profil_baru(profil["tujuan"], TANPA_LEGACY, instans, sumber)
        run.profil_arunika = tujuan
        run.save(update_fields=["profil_arunika"])
        siapkan_arunika(tujuan, db=db["tujuan"], mode="arunika", lapor=_pencatat(run, TAHAP[2]))

        muat.muat_semua(legacy, tujuan, run.dari, run.sampai, lapor=_pencatat(run, TAHAP[3]))
        run.status, run.tahap = TransferArunika.SELESAI, "Selesai"
    except Ditolak as exc:
        run.status, run.pesan_galat = TransferArunika.GAGAL, str(exc)
    except pyodbc.Error as exc:
        run.status = TransferArunika.GAGAL
        run.pesan_galat = mssql.friendly_error(exc, f"Gagal di tahap {run.tahap}")
    except Exception as exc:  # thread latar: galat apa pun harus tercatat, bukan hilang
        log.exception("transfer arunika %s gagal", run_id)
        run.status = TransferArunika.GAGAL
        run.pesan_galat = f"{type(exc).__name__}: {exc}"
    finally:
        run.selesai_pada = timezone.now()
        run.save(update_fields=["status", "tahap", "pesan_galat", "selesai_pada"])
        ActivityLog.objects.create(
            username=run.dibuat_oleh, action="transfer_arunika",
            detail=(f"Transfer ke Arunika '{run.nama}' {run.get_status_display().lower()}: "
                    f"{run.total_baris:,} baris")[:255],
        )
        # Koneksi thread latar tak ditutup Django (tak ada akhir request). Di jalan
        # sinkron (test) justru jangan: itu koneksi milik test itu sendiri.
        if _thread.pop(run_id, None) is not None:
            connections.close_all()

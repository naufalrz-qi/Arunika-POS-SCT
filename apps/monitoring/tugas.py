"""Tugas latar yang dipicu dari layar Kesehatan Sync.

## Kenapa semuanya lewat thread, tanpa jalur sinkron

Enam tugas di sini memanggil fungsi yang sama persis dengan yang dijalankan
scheduler. Durasinya sangat berbeda:

    pull_segar satu cabang      detik - menit
    sync_pair limit 2000        detik
    sapu(penuh=True)            puluhan detik (8 toko lewat WAN)
    cocokkan_harian             menit
    pull_arsip                  BERJAM-JAM

Menjalankan yang pendek sinkron dan yang panjang lewat thread berarti dua jalur
kegagalan, dua tempat menulis progres, dan satu keputusan "yang mana" yang harus
diambil ulang tiap kali tugas baru ditambahkan. Dan yang "aman sinkron" pun
mengunci satu thread waitress puluhan detik di server yang pada saat bersamaan
melayani kasir. Jadi: satu pola, disalin sekali dari `apps/bisnis/transfer.py`.

## Baris progres = baris riwayat

Tidak ada tabel progres terpisah. Satu baris `SyncLog` dibuat berstatus
`berjalan` SEBELUM thread mulai, `detail`-nya diisi baris demi baris selama
jalan, lalu statusnya pindah ke `ok`/`failed` dan `duration_ms` terisi saat
selesai. Layar membaca baris yang sama untuk progres dan untuk riwayat.

Itu sebabnya `pull_source` dipanggil dengan `catat=False`: ia punya penulis
`SyncLog` sendiri, dan tanpa saklar itu satu klik meninggalkan dua baris yang
menceritakan run yang sama.

## Yang sengaja tidak ada

- **Tombol batal.** Alasan yang sama dengan `transfer.py`: thread tak bisa
  dihentikan dengan aman di tengah INSERT beruntun.
- **"Arsip semua cabang".** Satu klik = berjam-jam × 9. Arsip WAJIB menyebut
  satu cabang.
- **Kunci lintas-proses.** `_kunci` hanya berlaku di proses web, jadi run CLI
  paralel tetap mungkin — dan itu sudah aman: tiap mode `hub_pull` idempoten
  (arsip melompati potongan bertanda `arsip_sampai`, cocok membandingkan ulang,
  segar menyalin ulang), dan `harga_sync`/`feed_sync` menulis nilai yang sama.
  Kunci database baru perlu kalau ada tugas yang TIDAK idempoten.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

import pyodbc
from django.db import connections
from django.utils import timezone

from apps.bisnis.siapkan import Ditolak
from apps.core.models import SyncLog
from core import mssql

log = logging.getLogger(__name__)

_kunci = threading.Lock()
_thread: dict[int, threading.Thread] = {}


def _hub():
    from apps.connections.models import ServerProfile

    nama = os.environ.get("HUB_NAME", "AMPHOREUS")
    hub = ServerProfile.objects.filter(name=nama).first()
    if hub is None:
        raise Ditolak(f"Profil pusat '{nama}' belum ada. Buat dulu di Kelola Koneksi.")
    return hub


# --- Isi tiap tugas -------------------------------------------------------
# Tiap fungsi menerima (profil, lapor) dan mengembalikan dict ringkasan.
# `profil` boleh None untuk tugas yang menentukan sasarannya sendiri dari env.

def _tarik(mode):
    def jalan(profil, lapor):
        from apps.transactions import hub_pull

        if profil is None:
            raise Ditolak("Tugas ini butuh satu cabang yang dipilih.")
        hasil = hub_pull.pull_source(
            profil, _hub(), mode=mode, lapor=lapor, username="", catat=False,
        )
        lapor(f"Selesai: header {hasil['header']}, detail {hasil['detail']}, "
              f"dihapus {hasil['dihapus']}, hari beda {hasil['hari_beda']}")
        if hasil["status"] == "failed":
            raise RuntimeError(hasil["error"] or "tarik gagal tanpa pesan")
        return {
            "compared": hasil["hari_beda"],
            "applied": hasil["header"] + hasil["detail"] + hasil["dihapus"],
        }
    return jalan


def _master(profil, lapor):
    from apps.transactions import hub_master
    from apps.transactions.hub_pull import sumber_profiles

    sumber = [p for p in sumber_profiles() if p.name == os.environ.get("MASTER_SUMBER", "GUDANG")]
    if not sumber:
        raise Ditolak("Profil GUDANG tidak ditemukan di antara cabang ber-kode_sumber.")
    lapor(f"Menyalin master data dari {sumber[0].name} ke pusat…")
    hasil = hub_master.sync_master(sumber[0], _hub())
    if hasil["status"] == "failed":
        raise RuntimeError(hasil["error"] or "sync master gagal tanpa pesan")
    # `hasil["tabel"]` adalah LIST dict per tabel: {tabel, baru, ubah, hapus,
    # hapus_dilewati, sama} — bukan peta nama->jumlah.
    ditulis = 0
    for t in hasil["tabel"]:
        n = t["baru"] + t["ubah"] + t["hapus"]
        ditulis += n
        lapor(f"  {t['tabel']}: {t['baru']} baru, {t['ubah']} ubah, {t['hapus']} hapus "
              f"({t['sama']} sama)")
    return {"compared": sum(t["sama"] for t in hasil["tabel"]) + ditulis, "applied": ditulis}


def _feed(profil, lapor):
    from apps.transactions import feed_sync, harga_sync

    source, targets = harga_sync.profil_fanout()
    if not source or not targets:
        raise Ditolak("FEED_SYNC_SOURCE / FEED_SYNC_TARGETS belum diatur.")
    try:
        limit = max(1, int(os.environ.get("FEED_SYNC_LIMIT", "2000")))
    except ValueError:
        limit = 2000
    total = 0
    for t in targets:
        h = feed_sync.sync_pair(source, t, limit=limit, username="")
        total += h["diterapkan"]
        lapor(f"  {t.name}: {h['diterapkan']} diterapkan, {h['dilewati']} dead-letter"
              + (f" — GAGAL: {h['error'][:120]}" if h["status"] == "failed" else ""))
    return {"compared": len(targets), "applied": total}


def _harga(profil, lapor):
    from apps.transactions import harga_sync

    source, targets = harga_sync.profil_fanout()
    if not source or not targets:
        raise Ditolak("FEED_SYNC_SOURCE / FEED_SYNC_TARGETS belum diatur.")
    lapor(f"Sapuan PENUH {source.name} -> {len(targets)} toko…")
    # Selalu penuh: sapuan cepat membandingkan dengan salinan memori, dan orang
    # yang menekan tombol ini justru sedang meragukan salinan itu.
    h = harga_sync.sapu(source, targets, penuh=True, username="")
    for t, n in sorted((h.get("per_toko") or {}).items()):
        lapor(f"  {t}: {n} baris")
    for t, p in sorted((h.get("gagal") or {}).items()):
        lapor(f"  GAGAL {t}: {p[:120]}")
    return {"compared": h["sku"], "applied": sum((h.get("per_toko") or {}).values())}


TUGAS = {
    "segar": ("Tarik segar", "hub_pull", _tarik("segar"), True),
    "cocok": ("Cocokkan harian", "hub_pull", _tarik("cocok"), True),
    "arsip": ("Tarik arsip", "hub_pull", _tarik("arsip"), True),
    "master": ("Master data ke pusat", "hub_master", _master, False),
    "feed": ("Fan-out master ke toko", "feed_sync", _feed, False),
    "harga": ("Sebar harga (penuh)", "harga_sync", _harga, False),
}


# --- Runner ---------------------------------------------------------------

def sedang_berjalan() -> bool:
    return any(t.is_alive() for t in _thread.values())


def rapikan_yatim() -> int:
    """Baris `berjalan` yang thread-nya sudah tak ada -> `failed`.

    Sesudah restart `_thread` kosong, jadi baris yang ditinggalkan proses mati
    tidak akan menggantung berstatus "berjalan" selamanya — dan kunci
    satu-tugas-sekaligus tidak macet permanen karenanya.
    """
    return (SyncLog.objects
            .filter(status=SyncLog.Status.BERJALAN)
            .exclude(pk__in=[pk for pk, t in _thread.items() if t.is_alive()])
            .update(status=SyncLog.Status.FAILED,
                    error_message="Server berhenti saat tugas berjalan. Hasilnya setengah jadi."))


def _pencatat(run: SyncLog):
    """Kembalikan `lapor(teks)` yang menambahkan satu baris ke `run.detail`.

    Bentuknya cocok dengan callback `lapor` yang SUDAH dipunyai `hub_pull`:
    teks satu arah, dipanggil tiap potongan bulanan sesudah commit. Itulah yang
    membuat progres run arsip bisa ditampilkan tanpa mengubah `hub_pull` sama
    sekali.
    """
    def lapor(teks):
        try:
            baris = json.loads(run.detail) if run.detail else []
        except ValueError:  # pragma: no cover — detail selalu ditulis fungsi ini
            baris = []
        baris.append({"waktu": timezone.localtime().strftime("%H:%M:%S"),
                      "teks": str(teks).strip()[:500]})
        run.detail = json.dumps(baris[-500:])  # batas atas: run arsip panjang
        run.save(update_fields=["detail"])
    return lapor


def mulai(nama: str, profil, username: str, sinkron: bool = False) -> SyncLog:
    if nama not in TUGAS:
        raise Ditolak(f"Tugas '{nama}' tidak dikenal.")
    label, feature, _fn, butuh_profil = TUGAS[nama]
    if butuh_profil and profil is None:
        raise Ditolak(f"{label} harus menyebut satu cabang.")
    hub = _hub()  # divalidasi di depan, sebelum baris apa pun dibuat
    with _kunci:
        if sedang_berjalan():
            raise Ditolak("Masih ada tugas yang berjalan. Tunggu sampai selesai.")
        rapikan_yatim()
        run = SyncLog.objects.create(
            feature=feature, mode=nama, status=SyncLog.Status.BERJALAN,
            src_profile=profil, src_name=profil.name if profil else "",
            dst_profile=hub, dst_name=hub.name, username=username, detail="[]",
        )
        profil_pk = profil.pk if profil else None
        if sinkron:
            # Hanya untuk test: `TestCase` membungkus tiap test dalam satu
            # transaksi, dan thread lain yang menulis SQLite di dalamnya kena
            # "database table is locked". Pola yang sama dipakai
            # `apps/bisnis/transfer.py`.
            _jalankan(run.pk, nama, profil_pk, sinkron=True)
            run.refresh_from_db()
            return run
        t = threading.Thread(target=_jalankan, args=(run.pk, nama, profil_pk),
                             name=f"tugas-{nama}-{run.pk}", daemon=True)
        _thread[run.pk] = t
        t.start()
    return run


def _jalankan(run_pk: int, nama: str, profil_pk: int | None, sinkron: bool = False) -> None:
    from apps.connections.models import ServerProfile

    run = SyncLog.objects.get(pk=run_pk)
    profil = ServerProfile.objects.filter(pk=profil_pk).first() if profil_pk else None
    lapor = _pencatat(run)
    mulai_detik = time.monotonic()
    _label, _feature, fn, _butuh = TUGAS[nama]
    try:
        hasil = fn(profil, lapor)
        run.status = SyncLog.Status.OK
        run.compared_count = hasil.get("compared", 0)
        run.applied_count = hasil.get("applied", 0)
    except Ditolak as exc:
        run.status, run.error_message = SyncLog.Status.FAILED, str(exc)[:255]
    except pyodbc.Error as exc:
        run.status = SyncLog.Status.FAILED
        run.error_message = mssql.friendly_error(exc, "Gagal")[:255]
    except Exception as exc:  # thread latar: galat apa pun harus tercatat, bukan hilang
        log.exception("tugas %s (run %s) gagal", nama, run_pk)
        run.status = SyncLog.Status.FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"[:255]
    finally:
        run.duration_ms = int((time.monotonic() - mulai_detik) * 1000)
        run.save(update_fields=["status", "error_message", "compared_count",
                                "applied_count", "duration_ms"])
        # Koneksi thread latar tak ditutup Django (tak ada akhir request). Di
        # jalur sinkron (test) justru jangan: itu koneksi milik test itu sendiri.
        if _thread.pop(run_pk, None) is not None and not sinkron:
            connections.close_all()


def aktif() -> dict | None:
    """Baris tugas yang sedang berjalan, untuk polling layar. Murni SQLite."""
    rapikan_yatim()
    run = SyncLog.objects.filter(status=SyncLog.Status.BERJALAN).first()
    if run is None:
        return None
    return {
        "id": run.pk,
        "tugas": run.mode,
        "label": TUGAS.get(run.mode, (run.mode,))[0],
        "cabang": run.src_name or "—",
        "mulai": timezone.localtime(run.created_at).strftime("%H:%M:%S"),
        "baris": run.items(),
    }

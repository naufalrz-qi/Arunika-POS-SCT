"""Jejak Audit — seluruh jejak `ActivityLog`, lintas akun (menu teknis).

Log Aktivitas (`views.logs_index`) sengaja hanya memperlihatkan jejak SENDIRI
lewat `log_untuk`. Layar ini kebalikannya: pekerjaan seluruh kantor, dengan isi
sebelum/sesudah setiap perubahan dokumen — karena itu menunya `teknis`, dan
hanya superadmin yang memberikannya.

Tabelnya satu (`ActivityLog`), bukan tabel audit kedua. Riwayat per nota
menggabungkan dua sumber yang memang berbeda dan harus tetap terbaca berdampingan:

- jejak Arunika di pangkal: siapa (akun Arunika), alasan yang diketik, isi
  sebelum/sesudah — hal-hal yang tak pernah ada di database legacy;
- log trigger legacy (`tbl_log_transaksi`, dibaca `riwayat_log`): SETIAP versi
  nota, termasuk edit dari aplikasi POS lama yang tak pernah lewat Arunika.

Edit yang dilakukan lewat Arunika muncul di kedua sumber. Peristiwa legacy
yang id log-nya jatuh di rentang yang dicatat Edit Nota (`data.log_id`) diberi
label "via Arunika", supaya satu edit tak terbaca sebagai dua.
"""
import datetime as dt
import json

import pyodbc
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from inertia import defer, render

from apps.auth_app.models import User
from apps.connections.akses import koneksi_boleh
from apps.connections.models import ServerProfile
from apps.core.models import ActivityLog, periksa_rantai
from apps.monitoring.views import (CONN_ERROR, _PESAN_LOG_BELUM, _active, _hidden_fields, _local,
                                   _log_siap, _wajib_menu)
from apps.transactions import riwayat_log
from apps.transactions.hub_sync import bind_varchar
from apps.inventory.services import _k
from core import mssql

PER_HALAMAN = 50

# Jejak memuat isi nota — harga per baris, total, diskon — dan ringkasan aksi
# lain yang menyebut rupiah. Menyaringnya per kolom di JSON bersarang adalah
# tempat paling mudah untuk terlewat satu, jadi seperti Laba Rugi dan Edit Nota:
# akun yang nilai uangnya disembunyikan ditolak utuh, dan diberi tahu sebabnya.
DITOLAK_UANG = (
    "Jejak Audit memuat isi nota beserta harga dan totalnya, dan izin melihat nilai "
    "uang tidak diberikan untuk akun Anda. Hubungi pengelola aplikasi bila Anda "
    "memang membutuhkannya."
)


def uang_boleh(request) -> bool:
    return not ({"nominal", "harga_jual"} & _hidden_fields(request))


def _data(a: ActivityLog) -> dict | None:
    if not a.data:
        return None
    try:
        return json.loads(a.data)
    except ValueError:
        # Isi yang tak terbaca tetap ditampilkan apa adanya: menyembunyikannya
        # di layar AUDIT berarti menyembunyikan justru baris yang janggal.
        return {"mentah": a.data}


def _baris(a: ActivityLog) -> dict:
    return {
        "id": a.id,
        "waktu": _local(a.timestamp),
        "user": a.username or "—",
        "aksi": a.action,
        "detail": a.detail,
        "ip": a.ip_address or "",
        "koneksi": a.profile_name,
        "jenis_dokumen": a.jenis_dokumen,
        "no_dokumen": a.no_dokumen,
        "alasan": a.alasan,
        "ada_data": bool(a.data),
        "berantai": bool(a.hash),
    }


def _saring(request):
    g = request.GET
    f = {k: (g.get(k) or "").strip() for k in ("dari", "sampai", "user", "aksi", "koneksi", "no")}
    try:
        f["page"] = max(1, int(g.get("page") or 1))
    except ValueError:
        f["page"] = 1
    qs = ActivityLog.objects.all()
    # Semua penyaring di SQL, lalu dipotong per halaman — bukan menyaring 300
    # baris yang sudah terpotong (kekeliruan lama Log Aktivitas).
    for kunci, kolom in (("dari", "timestamp__date__gte"), ("sampai", "timestamp__date__lte")):
        if f[kunci]:
            try:
                qs = qs.filter(**{kolom: dt.date.fromisoformat(f[kunci])})
            except ValueError:
                f[kunci] = ""
    if f["user"]:
        qs = qs.filter(username=f["user"])
    if f["aksi"]:
        qs = qs.filter(action=f["aksi"])
    if f["koneksi"]:
        qs = qs.filter(profile_name=f["koneksi"])
    if f["no"]:
        qs = qs.filter(no_dokumen__icontains=f["no"])
    return f, qs.order_by("-id")


def jejak_audit(request):
    if (denied := _wajib_menu(request)):
        return denied
    f, qs = _saring(request)

    def muat():
        if not uang_boleh(request):
            return {"rows": [], "page": 1, "pages": 1, "total": 0, "ditolak": DITOLAK_UANG}
        halaman = Paginator(qs, PER_HALAMAN).get_page(f["page"])
        return {
            "rows": [_baris(a) for a in halaman.object_list],
            "page": halaman.number,
            "pages": halaman.paginator.num_pages,
            "total": halaman.paginator.count,
        }

    return render(request, "Admin/JejakAudit", props={
        "jejak": defer(muat),
        "filters": f,
        # Pilihan penyaring dari sumber lengkapnya, bukan dari baris yang
        # terkirim — yang terakhir menyempit diam-diam saat log bertambah.
        "users": sorted(User.objects.values_list("username", flat=True)),
        "aksi_list": sorted(set(ActivityLog.objects.values_list("action", flat=True).distinct())),
        "koneksi_list": sorted(
            set(ServerProfile.objects.values_list("name", flat=True))
            | set(ActivityLog.objects.exclude(profile_name="")
                  .values_list("profile_name", flat=True).distinct())),
    })


def jejak_audit_detail(request):
    """JSON satu baris jejak, lengkap dengan isi sebelum/sesudahnya."""
    if (denied := _wajib_menu(request)):
        return denied
    if not uang_boleh(request):
        return JsonResponse({"error": DITOLAK_UANG}, status=403)
    try:
        a = ActivityLog.objects.get(pk=int(request.GET.get("id") or 0))
    except (ValueError, ActivityLog.DoesNotExist):
        return JsonResponse({"error": "Jejak tidak ditemukan."}, status=404)
    return JsonResponse({"baris": _baris(a), "data": _data(a)})


def jejak_audit_periksa(request):
    """Periksa rantai hash — atas permintaan, bukan setiap buka halaman:
    penelusurannya membaca seluruh tabel jejak."""
    if (denied := _wajib_menu(request)):
        return denied
    return JsonResponse(periksa_rantai())


def jejak_audit_riwayat(request):
    """Riwayat gabungan satu nota di satu koneksi (JSON)."""
    if (denied := _wajib_menu(request)):
        return denied
    if not uang_boleh(request):
        return JsonResponse({"error": DITOLAK_UANG}, status=403)
    no = (request.GET.get("no") or "").strip()
    nama = (request.GET.get("koneksi") or "").strip()
    # Hanya koneksi yang boleh dipakai akun ini: riwayat legacy DIBACA dari
    # server itu, dan layar audit tak boleh jadi jalan belakang ke server yang
    # tak pernah diberikan kepadanya.
    profile = koneksi_boleh(request.user).filter(name=nama).first() if nama else _active()
    if not no:
        return JsonResponse({"error": "Nomor nota tidak disebutkan."}, status=400)
    if not profile:
        return JsonResponse({"error": CONN_ERROR}, status=503)
    return JsonResponse(riwayat_gabungan(profile, no))


# --- Riwayat gabungan satu nota ----------------------------------------------

def _jejak_arunika(profile, no: str) -> list[dict]:
    qs = (ActivityLog.objects
          .filter(no_dokumen=no, jenis_dokumen="penjualan")
          .filter(Q(profile=profile) | Q(profile__isnull=True, profile_name=profile.name))
          .order_by("id"))
    out = []
    for a in qs:
        data = _data(a) or {}
        out.append(_baris(a) | {"selisih": data.get("selisih"),
                                "total": {"dari": (data.get("sebelum") or {}).get("total"),
                                          "ke": (data.get("sesudah") or {}).get("total")},
                                "log_id": data.get("log_id")})
    return out


def _nama_user(cur, kode: list[str]) -> dict:
    kode = sorted({k for k in kode if k})
    if not kode:
        return {}
    bind_varchar(cur, len(kode), max(len(k) for k in kode))
    try:
        cur.execute(  # nosec B608 — hanya placeholder yang diinterpolasi
            f"SELECT kd_user, nama FROM m_userx WHERE kd_user IN ({', '.join('?' for _ in kode)})", kode)
        return {_k(r[0]): (r[1] or "").strip() for r in cur.fetchall()}
    finally:
        cur.setinputsizes(None)


def riwayat_gabungan(profile, no: str) -> dict:
    """{arunika: [...], legacy: {...}} untuk nota `no` di `profile`.

    Legacy dibaca hanya bila index log ada (`_log_siap`); tanpa index setiap
    pencarian men-scan jutaan baris log, jadi yang tampil penjelasan, bukan
    layar yang menggantung — aturan yang sama dengan Nota Tanggal Mundur.
    """
    arunika = _jejak_arunika(profile, no)
    rentang = [(a["user"], a["log_id"]) for a in arunika if a.get("log_id")]
    legacy = {"siap": False, "pesan": "", "peristiwa": [], "barang_cocok": None}
    try:
        with mssql.report_cursor(profile, query_timeout=60) as cur:
            mssql.execute_varchar(
                cur, "SELECT tanggal, tanggal_server FROM t_penjualan WHERE no_transaksi = ?", [no])
            h = cur.fetchone()
            if not h:
                legacy["pesan"] = f"Nota {no} tidak ada di server {profile.name}."
            elif not _log_siap(profile, cur):
                legacy["pesan"] = _PESAN_LOG_BELUM
            elif not (h[0] and h[1]):
                legacy["pesan"] = "Nota ini tak punya cap waktu server, jadi lognya tak bisa dicari."
            else:
                jejak = riwayat_log.riwayat(cur, "t_penjualan", "no_transaksi", no, h[0], h[1])
                mssql.execute_varchar(
                    cur, "SELECT kd_barang, kd_satuan, kd_pegawai, jenis, qty "
                         "FROM t_penjualan_detail WHERE no_transaksi = ?", [no])
                kolom = [d[0] for d in cur.description]
                sekarang = [dict(zip(kolom, r)) for r in cur.fetchall()]
                nama = _nama_user(cur, [p["kd_user"] for p in jejak["peristiwa"]])
                for p in jejak["peristiwa"]:
                    p["user_nama"] = nama.get(_k(p["kd_user"]), "")
                    p["via_arunika"] = next(
                        (u for u, (dari, sampai) in rentang
                         if dari is not None and dari < p["log_id"] <= sampai), "")
                    p["waktu"] = p["waktu"].strftime("%Y-%m-%d %H:%M:%S") if p["waktu"] else ""
                legacy.update(siap=True, peristiwa=jejak["peristiwa"],
                              barang_cocok=riwayat_log.cocok_dengan_sekarang(
                                  jejak["barang_akhir"], sekarang, riwayat_log.DETAIL["t_penjualan"][1]))
    except pyodbc.Error as exc:
        legacy["pesan"] = mssql.friendly_error(exc, "Gagal membaca log legacy")
    return {"no": no, "koneksi": profile.name, "arunika": arunika, "legacy": legacy}

"""Edit Nota Penjualan — /admin-panel/penjualan/edit-nota (menu `edit_nota`).

Menu `tulis_kritis` + `butuh_tautan`: bawaan admin, dan ke supervisor/kasir
hanya lewat superadmin sebagai akses khusus. Jalur tulisnya ada di
`apps/transactions/edit_nota.py`; berkas ini hanya menjaga pintunya dan
mencatat jejaknya.

Tiga hal yang dijaga DI SINI, bukan di layar:

- `kd_user` pengedit dari tautan koneksi aktif (`tautan_wajib`), tak pernah dari
  kiriman layar — dan tak pernah dipinjam dari koneksi lain.
- Alasan wajib. Edit nota sesudah uangnya berpindah tangan tanpa alasan tertulis
  tak bisa diaudit siapa pun.
- Akun yang nilai uangnya disembunyikan DITOLAK utuh, seperti Laba Rugi: layar
  ini isinya harga dan total, dan menyaring per-kolom menyisakan formulir yang
  tak bisa diisi dengan benar.
"""
import pyodbc
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from inertia import defer, render

from apps.auth_app.tautan import tautan_untuk, tautan_wajib
from apps.core.http import get_data
from apps.core.models import log_activity
from apps.monitoring.views import CONN_ERROR, _active, _wajib_menu
from apps.monitoring.views_audit import riwayat_gabungan, uang_boleh as _uang_boleh
from apps.transactions import edit_nota as en
from apps.transactions import penjualan as pj
from core import mssql

URL = "/admin-panel/penjualan/edit-nota"

_DITOLAK_UANG = (
    "Edit Nota berisi harga dan total nota, dan izin melihat nilai uang tidak "
    "diberikan untuk akun Anda. Hubungi pengelola aplikasi bila Anda memang "
    "membutuhkannya."
)


def edit_nota(request):
    if (denied := _wajib_menu(request)):
        return denied
    no = (request.GET.get("no") or "").strip()
    tautan = tautan_untuk(request.user, _active())

    def muat():
        if not no:
            return {"nota": None, "pesan": "", "conn_error": None}
        profile = _active()
        if not profile:
            return {"nota": None, "pesan": "", "conn_error": CONN_ERROR}
        if not _uang_boleh(request):
            return {"nota": None, "ditolak": _DITOLAK_UANG, "conn_error": None}
        try:
            nota = en.baca_untuk_edit(profile, no)
            opsi = pj.opsi_nota(profile) if nota else {}
        except pyodbc.Error as exc:
            return {"nota": None, "pesan": "",
                    "conn_error": mssql.friendly_error(exc, "Gagal membaca nota")}
        if not nota:
            return {"nota": None, "pesan": f"Nota {no} tidak ditemukan di server ini.",
                    "conn_error": None}
        return {"nota": nota, "opsi": opsi, "pesan": "", "conn_error": None}

    return render(request, "Admin/Transaksi/EditNota", props={
        "data": defer(muat),
        "filters": {"no": no},
        "base": URL,
        "kd_user": tautan.kd_user,
        "kd_pegawai": tautan.kd_pegawai,
        "min_alasan": en.MIN_ALASAN,
    })


@require_POST
def edit_nota_save(request):
    if (denied := _wajib_menu(request)):
        return denied
    data = get_data(request)
    no = (data.get("no_transaksi") or "").strip()
    kembali = f"{URL}?no={no}" if no else URL
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect(kembali)
    if not _uang_boleh(request):
        request.session["flash_error"] = _DITOLAK_UANG
        return redirect(kembali)
    alasan = (data.get("alasan") or "").strip()
    if len(alasan) < en.MIN_ALASAN:
        request.session["flash_error"] = (
            f"Tuliskan alasan edit (minimal {en.MIN_ALASAN} huruf). Alasan ini tersimpan "
            f"di Jejak Audit bersama isi nota sebelum dan sesudahnya.")
        return redirect(kembali)

    try:
        tautan = tautan_wajib(request.user, profile)
        hasil = en.ubah_nota(
            profile, no,
            kd_user=tautan.kd_user,
            kd_pegawai_bawaan=tautan.kd_pegawai,
            perubahan={k: data[k] for k in en.KEPALA_UBAH if k in data},
            items=data.get("items") or [],
            versi_layar=(data.get("versi") or "").strip(),
        )
    except en.NotaDitolak as exc:
        # Upaya yang DITOLAK ikut dicatat: auditor ingin tahu siapa mencoba
        # mengubah nota yang sudah dicicil atau sudah ditutup bukunya.
        log_activity(request, "edit_nota_ditolak", f"Nota {no}: {exc}",
                     profile=profile, dokumen=("penjualan", no), alasan=alasan)
        request.session["flash_error"] = str(exc)
        return redirect(kembali)
    except ValueError as exc:  # tautan_wajib
        request.session["flash_error"] = str(exc)
        return redirect(kembali)
    except pyodbc.Error as exc:
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal menyimpan edit nota")
        return redirect(kembali)

    s = hasil["selisih"]
    b = s["barang"]
    # Tanpa rupiah di `detail`: kolom itu tampil di Log Aktivitas dan lonceng
    # notif tanpa penyaring uang. Totalnya ada di `data`, di balik gerbang izin.
    ringkas = (f"Nota {no} diedit — {len(b['diubah'])} baris diubah, {len(b['ditambah'])} ditambah, "
               f"{len(b['dihapus'])} dihapus, {len(s['kepala'])} isian kepala")
    log_activity(request, "edit_nota", ringkas, profile=profile, dokumen=("penjualan", no),
                 alasan=alasan, data=hasil)
    request.session["flash_success"] = (
        f"Nota {no} tersimpan. Total Rp {hasil['sesudah']['total']:,.0f}".replace(",", "."))
    return redirect(kembali)


def edit_nota_riwayat(request):
    """Riwayat nota di koneksi AKTIF — Arunika + log legacy (JSON).

    Di bawah prefix menu ini, bukan memanggil rute Jejak Audit: menu itu teknis,
    dan admin yang hanya diberi Edit Nota akan terpental dari riwayat nota yang
    sedang ia ubah sendiri.
    """
    if (denied := _wajib_menu(request)):
        return denied
    no = (request.GET.get("no") or "").strip()
    profile = _active()
    if not no:
        return JsonResponse({"error": "Nomor nota tidak disebutkan."}, status=400)
    if not profile:
        return JsonResponse({"error": CONN_ERROR}, status=503)
    if not _uang_boleh(request):
        return JsonResponse({"error": _DITOLAK_UANG}, status=403)
    return JsonResponse(riwayat_gabungan(profile, no))

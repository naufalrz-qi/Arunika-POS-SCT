"""Halaman harian kasir & supervisor (prefix /kasir).

Terpisah dari views.py bukan karena rapi-rapian: penjaga di apps/core/middleware.py
memperlakukan /kasir berbeda dari /admin-panel (tanpa syarat Tailscale), jadi
memisahkan berkasnya membuat batas itu terlihat saat membaca kode.
"""
import pyodbc
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from inertia import defer, render

from apps.core.http import get_data
from apps.core.models import log_activity
from apps.inventory import services as inv
from apps.transactions import penjualan as pj
from apps.monitoring.views import CONN_ERROR, _active, _hidden_fields
from core import mssql


def cek_stok(request):
    """Cari barang lalu lihat stok + harganya. Hanya baca."""
    cari = (request.GET.get("cari") or "").strip()
    kd_divisi = (request.GET.get("kd_divisi") or "").strip()

    def muat():
        rows, divisi_list, conn_error = [], [], None
        profile = _active()
        if not profile:
            return {"rows": [], "divisi_list": [], "conn_error": CONN_ERROR}
        try:
            divisi_list = inv.list_divisi(profile)
            rows = inv.cek_stok(profile, cari, kd_divisi=kd_divisi or None)
        except pyodbc.Error as exc:
            conn_error = mssql.friendly_error(exc, "Gagal membaca stok")

        # Kasir umumnya tak boleh melihat modal. Penjagaannya HARUS di sini —
        # membuang kolomnya di Vue hanya kosmetik.
        buang = _hidden_fields(request)
        if buang:
            rows = [{k: v for k, v in r.items() if k not in buang} for r in rows]
        return {"rows": rows, "divisi_list": divisi_list, "conn_error": conn_error}

    return render(
        request,
        "Kasir/CekStok",
        props={"stok": defer(muat), "filters": {"cari": cari, "kd_divisi": kd_divisi}},
    )


def penjualan(request):
    """Layar buat nota penjualan."""
    cari = (request.GET.get("cari") or "").strip()

    def muat():
        profile = _active()
        if not profile:
            return {"opsi": {}, "hasil_cari": [], "conn_error": CONN_ERROR}
        try:
            return {
                "opsi": pj.opsi_nota(profile),
                "hasil_cari": pj.cari_barang(profile, cari),
                "conn_error": None,
            }
        except pyodbc.Error as exc:
            return {"opsi": {}, "hasil_cari": [],
                    "conn_error": mssql.friendly_error(exc, "Gagal membaca data nota")}

    return render(request, "Kasir/Penjualan", props={
        "nota": defer(muat),
        "filters": {"cari": cari},
        # Ditampilkan di layar supaya kasir tahu nota akan tercatat atas nama
        # siapa — dan tahu sejak awal kalau akunnya belum ditautkan.
        "kd_user": request.user.kd_user,
        "kd_divisi": request.user.kd_divisi,
    })


@require_POST
def penjualan_save(request):
    data = get_data(request)
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/kasir/penjualan")
    try:
        hasil = pj.buat_nota(
            profile,
            kd_user=request.user.kd_user,
            # kd_divisi dari AKUN, tidak pernah dari kiriman layar: ia menentukan
            # awalan nomor nota dan milik cabang mana nota itu tercatat.
            kd_divisi=request.user.kd_divisi,
            kd_customer=data.get("kd_customer"),
            kd_jenis=data.get("kd_jenis"),
            kd_kas=data.get("kd_kas"),
            kd_voucher=data.get("kd_voucher"),
            kd_pegawai=data.get("kd_pegawai"),
            items=data.get("items") or [],
            keterangan=data.get("keterangan") or pj.KOSONG,
            diskon_uang=float(data.get("diskon_uang") or 0),
            pajak=float(data.get("pajak") or 0),
            status=int(data.get("status") or 1),
        )
    except ValueError as exc:
        request.session["flash_error"] = str(exc)
        return redirect("/kasir/penjualan")
    except (pyodbc.Error, RuntimeError) as exc:
        request.session["flash_error"] = (
            str(exc) if isinstance(exc, RuntimeError)
            else mssql.friendly_error(exc, "Gagal menyimpan nota"))
        return redirect("/kasir/penjualan")

    log_activity(request, "penjualan",
                 f"Nota {hasil['no_transaksi']} — {hasil['baris']} baris, total {hasil['total']:.0f}")
    request.session["flash_success"] = (
        f"Nota {hasil['no_transaksi']} tersimpan. Total Rp {hasil['total']:,.0f}".replace(",", "."))
    return redirect("/kasir/penjualan")

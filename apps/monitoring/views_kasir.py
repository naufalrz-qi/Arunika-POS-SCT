"""Halaman harian kasir & supervisor (prefix /kasir).

Terpisah dari views.py bukan karena rapi-rapian: penjaga di apps/core/middleware.py
memperlakukan /kasir berbeda dari /admin-panel (tanpa syarat Tailscale), jadi
memisahkan berkasnya membuat batas itu terlihat saat membaca kode.
"""
import pyodbc
from inertia import defer, render

from apps.inventory import services as inv
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

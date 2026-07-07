"""Connection Manager (PRD §7.2) — real ServerProfile CRUD + encrypted passwords."""
import pyodbc
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from inertia import render

from apps.core.http import get_data
from apps.core.models import log_activity
from apps.transactions import indexes
from core import mssql

from .models import ConnStatus, DbType, ServerProfile


def connections_index(request):
    profiles = [p.as_dict() for p in ServerProfile.objects.all()]
    return render(
        request,
        "Admin/Connections/Index",
        props={"connections": profiles, "db_types": [t.value for t in DbType]},
    )


def _apply_form(profile, data):
    profile.name = (data.get("name") or "").strip()
    profile.db_type = data.get("db_type") or DbType.GROSIR
    profile.host = (data.get("host") or "").strip()
    profile.port = int(data.get("port") or 1433)
    profile.db_name = (data.get("db_name") or "").strip()
    profile.username = (data.get("username") or "").strip()
    # Retail: acuan modal (server grosir/gudang). Non-retail: selalu kosong.
    profile.cost_source_id = (data.get("cost_source") or None) if profile.db_type == DbType.RETAIL else None
    # Replica opsional untuk baca laporan (disinkron via CDC, apps/transactions/cdc_sync.py).
    # Berlaku untuk semua tipe db, bukan cuma retail.
    profile.report_source_id = data.get("report_source") or None
    password = data.get("password") or ""
    if password:  # keep existing password if left blank on edit
        profile.set_password(password)


def connections_save(request):
    data = get_data(request)
    conn_id = data.get("id")
    profile = get_object_or_404(ServerProfile, pk=conn_id) if conn_id else ServerProfile()
    _apply_form(profile, data)
    if profile.db_type == DbType.RETAIL and not profile.cost_source_id:
        request.session["flash_error"] = "Server retail wajib memilih Sumber Modal (grosir/gudang)."
        return redirect("/admin-panel/connections")
    profile.save()
    from apps.transactions.indexes import ensure_indexes_async
    ensure_indexes_async(profile)  # PRD §9 — build registry indexes on registration
    log_activity(request, "konfigurasi", f"Simpan koneksi {profile.name}")
    request.session["flash_success"] = "Profil koneksi disimpan."
    return redirect("/admin-panel/connections")


def connections_delete(request, conn_id):
    profile = get_object_or_404(ServerProfile, pk=conn_id)
    name = profile.name
    profile.delete()
    log_activity(request, "konfigurasi", f"Hapus koneksi {name}")
    request.session["flash_success"] = "Profil koneksi dihapus."
    return redirect("/admin-panel/connections")


def connections_set_default(request, conn_id):
    profile = get_object_or_404(ServerProfile, pk=conn_id)
    profile.make_default()
    log_activity(request, "konfigurasi", f"Set default {profile.db_type}: {profile.name}")
    request.session["flash_success"] = "Koneksi default diperbarui."
    data = get_data(request)
    redirect_to = data.get("redirect_to") or "/admin-panel/connections"
    return redirect(redirect_to)


def connections_test(request, conn_id):
    """Ping a saved profile and cache the result on the row."""
    profile = get_object_or_404(ServerProfile, pk=conn_id)
    result = mssql.test_profile(profile)
    profile.last_status = ConnStatus.ONLINE if result["ok"] else ConnStatus.OFFLINE
    profile.last_checked = timezone.now()
    profile.save(update_fields=["last_status", "last_checked"])
    return JsonResponse({"id": conn_id, **result})


def connections_check_indexes(request, conn_id):
    """Manually re-run the index registry on a saved profile, on demand.

    Complements the automatic build on activation/registration (PRD §9,
    `ensure_indexes_async`) — this gives an immediate, visible per-index
    result instead of waiting on the background thread + ActivityLog.
    """
    profile = get_object_or_404(ServerProfile, pk=conn_id)
    try:
        failed, results = indexes.ensure_indexes(profile)
    except pyodbc.Error as exc:
        return JsonResponse(
            {"id": conn_id, "ok": False, "results": [], "error": str(exc.args[-1] if exc.args else exc)},
            status=502,
        )
    log_activity(request, "konfigurasi", f"Cek indexing {profile.name}")
    return JsonResponse({"id": conn_id, "ok": not failed, "results": results})

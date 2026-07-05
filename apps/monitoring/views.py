"""Admin panel views — wired to real data (MS SQL via services, SQLite via models)."""
import datetime as dt

import pyodbc
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from inertia import defer, render

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.http import get_data
from apps.core.menus import assignable_menus
from apps.core.models import ActivityLog, log_activity
from apps.inventory import services as inv
from apps.master_data import services as master
from apps.transactions import services as tx
from apps.core import reporting
from apps.transactions import reports as rpt
from core import mssql


def _parse_date(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d") if s else None
    except ValueError:
        return None


def _eod(d):
    """End-of-day so an as-of date includes that whole day's transactions."""
    return d.replace(hour=23, minute=59, second=59) if d else None

CONN_ERROR = "Tidak ada koneksi aktif, atau server tidak dapat dihubungi. Pilih koneksi di navbar."


def _active():
    return mssql.get_active_profile()


# --- Dashboard -------------------------------------------------------------

def dashboard(request):
    # Deferred: bundle servers + summary + activity so shell renders instantly.
    def load_dashboard():
        servers = [
            {"id": p.id, "name": p.name, "host": f"{p.host}:{p.port}", "status": p.last_status}
            for p in ServerProfile.objects.all()
        ]
        recent = [
            {
                "id": a.id,
                "user": a.username or "—",
                "action": a.action,
                "detail": a.detail,
                "time": a.timestamp.strftime("%Y-%m-%d %H:%M"),
            }
            for a in ActivityLog.objects.all()[:8]
        ]

        profile = _active()
        summary = {"total_transactions": 0, "total_items": 0, "revenue": 0, "hourly_transactions": []}
        conn_error = None
        if profile:
            try:
                summary = tx.dashboard_summary(profile)
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca transaksi: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR

        online = sum(1 for s in servers if s["status"] == "online")
        return {
            "servers": servers,
            "stats": {
                "total_transactions": summary["total_transactions"],
                "total_items": summary["total_items"],
                "revenue": summary["revenue"],
                "servers_online": online,
                "servers_total": len(servers),
            },
            "hourly_transactions": summary["hourly_transactions"],
            "recent_activity": recent,
            "conn_error": conn_error,
        }

    return render(
        request,
        "Admin/Dashboard",
        props={"dashboard": defer(load_dashboard)},
    )


# --- Users (real) ----------------------------------------------------------

def _user_dict(u):
    return {
        "id": u.id,
        "username": u.username,
        "name": u.get_full_name() or u.username,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.date_joined.strftime("%Y-%m-%d"),
    }


def users_index(request):
    users = User.objects.filter(role__in=[Role.KASIR, Role.SUPERVISOR]).order_by("username")
    return render(request, "Admin/Users/Index", props={"users": [_user_dict(u) for u in users]})


def users_save(request):
    data = get_data(request)
    user_id = data.get("id")
    name = (data.get("name") or "").strip()
    first, _, last = name.partition(" ")
    fields = {
        "first_name": first,
        "last_name": last,
        "role": data.get("role") or Role.KASIR,
    }
    if user_id:
        user = get_object_or_404(User, pk=user_id)
        for k, v in fields.items():
            setattr(user, k, v)
    else:
        user = User(username=(data.get("username") or "").strip(), **fields)

    password = data.get("password")
    if password:
        user.set_password(password)
    elif not user_id:
        user.set_password("kasir123")  # default for new accounts
    user.save()

    log_activity(request, "user", f"Simpan user {user.username}")
    request.session["flash_success"] = "Data user disimpan."
    return redirect("/admin-panel/users")


def users_delete(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    user.is_active = False
    user.save(update_fields=["is_active"])
    log_activity(request, "user", f"Nonaktifkan user {user.username}")
    request.session["flash_success"] = "User dinonaktifkan."
    return redirect("/admin-panel/users")


# --- Master: produk (read-only) -------------------------------------------

def products_index(request):
    search = request.GET.get("search", "")
    kd_kategori = request.GET.get("kd_kategori", "")
    profile = _active()
    products, categories, conn_error = [], [], None
    if profile:
        try:
            products = master.list_products(profile, search, kd_kategori)
            categories = master.list_categories(profile)
        except pyodbc.Error as exc:
            conn_error = f"Gagal membaca master produk: {exc.args[-1] if exc.args else exc}"
    else:
        conn_error = CONN_ERROR
    return render(
        request,
        "Admin/MasterData/Products",
        props={"products": products, "categories": categories, "conn_error": conn_error},
    )


def products_save(request):
    # Write to legacy m_barang deferred (PRD §7.3 write) — read-only phase.
    request.session["flash_error"] = "Tulis ke master produk belum aktif di fase ini."
    return redirect("/admin-panel/master/products")


# --- Master: pelanggan (read-only) ----------------------------------------

def customers_index(request):
    search = request.GET.get("search", "")
    profile = _active()
    customers, conn_error = [], None
    if profile:
        try:
            customers = master.list_customers(profile, search)
        except pyodbc.Error as exc:
            conn_error = f"Gagal membaca master pelanggan: {exc.args[-1] if exc.args else exc}"
    else:
        conn_error = CONN_ERROR
    return render(
        request,
        "Admin/MasterData/Customers",
        props={"customers": customers, "conn_error": conn_error},
    )


def suppliers_index(request):
    profile = _active()
    suppliers, conn_error = [], None
    if profile:
        try:
            with mssql.cursor(profile) as cur:
                cur.execute(
                    "SELECT kd_supplier, nama, alamat, kota, telepon, flag_aktif FROM m_supplier ORDER BY nama"
                )
                suppliers = reporting.dictify(cur)
                suppliers = reporting.clean_rows(suppliers)
        except pyodbc.Error as exc:
            conn_error = f"Gagal membaca supplier: {exc.args[-1] if exc.args else exc}"
    else:
        conn_error = CONN_ERROR
    return render(
        request,
        "Admin/MasterData/Supplier",
        props={"suppliers": suppliers, "conn_error": conn_error},
    )


def sync_history_index(request):
    def load_sync():
        # Query ActivityLog for sync operations
        syncs = []
        conn_error = None
        try:
            logs = ActivityLog.objects.filter(action="sync").order_by("-timestamp")[:100]
            syncs = [
                {
                    "id": a.id,
                    "created_at": a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "user": a.username or "—",
                    "src": "source",  # placeholder
                    "dst": "target",  # placeholder
                    "mode": "full",  # placeholder
                    "total_items": 0,  # placeholder
                    "status": "ok",  # placeholder
                    "detail": a.detail or "",
                }
                for a in logs
            ]
        except Exception as exc:
            conn_error = f"Gagal membaca riwayat sync: {str(exc)}"
        return {"rows": syncs, "conn_error": conn_error}

    return render(
        request,
        "Admin/MasterData/SyncHistory",
        props={"data": defer(load_sync)},
    )


def customers_save(request):
    request.session["flash_error"] = "Tulis ke master pelanggan belum aktif di fase ini."
    return redirect("/admin-panel/master/customers")


# --- Update Barang (WRITE ke MS SQL legacy) --------------------------------

def update_barang_index(request):
    # Ikut koneksi aktif (dipilih di navbar) — tidak ada pemilihan server terpisah.
    profile = _active()
    search = request.GET.get("search", "")

    items, conn_error = [], None
    if profile:
        try:
            items = master.list_barang_edit(profile, search)
        except pyodbc.Error as exc:
            conn_error = f"Gagal membaca barang: {exc.args[-1] if exc.args else exc}"
    else:
        conn_error = CONN_ERROR

    return render(
        request,
        "Admin/MasterData/UpdateBarang",
        props={
            "active": profile.as_dict() if profile else None,
            "profile_type": profile.db_type if profile else None,
            "items": items,
            "filters": {"search": search},
            "conn_error": conn_error,
        },
    )


def _redirect_update_barang(profile):
    return redirect("/admin-panel/master/update-barang")


def update_barang_harga(request):
    data = get_data(request)
    profile = get_object_or_404(ServerProfile, pk=data.get("profile"))
    kd_barang = (data.get("kd_barang") or "").strip()
    prices = data.get("prices") or {}  # {kd_satuan: harga_jual}
    try:
        n = master.update_harga(profile, kd_barang, prices)
        log_activity(request, "barang", f"Update harga {kd_barang} ({profile.name}): {n} satuan")
        request.session["flash_success"] = f"Harga {kd_barang} diperbarui ({n} satuan)."
    except pyodbc.Error as exc:
        request.session["flash_error"] = f"Gagal update harga: {exc.args[-1] if exc.args else exc}"
    return _redirect_update_barang(profile)


def update_barang_status(request):
    data = get_data(request)
    profile = get_object_or_404(ServerProfile, pk=data.get("profile"))
    kd_barang = (data.get("kd_barang") or "").strip()
    table = data.get("table") or ""
    status = data.get("status")
    kd_divisi = data.get("kd_divisi") or None
    try:
        master.update_status(profile, kd_barang, table, status, kd_divisi)
        log_activity(request, "barang", f"Update status {table} {kd_barang} -> {status} ({profile.name})")
        request.session["flash_success"] = f"Status ({table}) untuk {kd_barang} diperbarui."
    except (pyodbc.Error, ValueError) as exc:
        request.session["flash_error"] = f"Gagal update status: {exc}"
    return _redirect_update_barang(profile)


# --- Sinkronisasi Harga antar-server ---------------------------------------

def sync_harga_index(request):
    profiles = [p.as_dict() for p in ServerProfile.objects.all()]
    mode = request.GET.get("mode", "gudang_grosir")
    src = ServerProfile.objects.filter(pk=request.GET.get("src")).first() if request.GET.get("src") else None
    dst = ServerProfile.objects.filter(pk=request.GET.get("dst")).first() if request.GET.get("dst") else None

    diff, conn_error = [], None
    if src and dst:
        try:
            diff = master.compare_harga_jual(src, dst)
        except pyodbc.Error as exc:
            conn_error = f"Gagal membandingkan harga: {exc.args[-1] if exc.args else exc}"

    return render(
        request,
        "Admin/MasterData/SyncHarga",
        props={
            "profiles": profiles,
            "mode": mode,
            "src": src.id if src else None,
            "dst": dst.id if dst else None,
            "diff": diff,
            "conn_error": conn_error,
        },
    )


def sync_harga_apply(request):
    data = get_data(request)
    src = get_object_or_404(ServerProfile, pk=data.get("src"))
    dst = get_object_or_404(ServerProfile, pk=data.get("dst"))
    keys = data.get("keys") or []
    with_margin = bool(data.get("with_margin"))
    mode = data.get("mode", "gudang_grosir")
    try:
        n = master.sync_harga_jual(src, dst, keys, with_margin=with_margin)
        log_activity(request, "sync_harga", f"Sync harga {src.name} -> {dst.name}: {n} baris")
        request.session["flash_success"] = f"Sinkronisasi selesai: {n} baris diperbarui."
    except pyodbc.Error as exc:
        request.session["flash_error"] = f"Gagal sinkron: {exc.args[-1] if exc.args else exc}"
    return redirect(f"/admin-panel/master/sync-harga?mode={mode}&src={src.id}&dst={dst.id}")


# --- Logs ------------------------------------------------------------------

def logs_index(request):
    logs = [
        {
            "id": a.id,
            "user": a.username or "—",
            "action": a.action,
            "detail": a.detail,
            "ip_address": a.ip_address or "",
            "timestamp": a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for a in ActivityLog.objects.all()[:300]
    ]
    action_types = sorted({a["action"] for a in logs})
    users = sorted({a["user"] for a in logs if a["user"] != "—"})
    return render(
        request,
        "Admin/ActivityLogs",
        props={"logs": logs, "action_types": action_types, "users": users},
    )


# --- Monitoring Stok (computed from movement card, table-level) ------------

def stock_index(request):
    kd_divisi = request.GET.get("kd_divisi", "")
    tanggal = _parse_date(request.GET.get("tanggal")) or dt.datetime.now()

    # Deferred: the shell renders instantly, Inertia fetches this bundle right
    # after mount (the stock computation takes seconds on real servers).
    def load_stok():
        profile = _active()
        levels, divisi_list, conn_error = [], [], None
        if profile:
            try:
                divisi_list = inv.list_divisi(profile)
                levels = inv.stok_akhir_per_tanggal(
                    profile,
                    tanggal=_eod(tanggal),
                    kd_divisi=kd_divisi or None,
                )
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca stok: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR
        return {"levels": levels, "divisi_list": divisi_list, "conn_error": conn_error}

    return render(
        request,
        "Admin/Inventory/Stock",
        props={
            "stok": defer(load_stok),
            "filters": {
                "kd_divisi": kd_divisi,
                "tanggal": request.GET.get("tanggal", ""),
            },
        },
    )


def barang_histori_index(request):
    kd_barang = request.GET.get("kd_barang", "").strip()
    kd_divisi = request.GET.get("kd_divisi", "")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))

    def load_histori():
        profile = _active()
        rows, divisi_list, conn_error = [], [], None
        if profile:
            try:
                divisi_list = inv.list_divisi(profile)
                rows = inv.barang_histori(
                    profile,
                    kd_barang=kd_barang or None,
                    kd_divisi=kd_divisi or None,
                    date_from=date_from,
                    date_to=_eod(date_to),
                )
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca histori: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR

        return {
            "rows": rows,
            "divisi_list": divisi_list,
            "conn_error": conn_error,
        }

    return render(
        request,
        "Admin/Inventory/BarangHistori",
        props={
            "histori": defer(load_histori),
            "filters": {
                "kd_barang": kd_barang,
                "kd_divisi": kd_divisi,
                "date_from": request.GET.get("date_from", ""),
                "date_to": request.GET.get("date_to", ""),
            },
        },
    )


# --- Kelola Menu (superadmin only) -----------------------------------------

def _deny_non_superadmin(request):
    if request.user.role != Role.SUPERADMIN:
        return HttpResponseForbidden("403 Forbidden — khusus Superadmin.")
    return None


def menus_index(request):
    if (denied := _deny_non_superadmin(request)):
        return denied
    users = User.objects.exclude(role=Role.SUPERADMIN).order_by("role", "username")
    return render(
        request,
        "Admin/Menus/Index",
        props={
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "name": u.get_full_name() or u.username,
                    "role": u.role,
                    "allowed_menu_keys": u.allowed_menu_keys or [],
                }
                for u in users
            ],
            "menus": assignable_menus(),
        },
    )


def menus_save(request):
    if (denied := _deny_non_superadmin(request)):
        return denied
    data = get_data(request)
    user = get_object_or_404(User, pk=data.get("user_id"))
    if user.role == Role.SUPERADMIN:
        return HttpResponseForbidden("Superadmin tidak dapat dibatasi.")
    valid = {m["key"] for m in assignable_menus()}
    keys = [k for k in (data.get("menu_keys") or []) if k in valid]
    user.allowed_menu_keys = keys
    user.save(update_fields=["allowed_menu_keys"])
    log_activity(request, "menu", f"Set menu {user.username}: {','.join(keys) or '(kosong)'}")
    request.session["flash_success"] = f"Menu untuk {user.username} diperbarui."
    return redirect("/admin-panel/menus")


# --- Laporan & fitur baru ---------------------------------------------------
# --- Server-side report plumbing (PRD §6) ---------------------------------

def _opt_divisi(profile):
    return reporting.opt(inv.list_divisi(profile), "kd_divisi", "nama")


def _opt_master(profile, sql):
    with mssql.cursor(profile) as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return reporting.opt(rows, cols[0], cols[1])


def _opt_customer(profile):
    return _opt_master(profile, "SELECT TOP 1000 kd_customer, nama FROM m_customer WHERE status = 1 ORDER BY nama")


def _opt_supplier(profile):
    return _opt_master(profile, "SELECT TOP 1000 kd_supplier, nama FROM m_supplier ORDER BY nama")


def _opt_kas(profile):
    return _opt_master(profile, "SELECT kd_kas, keterangan FROM m_kas WHERE status <> 0 ORDER BY keterangan")


def _spec_params(request, spec):
    f = reporting.parse_report_params(request, spec["sorts"], spec["default_sort"])
    for k in spec.get("filter_keys", []):
        f[k] = (request.GET.get(k) or "").strip()
    return f


def _spec_filters(f, spec):
    filters = {
        "date_from": f["date_from_s"], "date_to": f["date_to_s"],
        "search": f["search"], "sort": f["sort"], "sort_dir": f["sort_dir"],
        "page": f["page"], "per_page": f["per_page"],
    }
    for k in spec.get("filter_keys", []):
        filters[k] = f[k]
    return filters


def _report_view(spec):
    def view(request):
        f = _spec_params(request, spec)

        def load_report():
            rows, total, summary, options, conn_error = [], 0, {}, {}, None
            profile = _active()
            if profile:
                try:
                    inner, params = spec["inner"](f)
                    with mssql.cursor(profile) as cur:
                        rows, total = reporting.run_paged(cur, inner, params, f)
                        cur.execute(f"SELECT {spec['summary']} FROM ({inner}) AS q", params)
                        summary = reporting.clean_rows(reporting.dictify(cur))[0]
                    if spec.get("options"):
                        options = spec["options"](profile)
                except pyodbc.Error as exc:
                    conn_error = f"Gagal membaca laporan: {exc.args[-1] if exc.args else exc}"
            else:
                conn_error = CONN_ERROR
            if f["warning"]:
                conn_error = f["warning"] if not conn_error else f"{conn_error} {f['warning']}"
            return {"rows": rows, "total": total, "summary": summary,
                    "options": options, "conn_error": conn_error}

        return render(request, spec["component"],
                      props={"report": defer(load_report), "filters": _spec_filters(f, spec)})

    return view


def _report_export(spec):
    def view(request):
        f = _spec_params(request, spec)
        profile = _active()
        if not profile:
            request.session["flash_error"] = CONN_ERROR
            return redirect(spec["url"])
        try:
            inner, params = spec["inner"](f)
            with mssql.cursor(profile) as cur:
                rows = reporting.run_all(cur, inner, params, f)
        except pyodbc.Error as exc:
            request.session["flash_error"] = f"Gagal export: {exc.args[-1] if exc.args else exc}"
            return redirect(spec["url"])
        log_activity(request, "export", f"Export {spec['filename']}: {len(rows)} baris")
        return reporting.xlsx_response(spec["filename"], spec["columns"], rows)

    return view


# Penjualan
_PENJUALAN_ALL = {
    "component": "Admin/Reports/PenjualanAll",
    "url": "/admin-panel/laporan/penjualan",
    "inner": rpt.penjualan_detail,
    "sorts": rpt.SORTS_PENJUALAN_DETAIL,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PENJUALAN_DETAIL,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-detail",
    "columns": [
        {"key": "no_transaksi", "label": "No. Transaksi"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "customer", "label": "Customer"},
        {"key": "barang", "label": "Barang"},
        {"key": "qty", "label": "Qty"},
        {"key": "harga", "label": "Harga"},
        {"key": "subtotal", "label": "Subtotal"},
    ],
}
penjualan_all = _report_view(_PENJUALAN_ALL)
penjualan_all_export = _report_export(_PENJUALAN_ALL)
_PENJUALAN_NOTA = {
    "component": "Admin/Reports/PenjualanNota",
    "url": "/admin-panel/laporan/penjualan-nota",
    "inner": rpt.penjualan_nota,
    "sorts": rpt.SORTS_PENJUALAN_NOTA,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PENJUALAN_NOTA,
    "filter_keys": ["kd_divisi", "kd_customer"],
    "options": lambda p: {"divisi": _opt_divisi(p), "customer": _opt_customer(p)},
    "filename": "penjualan-nota",
    "columns": [{"key": "no_transaksi", "label": "No. Nota"}, {"key": "tanggal", "label": "Tanggal"}, {"key": "customer", "label": "Customer"}, {"key": "total_kotor", "label": "Total Kotor"}, {"key": "potongan", "label": "Potongan"}, {"key": "pajak", "label": "Pajak"}, {"key": "total_bersih", "label": "Total Bersih"}],
}
penjualan_nota = _report_view(_PENJUALAN_NOTA)
penjualan_nota_export = _report_export(_PENJUALAN_NOTA)

_PENJUALAN_CUSTOMER = {
    "component": "Admin/Reports/PenjualanCustomer",
    "url": "/admin-panel/laporan/penjualan-customer",
    "inner": rpt.penjualan_customer,
    "sorts": rpt.SORTS_PENJUALAN_CUSTOMER,
    "default_sort": "total",
    "summary": rpt.SUMMARY_PENJUALAN_CUSTOMER,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-customer",
    "columns": [{"key": "customer", "label": "Customer"}, {"key": "jml_nota", "label": "Jml Nota"}, {"key": "total", "label": "Total"}],
}
penjualan_customer = _report_view(_PENJUALAN_CUSTOMER)
penjualan_customer_export = _report_export(_PENJUALAN_CUSTOMER)

_PENJUALAN_USER = {
    "component": "Admin/Reports/PenjualanUser",
    "url": "/admin-panel/laporan/penjualan-user",
    "inner": rpt.penjualan_user,
    "sorts": rpt.SORTS_PENJUALAN_USER,
    "default_sort": "total",
    "summary": rpt.SUMMARY_PENJUALAN_USER,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-user",
    "columns": [{"key": "user", "label": "User / Kasir"}, {"key": "jml_nota", "label": "Jml Nota"}, {"key": "total", "label": "Total"}],
}
penjualan_user = _report_view(_PENJUALAN_USER)
penjualan_user_export = _report_export(_PENJUALAN_USER)

_PENJUALAN_PERIODE = {
    "component": "Admin/Reports/PenjualanPeriode",
    "url": "/admin-panel/laporan/penjualan-periode",
    "inner": rpt.penjualan_periode,
    "sorts": rpt.SORTS_PENJUALAN_PERIODE,
    "default_sort": "total",
    "summary": rpt.SUMMARY_PENJUALAN_PERIODE,
    "filter_keys": ["kd_divisi", "granularitas"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-periode",
    "columns": [{"key": "periode", "label": "Periode"}, {"key": "jml_nota", "label": "Jml Nota"}, {"key": "total", "label": "Total"}],
}
penjualan_periode = _report_view(_PENJUALAN_PERIODE)
penjualan_periode_export = _report_export(_PENJUALAN_PERIODE)

_RETUR_PENJUALAN = {
    "component": "Admin/Reports/ReturPenjualan",
    "url": "/admin-panel/laporan/retur-penjualan",
    "inner": rpt.retur_penjualan,
    "sorts": rpt.SORTS_RETUR_PENJUALAN,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_RETUR_PENJUALAN,
    "filter_keys": ["kd_divisi", "kd_customer"],
    "options": lambda p: {"divisi": _opt_divisi(p), "customer": _opt_customer(p)},
    "filename": "retur-penjualan",
    "columns": [{"key": "no_retur", "label": "No. Retur"}, {"key": "tanggal", "label": "Tanggal"}, {"key": "customer", "label": "Customer"}, {"key": "barang", "label": "Barang"}, {"key": "qty", "label": "Qty"}, {"key": "nilai", "label": "Nilai"}],
}
retur_penjualan = _report_view(_RETUR_PENJUALAN)
retur_penjualan_export = _report_export(_RETUR_PENJUALAN)

# Pembelian
_PEMBELIAN = {
    "component": "Admin/Reports/Pembelian",
    "url": "/admin-panel/laporan/pembelian",
    "inner": rpt.pembelian,
    "sorts": rpt.SORTS_PEMBELIAN,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PEMBELIAN,
    "filter_keys": ["kd_divisi", "kd_supplier"],
    "options": lambda p: {"divisi": _opt_divisi(p), "supplier": _opt_supplier(p)},
    "filename": "pembelian",
    "columns": [{"key": "no_transaksi", "label": "No. Transaksi"}, {"key": "tanggal", "label": "Tanggal"}, {"key": "supplier", "label": "Supplier"}, {"key": "barang", "label": "Barang"}, {"key": "qty", "label": "Qty"}, {"key": "harga", "label": "Harga Beli"}, {"key": "subtotal", "label": "Subtotal"}],
}
pembelian = _report_view(_PEMBELIAN)
pembelian_export = _report_export(_PEMBELIAN)

_RETUR_PEMBELIAN = {
    "component": "Admin/Reports/ReturPembelian",
    "url": "/admin-panel/laporan/retur-pembelian",
    "inner": rpt.retur_pembelian,
    "sorts": rpt.SORTS_RETUR_PEMBELIAN,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_RETUR_PEMBELIAN,
    "filter_keys": ["kd_divisi", "kd_supplier"],
    "options": lambda p: {"divisi": _opt_divisi(p), "supplier": _opt_supplier(p)},
    "filename": "retur-pembelian",
    "columns": [{"key": "no_retur", "label": "No. Retur"}, {"key": "tanggal", "label": "Tanggal"}, {"key": "supplier", "label": "Supplier"}, {"key": "barang", "label": "Barang"}, {"key": "qty", "label": "Qty"}, {"key": "nilai", "label": "Nilai"}],
}
retur_pembelian = _report_view(_RETUR_PEMBELIAN)
retur_pembelian_export = _report_export(_RETUR_PEMBELIAN)
# Inventori — real services, deferred
def stok_divisi(request):
    kd_divisi = request.GET.get("kd_divisi", "")
    date_from = _parse_date(request.GET.get("date_from")) or dt.datetime.now() - dt.timedelta(days=30)
    date_to = _parse_date(request.GET.get("date_to")) or dt.datetime.now()

    def load():
        profile = _active()
        rows, divisi_list, conn_error = [], [], None
        if profile:
            try:
                divisi_list = inv.list_divisi(profile)
                rows = inv.stock_levels(
                    profile,
                    kd_divisi=kd_divisi or None,
                    date_from=date_from,
                    date_to=_eod(date_to),
                )
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca stok divisi: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "divisi_list": divisi_list, "conn_error": conn_error}

    return render(
        request,
        "Admin/Inventory/StokDivisi",
        props={
            "data": defer(load),
            "filters": {
                "kd_divisi": kd_divisi,
                "date_from": request.GET.get("date_from", ""),
                "date_to": request.GET.get("date_to", ""),
            },
        },
    )

def stok_akhir(request):
    tanggal = _parse_date(request.GET.get("tanggal")) or dt.datetime.now()

    def load():
        profile = _active()
        rows, conn_error = [], None
        if profile:
            try:
                rows = inv.stok_akhir_per_tanggal(profile, tanggal=_eod(tanggal))
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca stok akhir: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "conn_error": conn_error}

    return render(
        request,
        "Admin/Inventory/StokAkhir",
        props={
            "data": defer(load),
            "filters": {"tanggal": request.GET.get("tanggal", "")},
        },
    )
_OPNAME = {
    "component": "Admin/Inventory/Opname",
    "url": "/admin-panel/inventory/opname",
    "inner": rpt.opname,
    "sorts": rpt.SORTS_OPNAME,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_OPNAME,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "opname",
    "columns": [{"key": "no_transaksi", "label": "No. Opname"}, {"key": "tanggal", "label": "Tanggal", "format": "date"}, {"key": "divisi", "label": "Divisi"}, {"key": "kd_barang", "label": "Kd. Barang"}, {"key": "barang", "label": "Barang"}, {"key": "qty_sistem", "label": "Qty Sistem", "format": "number"}, {"key": "qty_fisik", "label": "Qty Fisik", "format": "number"}, {"key": "diferensi", "label": "Diferensi", "format": "number"}],
}
opname = _report_view(_OPNAME)
opname_export = _report_export(_OPNAME)

# Promo & Voucher
_PROMO = {
    "component": "Admin/Promo/Promo",
    "url": "/admin-panel/promo/diskon",
    "inner": rpt.promo,
    "sorts": rpt.SORTS_PROMO,
    "default_sort": "tanggal_awal",
    "summary": rpt.SUMMARY_PROMO,
    "filter_keys": [],
    "options": lambda p: {},
    "filename": "promo",
    "columns": [{"key": "kd_promo", "label": "Kode Promo"}, {"key": "divisi", "label": "Divisi"}, {"key": "barang", "label": "Barang"}, {"key": "harga_promo", "label": "Harga Promo", "format": "rupiah"}, {"key": "tanggal_awal", "label": "Tanggal Awal", "format": "date"}, {"key": "tanggal_akhir", "label": "Tanggal Akhir", "format": "date"}, {"key": "status", "label": "Status"}],
}
promo = _report_view(_PROMO)
promo_export = _report_export(_PROMO)

_VOUCHER = {
    "component": "Admin/Promo/Voucher",
    "url": "/admin-panel/promo/voucher",
    "inner": rpt.voucher,
    "sorts": rpt.SORTS_VOUCHER,
    "default_sort": "kd_voucher",
    "summary": rpt.SUMMARY_VOUCHER,
    "filter_keys": [],
    "options": lambda p: {},
    "filename": "voucher",
    "columns": [{"key": "kd_voucher", "label": "Kode Voucher"}, {"key": "nama", "label": "Nama"}, {"key": "nominal", "label": "Nominal", "format": "rupiah"}, {"key": "dipakai", "label": "Dipakai"}, {"key": "nilai_dipakai", "label": "Nilai Dipakai", "format": "rupiah"}, {"key": "status", "label": "Status"}],
}
voucher = _report_view(_VOUCHER)
voucher_export = _report_export(_VOUCHER)

# Analitik
_FMI_PENJUALAN = {
    "component": "Admin/Analytics/FmiPenjualan",
    "url": "/admin-panel/analitik/fmi-penjualan",
    "inner": rpt.fmi_penjualan,
    "sorts": rpt.SORTS_FMI_PENJUALAN,
    "default_sort": "qty_terjual",
    "summary": rpt.SUMMARY_FMI_PENJUALAN,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "fmi-penjualan",
    "columns": [{"key": "kd_barang", "label": "Kode"}, {"key": "barang", "label": "Barang"}, {"key": "kategori", "label": "Kategori"}, {"key": "qty_terjual", "label": "Qty Terjual", "align": "right", "format": "number"}, {"key": "nilai", "label": "Nilai", "align": "right", "format": "rupiah"}, {"key": "kelas", "label": "Kelas"}],
}
fmi_penjualan = _report_view(_FMI_PENJUALAN)
fmi_penjualan_export = _report_export(_FMI_PENJUALAN)

_FMI_STOK = {
    "component": "Admin/Analytics/FmiStok",
    "url": "/admin-panel/analitik/fmi-stok",
    "inner": rpt.fmi_stok,
    "sorts": rpt.SORTS_FMI_STOK,
    "default_sort": "qty_stok",
    "summary": rpt.SUMMARY_FMI_STOK,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "fmi-stok",
    "columns": [{"key": "kd_barang", "label": "Kode"}, {"key": "barang", "label": "Barang"}, {"key": "kategori", "label": "Kategori"}, {"key": "qty_stok", "label": "Qty Stok", "align": "right", "format": "number"}, {"key": "nilai_stok", "label": "Nilai Stok", "align": "right", "format": "rupiah"}, {"key": "terjual", "label": "Terjual", "align": "right", "format": "number"}, {"key": "rasio", "label": "Rasio", "align": "right", "format": "number"}, {"key": "status", "label": "Status"}],
}
fmi_stok = _report_view(_FMI_STOK)
fmi_stok_export = _report_export(_FMI_STOK)

# Kas & Shift
# Kas Harian has a running `saldo` column across the whole selected range, so
# it can't reuse the generic _report_view (SQL-level OFFSET/FETCH pagination
# would break the running total) — see rpt.kas_harian_rows().
_KAS_COLUMNS = [
    {"key": "tanggal", "label": "Tanggal"},
    {"key": "kas", "label": "Kas"},
    {"key": "keterangan", "label": "Keterangan"},
    {"key": "masuk", "label": "Masuk"},
    {"key": "keluar", "label": "Keluar"},
    {"key": "saldo", "label": "Saldo"},
]


def kas_harian(request):
    f = reporting.parse_report_params(request, rpt.SORTS_KAS, "tanggal")
    f["kd_kas"] = (request.GET.get("kd_kas") or "").strip()

    def load_report():
        rows, total, summary, options, conn_error = [], 0, {}, {}, None
        profile = _active()
        if profile:
            try:
                with mssql.cursor(profile) as cur:
                    all_rows, summary = rpt.kas_harian_rows(cur, f)
                    options = {"kas": _opt_kas(profile)}
                total = len(all_rows)
                start = (f["page"] - 1) * f["per_page"]
                rows = all_rows[start:start + f["per_page"]]
            except pyodbc.Error as exc:
                conn_error = f"Gagal membaca kas: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR
        if f["warning"]:
            conn_error = f["warning"] if not conn_error else f"{conn_error} {f['warning']}"
        return {"rows": rows, "total": total, "summary": summary, "options": options, "conn_error": conn_error}

    return render(request, "Admin/Cash/Kas", props={
        "report": defer(load_report),
        "filters": {
            "date_from": f["date_from_s"], "date_to": f["date_to_s"], "kd_kas": f["kd_kas"],
            "sort": f["sort"], "sort_dir": f["sort_dir"], "page": f["page"], "per_page": f["per_page"],
        },
    })


def kas_harian_export(request):
    f = reporting.parse_report_params(request, rpt.SORTS_KAS, "tanggal")
    f["kd_kas"] = (request.GET.get("kd_kas") or "").strip()
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/admin-panel/kas/harian")
    try:
        with mssql.cursor(profile) as cur:
            rows, _summary = rpt.kas_harian_rows(cur, f)
    except pyodbc.Error as exc:
        request.session["flash_error"] = f"Gagal export: {exc.args[-1] if exc.args else exc}"
        return redirect("/admin-panel/kas/harian")
    log_activity(request, "export", f"Export kas-harian: {len(rows)} baris")
    return reporting.xlsx_response("kas-harian", _KAS_COLUMNS, rows)

_SHIFT = {
    "component": "Admin/Cash/Shift",
    "url": "/admin-panel/kas/shift",
    "inner": rpt.shift,
    "sorts": rpt.SORTS_SHIFT,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_SHIFT,
    "filter_keys": [],
    "options": lambda p: {},
    "filename": "shift",
    "columns": [{"key": "no_transaksi", "label": "No. Transaksi"}, {"key": "tanggal", "label": "Tanggal", "format": "date"}, {"key": "pegawai", "label": "Pegawai"}, {"key": "shift", "label": "Shift"}, {"key": "keterangan", "label": "Keterangan"}],
}
shift = _report_view(_SHIFT)
shift_export = _report_export(_SHIFT)


# --- Profil Saya (edit own account) ----------------------------------------

def profile_view(request):
    u = request.user
    return render(
        request,
        "Admin/Profile",
        props={"profile": {"username": u.username, "name": u.get_full_name(), "role": u.role}},
    )


def profile_save(request):
    data = get_data(request)
    u = request.user
    name = (data.get("name") or "").strip()
    u.first_name, _, u.last_name = name.partition(" ")
    password = data.get("password")
    if password:
        u.set_password(password)
    u.save()
    if password:
        update_session_auth_hash(request, u)  # keep the current session valid
    log_activity(request, "profil", "Ubah profil sendiri")
    request.session["flash_success"] = "Profil diperbarui."
    return redirect("/admin-panel/profile")

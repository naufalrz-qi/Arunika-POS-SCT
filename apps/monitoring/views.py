"""Admin panel views — wired to real data (MS SQL via services, SQLite via models)."""
import datetime as dt

import pyodbc
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from inertia import render

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.http import get_data
from apps.core.menus import assignable_menus
from apps.core.models import ActivityLog, log_activity
from apps.inventory import services as inv
from apps.master_data import services as master
from apps.transactions import services as tx
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
    return render(
        request,
        "Admin/Dashboard",
        props={
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
        },
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
    profile = _active()
    kd_divisi = request.GET.get("kd_divisi", "")
    tanggal = _parse_date(request.GET.get("tanggal")) or dt.datetime.now()

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

    return render(
        request,
        "Admin/Inventory/Stock",
        props={
            "levels": levels,
            "divisi_list": divisi_list,
            "filters": {
                "kd_divisi": kd_divisi,
                "tanggal": request.GET.get("tanggal", ""),
            },
            "conn_error": conn_error,
        },
    )


def barang_histori_index(request):
    profile = _active()
    kd_barang = request.GET.get("kd_barang", "").strip()
    kd_divisi = request.GET.get("kd_divisi", "")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))

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

    return render(
        request,
        "Admin/Inventory/BarangHistori",
        props={
            "rows": rows,
            "divisi_list": divisi_list,
            "filters": {
                "kd_barang": kd_barang,
                "kd_divisi": kd_divisi,
                "date_from": request.GET.get("date_from", ""),
                "date_to": request.GET.get("date_to", ""),
            },
            "conn_error": conn_error,
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
# Frontend phase: these pages render their data from client-side mock modules
# (frontend/mock/*.js), so the Django view only needs to render the component.

def _mock_page(component):
    def view(request):
        return render(request, component, props={})

    return view


# Penjualan
penjualan_all = _mock_page("Admin/Reports/PenjualanAll")
penjualan_nota = _mock_page("Admin/Reports/PenjualanNota")
penjualan_customer = _mock_page("Admin/Reports/PenjualanCustomer")
penjualan_user = _mock_page("Admin/Reports/PenjualanUser")
penjualan_periode = _mock_page("Admin/Reports/PenjualanPeriode")
retur_penjualan = _mock_page("Admin/Reports/ReturPenjualan")
# Pembelian
pembelian = _mock_page("Admin/Reports/Pembelian")
retur_pembelian = _mock_page("Admin/Reports/ReturPembelian")
# Inventori
stok_divisi = _mock_page("Admin/Inventory/StokDivisi")
stok_akhir = _mock_page("Admin/Inventory/StokAkhir")
opname = _mock_page("Admin/Inventory/Opname")
# Analitik
fmi_penjualan = _mock_page("Admin/Analytics/FmiPenjualan")
fmi_stok = _mock_page("Admin/Analytics/FmiStok")
# Promo & Voucher
promo = _mock_page("Admin/Promo/Promo")
voucher = _mock_page("Admin/Promo/Voucher")
# Kas & Shift
kas_harian = _mock_page("Admin/Cash/Kas")
shift = _mock_page("Admin/Cash/Shift")


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

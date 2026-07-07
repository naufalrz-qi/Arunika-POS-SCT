"""Admin panel views — wired to real data (MS SQL via services, SQLite via models)."""
import datetime as dt
import json

import pyodbc
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from inertia import defer, render

from apps.auth_app.models import Role, User
from apps.connections.models import ServerProfile
from apps.core.http import get_data
from apps.core.menus import assignable_menus
from apps.core.models import ActivityLog, SyncLog, log_activity, log_sync
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
                # kota/flag_aktif don't exist on m_supplier (verified live via
                # INFORMATION_SCHEMA) — real columns are kd_kota/jenis; aliased
                # to keep Supplier.vue's existing prop contract unchanged.
                cur.execute(
                    "SELECT kd_supplier, nama, alamat, kd_kota AS kota, telepon, jenis AS flag_aktif "
                    "FROM m_supplier ORDER BY nama"
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
        # SQLite-only (SyncLog), no MS SQL involved — conn_error stays None,
        # kept in the payload shape only because SyncHistory.vue expects the key.
        syncs = [
            {
                "id": s.id,
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "user": s.username or "—",
                "feature": s.feature,
                "mode": s.mode,
                "src": s.src_name or "—",
                "dst": s.dst_name or "—",
                "total_items": s.applied_count,
                "status": s.status,
                "detail": {"items": s.items()},
            }
            for s in SyncLog.objects.all()[:200]
        ]
        return {"rows": syncs, "conn_error": None}

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
        # Built from the already-cached harga maps (no extra query) so the sync
        # history modal can show per-item before/after without changing
        # sync_harga_jual's return type (still a plain rowcount int). Read dst's
        # map BEFORE syncing (sync_harga_jual invalidates it after committing).
        src_map, dst_map = master._harga_map(src), master._harga_map(dst)
        items = []
        for k in keys:
            kb, ks = master._st(k.get("kd_barang")), master._st(k.get("kd_satuan"))
            s = src_map.get((kb, ks))
            if s:
                before = dst_map.get((kb, ks))
                items.append({
                    "label": kb,
                    "kode": ks,
                    "changes": [{"field": "harga_jual", "before": before["harga_jual"] if before else None, "after": s["harga_jual"]}],
                })

        n = master.sync_harga_jual(src, dst, keys, with_margin=with_margin)
        log_activity(request, "sync_harga", f"Sync harga {src.name} -> {dst.name}: {n} baris")
        log_sync(request, feature="harga", mode=mode, src=src, dst=dst, compared=len(keys), applied=n, items=items)
        request.session["flash_success"] = f"Sinkronisasi selesai: {n} baris diperbarui."
    except pyodbc.Error as exc:
        request.session["flash_error"] = f"Gagal sinkron: {exc.args[-1] if exc.args else exc}"
        log_sync(request, feature="harga", mode=mode, src=src, dst=dst, compared=len(keys), applied=0,
                  status="failed", error=str(exc.args[-1] if exc.args else exc))
    return redirect(f"/admin-panel/master/sync-harga?mode={mode}&src={src.id}&dst={dst.id}")


# --- Sinkronisasi Master Data (m_barang/m_customer/m_supplier) -------------
# Arah tetap: gudang = sumber data master, tujuan = server aktif/dipilih
# (grosir/retail) — beda dari sync-harga yang punya 2 mode simetris.

_SYNC_MASTER_ENTITIES = [
    {"value": k, "label": v["label"]} for k, v in master._SYNC_ENTITIES.items()
]


def sync_master_index(request):
    profiles = [p.as_dict() for p in ServerProfile.objects.all()]
    entity = request.GET.get("entity", "m_barang")
    src = ServerProfile.objects.filter(pk=request.GET.get("src")).first() if request.GET.get("src") else None
    dst = ServerProfile.objects.filter(pk=request.GET.get("dst")).first() if request.GET.get("dst") else None

    diff, conn_error = [], None
    if src and dst and entity in master._SYNC_ENTITIES:
        try:
            diff = master.compare_entity(entity, src, dst)
        except pyodbc.Error as exc:
            conn_error = f"Gagal membandingkan data: {exc.args[-1] if exc.args else exc}"

    return render(
        request,
        "Admin/MasterData/SyncMaster",
        props={
            "profiles": profiles,
            "entities": _SYNC_MASTER_ENTITIES,
            "entity": entity,
            "src": src.id if src else None,
            "dst": dst.id if dst else None,
            "diff": diff,
            "conn_error": conn_error,
        },
    )


def sync_master_apply(request):
    data = get_data(request)
    entity = data.get("entity")
    if entity not in master._SYNC_ENTITIES:
        request.session["flash_error"] = "Entitas tidak valid."
        return redirect("/admin-panel/master/sync-master")
    src = get_object_or_404(ServerProfile, pk=data.get("src"))
    dst = get_object_or_404(ServerProfile, pk=data.get("dst"))
    keys = data.get("keys") or []
    try:
        # Items dibangun sebelum apply (map dst masih pra-sync di cache),
        # sama seperti sync_harga_apply, untuk detail before/after di riwayat.
        cfg = master._SYNC_ENTITIES[entity]
        src_map = master._entity_row_map(src, entity)
        dst_map = master._entity_row_map(dst, entity)
        items = []
        for k in keys:
            pk = tuple(master._st(k.get(c)) for c in cfg["pk_cols"])
            s = src_map.get(pk)
            if not s:
                continue
            d = dst_map.get(pk)
            changes = [
                {"field": c, "before": d[c] if d else None, "after": s[c]}
                for c in cfg["cols"] if not d or master._st(d[c]) != master._st(s[c])
            ]
            items.append({"label": master._st(s.get("nama")), "kode": "/".join(pk), "changes": changes})

        n = master.sync_entity(entity, src, dst, keys)
        log_activity(request, "sync_master", f"Sync {entity} {src.name} -> {dst.name}: {n} baris")
        log_sync(request, feature=entity, mode="whole_row", src=src, dst=dst, compared=len(keys), applied=n, items=items)
        request.session["flash_success"] = f"Sinkronisasi selesai: {n} baris diperbarui."
    except pyodbc.Error as exc:
        request.session["flash_error"] = f"Gagal sinkron: {exc.args[-1] if exc.args else exc}"
        log_sync(request, feature=entity, mode="whole_row", src=src, dst=dst, compared=len(keys), applied=0,
                  status="failed", error=str(exc.args[-1] if exc.args else exc))
    return redirect(f"/admin-panel/master/sync-master?entity={entity}&src={src.id}&dst={dst.id}")


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


_KATEGORI_BIAYA_LABEL = {
    1: "Operasional (Penjualan)", 2: "Operasional (Adm. dan Umum)",
    3: "Produksi (Biaya Langsung)", 4: "Produksi (Biaya Tak Langsung)",
}


def _opt_kategori_biaya(profile):
    # Only status values actually assigned to a m_biaya row are offered — this
    # business (retail/toys) only uses 1/2; 3/4 (produksi) exist in the label
    # mapping but would otherwise be a dead filter option.
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT DISTINCT status FROM m_biaya WHERE status <> 0 ORDER BY status")
        statuses = [r[0] for r in cur.fetchall()]
    return [{"value": str(s), "label": _KATEGORI_BIAYA_LABEL.get(s, str(s))} for s in statuses]


def _spec_params(request, spec, export=False):
    # Export always covers the full filtered range — never the "100 terbaru"
    # first-load cap, which only applies to the on-screen table.
    f = reporting.parse_report_params(
        request, spec["sorts"], spec["default_sort"],
        enable_recent=spec.get("enable_recent", False) and not export,
        recent_sort=spec.get("recent_sort"),
    )
    for k in spec.get("filter_keys", []):
        f[k] = (request.GET.get(k) or "").strip()
    f["filters"] = reporting.parse_column_filters(request, spec.get("filters", {}))
    return f


def _spec_filters(f, spec):
    filters = {
        "date_from": f["date_from_s"], "date_to": f["date_to_s"],
        "date_mode": f["date_mode"],
        "search": f["search"], "sort": f["sort"], "sort_dir": f["sort_dir"],
        "page": f["page"], "per_page": f["per_page"],
        "recent": f["recent"],
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
                # Reads only: prefer the report_source replica (synced via
                # apps/transactions/cdc_sync.py) so this heavy query never
                # competes for locks with live POS transactions, but fall back
                # to the legacy server itself if no replica is set up OR the
                # replica is unreachable — a replica outage shouldn't break
                # every report when the primary can still serve them.
                inner, params = spec["inner"](f)
                inner, params = reporting.apply_column_filters(inner, params, f)
                for read_profile in mssql.report_read_profiles(profile):
                    rows, total, summary, options = [], 0, {}, {}  # reset per attempt
                    try:
                        with mssql.cursor(read_profile) as cur:
                            if f["recent"]:
                                rows, total, summary_sql = reporting.run_recent(cur, inner, params, f)
                            else:
                                rows, total = reporting.run_paged(cur, inner, params, f)
                                summary_sql = inner
                            cur.execute(f"SELECT {spec['summary']} FROM ({summary_sql}) AS q", params)
                            summary = reporting.clean_rows(reporting.dictify(cur))[0]
                        if spec.get("options"):
                            options = spec["options"](read_profile)
                        conn_error = None
                        break
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
        f = _spec_params(request, spec, export=True)
        profile = _active()
        if not profile:
            request.session["flash_error"] = CONN_ERROR
            return redirect(spec["url"])
        inner, params = spec["inner"](f)
        inner, params = reporting.apply_column_filters(inner, params, f)
        rows, last_exc = None, None
        # Prefer the replica, fall back to the primary if it's unreachable
        # (same read-offload-with-fallback policy as _report_view).
        for read_profile in mssql.report_read_profiles(profile):
            try:
                with mssql.cursor(read_profile) as cur:
                    rows = reporting.run_all(cur, inner, params, f)
                break
            except pyodbc.Error as exc:
                last_exc = exc
        if rows is None:
            request.session["flash_error"] = f"Gagal export: {last_exc.args[-1] if last_exc.args else last_exc}"
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
    "filters": rpt.FILTERS_PENJUALAN_DETAIL,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-detail",
    "columns": [
        {"key": "no_transaksi", "label": "No. Transaksi"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "divisi", "label": "Divisi"},
        {"key": "customer", "label": "Customer"},
        {"key": "kota", "label": "Kota"},
        {"key": "jth_tempo", "label": "Jth. Tempo"},
        {"key": "status", "label": "Status"},
        {"key": "keterangan", "label": "Ket."},
        {"key": "kd_barang", "label": "Kode Barang"},
        {"key": "barang", "label": "Barang"},
        {"key": "kategori", "label": "Kategori"},
        {"key": "sales", "label": "Sales"},
        {"key": "qty", "label": "Qty"},
        {"key": "satuan", "label": "Satuan"},
        {"key": "harga", "label": "Harga"},
        {"key": "dd1", "label": "DD1"},
        {"key": "dd2", "label": "DD2"},
        {"key": "dd3", "label": "DD3"},
        {"key": "dd4", "label": "DD4"},
        {"key": "dt1", "label": "DT1"},
        {"key": "dt2", "label": "DT2"},
        {"key": "dt3", "label": "DT3"},
        {"key": "dt4", "label": "DT4"},
        {"key": "harga_bersih", "label": "Harga Bersih"},
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
    "filters": rpt.FILTERS_PENJUALAN_NOTA,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p), "customer": _opt_customer(p)},
    "filename": "penjualan-nota",
    "columns": [
        {"key": "no_transaksi", "label": "No. Nota"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "divisi", "label": "Divisi"},
        {"key": "customer", "label": "Customer"},
        {"key": "kota", "label": "Kota"},
        {"key": "total_kotor", "label": "Total Kotor"},
        {"key": "potongan", "label": "Potongan"},
        {"key": "voucher", "label": "Voucher"},
        {"key": "total_setelah_voucher", "label": "Total Setelah Voucher"},
        {"key": "pajak", "label": "Pajak"},
        {"key": "pajak2", "label": "Pajak 2"},
        {"key": "total_bersih", "label": "Total Bersih"},
        {"key": "petugas", "label": "Petugas"},
    ],
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
    "filters": rpt.FILTERS_PENJUALAN_CUSTOMER,
    "enable_recent": True,
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-customer",
    "columns": [
        {"key": "divisi", "label": "Divisi"},
        {"key": "customer", "label": "Customer"},
        {"key": "jml_nota", "label": "Jml Nota"},
        {"key": "total", "label": "Total"},
    ],
}
penjualan_customer = _report_view(_PENJUALAN_CUSTOMER)
penjualan_customer_export = _report_export(_PENJUALAN_CUSTOMER)

_PENJUALAN_USER = {
    "component": "Admin/Reports/PenjualanUser",
    "url": "/admin-panel/laporan/penjualan-user",
    "inner": rpt.penjualan_user,
    "sorts": rpt.SORTS_PENJUALAN_USER,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PENJUALAN_USER,
    "filter_keys": ["kd_divisi"],
    "filters": rpt.FILTERS_PENJUALAN_USER,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-user",
    "columns": [
        {"key": "no_transaksi", "label": "No. Transaksi"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "divisi", "label": "Divisi"},
        {"key": "status", "label": "Status Transaksi"},
        {"key": "customer", "label": "Customer"},
        {"key": "nominal", "label": "Nominal"},
        {"key": "user", "label": "User"},
    ],
}
penjualan_user = _report_view(_PENJUALAN_USER)
penjualan_user_export = _report_export(_PENJUALAN_USER)

_PENJUALAN_PERIODE = {
    "component": "Admin/Reports/PenjualanPeriode",
    "url": "/admin-panel/laporan/penjualan-periode",
    "inner": rpt.penjualan_periode,
    "sorts": rpt.SORTS_PENJUALAN_PERIODE,
    "default_sort": "periode",
    "summary": rpt.SUMMARY_PENJUALAN_PERIODE,
    "filter_keys": ["kd_divisi", "granularitas"],
    "enable_recent": True,
    "recent_sort": "periode",
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "penjualan-periode",
    "columns": [
        {"key": "periode", "label": "Periode"},
        {"key": "jml_nota", "label": "Jml Nota"},
        {"key": "total_kotor", "label": "Total Kotor"},
        {"key": "total_diskon", "label": "Total Diskon"},
        {"key": "total_pajak", "label": "Total Pajak"},
        {"key": "total", "label": "Total Bersih"},
    ],
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
    "filters": rpt.FILTERS_RETUR_PENJUALAN,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p), "customer": _opt_customer(p)},
    "filename": "retur-penjualan",
    "columns": [
        {"key": "no_retur", "label": "No. Retur"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "no_bukti", "label": "No. Bukti"},
        {"key": "divisi", "label": "Divisi"},
        {"key": "keterangan_divisi", "label": "Keterangan Divisi"},
        {"key": "kepala_nota", "label": "Kepala Nota"},
        {"key": "customer", "label": "Customer"},
        {"key": "barang", "label": "Barang"},
        {"key": "satuan", "label": "Satuan"},
        {"key": "jenis_bayar", "label": "Jenis Bayar"},
        {"key": "no_rekening", "label": "No. Rekening"},
        {"key": "bank", "label": "Bank"},
        {"key": "harga_jual", "label": "Harga Jual"},
        {"key": "sales", "label": "Sales"},
        {"key": "qty", "label": "Qty"},
        {"key": "nilai", "label": "Nilai"},
    ],
}
retur_penjualan = _report_view(_RETUR_PENJUALAN)
retur_penjualan_export = _report_export(_RETUR_PENJUALAN)

_PIUTANG = {
    "component": "Admin/Reports/Piutang",
    "url": "/admin-panel/laporan/piutang",
    "inner": rpt.piutang,
    "sorts": rpt.SORTS_PIUTANG,
    "default_sort": "sisa_piutang",
    "summary": rpt.SUMMARY_PIUTANG,
    "filter_keys": ["kd_divisi", "kd_customer"],
    "filters": rpt.FILTERS_PIUTANG,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p), "customer": _opt_customer(p)},
    "filename": "piutang",
    "columns": [
        {"key": "no_transaksi", "label": "No. Nota"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "customer", "label": "Customer"},
        {"key": "jatuh_tempo", "label": "Jatuh Tempo"},
        {"key": "total_penjualan", "label": "Total Penjualan"},
        {"key": "total_cicilan", "label": "Total Cicilan"},
        {"key": "sisa_piutang", "label": "Sisa Piutang"},
        {"key": "hari_terlambat", "label": "Hari Terlambat"},
    ],
}
piutang = _report_view(_PIUTANG)
piutang_export = _report_export(_PIUTANG)

# Pembelian
_PEMBELIAN = {
    "component": "Admin/Reports/Pembelian",
    "url": "/admin-panel/laporan/pembelian",
    "inner": rpt.pembelian,
    "sorts": rpt.SORTS_PEMBELIAN,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PEMBELIAN,
    "filter_keys": ["kd_divisi", "kd_supplier"],
    "filters": rpt.FILTERS_PEMBELIAN,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p), "supplier": _opt_supplier(p)},
    "filename": "pembelian",
    "columns": [
        {"key": "no_transaksi", "label": "No. Transaksi"},
        {"key": "no_order", "label": "No Order"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "supplier", "label": "Supplier"},
        {"key": "note", "label": "Note"},
        {"key": "barang", "label": "Barang"},
        {"key": "qty", "label": "Qty"},
        {"key": "satuan", "label": "Satuan"},
        {"key": "harga", "label": "Harga Beli"},
        {"key": "diskon_item1", "label": "Diskon Item 1"},
        {"key": "diskon_item2", "label": "Diskon Item 2"},
        {"key": "diskon_item3", "label": "Diskon Item 3"},
        {"key": "diskon_item4", "label": "Diskon Item 4"},
        {"key": "diskon_total1", "label": "Diskon Total 1"},
        {"key": "diskon_total2", "label": "Diskon Total 2"},
        {"key": "diskon_total3", "label": "Diskon Total 3"},
        {"key": "diskon_total4", "label": "Diskon Total 4"},
        {"key": "pajak", "label": "Pajak"},
        {"key": "ppnbm", "label": "PPnBM"},
        {"key": "subtotal", "label": "Subtotal"},
    ],
}
pembelian = _report_view(_PEMBELIAN)
pembelian_export = _report_export(_PEMBELIAN)

_PEMBELIAN_SUPPLIER = {
    "component": "Admin/Reports/PembelianSupplier",
    "url": "/admin-panel/laporan/pembelian-supplier",
    "inner": rpt.pembelian_supplier,
    "sorts": rpt.SORTS_PEMBELIAN_SUPPLIER,
    "default_sort": "total",
    "summary": rpt.SUMMARY_PEMBELIAN_SUPPLIER,
    "filter_keys": ["kd_divisi"],
    "filters": rpt.FILTERS_PEMBELIAN_SUPPLIER,
    "enable_recent": True,
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "pembelian-supplier",
    "columns": [
        {"key": "divisi", "label": "Divisi"},
        {"key": "supplier", "label": "Supplier"},
        {"key": "jml_nota", "label": "Jml Nota"},
        {"key": "total", "label": "Total"},
    ],
}
pembelian_supplier = _report_view(_PEMBELIAN_SUPPLIER)
pembelian_supplier_export = _report_export(_PEMBELIAN_SUPPLIER)

_PEMBELIAN_PERIODE = {
    "component": "Admin/Reports/PembelianPeriode",
    "url": "/admin-panel/laporan/pembelian-periode",
    "inner": rpt.pembelian_periode,
    "sorts": rpt.SORTS_PEMBELIAN_PERIODE,
    "default_sort": "periode",
    "summary": rpt.SUMMARY_PEMBELIAN_PERIODE,
    "filter_keys": ["kd_divisi", "granularitas"],
    "enable_recent": True,
    "recent_sort": "periode",
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "pembelian-periode",
    "columns": [
        {"key": "periode", "label": "Periode"},
        {"key": "jml_nota", "label": "Jml Nota"},
        {"key": "total_kotor", "label": "Total Kotor"},
        {"key": "total_diskon", "label": "Total Diskon"},
        {"key": "total_pajak", "label": "Total Pajak"},
        {"key": "total", "label": "Total Bersih"},
    ],
}
pembelian_periode = _report_view(_PEMBELIAN_PERIODE)
pembelian_periode_export = _report_export(_PEMBELIAN_PERIODE)

_RETUR_PEMBELIAN = {
    "component": "Admin/Reports/ReturPembelian",
    "url": "/admin-panel/laporan/retur-pembelian",
    "inner": rpt.retur_pembelian,
    "sorts": rpt.SORTS_RETUR_PEMBELIAN,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_RETUR_PEMBELIAN,
    "filter_keys": ["kd_divisi", "kd_supplier"],
    "filters": rpt.FILTERS_RETUR_PEMBELIAN,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p), "supplier": _opt_supplier(p)},
    "filename": "retur-pembelian",
    "columns": [
        {"key": "no_retur", "label": "No. Retur"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "no_bukti", "label": "No. Bukti"},
        {"key": "divisi", "label": "Divisi"},
        {"key": "supplier", "label": "Supplier"},
        {"key": "pembayaran", "label": "Pembayaran"},
        {"key": "bank", "label": "Bank"},
        {"key": "no_rekening", "label": "No. Rekening"},
        {"key": "petugas", "label": "Petugas"},
        {"key": "kd_barang", "label": "Kode Barang"},
        {"key": "barang", "label": "Barang"},
        {"key": "harga", "label": "Harga"},
        {"key": "satuan", "label": "Satuan"},
        {"key": "keterangan", "label": "Keterangan"},
        {"key": "qty", "label": "Qty"},
        {"key": "nilai", "label": "Nilai"},
    ],
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

_BIAYA = {
    "component": "Admin/Reports/BiayaOperasional",
    "url": "/admin-panel/laporan/biaya-operasional",
    "inner": rpt.biaya_operasional,
    "sorts": rpt.SORTS_BIAYA,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_BIAYA,
    "filter_keys": ["kd_divisi", "kategori"],
    "options": lambda p: {"divisi": _opt_divisi(p), "kategori": _opt_kategori_biaya(p)},
    "filename": "biaya-operasional",
    "columns": [
        {"key": "no_transaksi", "label": "No. Transaksi"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "divisi", "label": "Divisi"},
        {"key": "biaya", "label": "Biaya"},
        {"key": "kategori", "label": "Kategori"},
        {"key": "nominal", "label": "Nominal"},
        {"key": "keterangan", "label": "Keterangan"},
    ],
}
biaya_operasional = _report_view(_BIAYA)
biaya_operasional_export = _report_export(_BIAYA)

_BIAYA_KATEGORI = {
    "component": "Admin/Reports/BiayaKategori",
    "url": "/admin-panel/laporan/biaya-kategori",
    "inner": rpt.biaya_kategori,
    "sorts": rpt.SORTS_BIAYA_KATEGORI,
    "default_sort": "total",
    "summary": rpt.SUMMARY_BIAYA_KATEGORI,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "biaya-kategori",
    "columns": [{"key": "kategori", "label": "Kategori"}, {"key": "jml_baris", "label": "Jml Baris"}, {"key": "total", "label": "Total"}],
}
biaya_kategori = _report_view(_BIAYA_KATEGORI)
biaya_kategori_export = _report_export(_BIAYA_KATEGORI)


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

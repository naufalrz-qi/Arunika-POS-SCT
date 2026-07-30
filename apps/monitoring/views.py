"""Admin panel views — wired to real data (MS SQL via services, SQLite via models)."""
import datetime as dt
import json
import logging
import time

import pyodbc
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from inertia import defer, render

from apps.auth_app.models import DATA_KEY_SET, DATA_KEYS, Role, User
from apps.connections.models import ServerProfile
from apps.core.http import get_data
from apps.core.middleware import ditolak
from apps.core.menus import SECTION_LABELS, SECTIONS, assignable_menus
from apps.core.models import (
    ActivityLog,
    BarangHargaChange,
    BarangUpdateLog,
    HargaSnapshotRun,
    SyncLog,
    log_activity,
    log_barang_updates,
    log_sync,
)
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

# --- Izin nilai uang -------------------------------------------------------
#
# Sebagian user tak boleh melihat harga/nominal/omset. Penyaringannya WAJIB di
# sini, bukan di Vue: menyembunyikan kolom di layar tak menahan apa pun karena
# datanya tetap terkirim dan terbaca di tab Network. Stok Akhir bahkan
# mengirim seluruh katalog dalam satu payload, jadi satu permintaan memuat
# harga ~55rb barang sekaligus.
#
# Satu kunci izin menutup beberapa field. `harga_average` ikut harga_beli
# karena ia rata-rata harga perolehan — modal, bukan harga jual.
_FIELDS_BY_DATA_KEY = {
    "harga_jual": {"harga_jual"},
    "harga_beli": {"harga_average", "harga_beli_akhir"},
    # `nilai` = kolom Nilai di kartu Fast Moving dashboard. Sempat terlewat pada
    # rilis pertama: omset di kartu ringkasan sudah hilang, tapi rupiah per
    # barang di tabel bawahnya masih tampil.
    #
    # `total_belanja`/`rata_nota`/`tier_nilai` + dua kunci ringkasannya milik
    # Klasifikasi Pelanggan (baris, ringkasan, DAN kedua sheet export-nya):
    # halaman itu memang berisi belanja per orang, jadi tanpa ini kunci `nominal`
    # jadi hiasan justru di halaman yang paling terang soal uang.
    "nominal": {"nominal", "revenue", "nilai", "total_belanja", "rata_nota",
                "tier_nilai", "total_nilai", "rata_nota_semua"},
}


def _hidden_fields(request) -> set[str]:
    """Nama FIELD yang harus dibuang untuk user ini (bukan nama kunci izin)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return set()
    out = set()
    for key in user.hidden_data():
        out |= _FIELDS_BY_DATA_KEY.get(key, set())
    return out


def _kolom_tanpa_uang(request, spec, columns=None):
    """`columns` tanpa kolom uang yang tak boleh dilihat user ini.

    Dipakai jalur export: di sana penyaringan tak bisa dilakukan dengan membuang
    key dari dict baris (baris datang sebagai tuple langsung dari cursor, demi
    memori datar), jadi yang dicabut adalah DAFTAR KOLOM-nya. Efeknya sama —
    nilainya tak pernah sampai ke sel."""
    columns = spec["columns"] if columns is None else columns
    hidden = _hidden_fields(request) & set(spec.get("money_fields", ()))
    if not hidden:
        return columns
    return [c for c in columns if c["key"] not in hidden]

log = logging.getLogger(__name__)


def _local(value, fmt="%Y-%m-%d %H:%M:%S"):
    """Cetak datetime milik ORM Django di zona waktu situs (settings.TIME_ZONE).

    USE_TZ=True menyimpan semuanya dalam UTC; `value.strftime(...)` langsung
    mencetak UTC itu apa adanya, jadi Log Aktivitas dan kawan-kawannya terbaca
    7 jam mundur di Asia/Jakarta. Hanya untuk datetime ORM — tanggal dari MS SQL
    legacy sudah waktu lokal naif dan tak boleh ikut digeser.
    """
    if not value:
        return ""
    if timezone.is_naive(value):
        return value.strftime(fmt)
    return timezone.localtime(value).strftime(fmt)


def _active():
    return mssql.get_active_profile()


def _redirect_back(data, default: str):
    """Redirect ke halaman asal form (opsional `redirect_to` di payload) supaya
    endpoint update barang bisa dipakai dari halaman lain (mis. Pergerakan
    Harga) tanpa terlempar balik ke Update Barang. Hanya path admin-panel."""
    target = (data.get("redirect_to") or "").strip()
    if target.startswith("/admin-panel/"):
        return redirect(target)
    return redirect(default)


# --- Dashboard -------------------------------------------------------------

def dashboard(request):
    hidden = _hidden_fields(request)

    # Deferred: bundle servers + summary + activity so shell renders instantly.
    def load_dashboard():
        # Status server hanya untuk superadmin. Daftar ini membuka nama host dan
        # port setiap server MS SQL — peta infrastruktur yang tak dibutuhkan
        # siapa pun untuk memakai aplikasi, dan tak layak dikirim ke peramban
        # yang tak berhak. Dikosongkan di server, bukan disembunyikan di layar.
        boleh_lihat_server = request.user.role == Role.SUPERADMIN
        servers = [
            {"id": p.id, "name": p.name, "host": f"{p.host}:{p.port}", "status": p.last_status}
            for p in ServerProfile.objects.all()
        ] if boleh_lihat_server else []
        # Kartu Aktivitas Terbaru di dashboard hanya menampilkan jejak pemakainya
        # sendiri; superadmin melihat semuanya. Ini kartu ringkasan pribadi —
        # "apa yang baru saja saya lakukan" — bukan jendela ke pekerjaan rekan
        # kerja. Halaman Log Aktivitas (/admin-panel/logs) sengaja TIDAK ikut
        # disaring: itu memang layar audit, dan aksesnya sudah dijaga menu.
        #
        # Disaring lewat `username` (salinan teks di baris log), bukan relasi ke
        # User: kolom itu didenormalisasi supaya jejak tetap terbaca setelah
        # akunnya dihapus.
        log_qs = ActivityLog.objects.all()
        if request.user.role != Role.SUPERADMIN:
            log_qs = log_qs.filter(username=request.user.username)
        recent = [
            {
                "id": a.id,
                "user": a.username or "—",
                "action": a.action,
                "detail": a.detail,
                "time": _local(a.timestamp, "%Y-%m-%d %H:%M"),
            }
            for a in log_qs[:8]
        ]

        profile = _active()
        summary = {"total_transactions": 0, "total_items": 0, "revenue": 0,
                   "hourly_transactions": [], "fast_movers": []}
        conn_error = None
        if profile:
            try:
                summary = tx.dashboard_summary(profile)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca transaksi")
        else:
            conn_error = CONN_ERROR

        stats = {
            "total_transactions": summary["total_transactions"],
            "total_items": summary["total_items"],
            "revenue": summary["revenue"],
        }
        if boleh_lihat_server:
            stats["servers_online"] = sum(1 for s in servers if s["status"] == "online")
            stats["servers_total"] = len(servers)
        # Omset dibuang dari respons, bukan sekadar disembunyikan di layar.
        for f in hidden:
            stats.pop(f, None)
        # Kartu Fast Moving membawa rupiah per barang; ia harus ikut dibuang,
        # kalau tidak omset cuma hilang dari kartu ringkasan dan tetap bisa
        # dijumlahkan sendiri dari tabel di bawahnya.
        movers = summary.get("fast_movers", [])
        if hidden:
            movers = [{k: v for k, v in m.items() if k not in hidden} for m in movers]
        return {
            "servers": servers,
            "stats": stats,
            "hourly_transactions": summary["hourly_transactions"],
            "fast_movers": movers,
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
        "created_at": _local(u.date_joined, "%Y-%m-%d"),
    }


# PRD §4 — operational-account management.
# Superadmin: kelola SEMUA user tanpa kecuali, termasuk mengangkat superadmin baru.
# Admin: kelola kasir/supervisor/admin (termasuk sesama admin), tapi tidak bisa
# membuat superadmin ataupun menyentuh akun superadmin. Set ini menjadi gerbang
# ganda — role target yang boleh dijangkau DAN nilai role yang boleh diberikan —
# sehingga eskalasi privilege via endpoint save/delete/reset tetap terblokir.
def _managed_roles(user):
    if user.role == Role.SUPERADMIN:
        return [Role.KASIR, Role.SUPERVISOR, Role.ADMIN, Role.SUPERADMIN]
    return [Role.KASIR, Role.SUPERVISOR, Role.ADMIN]


def _last_superadmin_guard(target, new_role=None, deactivate=False):
    """Pesan error bila aksi menghilangkan superadmin aktif terakhir (demosi /
    hapus / nonaktif), else None — kunci sistem tak boleh lenyap."""
    if target.role != Role.SUPERADMIN:
        return None
    if not (deactivate or (new_role is not None and new_role != Role.SUPERADMIN)):
        return None
    others = User.objects.filter(role=Role.SUPERADMIN, is_active=True).exclude(pk=target.pk).count()
    return "Tidak bisa: ini superadmin aktif terakhir." if others == 0 else None


def users_index(request):
    roles = _managed_roles(request.user)
    users = User.objects.filter(role__in=roles).order_by("role", "username")
    return render(request, "Admin/Users/Index", props={
        "users": [_user_dict(u) for u in users],
        "assignable_roles": roles,
        "me": request.user.id,
    })


def users_save(request):
    data = get_data(request)
    managed = _managed_roles(request.user)
    user_id = data.get("id")
    name = (data.get("name") or "").strip()
    first, _, last = name.partition(" ")

    role = data.get("role") or Role.KASIR
    if role not in managed:
        request.session["flash_error"] = "Role tidak valid atau di luar wewenang Anda."
        return redirect("/admin-panel/users")

    username = (data.get("username") or "").strip()
    if user_id:
        user = get_object_or_404(User, pk=user_id, role__in=managed)
        if (err := _last_superadmin_guard(user, new_role=role)):
            request.session["flash_error"] = err
            return redirect("/admin-panel/users")
        # Username ikut bisa diedit (dulu diabaikan diam-diam pada jalur edit).
        if username and username != user.username:
            if User.objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
                request.session["flash_error"] = "Username sudah dipakai."
                return redirect("/admin-panel/users")
            user.username = username
        user.first_name, user.last_name, user.role = first, last, role
    else:
        if not username:
            request.session["flash_error"] = "Username wajib diisi."
            return redirect("/admin-panel/users")
        if User.objects.filter(username__iexact=username).exists():
            request.session["flash_error"] = "Username sudah dipakai."
            return redirect("/admin-panel/users")
        user = User(username=username, first_name=first, last_name=last, role=role)

    password = data.get("password")
    if not password and not user_id:
        request.session["flash_error"] = "Password wajib diisi untuk user baru."
        return redirect("/admin-panel/users")
    if password:
        try:
            validate_password(password, user)
        except ValidationError as exc:
            request.session["flash_error"] = " ".join(exc.messages)
            return redirect("/admin-panel/users")
        user.set_password(password)
    user.save()

    log_activity(request, "user", f"Simpan user {user.username}")
    request.session["flash_success"] = "Data user disimpan."
    return redirect("/admin-panel/users")


def users_reset_password(request, user_id):
    user = get_object_or_404(User, pk=user_id, role__in=_managed_roles(request.user))
    data = get_data(request)
    password = data.get("password") or ""
    try:
        validate_password(password, user)
    except ValidationError as exc:
        request.session["flash_error"] = " ".join(exc.messages)
        return redirect("/admin-panel/users")
    user.set_password(password)
    user.save(update_fields=["password"])
    log_activity(request, "user", f"Reset password {user.username}")
    request.session["flash_success"] = "Password direset."
    return redirect("/admin-panel/users")


def users_toggle(request, user_id):
    """Aktif/nonaktif (soft) — dulunya menempati endpoint 'delete'."""
    user = get_object_or_404(User, pk=user_id, role__in=_managed_roles(request.user))
    if user.pk == request.user.pk:
        request.session["flash_error"] = "Tidak bisa menonaktifkan akun sendiri."
        return redirect("/admin-panel/users")
    if user.is_active and (err := _last_superadmin_guard(user, deactivate=True)):
        request.session["flash_error"] = err
        return redirect("/admin-panel/users")
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    state = "diaktifkan" if user.is_active else "dinonaktifkan"
    log_activity(request, "user", f"User {user.username} {state}")
    request.session["flash_success"] = f"User {state}."
    return redirect("/admin-panel/users")


def users_delete(request, user_id):
    """Hapus PERMANEN (bug lama: endpoint ini cuma toggle nonaktif, hapus
    sungguhan tidak pernah ada)."""
    user = get_object_or_404(User, pk=user_id, role__in=_managed_roles(request.user))
    if user.pk == request.user.pk:
        request.session["flash_error"] = "Tidak bisa menghapus akun sendiri."
        return redirect("/admin-panel/users")
    if (err := _last_superadmin_guard(user, deactivate=True)):
        request.session["flash_error"] = err
        return redirect("/admin-panel/users")
    username = user.username
    user.delete()
    log_activity(request, "user", f"User {username} dihapus permanen")
    request.session["flash_success"] = f"User {username} dihapus."
    return redirect("/admin-panel/users")


# --- Master: produk (read-only) -------------------------------------------

def products_index(request):
    search = request.GET.get("search", "")
    kd_kategori = request.GET.get("kd_kategori", "")
    profile = _active()

    # Deferred: katalog penuh (tanpa cap) bisa makan detik-an — shell (judul,
    # kartu) tampil instan, tabel muncul begitu query selesai.
    def load_products():
        products, categories, conn_error = [], [], None
        if profile:
            try:
                products = master.list_products(profile, search, kd_kategori)
                categories = master.list_categories(profile)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca master produk")
        else:
            conn_error = CONN_ERROR
        return {"rows": products, "categories": categories, "conn_error": conn_error}

    return render(
        request,
        "Admin/MasterData/Products",
        props={"products": defer(load_products)},
    )


# --- Master: pelanggan (read-only) ----------------------------------------

def customers_index(request):
    search = request.GET.get("search", "")
    profile = _active()

    def load_customers():
        customers, conn_error = [], None
        if profile:
            try:
                customers = master.list_customers(profile, search)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca master pelanggan")
        else:
            conn_error = CONN_ERROR
        return {"rows": customers, "conn_error": conn_error}

    return render(
        request,
        "Admin/MasterData/Customers",
        props={"customers": defer(load_customers)},
    )


def suppliers_index(request):
    profile = _active()

    def load_suppliers():
        suppliers, conn_error = [], None
        if profile:
            try:
                with mssql.cursor(profile) as cur:
                    cur.execute(
                        "SELECT kd_supplier, kd_kota, nama, alamat, telepon, fax, "
                        "kontak, hp, email, kd_bank, rekening, jenis, keterangan "
                        "FROM m_supplier ORDER BY nama"
                    )
                    suppliers = reporting.dictify(cur)
                    suppliers = reporting.clean_rows(suppliers)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca supplier")
        else:
            conn_error = CONN_ERROR
        return {"rows": suppliers, "conn_error": conn_error}

    return render(
        request,
        "Admin/MasterData/Supplier",
        props={"suppliers": defer(load_suppliers)},
    )


def sync_history_index(request):
    def load_sync():
        # SQLite-only (SyncLog), no MS SQL involved — conn_error stays None,
        # kept in the payload shape only because SyncHistory.vue expects the key.
        syncs = [
            {
                "id": s.id,
                "created_at": _local(s.created_at),
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


# --- Update Barang (WRITE ke MS SQL legacy) --------------------------------

_STATUS_FIELD = {
    "m_barang": BarangUpdateLog.Field.STATUS_BARANG,
    "m_barang_divisi": BarangUpdateLog.Field.STATUS_DIVISI,
    "m_barang_satuan": BarangUpdateLog.Field.STATUS_SATUAN,
}

# Nama tabel MS SQL tak boleh muncul di toast. Label disalin dari
# frontend/pages/Admin/MasterData/UpdateBarang.vue (bagian "Ketersediaan").
_STATUS_LABELS = {
    "m_barang": "status barang",
    "m_barang_divisi": "ketersediaan per divisi",
    "m_barang_satuan": "ketersediaan per satuan",
}


def update_barang_index(request):
    # Ikut koneksi aktif (dipilih di navbar) — tidak ada pemilihan server terpisah.
    profile = _active()
    search = request.GET.get("search", "")

    # Deferred: m_barang + m_barang_satuan + m_barang_divisi bisa makan detik-an
    # tanpa cache hangat (core/cache.py) — shell (filter, dsb) tetap tampil instan.
    def load_items():
        items, conn_error = [], None
        if profile:
            try:
                items = master.list_barang_edit(profile, search)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca barang")
        else:
            conn_error = CONN_ERROR
        return {"rows": items, "conn_error": conn_error}

    # Saran harga: katalog PENUH (bukan hasil search/TOP di atas) — tombol
    # "Saran Harga" harus melihat semua barang, bukan cuma yang sedang tampil.
    def load_saran():
        if not profile:
            return {"rows": [], "conn_error": CONN_ERROR}
        try:
            return {"rows": master.list_saran_harga(profile), "conn_error": None}
        except pyodbc.Error as exc:
            return {"rows": [], "conn_error": mssql.friendly_error(exc, "Gagal membaca saran harga")}

    # Audit harga berpecahan — grup sendiri supaya tidak menahan `items`.
    def load_pecahan():
        if not profile:
            return {"rows": [], "conn_error": CONN_ERROR}
        try:
            return {"rows": master.list_harga_pecahan(profile), "conn_error": None}
        except pyodbc.Error as exc:
            return {"rows": [], "conn_error": mssql.friendly_error(exc, "Gagal membaca audit harga")}

    return render(
        request,
        "Admin/MasterData/UpdateBarang",
        props={
            "active": profile.as_dict() if profile else None,
            "profile_type": profile.db_type if profile else None,
            "has_modal": bool(mssql.get_cost_source(profile)) if profile else False,
            "items": defer(load_items),
            "saran": defer(load_saran, group="saran"),
            "pecahan": defer(load_pecahan, group="pecahan"),
            "filters": {"search": search},
        },
    )


def update_barang_harga(request):
    # Selalu tulis ke koneksi aktif SAAT INI (server-side), bukan id yang dikirim
    # client — kalau tidak, halaman ini di tab lain yang masih terbuka setelah user
    # ganti koneksi di navbar akan menulis ke server LAMA meski UI-nya menampilkan
    # data server BARU (props.active sudah refresh, tapi id lama tetap terkirim).
    profile = _active()
    data = get_data(request)
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return _redirect_back(data, "/admin-panel/master/update-barang")
    kd_barang = (data.get("kd_barang") or "").strip()
    nama_barang = (data.get("nama") or "").strip()
    prices = data.get("prices") or {}  # {kd_satuan: harga_jual}
    try:
        changes = master.update_harga(profile, kd_barang, prices)
        log_barang_updates(
            request, profile, kd_barang, nama_barang,
            [
                (BarangUpdateLog.Field.HARGA, c["kd_satuan"], c["harga_lama"], c["harga_baru"])
                for c in changes
            ],
        )
        log_activity(request, "barang", f"Update harga {kd_barang} ({profile.name}): {len(changes)} satuan")
        request.session["flash_success"] = f"Harga {kd_barang} diperbarui ({len(changes)} satuan)."
    except master.HargaTidakBulat as exc:
        request.session["flash_error"] = f"Harga {kd_barang} ditolak. {exc}"
    except pyodbc.Error as exc:
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal update harga")
    return _redirect_back(data, "/admin-panel/master/update-barang")


def update_barang_harga_massal(request):
    """Terapkan banyak harga sekaligus (Saran Harga / Harga Berpecahan).

    Tetap lewat master.update_harga per barang supaya validasi harga bulat,
    hitung margin, invalidasi cache, dan BarangUpdateLog ikut jalan — tidak ada
    jalur tulis harga kedua yang perlu dijaga terpisah.
    """
    profile = _active()
    data = get_data(request)
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return _redirect_back(data, "/admin-panel/master/update-barang")

    # items: [{kd_barang, kd_satuan, harga, nama?}] -> {kd_barang: {kd_satuan: harga}}
    per_barang: dict = {}
    nama_map: dict = {}
    items = data.get("items")
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        kb = (it.get("kd_barang") or "").strip()
        ks = (it.get("kd_satuan") or "").strip()
        if not kb or not ks:
            continue
        per_barang.setdefault(kb, {})[ks] = it.get("harga")
        nama_map.setdefault(kb, (it.get("nama") or "").strip())

    if not per_barang:
        request.session["flash_error"] = "Tidak ada baris yang dipilih."
        return _redirect_back(data, "/admin-panel/master/update-barang")

    # ponytail: satu transaksi per barang (update_harga sudah atomic per barang).
    # Kalau jumlah baris tumbuh sampai ribuan, baru pertimbangkan batch tunggal.
    total, gagal = 0, []
    for kb, prices in per_barang.items():
        try:
            changes = master.update_harga(profile, kb, prices)
        except master.HargaTidakBulat as exc:
            gagal.append(f"{kb} ({exc})")
            continue
        except pyodbc.Error as exc:
            gagal.append(f"{kb} ({mssql.friendly_error(exc, 'gagal')})")
            continue
        total += len(changes)
        log_barang_updates(
            request, profile, kb, nama_map.get(kb, ""),
            [
                (BarangUpdateLog.Field.HARGA, c["kd_satuan"], c["harga_lama"], c["harga_baru"])
                for c in changes
            ],
        )

    log_activity(
        request, "barang",
        f"Terapkan harga massal ({profile.name}): {total} satuan pada {len(per_barang) - len(gagal)} barang",
    )
    if gagal:
        request.session["flash_error"] = (
            f"{total} satuan diperbarui. {len(gagal)} barang gagal: " + "; ".join(gagal[:5])
            + (" …" if len(gagal) > 5 else "")
        )
    else:
        request.session["flash_success"] = f"{total} satuan harga diperbarui pada {len(per_barang)} barang."
    return _redirect_back(data, "/admin-panel/master/update-barang")


def update_barang_status(request):
    # Sama seperti update_barang_harga: selalu pakai koneksi aktif server-side.
    profile = _active()
    data = get_data(request)
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return _redirect_back(data, "/admin-panel/master/update-barang")
    kd_barang = (data.get("kd_barang") or "").strip()
    nama_barang = (data.get("nama") or "").strip()
    table = data.get("table") or ""
    status = data.get("status")
    kd_divisi = data.get("kd_divisi") or None
    try:
        result = master.update_status(profile, kd_barang, table, status, kd_divisi)
        log_barang_updates(
            request, profile, kd_barang, nama_barang,
            [(_STATUS_FIELD.get(table, table), kd_divisi or "", result["lama"], status)],
        )
        log_activity(request, "barang", f"Update status {table} {kd_barang} -> {status} ({profile.name})")
        label = _STATUS_LABELS.get(table, table)
        request.session["flash_success"] = f"Perubahan {label} untuk {kd_barang} disimpan."
    except pyodbc.Error as exc:
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal update status")
    except ValueError as exc:
        # Penolakan whitelist dari master.update_status — pesannya sudah Indonesia.
        request.session["flash_error"] = f"Gagal update status: {exc}"
    return _redirect_back(data, "/admin-panel/master/update-barang")


def update_barang_detail(request):
    """Detail satu barang (satuan/harga/status, format list_barang_edit) dari
    koneksi AKTIF — dipakai halaman Pergerakan Harga untuk membuka modal edit
    yang sama persis dengan Update Barang."""
    profile = _active()
    kd_barang = (request.GET.get("kd_barang") or "").strip()
    if not profile or not kd_barang:
        return JsonResponse({"item": None, "error": CONN_ERROR if not profile else "Kode barang kosong."})
    try:
        rows = master.list_barang_edit(profile, kd_barang)
    except pyodbc.Error as exc:
        return JsonResponse({"item": None, "error": mssql.friendly_error(exc, "Gagal membaca barang")})
    key = kd_barang.strip().upper()
    item = next((r for r in rows if r["kd_barang"].strip().upper() == key), None)
    return JsonResponse({
        "item": item,
        "error": None if item else f"Barang {kd_barang} tidak ditemukan di koneksi {profile.name}.",
    })


def update_barang_riwayat(request):
    """Riwayat perubahan (harga/status) untuk satu barang — dipakai modal 'Riwayat' di kartu."""
    profile = _active()
    kd_barang = (request.GET.get("kd_barang") or "").strip()
    if not profile or not kd_barang:
        return JsonResponse({"rows": []})
    logs = BarangUpdateLog.objects.filter(profile=profile, kd_barang=kd_barang).order_by("-created_at")[:100]
    rows = [
        {
            "field": log.field,
            "field_label": log.get_field_display(),
            "kd_ref": log.kd_ref,
            "nilai_lama": log.nilai_lama,
            "nilai_baru": log.nilai_baru,
            "username": log.username,
            "created_at": timezone.localtime(log.created_at).isoformat(),
        }
        for log in logs
    ]
    return JsonResponse({"rows": rows})


def riwayat_update_barang_index(request):
    """Riwayat perubahan harga/status untuk SEMUA barang (lintas koneksi) — halaman terpisah
    dari modal 'Riwayat' per-kartu di update_barang_index."""
    f = request.GET
    kd_barang = (f.get("kd_barang") or "").strip()
    field = (f.get("field") or "").strip()
    date_from = _parse_date(f.get("date_from"))
    date_to = _eod(_parse_date(f.get("date_to")))
    profile_id = f.get("profile") or ""

    def load_riwayat():
        qs = BarangUpdateLog.objects.select_related("profile").all()
        if kd_barang:
            qs = qs.filter(kd_barang__icontains=kd_barang)
        if field:
            qs = qs.filter(field=field)
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        if profile_id:
            qs = qs.filter(profile_id=profile_id)

        rows = [
            {
                "id": log.id,
                "created_at": _local(log.created_at),
                "kd_barang": log.kd_barang,
                "nama_barang": log.nama_barang or "—",
                "field": log.field,
                "field_label": log.get_field_display(),
                "kd_ref": log.kd_ref,
                "nilai_lama": log.nilai_lama,
                "nilai_baru": log.nilai_baru,
                "username": log.username or "—",
                "profile_name": log.profile_name or "—",
            }
            for log in qs[:500]
        ]
        return {"rows": rows}

    return render(
        request,
        "Admin/MasterData/RiwayatUpdateBarang",
        props={
            "data": defer(load_riwayat),
            "profiles": [{"value": str(p.id), "label": p.name} for p in ServerProfile.objects.all()],
            "filters": {"kd_barang": kd_barang, "field": field, "date_from": f.get("date_from") or "", "date_to": f.get("date_to") or "", "profile": profile_id},
        },
    )


def pergerakan_harga_index(request):
    """Pergerakan Harga: perubahan harga terdeteksi snapshot harian (lintas
    koneksi, dari sumber apa pun — termasuk edit langsung di POS) + saran harga
    dari kolom keterangan untuk seluruh katalog server yang dipilih.

    Default menampilkan perubahan HARI INI; scope "semua" (atau filter tanggal
    eksplisit) membuka seluruh riwayat."""
    f = request.GET
    kd_barang = (f.get("kd_barang") or "").strip()
    date_from = _parse_date(f.get("date_from"))
    date_to = _eod(_parse_date(f.get("date_to")))
    profile_id = f.get("profile") or ""
    scope = f.get("scope") or "hari"

    active = _active()
    # Saran harga dibaca dari server yang dipilih di filter; tanpa pilihan,
    # ikut koneksi aktif. Penerapan saran tetap hanya ke koneksi aktif.
    saran_profile = ServerProfile.objects.filter(pk=profile_id).first() if profile_id else active

    def load_data():
        qs = BarangHargaChange.objects.all()
        if kd_barang:
            qs = qs.filter(kd_barang__icontains=kd_barang)
        if date_from:
            qs = qs.filter(detected_at__gte=date_from)
        if date_to:
            qs = qs.filter(detected_at__lte=date_to)
        if not date_from and not date_to and scope != "semua":
            qs = qs.filter(detected_at__gte=timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0))
        if profile_id:
            qs = qs.filter(profile_id=profile_id)
        rows = [
            {
                "id": c.id,
                "detected_at": _local(c.detected_at),
                "kd_barang": c.kd_barang,
                "nama_barang": c.nama_barang or "—",
                "kd_satuan": c.kd_satuan,
                "harga_lama": float(c.harga_lama),
                "harga_baru": float(c.harga_baru),
                "selisih": float(c.harga_baru - c.harga_lama),
                "profile_id": c.profile_id,
                "profile_name": c.profile_name or "—",
            }
            for c in qs[:500]
        ]

        saran, saran_error = [], None
        if saran_profile:
            try:
                saran = master.list_saran_harga(saran_profile)
            except pyodbc.Error as exc:
                saran_error = mssql.friendly_error(exc, "Gagal membaca saran harga")
        else:
            saran_error = CONN_ERROR
        return {"rows": rows, "saran": saran, "saran_error": saran_error}

    last = HargaSnapshotRun.objects.order_by("-ran_at").first()
    last_run = (
        {
            "ran_at": _local(last.ran_at, "%Y-%m-%d %H:%M"),
            "profile_name": last.profile_name or "—",
            "changes": last.changes,
            "total": last.total,
        }
        if last
        else None
    )

    return render(
        request,
        "Admin/MasterData/PergerakanHarga",
        props={
            "data": defer(load_data),
            "active": active.as_dict() if active else None,
            "profile_type": active.db_type if active else None,
            "saran_profile": {"id": saran_profile.id, "name": saran_profile.name} if saran_profile else None,
            "profiles": [{"value": str(p.id), "label": p.name} for p in ServerProfile.objects.all()],
            "filters": {
                "kd_barang": kd_barang,
                "date_from": f.get("date_from") or "",
                "date_to": f.get("date_to") or "",
                "profile": profile_id,
                "scope": scope,
            },
            "last_run": last_run,
        },
    )


# --- Sinkronisasi Harga antar-server ---------------------------------------


def sync_harga_index(request):
    profiles = [p.as_dict() for p in ServerProfile.objects.all()]
    mode = request.GET.get("mode", "gudang_grosir")
    src = ServerProfile.objects.filter(pk=request.GET.get("src")).first() if request.GET.get("src") else None
    dst = ServerProfile.objects.filter(pk=request.GET.get("dst")).first() if request.GET.get("dst") else None

    # Deferred: compare_harga_jual membaca m_barang_satuan PENUH di DUA server.
    # Sebelum ini jalan sinkron sebelum first paint, jadi cache dingin = halaman
    # membeku. Form-nya tetap prop biasa supaya langsung bisa dipakai.
    def load_diff():
        diff, conn_error = [], None
        if src and dst:
            try:
                diff = master.compare_harga_jual(src, dst)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membandingkan harga")
            except Exception:
                # ponytail: prop deferred yang meledak = halaman rusak; di UI tak
                # ada bedanya per-tipe, detailnya ke log.
                log.exception("compare_harga_jual gagal")
                conn_error = "Gagal membandingkan harga. Cek log server."
        return {"diff": diff, "conn_error": conn_error}

    return render(
        request,
        "Admin/MasterData/SyncHarga",
        props={
            "profiles": profiles,
            "mode": mode,
            "src": src.id if src else None,
            "dst": dst.id if dst else None,
            "compare": defer(load_diff),
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
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal sinkron")
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

    # Deferred: compare_entity membaca m_barang/m_customer/m_supplier PENUH di
    # DUA server — sama seperti sync_harga_index, jangan blokir first paint.
    def load_diff():
        diff, conn_error = [], None
        if src and dst and entity in master._SYNC_ENTITIES:
            try:
                diff = master.compare_entity(entity, src, dst)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membandingkan data")
            except Exception:
                log.exception("compare_entity(%s) gagal", entity)
                conn_error = "Gagal membandingkan data. Cek log server."
        return {"diff": diff, "conn_error": conn_error}

    return render(
        request,
        "Admin/MasterData/SyncMaster",
        props={
            "profiles": profiles,
            "entities": _SYNC_MASTER_ENTITIES,
            "col_labels": master.COL_LABELS,
            "entity": entity,
            "src": src.id if src else None,
            "dst": dst.id if dst else None,
            "compare": defer(load_diff),
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
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal sinkron")
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
            "timestamp": _local(a.timestamp),
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


# --- Stok Akhir (computed from movement card, dipaginasi di server) --------
#
# Dulu halaman ini mengirim SELURUH universe barang×divisi ke peramban dalam
# satu prop deferred. Terukur di RTL PUSAT: 54.955 baris = 17,9 MB JSON (1,35
# MB gzip) dan 123 MB heap JS untuk satu kali buka; di Firefox Android tabnya
# tak pernah selesai memuat. Hanya 14.123 baris (26%) yang stoknya bukan nol,
# dan menyaring per divisi tak menolong — server ini cuma punya satu divisi.
#
# Mesin stoknya tidak disentuh (inv.stok_akhir_per_tanggal — lihat catatan FMI
# Stok soal kenapa bukan m_barang_stok_akhir). Yang berubah: siapa yang
# memotong halaman. Polanya persis FMI Stok — hitung penuh di Python, iris di
# server, kirim satu halaman, export lewat rute sendiri.
_STOK_COLUMNS = [
    {"key": "kd_divisi", "label": "Kode Div."},
    {"key": "divisi", "label": "Divisi"},
    {"key": "kd_barang", "label": "Kode"},
    {"key": "barang", "label": "Barang"},
    {"key": "kategori", "label": "Kategori"},
    {"key": "merk", "label": "Merk"},
    {"key": "model", "label": "Model"},
    {"key": "warna", "label": "Warna"},
    {"key": "ukuran", "label": "Ukuran"},
    {"key": "stok_akhir", "label": "Stok Akhir"},
    {"key": "harga_average", "label": "Harga Avg"},
    {"key": "harga_jual", "label": "Harga Jual"},
    {"key": "nominal", "label": "Nominal"},
    {"key": "harga_beli_akhir", "label": "Harga Beli Akhir"},
]


def _tanpa_kolom(payload, hidden: set[str]):
    """Payload kolumnar tanpa kolom `hidden` — SALINAN, bukan hasil edit.

    Payload ini dicache PER PROFIL, bukan per user (`stok_kolumnar:<tanggal>`).
    Membuang kolom dengan `del payload["data"][c]` akan menghapus kolom itu
    untuk SEMUA user sampai pemanas berikutnya menimpanya — kegagalan hening
    yang arahnya justru merusak, dan yang hanya muncul kalau user terbatas
    kebetulan membuka halaman lebih dulu.

    Yang disalin cuma ketiga map kecil (~14 entri); larik kolomnya tetap
    dipakai bersama, jadi tak ada biaya memori berarti.
    """
    if not payload or not hidden:
        return payload
    keep = [c for c in payload["cols"] if c not in hidden]
    if len(keep) == len(payload["cols"]):
        return payload
    return {
        "cols": keep,
        "n": payload["n"],
        "types": {c: payload["types"][c] for c in keep},
        "dict": {c: payload["dict"][c] for c in keep if c in payload["dict"]},
        "data": {c: payload["data"][c] for c in keep},
    }


def _stok_sort_key(row, key):
    """Kunci urut aman untuk tabel yang kolomnya campur teks dan angka.

    `(r.get(k) or 0)` seperti di FMI Stok hanya benar bila seluruh kolomnya
    numerik: di kolom teks, sel kosong jadi 0 lalu dibandingkan dengan str dan
    sort meledak TypeError. Di sini tiap kolom menghasilkan bentuk tuple yang
    seragam, dan None selalu jatuh ke belakang.
    """
    v = row.get(key)
    if v is None:
        return (1, "", 0.0)
    if isinstance(v, (int, float)):
        return (0, "", float(v))
    return (0, str(v).lower(), 0.0)


def _stok_rows(profile, f):
    """(baris tersaring+terurut, daftar kategori yang ada).

    Kategori dikumpulkan SEBELUM filter kategori dipakai — kalau sesudah,
    memilih satu kategori akan menghapus semua pilihan lain dari dropdown.
    """
    levels = inv.stok_akhir_per_tanggal(
        profile, tanggal=f["date_to"], kd_divisi=f["kd_divisi"] or None)

    kategoris = sorted({r["kategori"] for r in levels if r["kategori"]})

    q = f["search"].lower()
    kat = f["kategori"]
    # `divisi` = NAMA divisi, bukan kode: itu yang dipegang layar (payload
    # kolumnar mengamuskan nama, bukan kode) dan yang dikirim balik tombol
    # export. `kd_divisi` tetap ada untuk pemanggil lain yang punya kodenya.
    div = f["divisi"]
    rows = [
        r for r in levels
        if (not kat or r["kategori"] == kat)
        and (not div or r["divisi"] == div)
        and (not q or q in r["barang"].lower() or q in r["kd_barang"].lower()
             or q in (r["merk"] or "").lower())
    ]
    rows.sort(key=lambda r: _stok_sort_key(r, f["sort"]),
              reverse=f["sort_dir"] == "desc")
    return rows, kategoris


def _stok_params(request, **kw):
    """Parameter jalur EXPORT Stok Akhir.

    Layarnya sendiri tak lagi memakai ini — sejak seluruh data dipegang klien,
    saring/urut/paginasi terjadi di peramban. Export tetap di server (SheetJS
    atas 55rb baris adalah lonjakan heap yang justru sedang dihindari), jadi ia
    perlu menerima ulang keadaan filter yang sedang dilihat pengguna.
    """
    f = reporting.parse_report_params(request, rpt.SORTS_STOK, "barang", **kw)
    # Halaman memakai satu parameter `tanggal`, bukan pasangan date_mode/date
    # milik laporan rentang. Timpa hasil parse-nya supaya keduanya tak berbeda.
    f["date_to"] = _eod(_parse_date(request.GET.get("tanggal")) or dt.datetime.now())
    f["kd_divisi"] = (request.GET.get("kd_divisi") or "").strip()
    f["divisi"] = (request.GET.get("divisi") or "").strip()
    f["kategori"] = (request.GET.get("kategori") or "").strip()
    # Daftar barang wajar dibaca A→Z; default parse_report_params DESC karena
    # laporan lain diurut tanggal (terbaru dulu).
    if not request.GET.get("sort_dir"):
        f["sort_dir"] = "asc"
    return f


def stock_index(request):
    """Kirim SELURUH katalog stok ke peramban dalam bentuk kolumnar.

    Halaman ini sengaja tidak dipaginasi server: gunanya justru mencari satu SKU
    di antara 55rb tanpa bolak-balik. Yang membuatnya mustahil dulu bukan jumlah
    barisnya, melainkan bentuk payloadnya — 15,6 MB "list of dict" yang jadi
    54.955 objek reaktif Vue (123 MB heap). Bentuk kolumnar + kamus mengirim
    data yang sama dalam 5,3 MB; lihat catatan panjang di
    apps/inventory/services.py::_kolumnar.

    Tanggal satu-satunya filter yang perlu ke server. Divisi/kategori/cari
    dikerjakan di klien atas data yang sudah ada di sana.
    """
    tanggal = _parse_date(request.GET.get("tanggal")) or dt.datetime.now()
    hidden = _hidden_fields(request)

    # Tetap deferred: shell + panel filter terlukis seketika. Pemanas terjadwal
    # menjaga tanggal hari ini tetap hangat, tapi tanggal lampau dan menit-menit
    # pertama setelah server restart masih bisa puluhan detik.
    def load_stok():
        profile = _active()
        payload, divisi_list, conn_error = None, [], None
        if profile:
            try:
                divisi_list = inv.list_divisi(profile)
                payload = _tanpa_kolom(
                    inv.stok_akhir_kolumnar(profile, tanggal=_eod(tanggal)), hidden)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca stok")
        else:
            conn_error = CONN_ERROR
        return {"tabel": payload, "divisi_list": divisi_list, "conn_error": conn_error}

    return render(request, "Admin/Inventory/Stock", props={
        "stok": defer(load_stok),
        "filters": {"tanggal": _eod(tanggal).strftime("%Y-%m-%d")},
    })


def stock_export(request):
    f = _stok_params(request, max_range_days=None)
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/admin-panel/inventory/stock")
    try:
        rows, _ = _stok_rows(profile, f)
    except pyodbc.Error as exc:
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal export")
        return redirect("/admin-panel/inventory/stock")
    # Kolom yang tak boleh dilihat juga tak boleh diunduh — kalau tidak,
    # pembatasan di layar cuma kosmetik: tekan Export, dapat semuanya.
    hidden = _hidden_fields(request)
    columns = [c for c in _STOK_COLUMNS if c["key"] not in hidden]
    log_activity(request, "export", f"Export stok-akhir: {len(rows)} baris")
    return reporting.xlsx_response("stok-akhir", columns, rows)


def barang_histori_index(request):
    kd_barang = request.GET.get("kd_barang", "").strip()
    kd_divisi = request.GET.get("kd_divisi", "")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))

    # Kolom `harga` di sini berisi harga BELI untuk baris pembelian dan harga
    # JUAL untuk baris penjualan — satu kolom, dua arti, ditentukan kolom
    # `transaksi` di sebelahnya. Karena itu ia butuh KEDUA izin: menampilkannya
    # bagi pemegang izin harga jual saja akan membocorkan modal.
    user = getattr(request, "user", None)
    sembunyikan_harga = bool(user and user.is_authenticated) and not (
        user.can_see("harga_jual") and user.can_see("harga_beli")
    )

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
                if sembunyikan_harga:
                    # Baris histori tidak dicache, jadi aman diubah di tempat.
                    for r in rows:
                        r.pop("harga", None)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca histori")
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
        return ditolak(
            request,
            "Halaman ini hanya untuk pengelola utama",
            "Pengaturan siapa boleh membuka apa hanya bisa diubah oleh pengelola "
            "utama aplikasi.",
        )
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
                    # Dikirim sebagai "boleh melihat" walau disimpan sebagai
                    # larangan: layar pengaturan tak boleh memaksa siapa pun
                    # berpikir terbalik saat mencentang.
                    "allowed_data_keys": sorted(DATA_KEY_SET - u.hidden_data()),
                }
                for u in users
            ],
            "menus": assignable_menus(),
            "data_keys": DATA_KEYS,
            # Urutan + label section untuk pengelompokan di UI (hanya section
            # yang punya menu assignable).
            "sections": [
                {"key": s, "label": SECTION_LABELS[s]}
                for s in SECTIONS
                if any(m["section"] == s for m in assignable_menus())
            ],
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

    # Layar mengirim yang BOLEH dilihat; yang disimpan kebalikannya. Konversi
    # ini satu-satunya tempat kedua bentuk itu bertemu — lihat alasan memilih
    # daftar larangan di apps/auth_app/models.py.
    boleh = {k for k in (data.get("data_keys") or []) if k in DATA_KEY_SET}
    user.hidden_data_keys = sorted(DATA_KEY_SET - boleh)

    user.save(update_fields=["allowed_menu_keys", "hidden_data_keys"])
    log_activity(request, "menu", f"Set menu {user.username}: {','.join(keys) or '(kosong)'}")
    if user.hidden_data_keys:
        log_activity(request, "menu",
                     f"Sembunyikan nilai untuk {user.username}: {','.join(user.hidden_data_keys)}")
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
        # Export (XLSX/CSV) melepas clamp 92 hari — akses rentang berapapun; jalur
        # interaktif tetap di-clamp supaya tak sengaja scan seluruh histori di layar.
        # Sebuah spec boleh melepas clamp itu juga (max_range_days=None) bila
        # pertanyaannya memang tentang riwayat panjang, bukan penjualan satu
        # periode — lihat Klasifikasi Pelanggan.
        max_range_days=None if export else spec.get("max_range_days", reporting.MAX_RANGE_DAYS),
        enable_recent=spec.get("enable_recent", False) and not export,
        recent_sort=spec.get("recent_sort"),
        default_from_days=spec.get("default_from_days"),
        default_sort_dir=spec.get("default_sort_dir", "desc"),
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
        "sort_keys": f["sort_keys"],
        "page": f["page"], "per_page": f["per_page"],
        "recent": f["recent"],
    }
    for k in spec.get("filter_keys", []):
        filters[k] = f[k]
    # Filter yang punya nilai bawaan bermakna (ambang klasifikasi) dikirim
    # TERISI, bukan kosong. Kotak ambang yang tampil kosong menyembunyikan
    # aturan yang sedang berlaku: pengguna melihat 195 pelanggan "Hilang" tanpa
    # cara tahu bahwa batasnya 180 hari, dan mengubahnya jadi menebak-nebak.
    for k, default in (spec.get("filter_defaults") or {}).items():
        if not filters.get(k):
            filters[k] = str(default)
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
                # spec["inner"]/apply_column_filters dulu di luar try — bentuk
                # filter yang aneh jadi 500, bukan banner.
                try:
                    inner, params = spec["inner"](f)
                    inner, params = reporting.apply_column_filters(inner, params, f)
                    for read_profile in mssql.report_read_profiles(profile):
                        rows, total, summary, options = [], 0, {}, {}  # reset per attempt
                        try:
                            with mssql.report_cursor(read_profile) as cur:
                                if f["recent"]:
                                    rows, total, summary_sql = reporting.run_recent(cur, inner, params, f)
                                else:
                                    rows, total = reporting.run_paged(cur, inner, params, f)
                                    summary_sql = inner
                                cur.execute(f"SELECT {spec['summary']} FROM ({summary_sql}) AS q", params)
                                summary = reporting.one_row(cur)
                            if spec.get("options"):
                                options = spec["options"](read_profile)
                            conn_error = None
                            break
                        except pyodbc.Error as exc:
                            conn_error = mssql.friendly_error(exc, "Gagal membaca laporan")
                except pyodbc.Error as exc:
                    conn_error = mssql.friendly_error(exc, "Gagal membaca laporan")
                except Exception:
                    log.exception("gagal menyiapkan laporan %s", spec.get("component"))
                    conn_error = "Filter yang dipilih tidak bisa diproses. Kembalikan filter ke bawaan."
            else:
                conn_error = CONN_ERROR
            # Izin nilai uang (User.hidden_data_keys). Opt-in per spec lewat
            # `money_fields`: laporan yang tak menyebutkannya tak berubah
            # perilakunya. Dijatuhkan DI SINI, setelah SQL — bukan dengan
            # membangun SELECT lain — supaya cuma ada satu query untuk dirawat,
            # dan tak mungkin ada jalur yang lupa menyaring.
            hidden = _hidden_fields(request) & set(spec.get("money_fields", ()))
            if hidden:
                rows = [{k: v for k, v in r.items() if k not in hidden} for r in rows]
                summary = {k: v for k, v in summary.items() if k not in hidden}
            # Peringatan rentang tanggal BUKAN kegagalan koneksi — kanal sendiri
            # supaya tak dirender sebagai banner error (atau digabung ke dalamnya).
            return {"rows": rows, "total": total, "summary": summary,
                    "options": options, "conn_error": conn_error,
                    "notice": f["warning"] or None}

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

        # Export = STREAMING XLSX: query di-execute lalu ditulis baris-per-baris
        # ke openpyxl write_only (tuple langsung dari cursor, TANPA numpuk
        # list-of-dict di RAM). Replica dulu, fallback primary (sama spt
        # _report_view). TOP EXPORT_CAP jaga batas baris Excel (~1jt); clamp
        # rentang tanggal sudah dilepas di _spec_params(export=True).
        order_sql = f"SELECT TOP {reporting.EXPORT_CAP} * FROM ({inner}) AS q ORDER BY {f['order_by']}"
        # Kolom uang dicabut dari DAFTAR KOLOM, jadi nilainya tak pernah ditulis
        # ke sel walau tetap ikut di hasil query. Export adalah jalur yang paling
        # mudah terlewat saat menambah pembatasan — dan pembatasan yang terlewat
        # di sini membuat pembatasan di layar tak berarti apa-apa.
        columns = _kolom_tanpa_uang(request, spec)
        resp, last_exc = None, None
        for read_profile in mssql.report_read_profiles(profile):
            try:
                with mssql.report_cursor(read_profile) as cur:
                    cur.execute(order_sql, params)
                    resp = reporting.xlsx_stream_response(spec["filename"], columns, cur)
                break
            except pyodbc.Error as exc:
                last_exc = exc
        if resp is None:
            request.session["flash_error"] = mssql.friendly_error(last_exc, "Gagal export")
            return redirect(spec["url"])
        log_activity(request, "export", f"Export {spec['filename']}")
        return resp

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

_PENJUALAN_HPP = {
    "component": "Admin/Reports/PenjualanHpp",
    "url": "/admin-panel/laporan/penjualan-hpp",
    "inner": rpt.penjualan_hpp,
    "sorts": rpt.SORTS_PENJUALAN_HPP,
    "default_sort": "tanggal",
    "summary": rpt.SUMMARY_PENJUALAN_HPP,
    "filter_keys": ["kd_divisi"],
    "filters": rpt.FILTERS_PENJUALAN_HPP,
    "enable_recent": True,
    "recent_sort": "tanggal",
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "laba-per-barang",
    "columns": [
        {"key": "no_transaksi", "label": "No. Transaksi"},
        {"key": "tanggal", "label": "Tanggal"},
        {"key": "divisi", "label": "Divisi"},
        {"key": "customer", "label": "Customer"},
        {"key": "kd_barang", "label": "Kode Barang"},
        {"key": "barang", "label": "Barang"},
        {"key": "kategori", "label": "Kategori"},
        {"key": "qty", "label": "Qty", "align": "right", "format": "number"},
        {"key": "satuan", "label": "Satuan"},
        {"key": "harga", "label": "Harga", "align": "right", "format": "rupiah"},
        {"key": "harga_pokok", "label": "Harga Pokok", "align": "right", "format": "rupiah"},
        {"key": "total_bersih", "label": "Total Bersih", "align": "right", "format": "rupiah"},
        {"key": "total_harga_pokok", "label": "Total HPP", "align": "right", "format": "rupiah"},
        {"key": "laba", "label": "Laba", "align": "right", "format": "rupiah"},
        {"key": "margin", "label": "Margin %", "align": "right", "format": "persen"},
    ],
}
penjualan_hpp = _report_view(_PENJUALAN_HPP)
penjualan_hpp_export = _report_export(_PENJUALAN_HPP)

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
def bantuan(request):
    # ponytail: isinya statis dan hidup di komponen Vue-nya. Tak ada query,
    # jadi tak perlu defer dan tak perlu prop.
    return render(request, "Admin/Bantuan", props={})


def stok_divisi(request):
    """Cek stok cepat: SELALU saldo HARI INI (point-in-time), tanpa input tanggal.

    date_from WAJIB None supaya _snapshot_date_if_usable() aktif. Versi lama
    memaksa date_from = now-30d, sehingga guard `date_from < snapshot` di
    apps/inventory/services.py selalu gagal dan tiap load me-re-agregasi
    SELURUH histori sejak tutup buku — ringkasan stok harian dibangun tiap
    malam tapi tak pernah terpakai di halaman ini.

    Butuh saldo per tanggal lampau? Menu "Stok Akhir" (punya filter tanggal dan
    tetap memakai jalur snapshot).
    """
    kd_divisi = request.GET.get("kd_divisi", "")

    def load():
        profile = _active()
        tabel, divisi_list, snapshot, conn_error = None, [], None, None
        if profile:
            try:
                t0 = time.perf_counter()
                divisi_list = inv.list_divisi(profile)
                snapshot = inv.snapshot_status(profile)
                # Kolumnar, sama seperti Stok Akhir: halaman ini juga mengirim
                # seluruh ~55rb baris ke peramban supaya cek stok bisa dicari
                # tanpa bolak-balik. Bentuk list-of-dict-nya 5,2 MB.
                tabel = inv.stock_levels_kolumnar(
                    profile,
                    kd_divisi=kd_divisi or None,
                    date_to=_eod(dt.datetime.now()),
                )
                log.info(
                    "stok_divisi(%s): %s baris, %.2fs",
                    kd_divisi or "semua", tabel["n"], time.perf_counter() - t0,
                )
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca stok divisi")
        else:
            conn_error = CONN_ERROR
        return {
            "tabel": tabel, "divisi_list": divisi_list,
            "snapshot": snapshot, "conn_error": conn_error,
        }

    return render(
        request,
        "Admin/Inventory/StokDivisi",
        props={"data": defer(load), "filters": {"kd_divisi": kd_divisi}},
    )

def mutasi_stok(request):
    """Mutasi stok per barang untuk sebuah periode (stok awal diasumsikan 0)."""
    kd_divisi = request.GET.get("kd_divisi", "")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    # Default: sejak 1 Januari tahun berjalan supaya seed/saldo lama (tanggal
    # tutup buku) selalu di bawah date_from dan tidak ikut terhitung.
    if not date_from:
        date_from = dt.datetime(dt.datetime.now().year, 1, 1)

    def load():
        profile = _active()
        rows, divisi_list, conn_error = [], [], None
        if profile:
            try:
                divisi_list = inv.list_divisi(profile)
                rows = inv.mutasi_stok(
                    profile,
                    date_from=date_from,
                    date_to=_eod(date_to) if date_to else None,
                    kd_divisi=kd_divisi or None,
                )
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca mutasi stok")
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "divisi_list": divisi_list, "conn_error": conn_error}

    return render(
        request,
        "Admin/Inventory/MutasiStok",
        props={
            "data": defer(load),
            "filters": {
                "kd_divisi": kd_divisi,
                "date_from": request.GET.get("date_from", ""),
                "date_to": request.GET.get("date_to", ""),
            },
        },
    )


def stok_awal_barang(request):
    tanggal = _parse_date(request.GET.get("tanggal"))
    tahun_raw = (request.GET.get("tahun") or "").strip()
    cutoff = None
    if tanggal:
        cutoff = tanggal  # date_from 00:00 -> saldo sebelum hari itu
    elif tahun_raw.isdigit() and 2000 <= int(tahun_raw) <= 2999:
        cutoff = dt.datetime(int(tahun_raw), 1, 1)

    def load():
        profile = _active()
        rows, conn_error = [], None
        if profile:
            try:
                rows = inv.stok_awal_barang(profile, cutoff=cutoff)
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca stok awal")
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "conn_error": conn_error}

    return render(
        request,
        "Admin/Inventory/StokAwalBarang",
        props={
            "data": defer(load),
            "filters": {"tanggal": request.GET.get("tanggal", ""), "tahun": tahun_raw},
        },
    )


# --- Transaksi Barang (laporan transaksi seluruh barang) -------------------
_TRANSAKSI_COLUMNS = [
    {"key": "tanggal", "label": "Tanggal"},
    {"key": "transaksi", "label": "Jenis"},
    {"key": "no_transaksi", "label": "No. Transaksi"},
    {"key": "divisi", "label": "Divisi"},
    {"key": "kd_barang", "label": "Kode"},
    {"key": "barang", "label": "Barang"},
    {"key": "masuk", "label": "Masuk"},
    {"key": "keluar", "label": "Keluar"},
    {"key": "satuan", "label": "Satuan"},
    {"key": "harga", "label": "Harga"},
]


def _transaksi_params(request):
    """Parse param laporan transaksi barang (semantik tanggal/closing custom)."""
    g = request.GET
    jenis = [j.strip() for j in (g.get("jenis") or "").split(",") if j.strip()]
    date_from = _parse_date(g.get("date_from"))
    date_to = _parse_date(g.get("date_to"))
    search = (g.get("search") or "").strip()
    kd_divisi = (g.get("kd_divisi") or "").strip()
    sort = g.get("sort") if g.get("sort") in rpt.SORTS_TRANSAKSI_BARANG else "tanggal"
    sort_dir = "asc" if (g.get("sort_dir") or "desc").lower() == "asc" else "desc"
    try:
        page = max(1, int(g.get("page") or 1))
    except ValueError:
        page = 1
    try:
        per_page = min(reporting.MAX_PER_PAGE, max(10, int(g.get("per_page") or reporting.DEFAULT_PER_PAGE)))
    except ValueError:
        per_page = reporting.DEFAULT_PER_PAGE
    recent = not (date_from or date_to or jenis or search) and page == 1
    if recent:
        per_page = reporting.RECENT_LIMIT  # first load: tampilkan N terbaru (sesuai banner)
    return {
        "jenis": jenis,
        "date_from": date_from,
        "date_to": _eod(date_to) if date_to else None,
        "search": search,
        "kd_divisi": kd_divisi,
        "sort": sort,
        "sort_dir": sort_dir,
        "page": page,
        "per_page": per_page,
        "recent": recent,
        "order_by": f"q.{rpt.SORTS_TRANSAKSI_BARANG[sort]} {sort_dir.upper()}",
        "date_from_s": g.get("date_from", ""),
        "date_to_s": g.get("date_to", ""),
    }


def _transaksi_inner(p):
    return rpt.transaksi_barang(
        jenis=p["jenis"],
        date_from=p["date_from"],
        date_to=p["date_to"],
        kd_divisi=p["kd_divisi"] or None,
        search=p["search"],
    )


def transaksi_barang(request):
    p = _transaksi_params(request)

    def load():
        rows, total, summary, options, conn_error = [], 0, {}, {}, None
        profile = _active()
        if profile:
            inner, params = _transaksi_inner(p)
            for read_profile in mssql.report_read_profiles(profile):
                rows, total, summary, options = [], 0, {}, {}
                try:
                    with mssql.report_cursor(read_profile) as cur:
                        if p["recent"]:
                            rows, total, summary_sql = reporting.run_recent(cur, inner, params, p)
                        else:
                            rows, total = reporting.run_paged(cur, inner, params, p)
                            summary_sql = inner
                        cur.execute(f"SELECT {rpt.SUMMARY_TRANSAKSI_BARANG} FROM ({summary_sql}) AS q", params)
                        summary = reporting.one_row(cur)
                    options = {"divisi": _opt_divisi(read_profile)}
                    conn_error = None
                    break
                except pyodbc.Error as exc:
                    conn_error = mssql.friendly_error(exc, "Gagal membaca transaksi")
        else:
            conn_error = CONN_ERROR
        # notice: halaman ini TIDAK memangkas rentang tanggal (_transaksi_params
        # punya semantik tanggalnya sendiri, tanpa clamp 92 hari), jadi tak ada
        # peringatan rentang untuk dilaporkan. Sebelumnya baris ini membaca
        # f["warning"] — nama yang tak pernah ada di scope ini, jadi setiap
        # pemuatan prop deferred halaman ini berakhir NameError (500), bukan
        # tabel.
        return {"rows": rows, "total": total, "summary": summary, "options": options,
                "conn_error": conn_error, "notice": None}

    return render(
        request,
        "Admin/Inventory/TransaksiBarang",
        props={
            "report": defer(load),
            "filters": {
                "date_from": p["date_from_s"], "date_to": p["date_to_s"], "date_mode": "range",
                "search": p["search"], "sort": p["sort"], "sort_dir": p["sort_dir"],
                "sort_keys": list(rpt.SORTS_TRANSAKSI_BARANG),
                "page": p["page"], "per_page": p["per_page"], "recent": p["recent"],
                "kd_divisi": p["kd_divisi"], "jenis": ",".join(p["jenis"]),
            },
        },
    )


def transaksi_barang_export(request):
    p = _transaksi_params(request)
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/admin-panel/inventory/transaksi")
    inner, params = _transaksi_inner(p)
    # Streaming XLSX (pola _report_export): tuple langsung dari cursor, tanpa
    # menumpuk list-of-dict rentang penuh di RAM.
    order_sql = f"SELECT TOP {reporting.EXPORT_CAP} * FROM ({inner}) AS q ORDER BY {p['order_by']}"
    resp, last_exc = None, None
    for read_profile in mssql.report_read_profiles(profile):
        try:
            with mssql.report_cursor(read_profile) as cur:
                cur.execute(order_sql, params)
                resp = reporting.xlsx_stream_response("transaksi-barang", _TRANSAKSI_COLUMNS, cur)
            break
        except pyodbc.Error as exc:
            last_exc = exc
    if resp is None:
        # Same policy as _report_export: surface the failure instead of
        # silently downloading an empty sheet.
        request.session["flash_error"] = mssql.friendly_error(last_exc, "Gagal export")
        return redirect("/admin-panel/inventory/transaksi")
    log_activity(request, "export", "Export transaksi-barang")
    return resp


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
    "default_sort": "nilai",
    "summary": rpt.SUMMARY_FMI_PENJUALAN,
    "filter_keys": ["kd_divisi"],
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "fmi-penjualan",
    "columns": [{"key": "kd_barang", "label": "Kode"}, {"key": "barang", "label": "Barang"}, {"key": "kategori", "label": "Kategori"}, {"key": "qty_terjual", "label": "Qty Terjual", "align": "right", "format": "number"}, {"key": "kontribusi_qty", "label": "Kontribusi Qty", "align": "right", "format": "persen"}, {"key": "akumulasi_qty", "label": "Akumulasi Qty", "align": "right", "format": "persen"}, {"key": "nilai", "label": "Nilai", "align": "right", "format": "rupiah"}, {"key": "kontribusi_nilai", "label": "Kontribusi Nilai", "align": "right", "format": "persen"}, {"key": "akumulasi_nilai", "label": "Akumulasi Nilai", "align": "right", "format": "persen"}, {"key": "kelas", "label": "Kelas (Pareto)"}],
}
fmi_penjualan = _report_view(_FMI_PENJUALAN)
fmi_penjualan_export = _report_export(_FMI_PENJUALAN)

# FMI Stok: bespoke (bukan _report_view) — stok dihitung engine asli
# (inv.stok_akhir_per_tanggal: movement engine + snapshot), BUKAN
# m_barang_stok_akhir yang sudah rusak/berhenti terisi. Angka "terjual" tetap
# SQL atas t_penjualan dalam rentang; join stok<->terjual di Python via _k.
_FMI_STOK_COLUMNS = [
    {"key": "kd_barang", "label": "Kode"}, {"key": "barang", "label": "Barang"},
    {"key": "kategori", "label": "Kategori"},
    {"key": "qty_stok", "label": "Qty Stok", "align": "right", "format": "number"},
    {"key": "nilai_stok", "label": "Nilai Stok", "align": "right", "format": "rupiah"},
    {"key": "terjual", "label": "Terjual", "align": "right", "format": "number"},
    {"key": "rasio", "label": "Rasio", "align": "right", "format": "number"},
    {"key": "status", "label": "Status"},
]


def _fmi_stok_rows(profile, f):
    """Baris FMI Stok terurut sesuai f — stok real per tanggal f['date_to'],
    velocity vs penjualan f['date_from']..f['date_to']. Barang tanpa harga jual
    (kresek/packaging) dan katalog mati (stok 0 & terjual 0) dikecualikan —
    konsisten aturan analisis FMI Penjualan."""
    from apps.inventory.services import _k

    levels = inv.stok_akhir_per_tanggal(
        profile, tanggal=f["date_to"], kd_divisi=f["kd_divisi"] or None)

    where = "h.tanggal >= ? AND h.tanggal <= ?"
    params = [f["date_from"], f["date_to"]]
    if f["kd_divisi"]:
        where += " AND h.kd_divisi = ?"
        params.append(f["kd_divisi"])
    with mssql.report_cursor(profile) as cur:
        cur.execute(
            "SELECT d.kd_barang, SUM(d.qty) AS terjual FROM t_penjualan_detail d "
            "INNER JOIN t_penjualan h ON d.no_transaksi = h.no_transaksi "
            f"WHERE {where} GROUP BY d.kd_barang", params)
        sold = {_k(r["kd_barang"]): float(r["terjual"] or 0) for r in reporting.dictify(cur)}

    days = max((f["date_to"].date() - f["date_from"].date()).days + 1, 1)
    agg = {}
    for r in levels:
        if r["harga_jual"] <= 0:
            continue  # barang non-jual — bukan objek analisis
        a = agg.setdefault(_k(r["kd_barang"]), {
            "kd_barang": r["kd_barang"], "barang": r["barang"],
            "kategori": r["kategori"], "qty_stok": 0.0, "nilai_stok": 0.0,
        })
        a["qty_stok"] += r["stok_akhir"]
        a["nilai_stok"] += r["nominal"]

    q = f["search"].lower()
    rows = []
    for kb, a in agg.items():
        terjual = sold.get(kb, 0.0)
        if a["qty_stok"] == 0 and terjual == 0:
            continue  # katalog mati — noise
        if q and q not in a["barang"].lower() and q not in a["kd_barang"].lower():
            continue
        a["terjual"] = terjual
        a["rasio"] = round(terjual / a["qty_stok"], 2) if a["qty_stok"] else None
        if terjual == 0:
            a["status"] = "Overstock"
        else:
            sisa_hari = a["qty_stok"] / (terjual / days)
            a["status"] = ("Kritis" if sisa_hari < rpt._FMI_STOK_KRITIS_HARI
                           else "Overstock" if sisa_hari > rpt._FMI_STOK_OVERSTOCK_HARI
                           else "Sehat")
        a["qty_stok"] = round(a["qty_stok"], 3)
        a["nilai_stok"] = round(a["nilai_stok"], 2)
        rows.append(a)

    key = f["sort"]
    rows.sort(key=lambda r: (r.get(key) is None, r.get(key) or 0),
              reverse=f["sort_dir"] == "desc")
    return rows


def fmi_stok(request):
    f = reporting.parse_report_params(request, rpt.SORTS_FMI_STOK, "qty_stok")
    f["kd_divisi"] = (request.GET.get("kd_divisi") or "").strip()

    def load_report():
        rows, total, summary, options, conn_error = [], 0, {}, {}, None
        profile = _active()
        if profile:
            try:
                all_rows = _fmi_stok_rows(profile, f)
                total = len(all_rows)
                summary = {
                    "jml_barang": total,
                    "total_qty": round(sum(r["qty_stok"] for r in all_rows), 3),
                    "total_nilai": round(sum(r["nilai_stok"] for r in all_rows), 2),
                    "total_terjual": round(sum(r["terjual"] for r in all_rows), 3),
                }
                start = (f["page"] - 1) * f["per_page"]
                rows = all_rows[start:start + f["per_page"]]
                for i, r in enumerate(rows):
                    r["_rid"] = start + i + 1
                options = {"divisi": _opt_divisi(profile)}
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca FMI stok")
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "total": total, "summary": summary,
                "options": options, "conn_error": conn_error,
                "notice": f["warning"] or None}

    return render(request, "Admin/Analytics/FmiStok", props={
        "report": defer(load_report),
        "filters": {
            "date_from": f["date_from_s"], "date_to": f["date_to_s"],
            "date_mode": f["date_mode"], "search": f["search"],
            "sort": f["sort"], "sort_dir": f["sort_dir"], "sort_keys": f["sort_keys"],
            "page": f["page"], "per_page": f["per_page"],
            "recent": False, "kd_divisi": f["kd_divisi"],
        },
    })


def fmi_stok_export(request):
    f = reporting.parse_report_params(request, rpt.SORTS_FMI_STOK, "qty_stok", max_range_days=None)
    f["kd_divisi"] = (request.GET.get("kd_divisi") or "").strip()
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/admin-panel/analitik/fmi-stok")
    try:
        rows = _fmi_stok_rows(profile, f)
    except pyodbc.Error as exc:
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal export")
        return redirect("/admin-panel/analitik/fmi-stok")
    log_activity(request, "export", f"Export fmi-stok: {len(rows)} baris")
    return reporting.xlsx_response("fmi-stok", _FMI_STOK_COLUMNS, rows)


# --- Klasifikasi Pelanggan (untuk follow-up) --------------------------------
# Dua hal yang beda dari laporan lain, keduanya karena pertanyaannya soal
# RIWAYAT pelanggan, bukan penjualan satu periode:
#   max_range_days=None   — clamp 92 hari membuat "belum belanja >1 tahun"
#                           mustahil dijawab.
#   default_from_days=730 — bawaan awal-bulan akan menandai semua orang 'Baru'.
# `enable_recent` sengaja TIDAK dipakai: mode itu memotong hasil ke 100 baris
# teratas, dan daftar follow-up yang terpotong diam-diam lebih buruk daripada
# daftar yang lambat.
# `nilai` milik sheet Barang Favorit, bukan tabel utama — tapi ia HARUS ada di
# daftar yang sama. Tanpa itu sheet kedua lolos dari pencabutan sementara sheet
# pertama tersaring: file export yang setengah tersensor, dan pembatasan yang
# terlihat bekerja di layar padahal tidak. Ini persis jenis kelalaian yang sudah
# pernah terjadi sekali di proyek ini.
_KLASIFIKASI_UANG = ("total_belanja", "rata_nota", "tier_nilai",
                     "total_nilai", "rata_nota_semua", "nilai")

_KLASIFIKASI_COLUMNS = [
    {"key": "kd_customer", "label": "Kode"},
    {"key": "customer", "label": "Pelanggan"},
    {"key": "hp", "label": "HP"},
    {"key": "telepon", "label": "Telepon"},
    {"key": "kota", "label": "Kota"},
    {"key": "segmen", "label": "Segmen"},
    {"key": "jml_nota", "label": "Jml Nota"},
    {"key": "total_belanja", "label": "Total Belanja"},
    {"key": "rata_nota", "label": "Rata per Nota"},
    {"key": "tier_nilai", "label": "Kelas Nilai"},
    {"key": "nota_pertama", "label": "Belanja Pertama"},
    {"key": "nota_terakhir", "label": "Belanja Terakhir"},
    {"key": "jeda_hari", "label": "Jeda (hari)"},
    {"key": "umur_hari", "label": "Lama Jadi Pelanggan (hari)"},
]

_KLASIFIKASI_PELANGGAN = {
    "component": "Admin/Analytics/KlasifikasiPelanggan",
    "url": "/admin-panel/analitik/klasifikasi-pelanggan",
    "inner": rpt.klasifikasi_pelanggan,
    "sorts": rpt.SORTS_KLASIFIKASI_PELANGGAN,
    "default_sort": "segmen",
    "filters": rpt.FILTERS_KLASIFIKASI_PELANGGAN,
    "filter_keys": ["kd_divisi", *rpt.AMBANG_KLASIFIKASI],
    "filter_defaults": {k: v[0] for k, v in rpt.AMBANG_KLASIFIKASI.items()},
    # segmen_urut: 1=Hilang .. 5=Aktif, jadi ASC = yang paling perlu dihubungi
    # di halaman pertama. Bawaan desc akan menaruhnya di halaman terakhir.
    "default_sort_dir": "asc",
    "max_range_days": None,
    "default_from_days": 730,
    "money_fields": _KLASIFIKASI_UANG,
    "options": lambda p: {"divisi": _opt_divisi(p)},
    "filename": "klasifikasi-pelanggan",
    "columns": _KLASIFIKASI_COLUMNS,
}


def klasifikasi_pelanggan(request):
    """Kolumnar: SELURUH pelanggan dikirim sekali, dicari & diurut di peramban.

    Bukan _report_view (paginasi server) karena pekerjaan nyata di halaman ini
    adalah MENCARI orang — "sudah lama tak datang, yang di Lombok Timur, yang
    belanjanya besar" — dan tiap pertanyaan itu jadi satu putaran ke server pada
    tabel yang dipaginasi. Sesudah pseudo-pelanggan dikeluarkan, profil terbesar
    tinggal ~4.800 baris; itu dua orde lebih kecil dari Stok Akhir yang memaksa
    bentuk kolumnar ini ada, jadi ongkosnya sudah terbayar.

    Yang TETAP ke server: periode, divisi, dan ambang segmen. Ketiganya mengubah
    hasil hitungan SQL, bukan cuma baris mana yang tampil.
    """
    spec = _KLASIFIKASI_PELANGGAN
    f = _spec_params(request, spec)
    hidden = _hidden_fields(request) & set(_KLASIFIKASI_UANG)

    def load():
        tabel, options, conn_error = None, {}, None
        profile = _active()
        if not profile:
            return {"tabel": None, "options": {}, "conn_error": CONN_ERROR, "notice": None}
        try:
            for read_profile in mssql.report_read_profiles(profile):
                try:
                    tabel = tx.klasifikasi_kolumnar(read_profile, f)
                    options = {"divisi": _opt_divisi(read_profile)}
                    conn_error = None
                    break
                except pyodbc.Error as exc:
                    conn_error = mssql.friendly_error(exc, "Gagal membaca klasifikasi")
        except Exception:
            log.exception("gagal menyiapkan klasifikasi pelanggan")
            conn_error = "Filter yang dipilih tidak bisa diproses. Kembalikan filter ke bawaan."
        # _tanpa_kolom mengembalikan SALINAN. Payload ini belum dicache hari ini,
        # tapi memakai jalur yang sama dengan Stok Akhir menutup jebakan itu
        # sebelum cache pertama ditambahkan — bukan sesudah seseorang menemukan
        # kolom uangnya hilang untuk semua orang.
        return {"tabel": _tanpa_kolom(tabel, hidden), "options": options,
                "conn_error": conn_error, "notice": f["warning"] or None}

    return render(request, spec["component"],
                  props={"klasifikasi": defer(load), "filters": _spec_filters(f, spec)})


def klasifikasi_pelanggan_export(request):
    """Export dua sheet: ringkasan per pelanggan + barang favorit tiap pelanggan.

    Bespoke (bukan _report_export) karena satu file memuat dua sudut pandang.
    Staf yang menyiapkan follow-up butuh keduanya di satu file — daftar nama
    tanpa "biasanya beli apa" memaksa mereka membuka aplikasi lagi per orang.
    """
    spec = _KLASIFIKASI_PELANGGAN
    f = _spec_params(request, spec, export=True)
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect(spec["url"])

    inner, params = spec["inner"](f)
    inner, params = reporting.apply_column_filters(inner, params, f)
    utama_sql = (f"SELECT TOP {reporting.EXPORT_CAP} * FROM ({inner}) AS q "
                 f"ORDER BY {f['order_by']}")
    favorit_sql, favorit_params = rpt.barang_favorit_massal(f, top_n=5)

    kolom_utama = _kolom_tanpa_uang(request, spec)
    kolom_favorit = _kolom_tanpa_uang(request, spec, rpt.FAVORIT_COLUMNS)

    resp, last_exc = None, None
    for read_profile in mssql.report_read_profiles(profile):
        try:
            with mssql.report_cursor(read_profile) as cur:
                cur.execute(utama_sql, params)
                utama = reporting.clean_rows(reporting.dictify(cur))
                cur.execute(favorit_sql, favorit_params)
                favorit = reporting.clean_rows(reporting.dictify(cur))
        except pyodbc.Error as exc:
            last_exc = exc
            continue

        # Sheet 2 disaring DI PYTHON ke pelanggan yang lolos saringan sheet 1.
        # Saringan kolom (segmen/kota/kelas nilai) adalah kolom turunan yang baru
        # ada setelah agregasi, jadi menyaringnya di SQL berarti menjalankan ulang
        # seluruh agregasi _nota_net di dalam pemeriksaan IN — terukur: query
        # timeout. Tanpa penyaringan apa pun, satu file memuat dua populasi
        # berbeda: 89 pelanggan di sheet 1, barang milik 316 orang di sheet 2.
        ikut = {r.get("kd_customer") for r in utama}
        favorit = [r for r in favorit if r.get("kd_customer") in ikut]

        resp = reporting.xlsx_multi_sheet_response(
            spec["filename"],
            [
                ("Klasifikasi", kolom_utama, utama),
                ("Barang Favorit", kolom_favorit, favorit),
            ],
        )
        break
    if resp is None:
        request.session["flash_error"] = mssql.friendly_error(last_exc, "Gagal export")
        return redirect(spec["url"])
    log_activity(request, "export", "Export klasifikasi-pelanggan (2 sheet)")
    return resp


def klasifikasi_pelanggan_detail(request):
    """JSON: satu pelanggan — barang favorit + nota terakhirnya (panel detail).

    Mengikuti pola update_barang_detail: JSON biasa, bukan halaman Inertia, dan
    hanya menyentuh satu kd_customer sehingga aman dipanggil per klik baris."""
    spec = _KLASIFIKASI_PELANGGAN
    kd_customer = (request.GET.get("kd_customer") or "").strip()
    if not kd_customer:
        return JsonResponse({"error": "Pelanggan tidak disebutkan."}, status=400)

    profile = _active()
    if not profile:
        return JsonResponse({"error": CONN_ERROR}, status=503)

    f = _spec_params(request, spec)
    # Panel detail memakai nama field sendiri (`nilai`, sudah terdaftar di bawah
    # kunci `nominal`), jadi ia harus dicabut di sini juga — bukan hanya kolom
    # tabel utama. Rute ketiga inilah yang paling mudah terlupakan.
    sembunyikan_nilai = "nilai" in _hidden_fields(request)

    def _bersih(rows):
        if not sembunyikan_nilai:
            return rows
        return [{k: v for k, v in r.items() if k != "nilai"} for r in rows]

    try:
        with mssql.report_cursor(profile) as cur:
            cur.execute("SELECT kd_customer, nama, alamat, hp, telepon, email, status "
                        "FROM m_customer WHERE kd_customer = ?", [kd_customer])
            profil = (reporting.clean_rows(reporting.dictify(cur)) or [None])[0]

            sql, prm = rpt.barang_favorit_pelanggan(f, kd_customer, top_n=20)
            cur.execute(sql, prm)
            favorit = reporting.clean_rows(reporting.dictify(cur))

            sql, prm = rpt.nota_pelanggan(f, kd_customer, top_n=20)
            cur.execute(sql, prm)
            nota = reporting.clean_rows(reporting.dictify(cur))
    except pyodbc.Error as exc:
        return JsonResponse({"error": mssql.friendly_error(exc, "Gagal membaca detail")}, status=502)

    return JsonResponse({
        "kd_customer": kd_customer,
        "profil": profil,
        "favorit": _bersih(favorit),
        "nota": _bersih(nota),
        "periode": {"dari": f["date_from_s"], "sampai": f["date_to_s"]},
    })


# Kas & Shift
# Kas Harian: saldo berjalan kini dihitung window function di SQL
# (rpt.kas_harian) sehingga paginasi OFFSET/FETCH aman; view tetap bespoke
# hanya karena summary-nya (saldo_awal pre-range) bukan agregat inner biasa.
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
    # tanggal tidak unik — tambah tiebreaker (sinkron dgn ORDER BY window di
    # rpt.kas_harian) supaya paginasi OFFSET stabil antar halaman.
    f["order_by"] = f"q.tanggal {f['sort_dir'].upper()}, q.kas, q.keterangan"

    def load_report():
        rows, total, summary, options, conn_error = [], 0, {}, {}, None
        profile = _active()
        if profile:
            try:
                inner, params = rpt.kas_harian(f)
                with mssql.cursor(profile) as cur:
                    rows, total = reporting.run_paged(cur, inner, params, f)
                    ssql, sparams = rpt.kas_summary(f)
                    cur.execute(ssql, sparams)
                    summary = reporting.one_row(cur)
                    options = {"kas": _opt_kas(profile)}
            except pyodbc.Error as exc:
                conn_error = mssql.friendly_error(exc, "Gagal membaca kas")
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "total": total, "summary": summary, "options": options,
                "conn_error": conn_error, "notice": f["warning"] or None}

    return render(request, "Admin/Cash/Kas", props={
        "report": defer(load_report),
        "filters": {
            "date_from": f["date_from_s"], "date_to": f["date_to_s"], "kd_kas": f["kd_kas"],
            "sort": f["sort"], "sort_dir": f["sort_dir"], "sort_keys": f["sort_keys"],
            "page": f["page"], "per_page": f["per_page"],
        },
    })


def kas_harian_export(request):
    # max_range_days=None: jalur export lepas clamp 92 hari (konsisten
    # _spec_params(export=True) pada laporan generik).
    f = reporting.parse_report_params(request, rpt.SORTS_KAS, "tanggal", max_range_days=None)
    f["kd_kas"] = (request.GET.get("kd_kas") or "").strip()
    f["order_by"] = f"q.tanggal {f['sort_dir'].upper()}, q.kas, q.keterangan"
    profile = _active()
    if not profile:
        request.session["flash_error"] = CONN_ERROR
        return redirect("/admin-panel/kas/harian")
    inner, params = rpt.kas_harian(f)
    order_sql = f"SELECT TOP {reporting.EXPORT_CAP} * FROM ({inner}) AS q ORDER BY {f['order_by']}"
    try:
        with mssql.cursor(profile) as cur:
            cur.execute(order_sql, params)
            resp = reporting.xlsx_stream_response("kas-harian", _KAS_COLUMNS, cur)
    except pyodbc.Error as exc:
        request.session["flash_error"] = mssql.friendly_error(exc, "Gagal export")
        return redirect("/admin-panel/kas/harian")
    log_activity(request, "export", "Export kas-harian")
    return resp

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
    # Self username change (superadmin & admin manage their own login name).
    username = (data.get("username") or "").strip()
    if username and username != u.username:
        if User.objects.filter(username__iexact=username).exclude(pk=u.pk).exists():
            request.session["flash_error"] = "Username sudah dipakai."
            return redirect("/admin-panel/profile")
        u.username = username
    password = data.get("password")
    if password:
        try:
            validate_password(password, u)
        except ValidationError as exc:
            request.session["flash_error"] = " ".join(exc.messages)
            return redirect("/admin-panel/profile")
        u.set_password(password)
    u.save()
    if password:
        update_session_auth_hash(request, u)  # keep the current session valid
    log_activity(request, "profil", "Ubah profil sendiri")
    request.session["flash_success"] = "Profil diperbarui."
    return redirect("/admin-panel/profile")

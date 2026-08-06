"""Inertia shared props + app-level access control."""
import ipaddress
import re

from inertia import render, share
from django.conf import settings
from django.shortcuts import redirect

from apps.core.menus import landing_for, menu_key_for_path, menus_for

# Paths reachable without authentication.
PUBLIC_PREFIXES = ("/login", "/static", "/@vite", "/favicon")
ADMIN_PREFIX = "/admin-panel"
# Halaman harian kasir/supervisor. Prefix terpisah supaya penjaga Tailscale tetap
# menutup rapat /admin-panel tanpa perlu dilonggarkan: kasir di toko tidak berada
# di rentang CGNAT Tailscale, dan melonggarkan penjaganya demi mereka akan
# membuka juga layar Manajemen User dan Koneksi Server.
POS_PREFIX = "/kasir"

# Admin-panel paths every admin-tier user may hit regardless of menu grants:
# the navbar connection switcher lives on every page, so it must keep working
# even when the "Koneksi Server" management menu itself is revoked.
_MENU_EXEMPT_RE = re.compile(r"^/admin-panel/connections/\d+/set-default$")


def _auth_user_dict(user):
    if not user or not user.is_authenticated:
        return None
    return {
        "id": user.pk,
        "name": user.get_full_name() or user.username,
        "username": user.username,
        "role": user.role,
        # Dipakai layar untuk membuang kolom yang datanya memang tak dikirim.
        # KOSMETIK: yang benar-benar menahan datanya ada di sisi server
        # (_hidden_fields di apps/monitoring/views.py). Jangan pernah jadikan
        # ini satu-satunya penjaga.
        "hidden_data_keys": sorted(user.hidden_data()),
    }


def inertia_share(get_response):
    def middleware(request):
        from core import mssql

        user = getattr(request, "user", None)

        # Per-user active connection: stamp THIS session's chosen profile for the
        # life of the request so every get_active_profile() call (shared props,
        # views, services) resolves to the current user's pick — not a global one
        # another user could change. Cleared in finally so the pooled thread never
        # carries a choice into the next request.
        session = getattr(request, "session", None)
        mssql.set_request_profile_id(session.get("active_profile_id") if session else None)

        def active_connection():
            # Lazy: only hit the DB on Inertia renders, not asset/XHR noise.
            profile = mssql.get_active_profile()
            return profile.as_dict() if profile else None

        def connections_list():
            from apps.connections.models import ServerProfile

            return [p.as_dict() for p in ServerProfile.objects.all()]

        share(
            request,
            app_name=settings.APP_NAME,
            auth_user=_auth_user_dict(user),
            allowed_menus=lambda: menus_for(user),
            active_connection=active_connection,
            connections=connections_list,
            flash=lambda: {
                "success": request.session.pop("flash_success", None),
                "error": request.session.pop("flash_error", None),
            },
        )
        try:
            return get_response(request)
        finally:
            mssql.clear_request_profile()

    return middleware


def auth_required(get_response):
    """Redirect unauthenticated users to /login (except public paths)."""

    def middleware(request):
        path = request.path
        if not path.startswith(PUBLIC_PREFIXES):
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated):
                # Bedakan sesi yang HABIS dari kunjungan pertama: hanya yang
                # masih membawa cookie sesi yang diberi tahu, supaya pengunjung
                # baru tak dituduh "sesi berakhir".
                if request.COOKIES.get(settings.SESSION_COOKIE_NAME):
                    return redirect(f"{settings.LOGIN_URL}?expired=1")
                return redirect(settings.LOGIN_URL)
        return get_response(request)

    return middleware


def _ip_allowed(ip: str) -> bool:
    if ip in settings.ADMIN_IP_ALLOWLIST:
        return True
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(settings.TAILSCALE_CIDR)
    except ValueError:
        return False


def admin_network_guard(get_response):
    """PRD §3.4/§7.6 — /admin-panel/* dan /kasir/* butuh menu yang diberikan, dan
    khusus /admin-panel/* juga alamat IP dari rentang Tailscale.

    Dulu di sini berdiri tembok berbasis peran (`is_admin_tier`). Ia diganti
    penjagaan berbasis MENU karena keduanya menjawab pertanyaan yang berbeda:
    peran menentukan bawaan seseorang, menu menentukan apa yang boleh ia buka.
    Selama tembok peran masih ada, superadmin yang memberikan satu menu laporan
    kepada supervisor tetap tidak menghasilkan apa-apa — orangnya ditolak
    sebelum pemeriksaan menu sempat berjalan.

    PRD §4.3 — pemberian per-menu ditegakkan di sini, bukan cuma di sidebar,
    supaya menu yang dicabut tidak bisa dicapai dengan mengetik URL-nya."""

    def middleware(request):
        path = request.path
        di_admin = path.startswith(ADMIN_PREFIX)
        if di_admin or path.startswith(POS_PREFIX):
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated) or not menus_for(user):
                return ditolak(
                    request,
                    "Halaman ini bukan untuk akun Anda",
                    "Belum ada satu pun halaman yang dibuka untuk akun Anda. "
                    "Minta pengelola aplikasi membukanya.",
                )
            # Tailscale hanya untuk panel pengaturan. Halaman kasir justru harus
            # bisa dibuka dari jaringan toko.
            if di_admin and settings.ENFORCE_TAILSCALE:
                ip = request.META.get("REMOTE_ADDR", "")
                if not _ip_allowed(ip):
                    return ditolak(
                        request,
                        "Belum tersambung ke jaringan kantor",
                        "Halaman ini hanya bisa dibuka dari jaringan kantor. Sambungkan "
                        "dulu perangkat Anda, lalu buka lagi halaman ini.",
                    )
            if not _menu_allowed(user, request.path):
                # Menu yang tak diberikan: antar ke halaman yang memang miliknya
                # alih-alih menghadang. Hanya untuk permintaan yang sekadar
                # MEMBACA — mengalihkan sebuah POST akan menelan tulisan pengguna
                # tanpa suara, dan ia takkan pernah tahu simpanannya gagal.
                tujuan = landing_for(user)
                if request.method in ("GET", "HEAD") and tujuan and tujuan != request.path:
                    request.session["flash_error"] = (
                        "Halaman itu belum dibuka untuk akun Anda. "
                        "Anda dibawa ke halaman yang bisa Anda buka."
                    )
                    return redirect(tujuan)
                return ditolak(
                    request,
                    "Halaman ini belum dibuka untuk Anda",
                    "Kalau Anda memang perlu membukanya, minta ke pengelola aplikasi.",
                )
        return get_response(request)

    return middleware


def ditolak(request, judul: str, saran: str):
    """Halaman penolakan yang bisa dibaca, bukan teks polos di layar putih.

    Dulu ketiga jalur penolakan mengembalikan satu baris teks tanpa kop, tanpa
    navigasi, dan tanpa jalan keluar — pengguna hanya bisa menekan tombol back.
    Statusnya tetap 403: yang berubah tampilannya, bukan hasilnya.
    """
    user = getattr(request, "user", None)
    resp = render(
        request,
        "Ditolak",
        props={
            "judul": judul,
            "saran": saran,
            # Ke mana ia masih boleh pergi. None kalau memang tak ke mana-mana
            # (mis. bukan admin sama sekali) — layar menawarkan keluar saja.
            "tujuan": landing_for(user) if user and user.is_authenticated else None,
        },
    )
    resp.status_code = 403
    return resp


def _menu_allowed(user, path: str) -> bool:
    if _MENU_EXEMPT_RE.match(path):
        return True
    key = menu_key_for_path(path)
    if key is None:  # pages outside the menu registry, e.g. /admin-panel/profile
        return True
    return key in {m["key"] for m in menus_for(user)}

"""Inertia shared props + app-level access control."""
import re

from inertia import render, share
from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone

from apps.core.http import client_ip, ip_dalam
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


# Berapa baris yang dibawa lonceng. Sengaja kecil: ini ringkasan "apa yang baru",
# bukan pengganti halaman Log Aktivitas — yang menampung 300 baris beserta
# penyaringnya.
NOTIF_TAMPIL = 8


def _notif(user):
    """Isi lonceng untuk `user`. Lazy — hanya jalan pada render Inertia.

    Aturan siapa-melihat-apa ada di `log_untuk`, satu tempat bersama dashboard
    dan halaman Log Aktivitas.
    """
    from apps.core.models import log_untuk

    if not (user and getattr(user, "is_authenticated", False)):
        return {"items": [], "belum": 0}
    qs = log_untuk(user)
    batas = user.notif_dibaca_at
    belum = qs.filter(timestamp__gt=batas).count() if batas else qs.count()
    return {
        "items": [
            {
                "id": a.id,
                "user": a.username or "—",
                "action": a.action,
                "detail": a.detail,
                "waktu": timezone.localtime(a.timestamp).strftime("%Y-%m-%d %H:%M"),
                "baru": batas is None or a.timestamp > batas,
            }
            for a in qs[:NOTIF_TAMPIL]
        ],
        "belum": belum,
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
        # Kasir/supervisor DIKUNCI ke server yang ditetapkan untuk akunnya dan
        # tak bisa berpindah lewat sesi. Koneksi menentukan ke server toko MANA
        # sebuah nota tertulis; nota yang masuk ke cabang salah tak bisa ditarik
        # karena trigger legacy langsung mengirimkannya ke pusat.
        if user is not None and getattr(user, "is_authenticated", False) \
                and getattr(user, "koneksi_terkunci", False):
            mssql.set_request_profile_id(user.server_profile_id, strict=True)
        else:
            mssql.set_request_profile_id(session.get("active_profile_id") if session else None)

        def active_connection():
            # Lazy: only hit the DB on Inertia renders, not asset/XHR noise.
            profile = mssql.get_active_profile()
            return profile.as_dict() if profile else None

        def connections_list():
            from apps.connections.models import ServerProfile

            if user is not None and getattr(user, "is_authenticated", False)                     and getattr(user, "koneksi_terkunci", False):
                # Hanya miliknya sendiri: pemilih koneksi di navbar jadi tak
                # punya apa pun untuk dipindah. Penjagaan sebenarnya tetap di
                # server (connections_set_default) — ini supaya layarnya jujur.
                p = user.server_profile
                return [p.as_dict()] if p else []
            return [p.as_dict() for p in ServerProfile.objects.all()]

        share(
            request,
            app_name=settings.APP_NAME,
            auth_user=_auth_user_dict(user),
            allowed_menus=lambda: menus_for(user),
            active_connection=active_connection,
            connections=connections_list,
            notif=lambda: _notif(user),
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
    """Boleh membuka /admin-panel dari alamat ini?

    Daftarnya kini JAMAK (`ADMIN_ALLOWED_NETWORKS`): rentang Tailscale plus
    rentang LAN mana pun yang sengaja diizinkan lewat `ADMIN_EXTRA_CIDRS`.
    Sebelumnya hanya satu CIDR, dan kantor yang perangkatnya tak ber-Tailscale
    tak punya cara menyatakan itu selain menjembataninya diam-diam — yang justru
    membuat penjaga ini meloloskan semua orang tanpa ada yang tahu.
    """
    if ip in settings.ADMIN_IP_ALLOWLIST:
        return True
    return ip_dalam(ip, settings.ADMIN_ALLOWED_NETWORKS)


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
                # `client_ip`, bukan REMOTE_ADDR langsung: di belakang reverse
                # proxy REMOTE_ADDR selalu proxy-nya, dan `ADMIN_IP_ALLOWLIST`
                # memuat 127.0.0.1 — proxy di mesin yang sama akan meloloskan
                # SETIAP permintaan tanpa satu pun tanda di layar maupun di log.
                if not _ip_allowed(client_ip(request)):
                    return ditolak(
                        request,
                        "Belum tersambung ke jaringan kantor",
                        "Halaman ini hanya bisa dibuka dari jaringan kantor. Sambungkan "
                        "dulu perangkat Anda, lalu buka lagi halaman ini.",
                    )
            if not _menu_allowed(user, request.path):
                # Tertutup karena TAUTAN, bukan karena menunya dicabut: katakan
                # begitu. Pesan generik di bawah akan mengirim orangnya ke
                # Kelola Menu, padahal yang kurang ada di Kelola Tautan User.
                if (pesan := _pesan_tautan(user, request.path)):
                    return ditolak(
                        request, "Akun Anda belum ditautkan untuk koneksi ini", pesan)
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


def _pesan_tautan(user, path: str) -> str | None:
    """Alasan sebenarnya kalau `path` tertutup karena tautan legacy, atau None.

    Sengaja TIDAK mengalihkan pemanggilnya ke landing_for seperti menu yang
    dicabut: bagi kasir, satu-satunya menu yang tak bisa dicabut adalah Bantuan,
    dan Bantuan ada di /admin-panel yang tertutup penjaga Tailscale dari jaringan
    toko. Mengalihkan ke sana berarti jalan buntu dengan pesan yang salah pula.
    """
    from apps.auth_app.tautan import pesan_belum_tertaut, tautan_untuk, yang_kurang
    from apps.core.menus import KEYS_BUTUH_TAUTAN, tautan_lengkap
    from core import mssql

    key = menu_key_for_path(path)
    if key not in KEYS_BUTUH_TAUTAN or tautan_lengkap(user):
        return None
    # Menu ini memang tak diberikan kepadanya — tautan bukan alasannya, dan
    # menyebutnya akan mengirim orangnya ke layar yang salah.
    if key not in {m["key"] for m in menus_for(user, abaikan_tautan=True)}:
        return None
    profile = mssql.get_active_profile()
    return pesan_belum_tertaut(profile, yang_kurang(tautan_untuk(user, profile)))


def _menu_allowed(user, path: str) -> bool:
    if _MENU_EXEMPT_RE.match(path):
        return True
    key = menu_key_for_path(path)
    if key is None:  # pages outside the menu registry, e.g. /admin-panel/profile
        return True
    return key in {m["key"] for m in menus_for(user)}

"""Inertia shared props + app-level access control."""
import ipaddress
import re

from inertia import share
from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from apps.core.menus import menu_key_for_path, menus_for

# Paths reachable without authentication.
PUBLIC_PREFIXES = ("/login", "/static", "/@vite", "/favicon")
ADMIN_PREFIX = "/admin-panel"

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
    }


def inertia_share(get_response):
    def middleware(request):
        user = getattr(request, "user", None)

        def active_connection():
            # Lazy: only hit the DB on Inertia renders, not asset/XHR noise.
            from core.mssql import get_active_profile

            profile = get_active_profile()
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
        return get_response(request)

    return middleware


def auth_required(get_response):
    """Redirect unauthenticated users to /login (except public paths)."""

    def middleware(request):
        path = request.path
        if not path.startswith(PUBLIC_PREFIXES):
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated):
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
    """PRD §3.4/§7.6 — /admin-panel/* requires Admin-tier role and (optionally)
    a Tailscale-range source IP. PRD §4.3 — per-menu grants (allowed_menu_keys)
    are enforced here too, not just in the sidebar, so a restricted admin can't
    reach revoked menus by typing the URL."""

    def middleware(request):
        if request.path.startswith(ADMIN_PREFIX):
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated and user.is_admin_tier):
                return HttpResponseForbidden("403 Forbidden — butuh hak akses Admin.")
            if settings.ENFORCE_TAILSCALE:
                ip = request.META.get("REMOTE_ADDR", "")
                if not _ip_allowed(ip):
                    return HttpResponseForbidden(
                        "403 Forbidden — akses Admin hanya via jaringan Tailscale."
                    )
            if not _menu_allowed(user, request.path):
                return HttpResponseForbidden(
                    "403 Forbidden — menu ini tidak diberikan untuk akun Anda."
                )
        return get_response(request)

    return middleware


def _menu_allowed(user, path: str) -> bool:
    if _MENU_EXEMPT_RE.match(path):
        return True
    key = menu_key_for_path(path)
    if key is None:  # pages outside the menu registry, e.g. /admin-panel/profile
        return True
    return key in {m["key"] for m in menus_for(user)}

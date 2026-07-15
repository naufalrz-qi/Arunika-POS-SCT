"""Auth views (real). PRD §7.1 — login/logout with bcrypt + SQLite sessions."""
from inertia import render
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.shortcuts import redirect

from apps.core.http import get_data
from apps.core.models import log_activity

# Brute-force throttle: lock a (username, IP) pair after N failures for a short
# window. Uses Django's process-local cache (no new dependency); adequate for the
# single-process waitress deploy this app targets.
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 15 * 60


def _login_fail_key(username, ip) -> str:
    return f"login_fail:{username.lower()}:{ip or '?'}"


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect("/admin-panel/dashboard")
    return redirect("/login")


def login_view(request):
    # Already logged in → go straight to the panel.
    if request.method == "GET" and request.user.is_authenticated:
        return redirect("/admin-panel/dashboard")

    if request.method == "POST":
        data = get_data(request)
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        ip = request.META.get("REMOTE_ADDR")
        fail_key = _login_fail_key(username, ip)

        if cache.get(fail_key, 0) >= LOGIN_MAX_FAILS:
            log_activity(request, "login_terkunci", f"username={username[:32]}")
            return render(
                request,
                "Auth/Login",
                props={"errors": {"username": "Terlalu banyak percobaan gagal. Coba lagi dalam beberapa menit."}},
            )

        user = authenticate(request, username=username, password=password)

        if user is None or not user.is_active:
            cache.set(fail_key, cache.get(fail_key, 0) + 1, LOGIN_LOCK_SECONDS)
            # Cap the logged value — a mistyped password can land in the username field.
            log_activity(request, "login_gagal", f"username={username[:32]}")
            return render(
                request,
                "Auth/Login",
                props={"errors": {"username": "Username atau password salah."}},
            )

        cache.delete(fail_key)  # reset counter on success
        login(request, user)
        log_activity(request, "login", "Login berhasil")

        # Kasir/supervisor have no admin panel yet in this phase.
        if not user.is_admin_tier:
            request.session["flash_error"] = "Akun ini belum punya halaman di fase ini."
            logout(request)
            return redirect("/login")

        request.session["flash_success"] = f"Selamat datang, {user.get_full_name() or user.username}."
        return redirect("/admin-panel/dashboard")

    return render(request, "Auth/Login", props={})


def logout_view(request):
    log_activity(request, "logout", "Logout")
    logout(request)
    return redirect("/login")

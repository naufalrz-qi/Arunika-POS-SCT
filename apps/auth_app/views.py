"""Auth views (real). PRD §7.1 — login/logout with bcrypt + SQLite sessions."""
from inertia import render
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect

from apps.core.http import get_data
from apps.core.models import log_activity


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
        user = authenticate(request, username=username, password=password)

        if user is None or not user.is_active:
            log_activity(request, "login_gagal", f"username={username}")
            return render(
                request,
                "Auth/Login",
                props={"errors": {"username": "Username atau password salah."}},
            )

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

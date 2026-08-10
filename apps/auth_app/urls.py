from django.urls import path

from . import views

urlpatterns = [
    path("", views.root_redirect, name="root"),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    # Di akar, bukan di bawah /admin-panel — lihat alasannya di views.notif_baca.
    path("notif/baca", views.notif_baca, name="notif_baca"),
]

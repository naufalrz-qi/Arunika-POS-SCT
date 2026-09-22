"""Siapa boleh memakai koneksi mana (spec 2026-09-22 §4).

Satu tempat untuk aturannya; middleware (pilihan sesi + daftar navbar),
connections_set_default, dan Manajemen User membacanya. Job latar belakang
tidak lewat sini — mereka tak punya user.
"""
from django.db.models import Q

from apps.auth_app.models import Role

from .models import Lingkungan, ServerProfile


def koneksi_boleh(user):
    """Profil yang boleh dipakai `user`.

    Superadmin: semua. Akun terkunci (kasir/supervisor): hanya servernya
    sendiri, apa pun labelnya — yang menentukannya Manajemen User. Selain itu:
    semua Produksi, ditambah `koneksi_khusus` pemberian superadmin.
    """
    qs = ServerProfile.objects.all()
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()
    if user.role == Role.SUPERADMIN:
        return qs
    if user.koneksi_terkunci:
        return qs.filter(pk=user.server_profile_id) if user.server_profile_id else qs.none()
    return qs.filter(
        Q(lingkungan=Lingkungan.PRODUKSI) | Q(pk__in=user.koneksi_khusus.values("pk"))
    ).distinct()


def boleh_pakai(user, profile_or_id) -> bool:
    pk = getattr(profile_or_id, "pk", profile_or_id)
    return pk is not None and koneksi_boleh(user).filter(pk=pk).exists()


def profil_untuk_sesi(user, pid_sesi):
    """Profil yang dipakai permintaan ini untuk akun TAK terkunci.

    Pilihan di sesi dipakai kalau masih boleh; kalau tidak — izinnya dicabut,
    atau profilnya kini non-produksi — jatuh ke `is_default` bila boleh, lalu ke
    profil pertama yang boleh. None kalau tak ada satu pun. Superadmin tak
    disaring: pilihannya apa adanya (None = default global, seperti dulu).
    """
    if user.role == Role.SUPERADMIN:
        return pid_sesi
    boleh = list(koneksi_boleh(user).values_list("pk", "is_default"))
    ids = [pk for pk, _ in boleh]
    if pid_sesi in ids:
        return pid_sesi
    default = next((pk for pk, is_default in boleh if is_default), None)
    if default is not None:
        return default
    return ids[0] if ids else None

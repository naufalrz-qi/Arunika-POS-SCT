"""Tautan user legacy pindah dari User ke TautanUser, satu baris per koneksi.

Kode `kd_user` dibuat berurutan oleh tiap server sendiri-sendiri, jadi satu
nilai di akun sudah salah begitu pemakainya berpindah koneksi. Lihat docstring
`apps.auth_app.models.TautanUser`.
"""
from django.db import migrations, models
import django.db.models.deletion


def _pindahkan(apps, schema_editor):
    """Salin tautan lama ke koneksi yang paling mungkin dimaksud.

    Kasir/supervisor terkunci ke `server_profile`, jadi untuk mereka tak ada
    tebakan sama sekali. Untuk admin yang terlanjur punya tautan tanpa server,
    profil `is_default` adalah satu-satunya koneksi yang pasti pernah ia pakai —
    dan kalaupun keliru, layar Kelola Tautan User menampilkannya apa adanya
    untuk diperbaiki. Menghapusnya diam-diam justru lebih buruk: pemiliknya
    tidak akan tahu tautannya hilang sampai simpan pertama gagal.
    """
    User = apps.get_model("auth_app", "User")
    TautanUser = apps.get_model("auth_app", "TautanUser")
    ServerProfile = apps.get_model("connections", "ServerProfile")

    bawaan = ServerProfile.objects.filter(is_default=True).first()
    for u in User.objects.exclude(kd_user="", kd_divisi="", kd_pegawai=""):
        profile = u.server_profile or bawaan
        if not profile:
            continue  # tak ada koneksi sama sekali — tak ada yang bisa ditautkan
        TautanUser.objects.update_or_create(
            user=u, profile=profile,
            defaults={"kd_user": u.kd_user, "kd_divisi": u.kd_divisi,
                      "kd_pegawai": u.kd_pegawai},
        )


def _kembalikan(apps, schema_editor):
    """Balik arah: ambil tautan koneksi milik user (atau bawaan) ke field lama."""
    User = apps.get_model("auth_app", "User")
    TautanUser = apps.get_model("auth_app", "TautanUser")
    for t in TautanUser.objects.select_related("user", "profile"):
        u = t.user
        if u.server_profile_id and u.server_profile_id != t.profile_id:
            continue
        u.kd_user, u.kd_divisi, u.kd_pegawai = t.kd_user, t.kd_divisi, t.kd_pegawai
        u.save(update_fields=["kd_user", "kd_divisi", "kd_pegawai"])


class Migration(migrations.Migration):

    dependencies = [
        ("connections", "0001_initial"),
        ("auth_app", "0005_user_server_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="TautanUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("kd_user", models.CharField(blank=True, default="", max_length=6)),
                ("kd_divisi", models.CharField(blank=True, default="", max_length=6)),
                ("kd_pegawai", models.CharField(blank=True, default="", max_length=6)),
                ("profile", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tautan", to="connections.serverprofile")),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tautan", to="auth_app.user")),
            ],
        ),
        migrations.AddConstraint(
            model_name="tautanuser",
            constraint=models.UniqueConstraint(
                fields=("user", "profile"), name="tautan_unik_per_koneksi"),
        ),
        migrations.RunPython(_pindahkan, _kembalikan),
        migrations.RemoveField(model_name="user", name="kd_user"),
        migrations.RemoveField(model_name="user", name="kd_divisi"),
        migrations.RemoveField(model_name="user", name="kd_pegawai"),
    ]

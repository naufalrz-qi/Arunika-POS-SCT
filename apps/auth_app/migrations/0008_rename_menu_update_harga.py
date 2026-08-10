"""Menu `update_barang` berganti key jadi `update_harga`.

`User.allowed_menu_keys` menyimpan key MENTAH sebagai JSON. Mengganti key di
`apps/core/menus.py` tanpa menulis ulang isinya akan **mencabut menu itu diam-diam**
dari setiap akun yang hak aksesnya diatur satu per satu — tanpa galat, tanpa gejala
di layar, dan justru dari akun yang paling sengaja dikonfigurasi.

Baris berdaftar KOSONG sengaja dilewati: konvensinya "kosong = akses penuh"
(lihat `apps/auth_app/models.py`), jadi mengisinya di sini malah menyempitkan hak
akses orang yang sebelumnya mendapat semuanya.
"""
from django.db import migrations

LAMA = "update_barang"
BARU = "update_harga"


def _tukar(apps, dari: str, ke: str) -> None:
    User = apps.get_model("auth_app", "User")
    for user in User.objects.exclude(allowed_menu_keys=[]).iterator():
        keys = user.allowed_menu_keys or []
        if dari not in keys:
            continue
        # Urutan dipertahankan dan duplikat dicegah: kalau `ke` entah bagaimana
        # sudah ada di daftar, jangan tulis dua kali.
        baru = []
        for k in keys:
            k = ke if k == dari else k
            if k not in baru:
                baru.append(k)
        user.allowed_menu_keys = baru
        user.save(update_fields=["allowed_menu_keys"])


def maju(apps, schema_editor):
    _tukar(apps, LAMA, BARU)


def mundur(apps, schema_editor):
    _tukar(apps, BARU, LAMA)


class Migration(migrations.Migration):

    dependencies = [
        ("auth_app", "0007_user_notif_dibaca_at"),
    ]

    operations = [
        migrations.RunPython(maju, mundur),
    ]

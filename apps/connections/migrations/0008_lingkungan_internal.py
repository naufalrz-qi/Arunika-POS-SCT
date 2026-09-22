"""Label Internal untuk database milik kita sendiri (AMPHOREUS).

Profil hub dikenali lewat HUB_NAME, nama yang sama yang dipakai scheduler dan
pull_hub untuk menemukannya — bukan tebakan dari host atau tipe.
"""
import os

from django.db import migrations, models


def tandai(apps, schema_editor):
    ServerProfile = apps.get_model("connections", "ServerProfile")
    nama = os.environ.get("HUB_NAME", "AMPHOREUS")
    ServerProfile.objects.filter(name=nama).update(lingkungan="internal")


def balik(apps, schema_editor):
    ServerProfile = apps.get_model("connections", "ServerProfile")
    ServerProfile.objects.filter(lingkungan="internal").update(lingkungan="produksi")


class Migration(migrations.Migration):
    dependencies = [("connections", "0007_tandai_profil_uji")]
    operations = [
        migrations.AlterField(
            model_name="serverprofile",
            name="lingkungan",
            field=models.CharField(
                choices=[("produksi", "Produksi"), ("uji", "Uji coba"), ("internal", "Internal")],
                default="produksi", max_length=10),
        ),
        migrations.RunPython(tandai, balik),
    ]

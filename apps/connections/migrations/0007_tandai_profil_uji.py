"""Tandai profil yang selama ini hanya dikenali dari namanya.

Aturannya `host = localhost`, dan itu benar untuk pemasangan ini secara
kebetulan-yang-terperiksa: dari dua belas profil, hanya `testgudang` (salinan
GUDANG) dan `Testing` (salinan grosirPusat) yang ada di mesin ini; sepuluh
sisanya menunjuk server sungguhan lewat jaringan (`SERVER-TOYS`,
`SERVER-GUDANG`, `SERVER-RETAIL`, dan seterusnya).

Ini migrasi data SEKALI JALAN, bukan aturan. "localhost berarti uji coba" tidak
berlaku umum — sebuah pemasangan produksi bisa saja satu mesin. Karena itu
penandanya jadi kolom yang bisa disunting, bukan sesuatu yang diturunkan ulang
dari host tiap kali dibaca.
"""
from django.db import migrations

LOKAL = ("localhost", "127.0.0.1", "(local)", ".")


def tandai(apps, schema_editor):
    ServerProfile = apps.get_model("connections", "ServerProfile")
    ServerProfile.objects.filter(host__in=LOKAL).update(lingkungan="uji")


def balik(apps, schema_editor):
    ServerProfile = apps.get_model("connections", "ServerProfile")
    ServerProfile.objects.filter(host__in=LOKAL).update(lingkungan="produksi")


class Migration(migrations.Migration):
    dependencies = [("connections", "0006_serverprofile_lingkungan")]
    operations = [migrations.RunPython(tandai, balik)]

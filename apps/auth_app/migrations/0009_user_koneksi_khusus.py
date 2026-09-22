from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("auth_app", "0008_rename_menu_update_harga"),
        ("connections", "0008_lingkungan_internal"),
    ]
    operations = [
        migrations.AddField(
            model_name="user",
            name="koneksi_khusus",
            field=models.ManyToManyField(
                blank=True, related_name="pengguna_khusus", to="connections.serverprofile"),
        ),
    ]

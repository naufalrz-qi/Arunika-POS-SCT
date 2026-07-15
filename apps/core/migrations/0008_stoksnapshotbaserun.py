# Generated for two-layer stock snapshot base run marker (snapshot revamp).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0003_serverprofile_report_source'),
        ('core', '0007_stoksnapshotrun'),
    ]

    operations = [
        migrations.CreateModel(
            name='StokSnapshotBaseRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('profile_name', models.CharField(blank=True, max_length=100)),
                ('base_month', models.CharField(max_length=7)),
                ('ran_at', models.DateTimeField(auto_now_add=True)),
                ('rows', models.PositiveIntegerField(default=0)),
                ('profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stok_snapshot_base_runs', to='connections.serverprofile')),
            ],
            options={
                'ordering': ['-ran_at'],
                'constraints': [models.UniqueConstraint(fields=('profile', 'base_month'), name='unique_stok_snapshot_base_per_month')],
            },
        ),
    ]

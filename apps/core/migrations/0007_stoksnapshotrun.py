# Generated for rolling stock snapshot (implementation_plan.md Fase 1).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0003_serverprofile_report_source'),
        ('core', '0006_hargasnapshotrun'),
    ]

    operations = [
        migrations.CreateModel(
            name='StokSnapshotRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('profile_name', models.CharField(blank=True, max_length=100)),
                ('run_date', models.DateField()),
                ('ran_at', models.DateTimeField(auto_now_add=True)),
                ('rows', models.PositiveIntegerField(default=0)),
                ('profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stok_snapshot_runs', to='connections.serverprofile')),
            ],
            options={
                'ordering': ['-ran_at'],
                'constraints': [models.UniqueConstraint(fields=('profile', 'run_date'), name='unique_stok_snapshot_run_per_day')],
            },
        ),
    ]

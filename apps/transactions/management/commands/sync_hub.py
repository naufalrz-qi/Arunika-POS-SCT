"""Tarik perubahan tiap cabang ke pusat AMPHOREUS.

    python manage.py sync_hub --hub AMPHOREUS --dry-run
    python manage.py sync_hub --hub AMPHOREUS --source PRAYA --limit 500
    python manage.py sync_hub --hub AMPHOREUS

Mekanismenya di apps/transactions/hub_sync.py. Tanpa `--source`, semua profil
ber-`kode_sumber` disapu; cabang tanpa kode dilewati, bukan ditebak.

Cabang yang belum punya cursor TIDAK memutar ulang riwayat: run pertamanya hanya
menetapkan posisi di ujung feed sekarang lalu berhenti — pusat sengaja mulai
kosong untuk transaksi. `--from-id` untuk sengaja mengambil lebih ke belakang.

Dijadwalkan lewat Windows Task Scheduler, atau scheduler in-process dengan
HUB_SYNC_ENABLED=1 (default mati).
"""
from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions import hub_sync


class Command(BaseCommand):
    help = "Sinkronkan cabang -> pusat AMPHOREUS lewat feed tbl_log_transaksi."

    def add_arguments(self, parser):
        parser.add_argument("--hub", default="AMPHOREUS", help="Nama ServerProfile pusat.")
        parser.add_argument("--source", action="append", default=None, help="Nama cabang. Boleh diulang.")
        parser.add_argument("--limit", type=int, default=2000, help="Maks baris feed per cabang per run.")
        parser.add_argument("--dry-run", action="store_true", help="Jalankan penuh lalu ROLLBACK.")
        parser.add_argument("--from-id", type=int, default=None, help="Mulai dari id feed ini, abaikan cursor.")

    def handle(self, *args, **opts):
        hub = ServerProfile.objects.filter(name=opts["hub"]).first()
        if not hub:
            raise CommandError(f"ServerProfile pusat '{opts['hub']}' tidak ditemukan.")

        if opts["source"]:
            sumber = []
            for nama in opts["source"]:
                p = ServerProfile.objects.filter(name=nama).first()
                if not p:
                    raise CommandError(f"ServerProfile '{nama}' tidak ditemukan.")
                sumber.append(p)
        else:
            sumber = hub_sync.sumber_profiles()
        if not sumber:
            raise CommandError(
                "Tidak ada cabang ber-kode_sumber. Isi dulu kode_sumber tiap cabang — "
                "tanpa itu baris tiap cabang tidak bisa dibedakan di pusat."
            )

        mode = " (DRY RUN — tidak ada yang ditulis)" if opts["dry_run"] else ""
        self.stdout.write(f"Pusat: {hub.name} <- {len(sumber)} cabang{mode}")

        gagal = []
        for src in sumber:
            hasil = hub_sync.sync_source(
                src, hub, limit=opts["limit"], dry_run=opts["dry_run"], from_id=opts["from_id"],
            )
            s = hasil["status"]
            label = f"{src.name} [{hasil['kd_sumber'] or '-'}]"
            if s == "failed":
                gagal.append(hasil)
                self.stderr.write(f"  {label}: GAGAL — {hasil['error']}")
            elif s == "tanpa_kode":
                self.stderr.write(f"  {label}: dilewati — kode_sumber belum diisi.")
            elif s == "posisi_awal":
                self.stdout.write(
                    f"  {label}: cursor ditetapkan di id {hasil['sampai_id']} "
                    f"(run pertama tidak memutar ulang riwayat)."
                )
            elif s == "tak_ada_perubahan":
                self.stdout.write(f"  {label}: sudah terbaru.")
            else:
                kemana = "dilewati" if opts["dry_run"] else "ke dead-letter"
                self.stdout.write(
                    f"  {label}: {hasil['diterapkan']} diterapkan ({hasil['nota']} nota "
                    f"diambil ulang), {hasil['disaring']} disaring, {hasil['dilewati']} {kemana}, "
                    f"sampai id {hasil['sampai_id']}."
                )
                for alasan, n in sorted(hasil["alasan"].items(), key=lambda kv: -kv[1])[:8]:
                    self.stdout.write(f"      {n:>6}  {alasan}")

        if gagal:
            raise CommandError(f"{len(gagal)} cabang gagal.")

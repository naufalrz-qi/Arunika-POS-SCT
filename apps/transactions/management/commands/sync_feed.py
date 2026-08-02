"""Fan-out master data dari satu server sumber (gudang) ke toko-toko.

    python manage.py sync_feed --source GUDANG --dry-run
    python manage.py sync_feed --source GUDANG --target "RTL RUMAK" --limit 500
    python manage.py sync_feed --source GUDANG            # semua toko

Mekanismenya di apps/transactions/feed_sync.py — baca dulu docstring modul itu,
terutama soal kenapa sumbernya `tbl_log_transaksi` dan bukan `tbl_tmp_post`.

Pasangan (sumber, tujuan) yang belum punya cursor TIDAK memutar ulang riwayat:
run pertamanya hanya menetapkan posisi di ujung feed sekarang dan berhenti.
Untuk sengaja mengulang dari titik tertentu, pakai `--from-id`.

Dijadwalkan lewat Windows Task Scheduler, atau lewat scheduler in-process dengan
FEED_SYNC_ENABLED=1 di .env (default mati — deploy tidak boleh langsung
memindahkan data).
"""
import os

from django.core.management.base import BaseCommand, CommandError

from apps.connections.models import ServerProfile
from apps.transactions import feed_sync


class Command(BaseCommand):
    help = "Sinkronkan master data dari server sumber ke toko lewat feed tbl_log_transaksi."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="Nama ServerProfile sumber (mis. GUDANG)")
        parser.add_argument(
            "--target", action="append", default=None,
            help="Nama ServerProfile tujuan. Boleh diulang. Default: semua kecuali sumber.",
        )
        parser.add_argument("--limit", type=int, default=2000, help="Maksimum baris feed per tujuan per run.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Jalankan penuh lalu ROLLBACK — tidak ada yang ditulis, tapi kegagalan tetap terlihat.",
        )
        parser.add_argument(
            "--from-id", type=int, default=None,
            help="Mulai dari id feed ini, abaikan cursor. Untuk mengulang batch tertentu.",
        )

    def _profil(self, nama):
        p = ServerProfile.objects.filter(name=nama).first()
        if not p:
            raise CommandError(f"ServerProfile '{nama}' tidak ditemukan.")
        return p

    def handle(self, *args, **opts):
        source = self._profil(opts["source"])
        if opts["target"]:
            targets = [self._profil(n) for n in opts["target"]]
        else:
            # Default HARUS sama dengan yang dipakai scheduler, yaitu
            # FEED_SYNC_TARGETS. Sebelum ini defaultnya "semua profil kecuali
            # sumber", sehingga menjalankan perintah ini tanpa --target memasang
            # cursor di server RETAIL yang jelas di luar lingkup — perintah dan
            # penjadwal punya pendapat berbeda tentang "semua toko".
            csv = os.environ.get("FEED_SYNC_TARGETS", "").strip()
            if not csv:
                raise CommandError(
                    "FEED_SYNC_TARGETS kosong dan --target tidak diberikan. Sebutkan "
                    "tujuannya secara eksplisit — 'semua profil' akan ikut menyeret "
                    "server retail yang di luar lingkup fan-out."
                )
            targets = [self._profil(n.strip()) for n in csv.split(",") if n.strip()]
        if not targets:
            raise CommandError("Tidak ada server tujuan.")

        mode = " (DRY RUN — tidak ada yang ditulis)" if opts["dry_run"] else ""
        self.stdout.write(f"Sumber: {source.name} -> {len(targets)} tujuan{mode}")
        self.stdout.write(f"Tabel yang difan-out: {', '.join(sorted(feed_sync.FEED_TABLE_SPECS))}")

        gagal = []
        for target in targets:
            hasil = feed_sync.sync_pair(
                source, target, limit=opts["limit"], dry_run=opts["dry_run"], from_id=opts["from_id"],
            )
            status = hasil["status"]
            if status == "failed":
                gagal.append(hasil)
                self.stderr.write(f"  {target.name}: GAGAL — {hasil['error']}")
            elif status == "posisi_awal":
                self.stdout.write(
                    f"  {target.name}: cursor ditetapkan di id {hasil['sampai_id']} "
                    f"(run pertama tidak memutar ulang riwayat)."
                )
            elif status == "tak_ada_perubahan":
                self.stdout.write(f"  {target.name}: sudah terbaru.")
            else:
                kemana = "dilewati" if opts["dry_run"] else "ke dead-letter"
                hilang = hasil.get("dilewati_hilang", 0)
                catatan = f", {hilang} tak ada lagi di sumber" if hilang else ""
                self.stdout.write(
                    f"  {target.name}: {hasil['diterapkan']} diterapkan, "
                    f"{hasil['disaring']} disaring, {hasil['dilewati']} {kemana}"
                    f"{catatan}, sampai id {hasil['sampai_id']}."
                )
                # Rincian alasan: "2.566 dilewati" tak berarti apa-apa tanpa tahu
                # apakah itu tabel yang memang tak difan-out atau kegagalan nyata.
                for alasan, n in sorted(hasil["alasan"].items(), key=lambda kv: -kv[1])[:10]:
                    self.stdout.write(f"      {n:>6}  {alasan}")

        if gagal:
            raise CommandError(f"{len(gagal)} tujuan gagal.")

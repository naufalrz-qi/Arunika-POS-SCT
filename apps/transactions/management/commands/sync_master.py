"""Samakan katalog toko grosir dengan GUDANG, tanpa lewat tbl_log_transaksi.

    python manage.py sync_master --dry-run
    python manage.py sync_master

Menutup celah yang ditinggalkan `feed_sync`: nama barang dan merek disebar lewat
memo `tbl_log_transaksi`, dan memo bisa dipangkas atau terpotong trigger. Di sini
kedua sisi dibaca lalu dibandingkan, jadi yang beda pasti ketahuan.

Harga TIDAK ikut — `m_barang_satuan` milik `harga_sync`, yang menyapunya tiap
60 detik. Menyapunya dua kali cuma menambah tulisan ke server toko, dan tiap
tulisan menyalakan trigger legacy di sana.

Supplier TIDAK ikut, dan itu aturan tetap: yang membeli adalah gudang, toko cuma
memakai segelintir supplier miliknya sendiri. Lihat daftar-izin `feed_sync`.

TIDAK PERNAH MENGHAPUS di toko. Barang lokal toko yang tak ada di gudang
dibiarkan; jumlahnya dilaporkan sebagai `dilewati` supaya keputusan itu
terlihat.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.transactions import harga_sync, hub_master


class Command(BaseCommand):
    help = "Samakan nama barang & merek di toko grosir dengan GUDANG."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--source", default="", help="Kosong = FEED_SYNC_SOURCE")

    def handle(self, *args, **o):
        source, targets = harga_sync.profil_fanout()
        if o["source"]:
            from apps.connections.models import ServerProfile

            source = ServerProfile.objects.filter(name=o["source"]).first()
        if not source:
            raise CommandError("Profil sumber tidak ada.")
        if not targets:
            raise CommandError("Tidak ada toko tujuan (FEED_SYNC_TARGETS).")

        self.stdout.write(
            f"{source.name} -> {', '.join(t.name for t in targets)}  "
            f"({', '.join(hub_master.TABEL_TOKO)})"
        )
        hasil = hub_master.sync_master_toko(source, targets, dry_run=o["dry_run"])

        for nama, baris in sorted(hasil["per_toko"].items()):
            total = {k: sum(b[k] for b in baris) for k in ("baru", "ubah", "hapus_dilewati")}
            self.stdout.write(
                f"  {nama:<14} baru={total['baru']:<6} ubah={total['ubah']:<6} "
                f"dilewati={total['hapus_dilewati']:,}"
            )
            for b in baris:
                if b["baru"] or b["ubah"]:
                    self.stdout.write(
                        f"      {b['tabel']:<18} baru={b['baru']:<6} ubah={b['ubah']:<6} "
                        f"sama={b['sama']:,}"
                    )
        for nama, pesan in sorted(hasil["gagal"].items()):
            # Toko yang gagal bukan sekadar catatan: katalognya tetap basi sampai
            # sapuan berikutnya, tanpa gejala apa pun di layar siapa pun.
            self.stdout.write(self.style.ERROR(f"  {nama:<14} GAGAL {pesan}"))

        gaya = self.style.WARNING if hasil["gagal"] else self.style.SUCCESS
        self.stdout.write(
            gaya("dry run - tidak ada yang ditulis" if o["dry_run"] else "selesai")
        )

r"""Bandingkan bentuk Arunika dengan sumber legacy-nya. Baca-saja.

Adapter yang salah petakan **tidak memunculkan galat**. View-nya tetap valid
secara SQL; yang terjadi cuma daftar pelanggan yang kurang, layar biaya yang
tampak "belum ada datanya", atau omzet yang meleset. Gejala seperti itu akan
dikira masalah data, bukan masalah kode -- dan bisa berbulan-bulan tak ketahuan.

Perintah ini menjadikan pemeriksaan yang tadinya manual sebagai sesuatu yang
bisa diulang siapa pun, kapan pun: sesudah mengubah pemetaan, sesudah menyiapkan
server baru, atau saat sebuah angka terasa janggal. Bentuknya mengikuti
`check_stock_agg` yang sudah ada -- membandingkan dua jalan menuju jawaban yang
sama, lalu mengatakan OK atau menunjukkan selisihnya.

    manage.py cek_arunika --profile testgudang
    manage.py cek_arunika --profile Testing --contoh 500

TIDAK menulis apa pun, di database mana pun.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.bisnis import master_src
from apps.connections.models import ServerProfile
from apps.transactions import reports
from core import mssql


# Filter "seluruh riwayat": tanpa predikat tanggal, supaya acuan dan yang
# diperiksa melihat kumpulan nota yang sama.
_FILTER_KOSONG = {"skip_date_predicate": True, "search": "", "recent": True}


class Command(BaseCommand):
    help = "Bandingkan jumlah baris view arunika_src.* dengan tabel legacy sumbernya."

    def add_arguments(self, parser):
        parser.add_argument("--profile", required=True)
        parser.add_argument(
            "--contoh", type=int, default=200,
            help="Berapa nota diperiksa untuk uji nilai uang. 0 = lewati.",
        )

    def handle(self, *args, **o):
        try:
            profil = ServerProfile.objects.get(name=o["profile"])
        except ServerProfile.DoesNotExist:
            raise CommandError(f"ServerProfile '{o['profile']}' tidak ada.")
        if not mssql.punya_arunika(profil):
            raise CommandError(
                f"Profil '{profil.name}' belum punya database Arunika. "
                "Jalankan `manage.py init_arunika` lebih dulu."
            )

        self.stdout.write(f"{profil.name}: legacy=[{profil.db_name}] arunika=[{profil.db_arunika}]")
        beda = []

        # --- 1. Database legacy tak boleh punya objek kita --------------
        with mssql.report_cursor(profil) as lc:
            lc.execute("SELECT COUNT(*) FROM sys.schemas WHERE name IN (?, ?)",
                       [master_src.SKEMA, "arunika"])
            n = lc.fetchone()[0]
        if n:
            beda.append(f"{n} schema milik kita ADA di database legacy")
            self.stdout.write(self.style.ERROR(f"  [1] schema kita di legacy: {n} (harus 0)"))
        else:
            self.stdout.write("  [1] database legacy bersih: 0 schema milik kita")

        # --- 2. Jumlah baris per entitas --------------------------------
        self.stdout.write("  [2] jumlah baris view vs tabel legacy")
        with mssql.arunika_cursor(profil) as vc, mssql.report_cursor(profil) as lc:
            for nama in master_src.daftar():
                tab = master_src.SUMBER_UTAMA[nama]
                vc.execute(f"SELECT COUNT(*) FROM {master_src.SKEMA}.{nama}")
                nv = vc.fetchone()[0]
                if nama == "penjualan":
                    # Acuannya BUKAN `t_penjualan` mentah. Badan view ini
                    # dibangkitkan dari `_nota_net()`, yang meng-INNER JOIN ke
                    # `t_penjualan_detail` -- jadi nota TANPA baris detail tidak
                    # muncul. Itu perilaku yang sudah berlaku di seluruh laporan
                    # penjualan Arunika, bukan sesuatu yang dibawa adapter.
                    # (grosirPusat: 1 nota, CT2202150001, nol baris detail.)
                    # Membandingkan dengan tabel mentah akan melaporkan selisih
                    # yang justru menandakan view-nya BENAR.
                    nota_sql, nota_prm = reports.penjualan_nota(_FILTER_KOSONG)
                    lc.execute(f"SELECT COUNT(*) FROM ({nota_sql}) q", nota_prm)
                    nl = lc.fetchone()[0]
                    tab = "_nota_net()"
                else:
                    lc.execute(f"SELECT COUNT(*) FROM {tab}")
                    nl = lc.fetchone()[0]
                if nv == nl:
                    self.stdout.write(f"      {nama:<18} {nv:>9}  OK")
                else:
                    beda.append(f"{nama}: view {nv} vs legacy {nl}")
                    self.stdout.write(self.style.ERROR(
                        f"      {nama:<18} {nv:>9}  != {nl} ({tab})"
                    ))

            # --- 3. Nilai uang nota ------------------------------------
            #
            # Acuan kebenarannya `_nota_net()` -- formula yang dipakai SELURUH
            # laporan penjualan Arunika -- karena badan view ini dibangkitkan
            # darinya. Keduanya wajib identik; kalau tidak, generatornya rusak.
            if o["contoh"] > 0 and "penjualan" in master_src.daftar():
                n = o["contoh"]
                nota_sql, nota_prm = reports.penjualan_nota(_FILTER_KOSONG)
                lc.execute(
                    f"SELECT TOP {n} RTRIM(q.no_transaksi), q.total_bersih "
                    f"FROM ({nota_sql}) q ORDER BY q.tanggal DESC", nota_prm
                )
                acuan = {r[0]: float(r[1] or 0) for r in lc.fetchall()}
                if acuan:
                    kode = list(acuan)
                    isi = ",".join("?" * len(kode))
                    vc.execute(
                        f"SELECT nomor, total FROM {master_src.SKEMA}.penjualan "
                        f"WHERE nomor IN ({isi})", kode
                    )
                    lihat = {r[0]: float(r[1] or 0) for r in vc.fetchall()}
                    meleset = [k for k in acuan if abs(acuan[k] - lihat.get(k, 0)) >= 0.005]
                    if meleset:
                        beda.append(f"nilai uang: {len(meleset)} dari {len(acuan)} nota meleset")
                        self.stdout.write(self.style.ERROR(
                            f"  [3] nilai uang vs _nota_net: {len(meleset)}/{len(acuan)} MELESET"
                        ))
                        k = meleset[0]
                        self.stdout.write(f"      {k}: view {lihat.get(k)} vs _nota_net {acuan[k]}")
                    else:
                        self.stdout.write(
                            f"  [3] nilai uang: {len(acuan)}/{len(acuan)} cocok dgn _nota_net"
                        )

                # Informasi, BUKAN kegagalan: `t_penjualan_total` (dan aplikasi
                # legacy) memotong nominal voucher, `_nota_net()` tidak. Selisih
                # di sini adalah perbedaan akuntansi yang sudah diketahui dan
                # belum diputuskan -- bukan adapter yang rusak.
                vc.execute(
                    f"SELECT COUNT(*) FROM {master_src.SKEMA}.penjualan v "
                    f"INNER JOIN [{profil.db_name}].dbo.t_penjualan_total t "
                    f"  ON RTRIM(t.no_transaksi) = v.nomor "
                    f"WHERE ABS(v.total - t.total) >= 0.005"
                )
                nbeda = vc.fetchone()[0]
                self.stdout.write(
                    f"  [4] beda dgn t_penjualan_total: {nbeda} nota "
                    "(voucher; keputusan akuntansi yang belum diambil, bukan galat)"
                )

        if beda:
            raise CommandError("TIDAK COCOK:\n  - " + "\n  - ".join(beda))
        self.stdout.write(self.style.SUCCESS("OK: bentuk Arunika cocok dengan sumber legacy."))

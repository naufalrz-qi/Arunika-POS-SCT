"""Pindahkan isi pangkal SQLite lama ke pangkal MS SQL yang sudah di-migrate.

Sekali jalan, saat cutover. Sesudahnya berkas SQLite-nya tinggal arsip.

## Kenapa bukan dumpdata/loaddata

`loaddata` menyimpan SATU OBJEK PER `save()`. `BarangHargaState` sendiri berisi
778.916 baris; lewat jalur itu ia butuh berjam-jam, dan JSON perantaranya ratusan
MB. Perintah ini membaca lewat ORM dari alias SQLite read-only dan menulis dengan
`bulk_create` berbatch — backend mengecilkan batch-nya sendiri ke batas
2.100 parameter SQL Server.

## Tiga hal yang diam-diam salah kalau tidak ditangani

1. **`auto_now` / `auto_now_add`.** `bulk_create` memanggil `pre_save`, yang
   MENIMPA kolom itu dengan waktu sekarang. Tanpa `_bekukan_waktu`, seluruh cap
   waktu riwayat — `ActivityLog.timestamp`, `SyncLog.created_at`,
   `ServerProfile.created_at`, 778.916 `BarangHargaState.last_seen` — berubah
   jadi jam migrasi. Jumlah barisnya tetap cocok, `check_constraints()` tetap
   bersih, dan tak ada satu pun gejala.
2. **Urutan foreign key.** Diselesaikan dengan mematikan penjagaan constraint
   selama penyalinan, LALU memanggil `check_constraints()` sendiri:
   `enable_constraint_checking()` milik mssql-django memakai `WITH NOCHECK`,
   jadi tanpa panggilan eksplisit itu FK-nya "untrusted" dan tak pernah
   divalidasi. PK/UNIQUE tidak ikut dimatikan — duplikat memang harus meledak.
3. **Benih IDENTITY.** Primary key asli ikut disalin (mssql-django membungkus
   insert-nya dengan `SET IDENTITY_INSERT`), tapi benih kolom identity-nya
   diperiksa ulang di akhir: satu `INSERT` pertama yang menabrak pk lama adalah
   cara paling bodoh untuk kehilangan sore hari.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from __future__ import annotations

import contextlib
import itertools
import time
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count
from django.db.models.functions import Length

from apps.core.db_alias import lupakan

ALIAS = "pangkal_lama"

# Dibangkitkan ulang `post_migrate` di target, dan id-nya boleh berbeda.
# Ketiga tabel M2M yang merujuknya kosong — diperiksa, bukan diasumsikan:
# penyalinan tetap membawa tabel M2M, jadi kalau suatu saat berisi, jumlah
# barisnya akan berbeda dan verifikasi di akhir yang menolak.
LEWATI = {("contenttypes", "contenttype"), ("auth", "permission")}


def daftarkan_sumber(berkas: Path) -> str:
    """Daftarkan berkas SQLite sebagai alias baca-saja. Pola sama dengan db_alias.

    `file:...?mode=ro` — Django selalu mengirim `uri=True` ke sqlite3, jadi tak
    perlu OPTIONS. Read-only itu bukan kehati-hatian umum: ia jaminan bahwa
    berkas cadangan tak pernah berubah, sehingga rollback selalu mungkin.
    """
    konfigurasi = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": f"file:{berkas.as_posix()}?mode=ro",
    }
    lengkap = connections.configure_settings(
        {**connections.settings, ALIAS: konfigurasi}
    )[ALIAS]
    connections.settings[ALIAS] = lengkap
    settings.DATABASES[ALIAS] = lengkap
    return ALIAS


@contextlib.contextmanager
def _bekukan_waktu(model):
    """Matikan auto_now/auto_now_add milik `model` selama penyalinan."""
    asli = [
        (f, f.auto_now, f.auto_now_add)
        for f in model._meta.fields
        if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False)
    ]
    for f, _an, _ana in asli:
        f.auto_now = f.auto_now_add = False
    try:
        yield
    finally:
        for f, an, ana in asli:
            f.auto_now, f.auto_now_add = an, ana


def model_disalin():
    """Model yang ikut pindah, termasuk tabel M2M yang dibuat otomatis."""
    return [
        m for m in django_apps.get_models(include_auto_created=True)
        if (m._meta.app_label, m._meta.model_name) not in LEWATI
    ]


def _kolom_teks(model):
    return [f for f in model._meta.fields
            if f.get_internal_type() == "CharField" and f.max_length]


def periksa_panjang(model, using: str) -> list[tuple[str, int, int]]:
    """[(kolom, pk, panjang)] untuk nilai yang melebihi max_length."""
    temuan = []
    for f in _kolom_teks(model):
        qs = (model._base_manager.using(using)
              .annotate(_p=Length(f.attname))
              .filter(_p__gt=f.max_length)
              .values_list("pk", "_p")[:50])
        temuan += [(f.attname, pk, p) for pk, p in qs]
    return temuan


def _kunci_unik(model):
    """Daftar tuple kolom yang unik TANPA syarat — yang NULL-nya digabung MS SQL."""
    kunci = [list(u) for u in model._meta.unique_together]
    for c in model._meta.constraints:
        if type(c).__name__ == "UniqueConstraint" and not c.condition and c.fields:
            kunci.append(list(c.fields))
    kunci += [[f.name] for f in model._meta.fields if f.unique and not f.primary_key]
    return kunci


def periksa_duplikat(model, using: str) -> list[tuple[tuple, dict, int]]:
    """[(kolom, nilai, jumlah)] untuk kunci unik yang kembar bila NULL == NULL.

    GROUP BY di SQLite menggabungkan NULL persis seperti unique index MS SQL,
    jadi pertanyaan ini bisa ditanyakan ke sumbernya sendiri.
    """
    temuan = []
    for kolom in _kunci_unik(model):
        qs = (model._base_manager.using(using).values(*kolom)
              .annotate(_n=Count("*")).filter(_n__gt=1)[:20])
        temuan += [(tuple(kolom), {k: b[k] for k in kolom}, b["_n"]) for b in qs]
    return temuan


def _tabel_ada(model, using: str) -> bool:
    with connections[using].cursor() as cur:
        return model._meta.db_table in connections[using].introspection.table_names(cur)


def kolom_hilang(model, using: str) -> list[str]:
    """Kolom yang dituntut model tapi tak ada di tabel sumber.

    Skema sumber bisa lebih tua daripada kode: berkas cadangan dibuat sebelum
    migrasi terakhir. Membaca lewat ORM lalu akan gagal dengan "no such column"
    di tengah penyalinan, sesudah tabel-tabel sebelumnya terlanjur masuk.
    """
    with connections[using].cursor() as cur:
        ada = {k.name for k in connections[using].introspection.get_table_description(
            cur, model._meta.db_table)}
    return [f.column for f in model._meta.concrete_fields if f.column not in ada]


LEWAT_ARUNIKA = "skema Arunika, bukan milik pangkal"


def keputusan_model(model, ada: bool, baris: int, kurang: list[str]) -> tuple[str, str]:
    """(tindakan, alasan) untuk satu model: salin / lewati / tolak_arunika / tolak_skema.

    Murni — seluruh fakta database sudah di tangan pemanggil. Dipisah dari `handle()`
    bukan demi kerapian: mengujinya lewat perintah utuh menuntut berkas SQLite palsu
    plus alias runtime, dan kerangka test Django memblokir alias yang tak disebut di
    muka. Aturannya sendiri hanyalah urutan keempat syarat ini.
    """
    if not ada:
        return "lewati", "tabelnya tak ada di sumber"
    if model._meta.app_label == "bisnis":
        # Skema Arunika milik database cabang, dan sejak `apps/core/db_router.py`
        # tabelnya tak lagi dibuat di pangkal — di target tak ada tujuan untuk
        # menyalinnya. Kosong = memang begitu seharusnya. Berisi = ada sesuatu yang
        # tak kita mengerti, dan menyalinnya diam-diam ke tempat yang salah lebih
        # buruk daripada berhenti.
        return ("tolak_arunika", "") if baris else ("lewati", LEWAT_ARUNIKA)
    if kurang:
        # Skema sumber lebih tua. Kosong = tak ada yang hilang kalau dilewati;
        # berisi = penyalinannya TIDAK boleh diteruskan diam-diam.
        if baris:
            return "tolak_skema", ", ".join(kurang)
        return "lewati", "kolom " + ", ".join(kurang) + " belum ada, tabelnya kosong"
    return "salin", ""


def _jumlah_mentah(model, using: str) -> int:
    """COUNT(*) lewat SQL mentah — ORM tak bisa dipakai kalau kolomnya kurang."""
    with connections[using].cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{model._meta.db_table}"')
        return cur.fetchone()[0]


class Command(BaseCommand):
    help = "Salin isi pangkal SQLite lama ke pangkal MS SQL yang aktif."

    def add_arguments(self, p):
        p.add_argument("--sumber", required=True,
                       help="Berkas db-YYYYMMDD.sqlite3 hasil backup_db (BUKAN db.sqlite3 hidup).")
        p.add_argument("--periksa-saja", action="store_true",
                       help="Hanya praperiksa/verifikasi; tak menulis apa pun.")
        p.add_argument("--perbaiki", action="store_true",
                       help="Potong nilai yang melebihi max_length saat menyalin (dilaporkan satu per satu).")
        p.add_argument("--paksa", action="store_true",
                       help="Lanjutkan walau ada -wal di sebelah berkas sumber.")
        p.add_argument("--batch", type=int, default=1000)

    # ------------------------------------------------------------------ jalan
    def handle(self, *args, **o):
        berkas = Path(o["sumber"])
        self._praperiksa_berkas(berkas, o["paksa"])
        self._praperiksa_target()
        daftarkan_sumber(berkas)
        try:
            model, dilewati, berisi, arunika = [], [], [], []
            for m in model_disalin():
                ada = _tabel_ada(m, ALIAS)
                baris = _jumlah_mentah(m, ALIAS) if ada else 0
                kurang = kolom_hilang(m, ALIAS) if ada else []
                tindakan, alasan = keputusan_model(m, ada, baris, kurang)
                if tindakan == "salin":
                    model.append(m)
                elif tindakan == "lewati":
                    dilewati.append((m, alasan))
                elif tindakan == "tolak_arunika":
                    arunika.append((m, baris))
                else:
                    berisi.append((m, kurang))
            for m, alasan in dilewati:
                self.stdout.write(self.style.WARNING(f"  lewati {m._meta.db_table}: {alasan}"))
            if berisi:
                for m, kurang in berisi:
                    self.stdout.write(self.style.ERROR(
                        f"  {m._meta.db_table}: berisi data tapi kolom {', '.join(kurang)} "
                        "tak ada di sumber"))
                raise CommandError(
                    "Skema sumber lebih tua daripada kode DAN tabelnya berisi. Jalankan "
                    "migrasi pada pemasangan lama dulu, buat cadangan baru, lalu ulangi."
                )
            if arunika:
                for m, baris in arunika:
                    self.stdout.write(self.style.ERROR(
                        f"  {m._meta.db_table}: {baris} baris skema Arunika di pangkal "
                        "SQLite lama"))
                raise CommandError(
                    "Tabel skema Arunika berisi data di pangkal lama. Tempatnya bukan di "
                    "pangkal (lihat apps/core/db_router.py), jadi perintah ini tak punya "
                    "tujuan yang benar untuk menyalinnya. Pindahkan dulu ke database "
                    "Arunika cabang yang bersangkutan, kosongkan di sumber, lalu ulangi."
                )
            self._praperiksa_target_kosong(model, o["periksa_saja"])
            cacat = self._praperiksa_data(model, o["perbaiki"])
            if o["periksa_saja"]:
                # Target masih kosong = ini praperiksa SEBELUM pindah, bukan
                # verifikasi sesudahnya. Menjalankan verifikasi di situ hanya
                # menghasilkan "gagal" untuk keadaan yang memang diharapkan.
                if any(m._base_manager.using("default").exists() for m in model):
                    self._verifikasi(model)
                else:
                    self.stdout.write(self.style.SUCCESS(
                        "Target masih kosong. " + ("Bereskan cacat di atas dulu."
                                                   if cacat else "Siap disalin.")))
                return
            if cacat:
                raise CommandError(
                    "Praperiksa menemukan cacat data di atas. Jalankan ulang dengan "
                    "--perbaiki untuk memotong nilai kepanjangan; duplikat kunci unik "
                    "harus dibereskan di sumbernya (lihat migrasi core 0017)."
                )
            self._salin(model, o["batch"], o["perbaiki"])
            self._verifikasi(model)
        finally:
            lupakan(ALIAS)

    # ------------------------------------------------------------ praperiksa
    def _praperiksa_berkas(self, berkas: Path, paksa: bool):
        if not berkas.is_file():
            raise CommandError(f"Berkas sumber tak ada: {berkas}")
        if berkas.open("rb").read(16) != b"SQLite format 3\x00":
            raise CommandError(f"{berkas} bukan berkas SQLite.")
        wal = berkas.with_name(berkas.name + "-wal")
        if wal.exists() and wal.stat().st_size and not paksa:
            raise CommandError(
                f"Ada {wal.name} tak kosong di sebelah sumber. Berkasnya masih dipakai "
                "atau belum ter-checkpoint, dan membacanya read-only akan gagal atau "
                "melewatkan transaksi terakhir. Pakai berkas hasil `backup_db`, atau "
                "--paksa kalau Anda yakin."
            )

    def _praperiksa_target_kosong(self, model, periksa_saja: bool):
        """Target harus kosong sebelum menyalin — tak ada mode lanjut-separuh.

        Perintah ini tidak tahu baris mana yang sudah masuk, dan menyalin ulang
        di atas isi lama berarti pk yang bentrok atau, lebih buruk, separuh
        tabel yang tak pernah ketahuan.
        """
        if periksa_saja:
            return
        terisi = [m._meta.db_table for m in model if m._base_manager.using("default").exists()]
        if terisi:
            raise CommandError(
                "Target sudah berisi: " + ", ".join(terisi[:5])
                + (" ..." if len(terisi) > 5 else "")
                + ". Hapus databasenya, buat ulang, `migrate`, lalu ulangi — "
                "perintah ini sengaja tak punya mode lanjut-separuh."
            )

    def _praperiksa_target(self):
        if connection.vendor not in ("microsoft", "mssql"):
            raise CommandError(
                f"Target bukan MS SQL ({connection.vendor}). Isi POS_APP_DB_* di .env."
            )
        versi = getattr(connection, "sql_server_version", None)
        if versi and versi < 2016:
            raise CommandError(f"SQL Server {versi} terlalu tua; JSONField butuh 2016+.")
        executor = MigrationExecutor(connection)
        tertunda = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if tertunda:
            raise CommandError(
                f"{len(tertunda)} migrasi belum dijalankan di target. "
                "Jalankan `manage.py migrate` dulu."
            )

    def _praperiksa_data(self, model, perbaiki: bool) -> bool:
        cacat = False
        for m in model:
            nama = m._meta.db_table
            for kolom, pk, panjang in periksa_panjang(m, ALIAS):
                batas = m._meta.get_field(kolom.removesuffix("_id")
                                          if kolom.endswith("_id") else kolom).max_length
                tindakan = "akan dipotong" if perbaiki else "PERLU --perbaiki"
                self.stdout.write(self.style.WARNING(
                    f"  panjang: {nama}.{kolom} pk={pk}: {panjang} > {batas} ({tindakan})"))
                cacat = cacat or not perbaiki
            for kolom, nilai, jumlah in periksa_duplikat(m, ALIAS):
                self.stdout.write(self.style.ERROR(
                    f"  kembar: {nama} {'+'.join(kolom)} = {nilai} sebanyak {jumlah}x"))
                cacat = True
        self.stdout.write("Praperiksa data selesai." + ("" if cacat else " Bersih."))
        return cacat

    # ---------------------------------------------------------------- salinan
    def _potong(self, m, baris):
        for f in _kolom_teks(m):
            nilai = getattr(baris, f.attname)
            if isinstance(nilai, str) and len(nilai) > f.max_length:
                setattr(baris, f.attname, nilai[:f.max_length])
        return baris

    def _salin(self, model, batch: int, perbaiki: bool):
        mulai = time.monotonic()
        with connection.constraint_checks_disabled():
            for m in model:
                t0 = time.monotonic()
                n = 0
                sumber = m._base_manager.using(ALIAS).order_by("pk").iterator(chunk_size=2000)
                with _bekukan_waktu(m):
                    for potongan in itertools.batched(sumber, batch):
                        isi = [self._potong(m, b) for b in potongan] if perbaiki else list(potongan)
                        with transaction.atomic(using="default"):
                            m._base_manager.using("default").bulk_create(isi, batch_size=batch)
                        n += len(isi)
                if n:
                    self.stdout.write(
                        f"  {m._meta.db_table}: {n:,} baris ({time.monotonic() - t0:.1f}s)")
        self.stdout.write(self.style.SUCCESS(
            f"Penyalinan selesai dalam {time.monotonic() - mulai:.1f}s."))

    # ------------------------------------------------------------- verifikasi
    def _verifikasi(self, model):
        gagal = []
        for m in model:
            a = m._base_manager.using(ALIAS).count()
            b = m._base_manager.using("default").count()
            if a != b:
                gagal.append(f"{m._meta.db_table}: sumber {a:,} vs target {b:,}")
        self.stdout.write(f"Jumlah baris dibandingkan untuk {len(model)} model.")

        connection.check_constraints()
        self.stdout.write("check_constraints(): bersih (FK, ISJSON, dan CHECK >= 0).")

        for m in model:
            auto = m._meta.auto_field
            if not auto:
                continue
            maks = m._base_manager.using("default").order_by("-pk").values_list("pk", flat=True).first()
            if maks is None:
                continue
            with connection.cursor() as cur:
                kini = cur.execute(
                    "SELECT IDENT_CURRENT(%s)", [m._meta.db_table]).fetchone()[0]
                if kini is None or int(kini) < maks:
                    cur.execute(f"DBCC CHECKIDENT ('{m._meta.db_table}', RESEED, {maks})")
                    self.stdout.write(f"  benih identity {m._meta.db_table} -> {maks}")

        from apps.auth_app.models import TautanUser
        from apps.connections.models import ServerProfile
        from core.encryption import decrypt_checked

        tautan_sumber = {(t.user_id, t.profile_id) for t in TautanUser.objects.using(ALIAS)}
        tautan_target = {(t.user_id, t.profile_id) for t in TautanUser.objects.using("default")}
        if tautan_sumber != tautan_target:
            gagal.append(f"TautanUser berbeda: hanya di sumber {tautan_sumber - tautan_target}, "
                         f"hanya di target {tautan_target - tautan_sumber}")
        else:
            self.stdout.write(f"TautanUser: {len(tautan_target)} pasangan, sama dengan sumber.")

        buruk = []
        for p in ServerProfile.objects.using("default"):
            try:
                decrypt_checked(p.password_encrypted)
            except Exception as exc:  # noqa: BLE001 — pesannya yang penting
                buruk.append(f"{p.name}: {type(exc).__name__}")
        if buruk:
            gagal.append("password profil tak bisa didekripsi: " + ", ".join(buruk))
        else:
            self.stdout.write(
                f"Password profil: {ServerProfile.objects.using('default').count()} terbaca "
                "dengan POS_FERNET_KEY yang aktif.")

        if gagal:
            for g in gagal:
                self.stdout.write(self.style.ERROR("  " + g))
            raise CommandError(
                "Verifikasi GAGAL. Target belum boleh dipakai: hapus databasenya, "
                "buat ulang, `migrate`, lalu jalankan perintah ini lagi."
            )
        self.stdout.write(self.style.SUCCESS("Verifikasi lulus."))

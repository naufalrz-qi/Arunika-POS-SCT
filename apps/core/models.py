"""Audit trail (pangkal, MS SQL). PRD §5.1 / §7.6."""
import datetime as dt
import hashlib
import json

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone


class ActivityLog(models.Model):
    """Satu peristiwa: siapa melakukan apa, kapan, dari mana — dan, untuk
    perubahan data bisnis, isi sebelum/sesudahnya.

    Satu tabel untuk semua jejak, bukan tabel audit kedua. Lonceng notif, kartu
    dashboard, Log Aktivitas, dan Jejak Audit membaca baris yang SAMA; dua tabel
    berarti dua tempat sebuah peristiwa bisa tercatat di satu dan terlewat di
    yang lain.

    Baris baru dirangkai hash (`hash_prev` → `hash`, lihat `save()`), sehingga
    baris yang diubah atau dihapus langsung di database terdeteksi oleh
    `manage.py cek_jejak`. Baris dari sebelum migrasi 0019 tak ber-hash dan
    berada di luar rantai.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    # Denormalized username so logs survive user deletion.
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=50)
    detail = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    # --- Kolom audit (0019). Semuanya boleh kosong: ±40 pemanggil lama tetap
    # sah tanpa menyebutnya, dan baris lama tetap terbaca.
    #
    # Koneksi tempat peristiwa itu terjadi. `no_transaksi` bertabrakan antar
    # server, jadi nomor dokumen tanpa koneksi tak menunjuk apa pun. Namanya
    # didenormalisasi seperti `username`: profil yang dihapus tak boleh membuat
    # jejaknya kehilangan tempat.
    profile = models.ForeignKey(
        "connections.ServerProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    profile_name = models.CharField(max_length=100, blank=True)
    # Dokumen yang disentuh, mis. ("penjualan", "SC2609250001").
    jenis_dokumen = models.CharField(max_length=30, blank=True)
    no_dokumen = models.CharField(max_length=40, blank=True)
    # Alasan yang DIKETIK orangnya. Wajib untuk perubahan dokumen; dipisah dari
    # `detail` karena `detail` ringkasan buatan kode, bukan kata-kata manusia.
    alasan = models.CharField(max_length=255, blank=True)
    # JSON: {"skema": "legacy", "sebelum": {...}, "sesudah": {...}, ...}.
    # TextField, bukan JSONField, supaya isi yang di-hash persis string yang
    # tersimpan — JSONField boleh menormalkan urutan/spasi saat membaca ulang.
    data = models.TextField(blank=True)
    hash_prev = models.CharField(max_length=64, blank=True)
    hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["no_dokumen", "profile_name"], name="ix_log_dokumen"),
        ]

    def __str__(self) -> str:
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.username} {self.action}"

    def save(self, *args, **kwargs):
        """Baris BARU dirangkai ke rantai hash; update biasa tidak.

        Di `save()`, bukan di `log_activity()`: ada penulis yang memanggil
        `ActivityLog.objects.create()` langsung (`bisnis/transfer.py`), dan
        rantai yang hanya dijaga satu pintu masuk punya lubang di pintu lain.
        `bulk_create` memang melewatinya — satu-satunya pemakainya
        `pindah_pangkal`, yang menyalin baris lama beserta hash-nya apa adanya.
        """
        if not (self._state.adding and not self.hash):
            return super().save(*args, **kwargs)
        using = kwargs.get("using") or "default"
        with transaction.atomic(using=using):
            kepala = _kunci_rantai(using)
            self.hash_prev = kepala.hash_terakhir
            super().save(*args, **kwargs)
            # Di-hash dari BACAAN ULANG database, bukan dari atribut di memori:
            # GenericIPAddressField menormalkan IPv6 saat menyimpan, dan waktu
            # bisa dibulatkan kolomnya. Hash dari nilai di memori akan gagal
            # diverifikasi untuk baris yang tak pernah diubah siapa pun.
            isi = type(self).objects.using(using).values(*KOLOM_HASH).get(pk=self.pk)
            self.hash = hash_jejak(isi)
            type(self).objects.using(using).filter(pk=self.pk).update(hash=self.hash)
            kepala.hash_terakhir = self.hash
            kepala.id_terakhir = self.pk
            kepala.save(update_fields=["hash_terakhir", "id_terakhir"])


class RantaiJejak(models.Model):
    """Kepala rantai hash ActivityLog: SATU baris, dikunci setiap penulisan.

    Tanpa kunci, dua thread waitress (atau thread penjadwal dan `manage.py`)
    yang menulis bersamaan sama-sama membaca hash terakhir yang sama dan rantai
    bercabang — lalu `cek_jejak` melaporkan kerusakan yang tak pernah terjadi.
    Kunci baris di database, bukan `threading.Lock`, karena penulisnya bisa
    berada di proses yang berbeda.

    `hash_terakhir` juga menangkap penghapusan EKOR rantai: baris terakhir yang
    dihapus tak meninggalkan mata rantai putus di tengah, tapi kepala ini masih
    menunjuk hash-nya.
    """

    kunci = models.CharField(max_length=10, unique=True, default="utama")
    hash_terakhir = models.CharField(max_length=64, blank=True)
    id_terakhir = models.BigIntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"rantai {self.kunci}: #{self.id_terakhir}"


# Kolom yang ikut di-hash. `user_id` dan `profile_id` SENGAJA tidak: keduanya
# SET_NULL, jadi menghapus akun atau profil akan "merusak" rantai yang tak
# disentuh siapa pun. Nama tersalinnya (`username`, `profile_name`) yang dijaga.
KOLOM_HASH = (
    "id", "timestamp", "username", "action", "detail", "ip_address",
    "profile_name", "jenis_dokumen", "no_dokumen", "alasan", "data", "hash_prev",
)


def _cap_waktu(v) -> str:
    if v is None:
        return ""
    if timezone.is_aware(v):
        v = v.astimezone(dt.timezone.utc)
    return v.isoformat(timespec="microseconds")


def hash_jejak(isi: dict) -> str:
    """sha256 dari kolom `KOLOM_HASH` satu baris (dict hasil `.values()`)."""
    urut = [_cap_waktu(isi["timestamp"]) if k == "timestamp" else (isi.get(k) or "")
            for k in KOLOM_HASH]
    urut[0] = int(isi["id"])
    teks = json.dumps(urut, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(teks.encode("utf-8")).hexdigest()


def _kunci_rantai(using: str = "default") -> "RantaiJejak":
    """Baris kepala rantai, terkunci sampai transaksi pemanggil selesai."""
    qs = RantaiJejak.objects.using(using).select_for_update()
    kepala = qs.filter(kunci="utama").first()
    if kepala is None:
        # Migrasi 0019 membuatnya; ini untuk database yang dikosongkan (test
        # TransactionTestCase memotong semua tabel). Dua pembuat bersamaan:
        # yang kalah menabrak unique `kunci`, lalu membaca milik pemenang.
        try:
            with transaction.atomic(using=using):
                RantaiJejak.objects.using(using).create(kunci="utama")
        except IntegrityError:
            pass
        kepala = qs.get(kunci="utama")
    return kepala


def periksa_rantai(using: str = "default") -> dict:
    """Telusuri rantai dari awal. Mengembalikan ringkasan + mata rantai putus
    PERTAMA (bukan semua: sesudah satu putus, setiap baris sesudahnya ikut
    tak cocok dan daftar panjang itu tak menambah informasi)."""
    qs = (ActivityLog.objects.using(using).exclude(hash="")
          .order_by("id").values(*KOLOM_HASH, "hash"))
    sebelum, jumlah, putus = "", 0, None
    for isi in qs.iterator(chunk_size=2000):
        jumlah += 1
        if isi["hash_prev"] != sebelum:
            putus = {"id": isi["id"], "sebab": "hash_prev tak menyambung ke baris sebelumnya "
                                               "(ada baris yang dihapus atau disisipkan)"}
            break
        if hash_jejak(isi) != isi["hash"]:
            putus = {"id": isi["id"], "sebab": "isi baris tak cocok dengan hash-nya (baris diubah)"}
            break
        sebelum = isi["hash"]
    if putus is None:
        kepala = RantaiJejak.objects.using(using).filter(kunci="utama").first()
        if kepala and kepala.hash_terakhir and kepala.hash_terakhir != sebelum:
            putus = {"id": kepala.id_terakhir,
                     "sebab": "baris terakhir rantai hilang (ekor rantai dihapus)"}
    return {"jumlah": jumlah, "putus": putus}


def log_untuk(user):
    """Jejak yang boleh dilihat `user`: miliknya sendiri, kecuali superadmin.

    Satu aturan untuk TIGA layar — kartu Aktivitas Terbaru di dashboard, kotak
    notif di navbar, dan halaman Log Aktivitas. Sebelumnya hanya dashboard yang
    menyaring, dan halaman log memperlihatkan jejak semua orang kepada admin
    mana pun; dua aturan untuk data yang sama adalah cara paling rapi supaya
    satu di antaranya diam-diam tertinggal saat yang lain diperbaiki.

    Disaring lewat `username` (salinan teks di baris log), bukan relasi ke User:
    kolom itu didenormalisasi supaya jejak tetap terbaca setelah akunnya dihapus,
    dan menyaring lewat FK akan menyembunyikan baris-baris itu dari superadmin.
    """
    from apps.auth_app.models import Role

    qs = ActivityLog.objects.all()
    if not (user and getattr(user, "is_authenticated", False)):
        return qs.none()
    if user.role == Role.SUPERADMIN:
        return qs
    return qs.filter(username=user.username)


def log_activity(request, action, detail="", *, profile=None, dokumen=None,
                 alasan="", data=None):
    """Catat satu jejak dari sebuah request.

    Argumen kata-kunci hanya untuk perubahan data bisnis (Edit Nota, dsb.):
    `profile` koneksi tempat dokumennya tinggal, `dokumen` = (jenis, nomor),
    `alasan` ketikan orangnya, `data` dict sebelum/sesudah. Pemanggil lama tak
    menyebut satu pun dan barisnya tetap sama seperti dulu.
    """
    from apps.core.http import client_ip

    user = getattr(request, "user", None)
    # Lewat helper, bukan REMOTE_ADDR mentah: di belakang proxy setiap baris
    # audit akan mencatat alamat proxy-nya, dan pertanyaan "dari mana" — satu-
    # satunya alasan kolom ini ada — berhenti bisa dijawab untuk semua orang
    # sekaligus, tanpa ada yang menyadarinya sampai dibutuhkan.
    ip = client_ip(request) if request else None
    jenis_dok, no_dok = dokumen if dokumen else ("", "")
    return ActivityLog.objects.create(
        profile=profile,
        profile_name=(getattr(profile, "name", "") or "")[:100],
        jenis_dokumen=str(jenis_dok or "")[:30],
        no_dokumen=str(no_dok or "").strip()[:40],
        alasan=str(alasan or "").strip()[:255],
        # Isi LENGKAP tinggal di sini, bukan di `detail` yang dipotong 255.
        data=(json.dumps(data, ensure_ascii=False, default=str) if data is not None else ""),
        user=user if (user and user.is_authenticated) else None,
        username=(user.username if (user and user.is_authenticated) else ""),
        action=action,
        # Dipotong DI SINI, penulis satu-satunya, bukan di pemanggil yang
        # kebetulan meluap duluan (`monitoring.views.menus_save` mengirim
        # daftar 40+ kunci menu dipisah koma). SQLite tak menegakkan panjang
        # kolom, jadi baris 505 karakter lolos bertahun-tahun; MS SQL
        # menolaknya. Kolomnya sengaja tidak dilebarkan: 255 -> 1000 hanya
        # memindahkan tebingnya, dan layar Log Aktivitas menampilkan detail
        # ini apa adanya dalam satu baris.
        detail=str(detail)[:255],
        ip_address=ip,
    )


class SyncLog(models.Model):
    """Riwayat SATU proses latar: sinkronisasi, tarik AMPHOREUS, cadangan, transfer.

    Menggantikan ActivityLog (terlalu generik: tidak ada field src/dst/mode/
    jumlah) sebagai sumber data untuk halaman Riwayat Operasi.

    Dipakai lintas-fitur, bukan hanya sync harga/master seperti dulu. `feature`
    adalah nama bebas ("harga", "hub_pull", "feed_sync", "backup", "transfer"),
    dan `compared_count`/`applied_count` dibaca sebagai "diperiksa"/"diterapkan"
    — sengaja generik supaya enam fitur muat di satu tabel dan satu garis waktu,
    bukan enam tabel 80% identik yang harus di-UNION di Python.

    Yang TIDAK ditanyakan ke tabel ini: "apakah job-nya masih hidup?". Baris di
    sini adalah KEJADIAN, dan job yang sehat di hari sunyi tidak menulis apa pun
    (lihat aturan anti-banjir di tiap pemanggil). Liveness dijawab
    `scheduler.status()`, yang membaca memori proses. Satu kolom dua arti adalah
    persis yang bikin `m_barang_stok_akhir` legacy tak bisa dipercaya.
    """

    class Status(models.TextChoices):
        OK = "ok", "Berhasil"
        PARTIAL = "partial", "Sebagian"
        FAILED = "failed", "Gagal"
        # Dipakai tugas latar yang dipicu dari web: baris progres dan baris
        # riwayat adalah baris yang SAMA. Selesai = status pindah dari sini ke
        # ok/failed dan duration_ms terisi — tak ada tabel progres kedua yang
        # harus dijaga tetap sinkron dengan yang ini.
        BERJALAN = "berjalan", "Berjalan"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_logs",
    )
    # Denormalized so logs survive user/profile deletion, same pattern as ActivityLog.username.
    username = models.CharField(max_length=150, blank=True)
    feature = models.CharField(max_length=30)  # "harga" | "m_barang" | "m_customer" | "m_supplier"
    mode = models.CharField(max_length=30, blank=True)
    src_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="sync_logs_src"
    )
    src_name = models.CharField(max_length=100, blank=True)
    dst_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="sync_logs_dst"
    )
    dst_name = models.CharField(max_length=100, blank=True)
    compared_count = models.PositiveIntegerField(default=0)
    applied_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK)
    detail = models.TextField(blank=True)  # JSON-serialized list of changed-item dicts
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Satu-satunya angka di baris ini yang tak bisa dihitung ulang: tidak ada
    # `selesai_at`, jadi tanpa kolom ini "hub_pull lambat" tak bisa dibedakan
    # dari "hub_pull sedang jalan". Diisi di akhir run, tetap 0 untuk baris yang
    # masih BERJALAN.
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.feature} {self.src_name}->{self.dst_name}"

    def items(self) -> list:
        return json.loads(self.detail) if self.detail else []


class BarangUpdateLog(models.Model):
    """Riwayat perubahan per-barang dari halaman Update Barang (harga & status).

    Satu baris per field yang benar-benar berubah (bukan per klik simpan), supaya
    "Riwayat" pada kartu barang bisa langsung menampilkan nilai lama -> baru.
    """

    class Field(models.TextChoices):
        HARGA = "harga", "Harga Jual"
        STATUS_BARANG = "status_barang", "Status Barang"
        STATUS_DIVISI = "status_divisi", "Status Divisi"
        STATUS_SATUAN = "status_satuan", "Status Satuan"
        # Identitas barang — hanya bisa diubah dari server gudang. Dicatat di
        # riwayat yang sama supaya satu tempat menjawab "apa yang berubah pada
        # barang ini"; nama yang berubah tanpa jejak adalah perubahan yang paling
        # menyulitkan, karena ia menyebar ke seluruh cabang lewat sinkronisasi.
        NAMA = "nama", "Nama Barang"
        KETERANGAN = "keterangan", "Keterangan"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barang_update_logs",
    )
    # Denormalized so logs survive user/profile deletion, same pattern as ActivityLog.username.
    username = models.CharField(max_length=150, blank=True)
    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="barang_update_logs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    kd_barang = models.CharField(max_length=30)
    nama_barang = models.CharField(max_length=150, blank=True)
    field = models.CharField(max_length=20, choices=Field.choices)
    kd_ref = models.CharField(max_length=30, blank=True)  # kd_satuan / kd_divisi, kosong utk level m_barang
    nilai_lama = models.CharField(max_length=100, blank=True)
    nilai_baru = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["profile", "kd_barang", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.kd_barang} {self.field}: {self.nilai_lama} -> {self.nilai_baru}"


def log_barang_updates(request, profile, kd_barang, nama_barang, entries):
    """Catat satu atau lebih perubahan field untuk satu barang (harga/status).

    `entries`: list of (field, kd_ref, nilai_lama, nilai_baru). Entri dengan
    nilai_lama == nilai_baru dilewati (bukan perubahan nyata).
    """
    user = getattr(request, "user", None)
    username = user.username if (user and user.is_authenticated) else ""
    rows = [
        BarangUpdateLog(
            user=user if (user and user.is_authenticated) else None,
            username=username,
            profile=profile,
            profile_name=profile.name if profile else "",
            kd_barang=kd_barang,
            nama_barang=nama_barang,
            field=field,
            kd_ref=kd_ref or "",
            nilai_lama="" if nilai_lama is None else str(nilai_lama),
            nilai_baru="" if nilai_baru is None else str(nilai_baru),
        )
        for field, kd_ref, nilai_lama, nilai_baru in entries
        if str(nilai_lama) != str(nilai_baru)
    ]
    if rows:
        BarangUpdateLog.objects.bulk_create(rows)


class CdcSyncCursor(models.Model):
    """Resume point for one CDC-synced table (apps/transactions/cdc_sync.py).

    `last_lsn` is the SQL Server LSN (varbinary(10)) up to which changes for
    this table have already been applied to the report_source replica, stored
    as a hex string (bytes.hex()) since Django/SQLite has no native varbinary.
    One row per (profile, table_name) — the sync job reads it to know where to
    resume, and writes it after each successful batch.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="cdc_cursors"
    )
    table_name = models.CharField(max_length=64)
    last_lsn = models.CharField(max_length=20, blank=True)  # hex(varbinary(10)) = 20 chars
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_rows_applied = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, default="ok")  # "ok" | "failed"
    error_message = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "table_name"], name="unique_cdc_cursor_per_table")
        ]

    def __str__(self) -> str:
        return f"{self.profile_id}:{self.table_name} @ {self.last_lsn or '(belum sync)'}"


def _fk_profil(p):
    """`p` kalau ia benar-benar `ServerProfile` yang sudah tersimpan, selain itu None."""
    from apps.connections.models import ServerProfile

    return p if isinstance(p, ServerProfile) and p.pk else None


def log_sync(request, feature, mode, src, dst, compared, applied, status="ok", items=None,
             error="", duration_ms=0, username=""):
    """Catat satu proses latar untuk halaman Riwayat Operasi.

    `request` boleh None: job terjadwal dan management command tidak punya satu,
    dan `getattr(None, "user", None)` sudah mengembalikan None sejak dulu. Yang
    kurang cuma cara memberi nama pelakunya — itulah `username`, yang diisi
    "(terjadwal)" oleh scheduler dan "(cli)" oleh management command. Karena itu
    TIDAK ada writer kedua untuk jalur tanpa request.

    `src`/`dst` boleh objek apa pun yang punya `.name`, bukan harus
    `ServerProfile` tersimpan. Nama tetap masuk (kolomnya memang sudah
    didenormalisasi supaya baris bertahan sesudah profilnya dihapus); hanya
    FK-nya yang dilepas. Alasannya bukan kenyamanan test: fungsi ini dipanggil
    dari dalam job yang sedang berjalan, dan sebuah PENCATAT tidak boleh pernah
    menjatuhkan pekerjaan yang dicatatnya.
    """
    user = getattr(request, "user", None)
    SyncLog.objects.create(
        user=user if (user and user.is_authenticated) else None,
        username=username or (user.username if (user and user.is_authenticated) else ""),
        feature=feature,
        mode=mode,
        src_profile=_fk_profil(src),
        src_name=getattr(src, "name", "") if src else "",
        dst_profile=_fk_profil(dst),
        dst_name=getattr(dst, "name", "") if dst else "",
        compared_count=compared,
        applied_count=applied,
        status=status,
        detail=json.dumps(items or []),
        error_message=error,
        duration_ms=duration_ms,
    )


class BarangHargaState(models.Model):
    """Harga terkini per SKU per koneksi — baseline untuk deteksi perubahan harga
    harian (management command `snapshot_harga`). Di-update di tempat, jadi
    ukurannya tetap (satu baris per SKU per server), bukan bertambah tiap hari.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="harga_states"
    )
    kd_barang = models.CharField(max_length=30)
    kd_satuan = models.CharField(max_length=30)
    harga_jual = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    margin = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "kd_barang", "kd_satuan"], name="unique_harga_state_sku")
        ]
        indexes = [models.Index(fields=["profile", "kd_barang", "kd_satuan"])]

    def __str__(self) -> str:
        return f"{self.profile_id}:{self.kd_barang}/{self.kd_satuan} = {self.harga_jual}"


class BarangHargaChange(models.Model):
    """Log perubahan harga yang terdeteksi job harian (append-only). Menangkap
    perubahan dari sumber APA PUN (termasuk edit langsung di POS), beda dari
    `BarangUpdateLog` yang hanya mencatat perubahan lewat aplikasi ini.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="harga_changes"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    kd_barang = models.CharField(max_length=30)
    nama_barang = models.CharField(max_length=150, blank=True)
    kd_satuan = models.CharField(max_length=30)
    harga_lama = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    harga_baru = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["profile", "-detected_at"]),
            models.Index(fields=["kd_barang", "-detected_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.detected_at:%Y-%m-%d} {self.kd_barang}/{self.kd_satuan} {self.harga_lama}->{self.harga_baru}"


class HargaSnapshotRun(models.Model):
    """Penanda satu kali jalan snapshot harga per (profile, tanggal). Dipakai
    scheduler in-process (config/wsgi.py + apps.core.scheduler) supaya cukup jalan
    sekali/hari selama server hidup, sekaligus info "terakhir dijalankan".
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="harga_snapshot_runs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    run_date = models.DateField()
    ran_at = models.DateTimeField(auto_now_add=True)
    changes = models.PositiveIntegerField(default=0)
    seeded = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-ran_at"]
        constraints = [
            # `condition`, karena `profile` nullable (SET_NULL saat profilnya
            # dihapus). SQLite menganggap dua NULL berbeda; SQL Server
            # menganggapnya SAMA, jadi tanpa syarat ini run yatim milik dua
            # profil berbeda di hari yang sama saling menabrak. Penulisnya
            # (apps/core/scheduler.py) selalu mengisi `profile`, jadi indeks
            # tersaring menutupi setiap baris yang benar-benar dibaca.
            models.UniqueConstraint(
                fields=["profile", "run_date"],
                condition=models.Q(profile__isnull=False),
                name="unique_harga_snapshot_run_per_day",
            )
        ]

    def __str__(self) -> str:
        return f"{self.run_date} {self.profile_name}: {self.changes} perubahan"


class StokSnapshotRun(models.Model):
    """Penanda satu kali jalan snapshot stok per (profile, tanggal). Sama pola
    dengan HargaSnapshotRun: dipakai scheduler in-process supaya rebuild penuh
    (berat) cukup sekali/hari, sekaligus info "terakhir dijalankan".
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="stok_snapshot_runs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    run_date = models.DateField()
    ran_at = models.DateTimeField(auto_now_add=True)
    rows = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-ran_at"]
        constraints = [
            # Sama seperti HargaSnapshotRun di atas: NULL yang dianggap sama
            # oleh SQL Server.
            models.UniqueConstraint(
                fields=["profile", "run_date"],
                condition=models.Q(profile__isnull=False),
                name="unique_stok_snapshot_run_per_day",
            )
        ]

    def __str__(self) -> str:
        return f"{self.run_date} {self.profile_name}: {self.rows} baris"


class StokSnapshotBaseRun(models.Model):
    """Penanda rebuild BASE snapshot (beku ~13 bln) per (profile, bulan-base).
    Base cukup dibangun sekali per bulan kalender base — marker ini mencegah
    rebuild penuh (berat, scan sejak tutup buku) berulang di bulan yang sama.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="stok_snapshot_base_runs"
    )
    profile_name = models.CharField(max_length=100, blank=True)
    base_month = models.CharField(max_length=7)  # "YYYY-MM" dari base_date
    ran_at = models.DateTimeField(auto_now_add=True)
    rows = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-ran_at"]
        constraints = [
            # Sama seperti dua di atas.
            models.UniqueConstraint(
                fields=["profile", "base_month"],
                condition=models.Q(profile__isnull=False),
                name="unique_stok_snapshot_base_per_month",
            )
        ]

    def __str__(self) -> str:
        return f"{self.base_month} {self.profile_name}: {self.rows} baris"


class SyncHealthSample(models.Model):
    """Satu pengukuran kesehatan sync legacy untuk satu server, satu waktu.

    Halaman Kesehatan Sync membaca angka LANGSUNG dari server tiap kali dibuka;
    tabel ini yang membuatnya jadi riwayat. Tanpa riwayat, "antre 8.000" tak bisa
    dibedakan dari "antre 8.000 dan naik terus sejak Mei" — dan justru pembedaan
    itulah yang tak ada selama empat tahun sementara RTL PUSAT menumpuk sejuta
    baris tanpa seorang pun tahu.

    Ditulis tiap tick scheduler (bukan harian): sync yang mati perlu ketahuan
    dalam hitungan menit, bukan besok.
    """

    class Status(models.TextChoices):
        OK = "ok", "Sehat"
        LAMBAT = "lambat", "Lambat"
        MATI = "mati", "Mati"
        OFFLINE = "offline", "Tak terhubung"

    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sync_health_samples",
    )
    profile_name = models.CharField(max_length=100, blank=True)
    # Kedalaman antrean keluar (tbl_tmp_post) + umur baris tertuanya.
    antre = models.BigIntegerField(default=0)
    antre_tertua = models.DateTimeField(null=True, blank=True)
    antre_terbaru = models.DateTimeField(null=True, blank=True)
    # Watermark arah masuk (tbl_waktu_get) — kapan server ini terakhir menarik data.
    watermark_get = models.DateTimeField(null=True, blank=True)
    # Ujung feed (tbl_log_transaksi) — dipakai feed_sync/hub_sync sbg cursor.
    # Tidak dihapus job legacy, tapi BISA dipangkas pemeliharaan DB; nilai yang
    # turun antar-sampel dibaca `services_sync._stuck()` sebagai feed di-reset.
    feed_id = models.BigIntegerField(null=True, blank=True)
    feed_waktu = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK)
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["profile", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.profile_name}: {self.status} (antre {self.antre})"


class FeedSyncCursor(models.Model):
    """Titik lanjut satu pasangan (sumber → tujuan) untuk apps/transactions/feed_sync.py.

    `last_id` adalah tbl_log_transaksi.id terakhir yang SUDAH diterapkan ke
    server tujuan. Kolom itu IDENTITY + clustered PK di sumber, jadi `WHERE id > ?`
    adalah seek, bukan scan — itulah sebabnya feed ini dipakai sebagai sumber
    perubahan alih-alih tbl_tmp_post (yang dihapus job legacy).

    Satu baris per (source_profile, target_profile): tiap toko punya posisi
    sendiri, jadi satu toko yang mati tidak menahan yang lain.
    """

    source_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="feed_cursors_out"
    )
    target_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="feed_cursors_in"
    )
    last_id = models.BigIntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_rows_applied = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, default="ok")  # "ok" | "failed"
    error_message = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_profile", "target_profile"], name="unique_feed_cursor_per_pair"
            )
        ]

    def __str__(self) -> str:
        # ASCII, bukan panah: __str__ ini muncul di log dan konsol Windows
        # (cp1252) yang tak bisa mengencode U+2192 dan melempar UnicodeEncodeError
        # justru saat seseorang sedang menelusuri kegagalan.
        return f"{self.source_profile_id}->{self.target_profile_id} @ id {self.last_id}"


class SyncDeadLetter(models.Model):
    """Satu baris feed yang TIDAK diterapkan, beserta alasannya.

    Ada supaya kegagalan tidak punya dua jalan keluar yang sama-sama buruk:
    menghentikan seluruh run (pola `goto hell` di job legacy, yang membuat sisa
    antrean terlewat sesiklus) atau ditelan diam-diam. Baris masuk sini, cursor
    tetap maju, dan kegagalannya bisa dibaca manusia.

    Yang TIDAK masuk sini: baris yang tabelnya di luar daftar-izin. Itu
    penyaringan yang disengaja, bukan kerusakan, dan jumlahnya mayoritas isi feed
    (2.566 dari 3.000 pada uji nyata) — mencatatnya akan menimbun ribuan baris
    tiap tick dan menenggelamkan kegagalan yang sungguhan. Jumlahnya dilaporkan
    per run sebagai `disaring`, tidak disimpan.

    Jadi tabel ini idealnya KOSONG. Isinya berarti ada yang perlu dilihat.
    """

    source_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dead_letters_out",
    )
    target_profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dead_letters_in",
    )
    feed_id = models.BigIntegerField(default=0)
    table_aksi = models.CharField(max_length=255, blank=True)
    formatted_data = models.TextField(blank=True)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["source_profile", "-created_at"])]

    def __str__(self) -> str:
        return f"id {self.feed_id} {self.table_aksi}: {self.reason}"


class HubPullState(models.Model):
    """Posisi tarik-langsung satu cabang ke pusat (apps/transactions/hub_pull.py).

    BUKAN `FeedSyncCursor`. Cursor itu menyimpan `last_id` feed dan seluruh
    halaman Kesehatan Sync menafsirkannya sebagai "ketinggalan" — jarak ke ujung
    feed. `hub_pull` tidak punya konsep itu sama sekali: ia menyapu rentang
    tanggal, jadi tidak ada yang bisa tertinggal, dan angka yang bisa basi
    hanyalah KAPAN sapuan terakhir terjadi. Menumpangkan dua arti pada satu
    kolom adalah cara paling rapi untuk membuat halaman monitoring berbohong.

    Tiga tingkat, tiga stempel waktu:

    - `arsip_selesai_at` — sekali seumur hidup, untuk `tanggal <= tutup_buku`.
      Tutup buku adalah lantai keras; di bawahnya data tidak berubah lagi.
    - `cocok_terakhir_at` — sekali sehari, membandingkan agregat per hari antara
      tutup buku dan jendela segar. `hari_beda` = berapa hari yang tidak cocok
      dan karena itu disalin ulang; idealnya 0, dan angka yang bukan 0 adalah
      temuan, bukan derau.
    - `segar_terakhir_at` — tiap tick, N hari terakhir disalin ulang tanpa
      dibandingkan.

    `tutup_buku` disimpan hanya untuk ditampilkan. Yang dipakai saat menyapu
    selalu dibaca ulang dari cabang: kalau klien menjalankan tutup buku lagi,
    batasnya maju, dan batas yang di-cache akan diam-diam menyapu ulang rentang
    yang sudah jadi arsip.
    """

    source_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="hub_pull_out"
    )
    target_profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="hub_pull_in"
    )
    tutup_buku = models.DateTimeField(null=True, blank=True)
    arsip_selesai_at = models.DateTimeField(null=True, blank=True)
    # Ujung atas potongan arsip terakhir yang BERHASIL di-commit. Titik lanjut,
    # bukan hiasan: run pertama kehilangan 285.809 header PUSAT karena jaringan
    # putus di potongan ke-32 dari 48 dan tidak ada yang menandai 31 potongan
    # sebelumnya sudah selesai. Menjalankan ulang dari nol tetap BENAR (semuanya
    # idempoten) — yang hilang cuma jam kerjanya, dan justru itu yang mahal.
    arsip_sampai = models.DateTimeField(null=True, blank=True)
    cocok_terakhir_at = models.DateTimeField(null=True, blank=True)
    segar_terakhir_at = models.DateTimeField(null=True, blank=True)
    hari_beda = models.IntegerField(default=0)
    rows_header = models.BigIntegerField(default=0)
    rows_detail = models.BigIntegerField(default=0)
    rows_deleted = models.BigIntegerField(default=0)
    status = models.CharField(max_length=10, default="ok")  # "ok" | "failed"
    error_message = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_profile", "target_profile"], name="unique_hub_pull_per_pair"
            )
        ]

    def __str__(self) -> str:
        # ASCII, bukan panah: ini muncul di konsol Windows (cp1252), yang tak bisa
        # mengencode U+2192 dan melempar justru saat seseorang menelusuri kegagalan.
        return f"{self.source_profile_id}->{self.target_profile_id} arsip={bool(self.arsip_selesai_at)}"


class InfoPerusahaan(models.Model):
    """Identitas perusahaan untuk kop struk — SATU baris per koneksi.

    Disimpan di SQLite, bukan di `g_info_profile` pada server legacy, dan itu
    keputusan yang dibeli dengan pengukuran. Tabel legacy itu bukan tabel master:
    16.581 baris di grosirPusat / 18.927 di SERVER-TOYS / 14.867 di testGudang,
    `COUNT(DISTINCT)` = 1 pada SETIAP kolom (seluruhnya duplikat identik), dan
    `sys.indexes` cuma memulangkan satu baris HEAP — tanpa primary key, tanpa
    kolom identity, tanpa index. Tak ada `WHERE` yang bisa menunjuk satu baris di
    sana, sehingga satu-satunya tulis yang benar adalah mengganti SELURUH isinya.
    Menulis belasan ribu baris tiap klik Simpan, ke tabel milik aplikasi lama
    yang masih membacanya, bukan harga yang pantas dibayar untuk tiga baris kop.

    Di sini identitasnya milik Arunika sendiri: satu baris, punya kunci, dan
    tidak menyentuh satu pun tabel legacy.

    Per KONEKSI, bukan global — alasan yang sama seperti `TautanUser`: satu
    Arunika melayani gudang dan delapan grosir, dan tiap server punya alamat dan
    telepon sendiri.
    """

    profile = models.OneToOneField(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="info_perusahaan")
    perusahaan = models.CharField(max_length=200, blank=True, default="")
    alamat = models.CharField(max_length=300, blank=True, default="")
    kota = models.CharField(max_length=100, blank=True, default="")
    telp = models.CharField(max_length=60, blank=True, default="")
    hp = models.CharField(max_length=60, blank=True, default="")
    email = models.CharField(max_length=120, blank=True, default="")
    website = models.CharField(max_length=120, blank=True, default="")
    nama_kontak = models.CharField(max_length=120, blank=True, default="")
    diperbarui_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.profile_id}: {self.perusahaan or '(belum diisi)'}"


class TransferArunika(models.Model):
    """Satu kali jalan layar Transfer ke Arunika: legacy -> salinan lokal -> DB Arunika.

    Tinggal di database pangkal, BUKAN `apps/bisnis/models.py`: model di sana
    adalah skema Arunika sendiri dan ikut termigrasi ke setiap database Arunika
    yang dibuat -- catatan jalan tak boleh ikut tersalin ke sana.

    Pekerjaannya berjalan di thread latar (`apps/bisnis/transfer.py`), dan baris
    ini satu-satunya tempat layar membaca progresnya. `langkah` diperbarui tiap
    tabel/entitas selesai; halaman memuat ulang prop-nya selama status
    `berjalan`.
    """

    BERJALAN, SELESAI, GAGAL, TERPUTUS = "berjalan", "selesai", "gagal", "terputus"
    STATUS = [
        (BERJALAN, "Berjalan"),
        (SELESAI, "Selesai"),
        (GAGAL, "Gagal"),
        # Server berhenti (restart, deploy) saat thread masih bekerja. Hasilnya
        # setengah jadi; profil & database-nya tetap ada dan boleh dihapus.
        (TERPUTUS, "Terputus"),
    ]

    nama = models.CharField(max_length=100)
    sumber = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="transfer_arunika_sumber",
    )
    sumber_nama = models.CharField(max_length=100, blank=True)
    profil_legacy = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="transfer_arunika_legacy",
    )
    profil_arunika = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="transfer_arunika_tujuan",
    )
    dari = models.DateField()
    sampai = models.DateField()
    # Tutup buku terakhir server sumber saat transfer dimulai. Mesin stok
    # berjangkar di tanggal ini dan menghitung maju/mundur darinya, jadi stok di
    # profil legacy hasil transfer hanya benar kalau rentang `dari..sampai`
    # mencakupnya. Terukur pada salinan PUSAT Januari 2025: stok 31 Des 2025
    # nol beda, stok 31 Jan 2025 beda di 9.741 barang. NULL = sumber tak punya
    # catatan tutup buku.
    tutup_buku = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default=BERJALAN)
    tahap = models.CharField(max_length=100, blank=True)
    # [{tahap, nama, baris, detik, dilewati, alasan}], urut selesai.
    langkah = models.JSONField(default=list, blank=True)
    pesan_galat = models.TextField(blank=True)
    total_baris = models.PositiveIntegerField(default=0)
    total_dilewati = models.PositiveIntegerField(default=0)
    dibuat_oleh = models.CharField(max_length=150, blank=True)
    mulai_pada = models.DateTimeField(auto_now_add=True)
    selesai_pada = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-mulai_pada"]

    @property
    def stok_benar(self):
        """True/False: apakah stok di profil legacy-nya bisa dipercaya. None = tak diketahui."""
        if self.tutup_buku is None:
            return None
        from django.utils import timezone

        tgl = self.tutup_buku
        tgl = timezone.localtime(tgl).date() if timezone.is_aware(tgl) else tgl.date()
        return self.dari <= tgl <= self.sampai

    def __str__(self) -> str:
        return f"{self.nama} ({self.status})"


class CadanganBerkas(models.Model):
    """Inventaris berkas cadangan, beserta hasil verifikasinya.

    Kenapa tabel dan bukan `os.listdir` pada folder cadangan — dua alasan, dan
    keduanya sudah pasti terjadi di pemasangan ini:

    1. **Berkas `.bak` AMPHOREUS ditulis DI MESIN SQL SERVER**, bukan di mesin
       yang menjalankan aplikasi. Kalau SQL Server ada di mesin lain, folder itu
       tidak terjangkau sama sekali dari sini, dan daftar berbasis `listdir`
       akan berkata "tidak ada cadangan" untuk cadangan yang sebenarnya ada.
    2. **Hasil verifikasi harus bertahan.** `RESTORE VERIFYONLY` pada berkas
       ratusan MB lewat WAN butuh waktu; menjalankannya ulang tiap kali halaman
       dibuka bukan pilihan.

    `verifikasi_ok` sengaja nullable TIGA nilai. "Belum pernah diverifikasi"
    bukan "gagal verifikasi", dan default `False` akan mengecat seluruh daftar
    merah pada hari pertama — peringatan yang selalu menyala adalah peringatan
    yang berhenti dibaca.
    """

    PANGKAL = "pangkal"
    AMPHOREUS = "amphoreus"
    JENIS = [(PANGKAL, "Basis data pangkal"), (AMPHOREUS, "Pusat AMPHOREUS")]

    jenis = models.CharField(max_length=10, choices=JENIS)
    profile = models.ForeignKey(
        "connections.ServerProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cadangan",
    )
    nama_berkas = models.CharField(max_length=255)
    # Sebagaimana dilihat MESIN PENULISNYA. Untuk AMPHOREUS itu path di mesin
    # SQL Server, yang bisa sama sekali tak berarti di mesin ini.
    path = models.CharField(max_length=500)
    # 0 = tak terjangkau dari mesin ini, BUKAN "berkas kosong".
    ukuran_byte = models.BigIntegerField(default=0)
    # `default=timezone.now`, BUKAN `auto_now_add`: cadangan harian menimpa
    # berkas bertanggal sama, dan barisnya diperbarui — bukan dibuat ulang.
    # `auto_now_add` tidak bisa disetel saat UPDATE, jadi tanggalnya akan beku
    # di kapan berkas itu pertama kali pernah ada, bukan kapan isinya ditulis.
    dibuat_at = models.DateTimeField(default=timezone.now)
    dibuat_oleh = models.CharField(max_length=150, blank=True)
    verifikasi_at = models.DateTimeField(null=True, blank=True)
    verifikasi_ok = models.BooleanField(null=True)
    verifikasi_pesan = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-dibuat_at"]
        constraints = [
            # Satu baris per berkas. Cadangan harian menimpa berkas bertanggal
            # sama (VACUUM INTO menghapus dulu, BACKUP pakai WITH INIT), jadi
            # baris keduanya akan menunjuk berkas yang sudah tidak ada isinya.
            models.UniqueConstraint(fields=["jenis", "path"], name="unique_cadangan_path"),
        ]

    def __str__(self) -> str:
        return f"{self.jenis}: {self.nama_berkas}"


class BayarNota(models.Model):
    """Uang yang DITERIMA kasir untuk sebuah nota penjualan.

    `t_penjualan` legacy tak punya kolom untuk ini (lihat `penjualan._HEADER`),
    dan database itu milik bersama dengan aplikasi POS lama — menambah kolom di
    sana bukan pilihan. Jadi angkanya tinggal di pangkal.

    Ia disimpan, bukan dihitung ulang, karena TAK BISA diturunkan dari apa pun:
    berapa lembar yang disodorkan pembeli adalah kejadian di meja kasir, bukan
    fungsi dari total nota. Sekali tak dicatat, ia hilang selamanya — sebelum
    ini ia cuma dioper lewat query string ke halaman cetak lalu lenyap, sehingga
    cetak ulang lewat Cetak Faktur sengaja mengosongkan baris Bayar/Kembali.

    `kembalian` TIDAK ikut disimpan. Ia `dibayar - total`, dan menghitungnya
    dari total versi server itulah yang membuat angka di struk tak bisa dikarang
    lewat URL.

    `profile` ikut jadi kunci dan NOT NULL: `no_transaksi` bertabrakan antar
    server — kode yang sama menunjuk nota yang lain di gudang dan di tiap toko.
    Kolom profil yang boleh NULL sudah pernah menggigit di proyek ini, lihat
    migrasi `0017_snapshot_unik_hanya_dengan_profil`.
    """

    profile = models.ForeignKey(
        "connections.ServerProfile", on_delete=models.CASCADE, related_name="bayar_nota")
    no_transaksi = models.CharField(max_length=30)
    dibayar = models.DecimalField(max_digits=18, decimal_places=2)
    # SET_NULL, bukan CASCADE: kasir yang keluar kerja tak boleh menghapus bukti
    # uang yang pernah ia terima.
    dibuat_oleh = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bayar_nota")
    dibuat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "no_transaksi"], name="unique_bayar_nota"),
        ]

    def __str__(self) -> str:
        return f"{self.no_transaksi}: {self.dibayar}"

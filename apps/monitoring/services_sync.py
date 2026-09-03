r"""Kesehatan sinkronisasi legacy per server — read-only, tanpa menyentuh apa pun.

Sync antar-server dijalankan oleh SQL Agent job di msdb tiap server (dump di
`scripts/job/`), bukan oleh aplikasi ini. Job itu tidak melaporkan apa-apa ke
mana pun: kalau ia berhenti bekerja, tidak ada yang berubah di layar siapa pun.
Modul ini membaca jejak yang ditinggalkannya di database dan menerjemahkannya
jadi satu status per server.

Tiga jejak yang dibaca:

- `tbl_tmp_post` — antrean KELUAR. Diisi trigger legacy, lalu **DIHAPUS** job
  setelah terkirim (`DELETE ... WHERE status='sent'`). Menumpuk = pengirimnya
  mati sementara trigger jalan terus.

  **Antrean kosong BUKAN bukti sehat.** Karena barisnya dihapus, tabel ini cuma
  menyimpan residu sesaat, tak menyimpan riwayat, dan "kosong" punya tiga tafsir
  yang tidak bisa dibedakan dari tabel itu sendiri: benar-benar terkirim, toko
  sedang tutup, atau trigger berhenti menulis. Karena itu ada dua penopang:
  kolom `bukti` (memakai keaktifan `tbl_log_transaksi` untuk memisahkan
  "terkirim" dari "tidak tahu") dan `_stuck()` (membandingkan dua sampel
  berturut-turut, satu-satunya deteksi yang tak bisa dikelabui penghapusan).

  Yang TETAP sahih dibaca dari tabel ini adalah timbunan yang tak pernah
  terkirim: RTL PUSAT menahan 1.043.804 baris ber-`status='waiting'` sejak
  2022-05-13 — terlihat justru karena tak satu pun pernah dihapus.
- `tbl_waktu_get` — watermark MASUK. Satu baris, di-`UPDATE ... GETDATE()` oleh
  job tiap kali ia berhasil menarik data dari pusat. Basi = penarikan mati.
- `tbl_log_transaksi` — feed perubahan. Bukan indikator kesehatan job legacy;
  kedua ujungnya dibaca di sini karena `feed_sync`/`hub_sync` memakainya sebagai
  cursor, dan enak dilihat berdampingan.

  **Append-only oleh aplikasi, TAPI BUKAN oleh pemeliharaan database.** Terukur
  di lini PUSAT: 1.469.155 id lenyap dalam satu blok utuh semalam 15-16 Mei 2024,
  saat database dipisah untuk meringankannya. Sisa lubangnya hanya 19, tiga di
  antaranya berukuran ~1.000 — lompatan identity-cache biasa saat layanan
  restart, bukan penghapusan. Karena itu `id` yang "cuma bertambah" tidak boleh
  dijadikan asumsi; lihat `_periksa_cursor()`.

## Kenapa kuerinya berbentuk begini

Bentuk polos (`COUNT(*)`, `MIN(waktu)`) memindai seluruh tabel. `tbl_tmp_post`
di RTL PUSAT berisi sejuta baris, dan halaman ini menyapu 11 server tiap kali
dibuka DAN tiap tick scheduler. Jadi:

- Jumlah antrean dibaca dari metadata partisi (`sys.dm_db_partition_stats`),
  bukan dihitung. Nilainya akurat untuk baris ter-commit dan didapat tanpa
  menyentuh datanya.
- Baris tertua/terbaru diambil lewat `TOP 1 ... ORDER BY id [DESC]`. `id` adalah
  IDENTITY dengan clustered PK, jadi keduanya seek satu baris. Ini sah karena id
  naik searah waktu (trigger menulis keduanya bersamaan); `MIN(waktu)` akan
  memberi jawaban sama dengan ongkos sejuta baris.

## Waktu

Datetime dari MS SQL di sini adalah jam dinding lokal server, tanpa tzinfo.
Umur dihitung terhadap "sekarang" lokal yang juga naif. Sengaja tidak ada
konversi zona waktu: file `d:\utc.txt` di job legacy ada persis karena seseorang
mencoba mengoreksi zona waktu di jalur ini dan hasilnya adalah watermark yang
meleset. Dua jam dinding dibandingkan apa adanya.
"""
from __future__ import annotations

import pyodbc
from django.utils import timezone

from core import mssql

# Ambang umur (menit). Antrean dinilai lebih ketat daripada watermark: job
# keluar berjadwal 5 menit, job masuk 5-10 menit dan wajar tersendat sesaat.
ANTRE_OK_MENIT = 15
ANTRE_LAMBAT_MENIT = 120
WATERMARK_OK_MENIT = 30
WATERMARK_LAMBAT_MENIT = 360
# Umur baris terbaru `tbl_log_transaksi` yang masih dianggap "ada aktivitas".
# Longgar (2 jam) karena toko sepi di jam-jam tertentu adalah hal normal, dan
# ini bukan alarm — hanya penentu apakah "antrean kosong" boleh dibaca sebagai
# bukti terkirim atau harus dibaca sebagai "tidak tahu".
AKTIF_MENIT = 120

STATUS_OK = "ok"
STATUS_LAMBAT = "lambat"
STATUS_MATI = "mati"
STATUS_OFFLINE = "offline"

# Urutan keparahan — dipakai untuk mengambil yang terburuk dari dua sumbu.
_PERINGKAT = {STATUS_OK: 0, STATUS_LAMBAT: 1, STATUS_MATI: 2, STATUS_OFFLINE: 3}

LABEL = {
    STATUS_OK: "Sehat",
    STATUS_LAMBAT: "Lambat",
    STATUS_MATI: "Mati",
    STATUS_OFFLINE: "Tak terhubung",
}


def _now_naive():
    """Jam dinding lokal tanpa tzinfo — sebanding dengan datetime dari MS SQL."""
    return timezone.localtime().replace(tzinfo=None)


def _umur_menit(waktu, sekarang=None):
    """Umur `waktu` dalam menit, atau None kalau tak ada waktunya.

    Waktu di masa depan (jam server tujuan lebih maju) menghasilkan angka
    negatif, dan itu dibiarkan apa adanya: 0 akan menyamarkan jam yang meleset
    sebagai 'baru saja', padahal selisih jam antar-server justru salah satu hal
    yang ingin terlihat di halaman ini.
    """
    if waktu is None:
        return None
    return (( sekarang or _now_naive()) - waktu).total_seconds() / 60.0


def _nilai_status(umur, ok_menit, lambat_menit):
    """Klasifikasi satu sumbu. `umur=None` berarti belum pernah ada datanya."""
    if umur is None:
        return None
    if umur < ok_menit:
        return STATUS_OK
    if umur < lambat_menit:
        return STATUS_LAMBAT
    return STATUS_MATI


def _terburuk(*statuses):
    kandidat = [s for s in statuses if s]
    if not kandidat:
        return STATUS_OK
    return max(kandidat, key=lambda s: _PERINGKAT[s])


def _scalar(cur, sql, params=None):
    cur.execute(sql, params or [])
    row = cur.fetchone()
    return row[0] if row else None


def _ujung_feed(cur) -> tuple[int | None, int]:
    """(id tertua, id terbaru) di `tbl_log_transaksi`.

    Dua `TOP 1 ... ORDER BY id [DESC]`, keduanya seek lewat clustered PK — sama
    murahnya dengan membaca `MAX(id)` saja. Yang tertua dibaca karena feed BISA
    kehilangan barisnya (lihat `_periksa_cursor`), dan tanpa angka itu lubang di
    depan cursor tidak bisa dibedakan dari feed yang baik-baik saja.
    """
    awal = _scalar(cur, "SELECT TOP 1 id FROM tbl_log_transaksi ORDER BY id")
    akhir = _scalar(cur, "SELECT TOP 1 id FROM tbl_log_transaksi ORDER BY id DESC")
    return (int(awal) if awal is not None else None, int(akhir or 0))


def _baca(cur) -> dict:
    """Kumpulkan angka mentah dari satu server. Semua kueri seek/metadata."""
    # index_id 0 = heap, 1 = clustered. Keduanya diikutkan supaya benar apa pun
    # bentuk tabelnya; hanya satu yang akan ada.
    antre = _scalar(
        cur,
        "SELECT SUM(row_count) FROM sys.dm_db_partition_stats "
        "WHERE object_id = OBJECT_ID('tbl_tmp_post') AND index_id IN (0, 1)",
    )
    antre_tertua = _scalar(cur, "SELECT TOP 1 waktu FROM tbl_tmp_post ORDER BY id")
    antre_terbaru = _scalar(cur, "SELECT TOP 1 waktu FROM tbl_tmp_post ORDER BY id DESC")
    watermark_get = _scalar(cur, "SELECT MAX(waktu) FROM tbl_waktu_get")
    feed = None
    cur.execute("SELECT TOP 1 id, waktu FROM tbl_log_transaksi ORDER BY id DESC")
    row = cur.fetchone()
    if row:
        feed = (row[0], row[1])
    return {
        "antre": int(antre or 0),
        "antre_tertua": antre_tertua,
        "antre_terbaru": antre_terbaru,
        "watermark_get": watermark_get,
        "feed_id": feed[0] if feed else None,
        "feed_waktu": feed[1] if feed else None,
    }


def sync_health(profile) -> dict:
    """Status sync satu server. Tidak pernah melempar — server yang tak bisa
    dihubungi mengembalikan status `offline` berikut pesannya.

    Halaman ini justru paling dibutuhkan saat ada yang rusak, jadi satu server
    mati tidak boleh menjatuhkan barisan yang lain (pola yang sama dipakai
    `apps/core/scheduler.py:_run_due_jobs`).
    """
    hasil = {
        "profile_id": profile.pk,
        "profile": profile.name,
        "host": profile.host,
        "antre": 0,
        "antre_tertua": None,
        "antre_terbaru": None,
        "antre_umur_menit": None,
        "watermark_get": None,
        "watermark_umur_menit": None,
        "feed_id": None,
        "feed_waktu": None,
        "aktivitas_menit": None,
        "bukti": "",
        "penyebab": "",
        "status": STATUS_OFFLINE,
        "status_label": LABEL[STATUS_OFFLINE],
        "error": "",
    }
    try:
        with mssql.cursor(profile) as cur:
            mentah = _baca(cur)
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["error"] = str(exc.args[-1] if exc.args else exc)[:255]
        return hasil

    sekarang = _now_naive()
    hasil.update(mentah)
    # Antrean kosong = tak ada yang tertunggak SAAT INI. Umur baris tertua hanya
    # berarti kalau memang ada barisnya.
    umur_antre = _umur_menit(mentah["antre_tertua"], sekarang) if mentah["antre"] else None
    umur_watermark = _umur_menit(mentah["watermark_get"], sekarang)
    umur_feed = _umur_menit(mentah["feed_waktu"], sekarang)
    hasil["antre_umur_menit"] = umur_antre
    hasil["watermark_umur_menit"] = umur_watermark
    hasil["aktivitas_menit"] = umur_feed

    # Bukti: apakah "antrean kosong" itu benar-benar berarti terkirim.
    #
    # `tbl_tmp_post` DIHAPUS begitu terkirim (`DELETE ... WHERE status='sent'`
    # di job_post_grosirPusat.sql), jadi antrean kosong punya tiga tafsir yang
    # tidak bisa dibedakan dari tabel itu sendiri: benar-benar terkirim, toko
    # sedang tutup, atau trigger berhenti menulis. `tbl_log_transaksi` tidak
    # dihapus oleh job legacy, jadi ujungnya dipakai untuk memisahkan yang
    # pertama dari dua sisanya. (Ia bisa dipangkas oleh pemeliharaan database —
    # lihat docstring modul — tapi itu peristiwa sesekali, bukan penghapusan
    # rutin per baris seperti `tbl_tmp_post`, jadi keaktifannya tetap sahih
    # dibaca sebagai bukti.)
    if umur_antre is not None:
        hasil["bukti"] = "antre"        # ada yang tertunggak; antrean memang berbicara
    elif umur_feed is None or umur_feed >= AKTIF_MENIT:
        hasil["bukti"] = "sepi"          # tak ada aktivitas: TIDAK TAHU, bukan sehat
    else:
        hasil["bukti"] = "aktif"         # ada perubahan baru DAN antrean bersih

    status_antre = _nilai_status(umur_antre, ANTRE_OK_MENIT, ANTRE_LAMBAT_MENIT)
    status_watermark = _nilai_status(umur_watermark, WATERMARK_OK_MENIT, WATERMARK_LAMBAT_MENIT)
    status_stuck = _stuck(profile, mentah)
    status = _terburuk(status_antre, status_watermark, status_stuck)

    # Sumbu mana pun yang serendah status akhir ikut disebut — bisa lebih dari
    # satu kalau seri (antre DAN watermark sama-sama mati). Ini yang membuat
    # badge "Mati" tidak perlu ditebak: user tak lagi harus membandingkan dua
    # kolom angka terhadap ambang sendiri untuk tahu penyebabnya.
    penyebab = []
    if status_antre and _PERINGKAT[status_antre] == _PERINGKAT[status]:
        penyebab.append("tertunggak")
    if status_watermark and _PERINGKAT[status_watermark] == _PERINGKAT[status]:
        penyebab.append("tarik terakhir")
    if status_stuck and _PERINGKAT[status_stuck] == _PERINGKAT[status]:
        penyebab.append("macet")
    hasil["penyebab"] = ", ".join(penyebab)

    hasil["status"] = status
    hasil["status_label"] = LABEL[status]
    return hasil


def _stuck(profile, mentah) -> str | None:
    """MATI kalau antrean tak bergerak padahal feed terus bertambah — ATAU kalau
    feed itu sendiri mundur.

    Ini deteksi yang tidak bisa dikelabui penghapusan: `tbl_tmp_post` dihapus
    saat terkirim, jadi kedalaman antrean saja tak pernah bisa membuktikan
    pengirimnya hidup. Yang membuktikan justru PERGERAKAN — baris tertua yang
    sama persis di dua sampel berturut-turut sementara `tbl_log_transaksi`
    bertambah berarti ada yang menumpuk dan tidak ada yang mengangkut.

    Menangkap pengirim yang baru saja mati, jauh sebelum ambang umur 2 jam
    tercapai. Butuh riwayat, jadi hanya bekerja kalau SYNC_HEALTH_ENABLED=1.
    """
    from apps.core.models import SyncHealthSample

    sebelum = (
        SyncHealthSample.objects.filter(profile=profile)
        .order_by("-created_at")
        .values("antre_tertua", "feed_id")
        .first()
    )
    if not sebelum or sebelum["feed_id"] is None:
        return None

    # Feed MUNDUR antar-sampel. Diperiksa lebih dulu dan tanpa syarat antrean,
    # karena kalau tidak, pemangkasan feed justru MEMATIKAN deteksi ini tanpa
    # suara: `feed_maju` di bawah jadi False selamanya dan fungsi ini pulang
    # `None` seolah semuanya baik-baik saja. Yang membuat pemeriksaan ini
    # berbeda dari `_periksa_cursor` adalah ia melihat pergerakan feed itu
    # sendiri, jadi ia menangkap pemangkasan bahkan pada server yang tidak jadi
    # sumber sync mana pun.
    if (mentah["feed_id"] or 0) < sebelum["feed_id"]:
        return STATUS_MATI

    if not mentah["antre"] or mentah["antre_tertua"] is None or sebelum["antre_tertua"] is None:
        return None
    tertua_sama = _aware(mentah["antre_tertua"]) == sebelum["antre_tertua"]
    feed_maju = (mentah["feed_id"] or 0) > sebelum["feed_id"]
    return STATUS_MATI if (tertua_sama and feed_maju) else None


def sync_health_all(profiles) -> list[dict]:
    """Sapu semua server, berurutan. Yang paling parah di atas supaya server
    mati tidak terkubur di halaman terakhir daftar yang diurut abjad."""
    baris = [sync_health(p) for p in profiles]
    baris.sort(key=lambda r: (-_PERINGKAT[r["status"]], r["profile"]))
    return baris


# --- Kesehatan pusat AMPHOREUS --------------------------------------------
#
# Sync baru yang tidak terpantau akan mati diam-diam persis seperti yang lama.
# Ukurannya beda dari job legacy: bukan "antrean menumpuk" (pusat tidak punya
# antrean), tapi KETINGGALAN — jarak antara ujung feed cabang dan posisi cursor
# kita. Ketinggalan yang terus naik antar-sampel = sync berhenti mengejar.
HUB_OK_LAG = 5_000
HUB_LAMBAT_LAG = 50_000


def _periksa_cursor(cursor_id: int, feed_min: int | None, feed_id: int) -> tuple[str | None, str, int]:
    """Cursor terhadap ujung feed. -> (status, alasan, jumlah id yang hilang).

    `tbl_log_transaksi` append-only **oleh aplikasi**, tapi bukan oleh
    pemeliharaan database. Terukur di lini PUSAT: 1.469.155 id lenyap dalam satu
    blok utuh semalam 15-16 Mei 2024 (sisa lubangnya cuma 19 dan tiga di
    antaranya berukuran ~1.000 — lompatan identity-cache biasa saat layanan
    restart, bukan penghapusan). Jadi "id cuma bertambah" bukan jaminan.

    Dua akibatnya tidak memunculkan error apa pun, dan tanpa pemeriksaan ini
    keduanya tampil `ok` dengan ketinggalan 0 — persis kegagalan senyap yang
    halaman ini dibuat untuk menghapuskan:

    - **Cursor mendahului ujung feed** (log dipangkas dari belakang, atau IDENTITY
      di-reseed). `WHERE id > cursor` tidak akan pernah mengembalikan baris lagi:
      cabang itu berhenti mengirim SELAMANYA sementara `max(0, feed - cursor)`
      membacanya sebagai 0 alias paling sehat.
    - **Cursor tertinggal di belakang baris tertua yang masih ada.** Sync tetap
      jalan dan ketinggalannya wajar, tapi baris di antaranya sudah lenyap dari
      feed dan tidak akan terisi sendiri. Hanya rekonsiliasi terhadap tabel
      aslinya yang bisa menambalnya — feed tidak bisa menceritakan apa yang sudah
      terhapus darinya.

    Keduanya dinilai `mati` supaya naik ke puncak daftar. Yang kedua sebetulnya
    masih berjalan, jadi yang membedakan adalah pesannya, bukan labelnya:
    menambah status kelima hanya untuk itu akan merembet ke `_PERINGKAT`, `LABEL`,
    pilihan status di model, dan tabel di layar.
    """
    if not cursor_id:
        return None, "", 0
    if feed_id < cursor_id:
        return (
            STATUS_MATI,
            # ASCII saja: pesan ini bisa ikut tercetak ke konsol Windows (cp1252),
            # dan em-dash di sana berubah jadi sampah — konvensi yang sama dengan
            # `FeedSyncCursor.__str__` di apps/core/models.py.
            f"feed dipangkas: ujung feed di {feed_id}, cursor di {cursor_id}, "
            "tak ada baris baru yang bisa terbaca lagi",
            0,
        )
    if feed_min is not None and cursor_id < feed_min - 1:
        hilang = feed_min - cursor_id - 1
        return (
            STATUS_MATI,
            f"lubang: {hilang} baris feed antara cursor ({cursor_id}) dan baris "
            f"tertua yang masih ada ({feed_min}) sudah terhapus",
            hilang,
        )
    return None, "", 0


def hub_health(source, hub) -> dict:
    """Posisi sync pusat untuk satu cabang. Tidak pernah melempar."""
    from apps.core.models import FeedSyncCursor, SyncDeadLetter

    hasil = {
        "profile_id": source.pk,
        "profile": source.name,
        "kode_sumber": source.kode_sumber,
        "cursor_id": 0,
        "feed_id": None,
        "feed_min": None,
        "ketinggalan": None,
        "lubang": 0,
        "last_synced_at": None,
        "dead_letter": 0,
        "status": STATUS_OFFLINE,
        "status_label": LABEL[STATUS_OFFLINE],
        "error": "",
    }
    row = FeedSyncCursor.objects.filter(source_profile=source, target_profile=hub).first()
    if row:
        hasil["cursor_id"] = row.last_id
        hasil["last_synced_at"] = row.last_synced_at
        if row.status == "failed":
            hasil["error"] = row.error_message
    hasil["dead_letter"] = SyncDeadLetter.objects.filter(
        source_profile=source, target_profile=hub,
        created_at__gte=timezone.now() - timezone.timedelta(days=1),
    ).count()

    try:
        with mssql.cursor(source) as cur:
            feed_min, feed_id = _ujung_feed(cur)
    except (pyodbc.Error, RuntimeError) as exc:
        hasil["error"] = str(exc.args[-1] if exc.args else exc)[:255]
        return hasil

    hasil["feed_id"] = feed_id
    hasil["feed_min"] = feed_min
    lag = max(0, feed_id - hasil["cursor_id"])
    if not row:
        # Belum pernah disync. Bukan sehat, bukan mati — belum mulai.
        #
        # Ketinggalannya sengaja dibiarkan kosong, bukan diisi feed_id - 0.
        # Angka itu akan terbaca "5,6 juta baris tertinggal" padahal run pertama
        # menetapkan cursor di UJUNG feed: tak satu pun dari baris itu akan
        # ditarik. Menampilkannya cuma bikin panik pada hal yang tidak terjadi.
        hasil["status"] = STATUS_LAMBAT
        hasil["error"] = hasil["error"] or "belum pernah sync"
        return hasil | {"status_label": LABEL[STATUS_LAMBAT]}
    # Ketinggalan dilaporkan APA ADANYA, tanpa `max(0, ...)`. Angka negatif
    # berarti cursor mendahului ujung feed, dan justru itulah yang perlu terlihat;
    # menjepitnya ke 0 mengubah cabang yang berhenti selamanya jadi baris paling
    # sehat di layar.
    hasil["ketinggalan"] = feed_id - hasil["cursor_id"]
    status_cursor, alasan, lubang = _periksa_cursor(hasil["cursor_id"], feed_min, feed_id)
    hasil["lubang"] = lubang
    if alasan:
        hasil["error"] = hasil["error"] or alasan
    if row.status == "failed":
        hasil["status"] = STATUS_MATI
    elif status_cursor:
        hasil["status"] = status_cursor
    elif lag < HUB_OK_LAG:
        hasil["status"] = STATUS_OK
    elif lag < HUB_LAMBAT_LAG:
        hasil["status"] = STATUS_LAMBAT
    else:
        hasil["status"] = STATUS_MATI
    hasil["status_label"] = LABEL[hasil["status"]]
    return hasil


def hub_health_all(hub, sources) -> list[dict]:
    baris = [hub_health(s, hub) for s in sources]
    baris.sort(key=lambda r: (-_PERINGKAT[r["status"]], r["profile"]))
    return baris


# --- Kesehatan tarik-langsung (apps/transactions/hub_pull.py) --------------
#
# Menggantikan `hub_health_all` di halaman. Ukurannya beda dan itu justru intinya:
# `hub_sync` diukur dengan KETINGGALAN (jarak cursor ke ujung feed), sementara
# `hub_pull` tidak punya cursor dan tidak bisa tertinggal — ia menyapu rentang
# tanggal. Satu-satunya yang bisa basi adalah KAPAN sapuan terakhir terjadi.
#
# Membiarkan bagian lama tetap tampil sesudah `hub_sync` dimatikan akan
# membekukan angkanya di posisi terakhir sambil tetap terlihat hijau — persis
# kegagalan senyap yang halaman ini dibuat untuk menghapuskan.
PULL_OK_MENIT = 60
PULL_LAMBAT_MENIT = 360


def hub_pull_health_all(hub, sources) -> list[dict]:
    """Status tarik-langsung tiap cabang ke pusat. Tanpa menyentuh MS SQL.

    Semua angkanya sudah ada di SQLite (`HubPullState`), jadi bagian ini tidak
    menambah satu pun round-trip ke sebelas server yang sudah disapu bagian
    pertama halaman.
    """
    from apps.core.models import HubPullState

    state = {
        s.source_profile_id: s
        for s in HubPullState.objects.filter(target_profile=hub)
    }
    sekarang = timezone.now()
    baris = []
    for src in sources:
        s = state.get(src.pk)
        r = {
            "profile_id": src.pk,
            "profile": src.name,
            "kode_sumber": src.kode_sumber,
            "tutup_buku": s.tutup_buku if s else None,
            "arsip_selesai": bool(s and s.arsip_selesai_at),
            "cocok_terakhir_at": s.cocok_terakhir_at if s else None,
            "hari_beda": s.hari_beda if s else 0,
            "segar_terakhir_at": s.segar_terakhir_at if s else None,
            "umur_menit": None,
            "rows_header": s.rows_header if s else 0,
            "rows_detail": s.rows_detail if s else 0,
            "rows_deleted": s.rows_deleted if s else 0,
            "error": (s.error_message if s else "") or "",
            "status": STATUS_LAMBAT,
        }
        if s is None or s.segar_terakhir_at is None:
            # Belum pernah ditarik. Bukan sehat, bukan mati — belum mulai. Sama
            # dengan perlakuan `hub_health` untuk cabang tanpa cursor.
            r["error"] = r["error"] or "belum pernah tarik"
        elif s.status == "failed":
            r["status"] = STATUS_MATI
        else:
            umur = (sekarang - s.segar_terakhir_at).total_seconds() / 60.0
            r["umur_menit"] = umur
            r["status"] = _nilai_status(umur, PULL_OK_MENIT, PULL_LAMBAT_MENIT) or STATUS_OK
        r["status_label"] = LABEL[r["status"]]
        baris.append(r)
    baris.sort(key=lambda x: (-_PERINGKAT[x["status"]], x["profile"]))
    return baris


def fanout_health_all(source, targets) -> list[dict]:
    """Kesehatan fan-out master data `source` -> tiap toko (apps/transactions/feed_sync.py).

    Bentuknya kebalikan `hub_health`: di sana banyak sumber satu tujuan, di sini
    satu sumber banyak tujuan. Karena sumbernya sama untuk semua baris, ujung
    feed dibaca SEKALI — bukan sekali per toko.
    """
    from apps.core.models import FeedSyncCursor, SyncDeadLetter

    try:
        with mssql.cursor(source) as cur:
            feed_min, feed_id = _ujung_feed(cur)
        sumber_error = ""
    except (pyodbc.Error, RuntimeError) as exc:
        feed_min, feed_id = None, 0
        sumber_error = str(exc.args[-1] if exc.args else exc)[:255]

    cursors = {
        c.target_profile_id: c
        for c in FeedSyncCursor.objects.filter(source_profile=source, target_profile__in=targets)
    }
    sejak = timezone.now() - timezone.timedelta(days=1)
    baris = []
    for t in targets:
        row = cursors.get(t.pk)
        r = {
            "profile_id": t.pk,
            "profile": t.name,
            "cursor_id": row.last_id if row else 0,
            "feed_id": feed_id or None,
            "feed_min": feed_min,
            "ketinggalan": None,
            "lubang": 0,
            "last_synced_at": row.last_synced_at if row else None,
            "dead_letter": SyncDeadLetter.objects.filter(
                source_profile=source, target_profile=t, created_at__gte=sejak
            ).count(),
            "status": STATUS_OK,
            "error": sumber_error or (row.error_message if row and row.status == "failed" else ""),
        }
        if sumber_error:
            r["status"] = STATUS_OFFLINE
        elif row is None or not row.last_id:
            # Belum pernah sync. Ketinggalan dibiarkan kosong, bukan feed_id - 0:
            # run pertama menetapkan cursor di UJUNG feed, jadi angka itu tidak
            # akan pernah ditarik dan cuma bikin panik pada hal yang tak terjadi.
            r["status"] = STATUS_LAMBAT
            r["error"] = r["error"] or "belum pernah sync"
        elif row.status == "failed":
            r["status"] = STATUS_MATI
        else:
            # Sama seperti `hub_health`: ketinggalan apa adanya, dan cursor
            # diperiksa terhadap KEDUA ujung feed sebelum ambang lag dipakai.
            r["ketinggalan"] = feed_id - row.last_id
            status_cursor, alasan, lubang = _periksa_cursor(row.last_id, feed_min, feed_id)
            r["lubang"] = lubang
            if alasan:
                r["error"] = r["error"] or alasan
            lag = max(0, feed_id - row.last_id)
            r["status"] = status_cursor or (
                STATUS_OK if lag < HUB_OK_LAG
                else STATUS_LAMBAT if lag < HUB_LAMBAT_LAG
                else STATUS_MATI
            )
        r["status_label"] = LABEL[r["status"]]
        baris.append(r)
    baris.sort(key=lambda x: (-_PERINGKAT[x["status"]], x["profile"]))
    return baris


def _aware(waktu):
    """Naif (jam dinding server) -> aware, untuk disimpan lewat ORM.

    USE_TZ=True, jadi menyimpan datetime naif memicu peringatan dan menyimpan
    nilai yang ditafsirkan sebagai UTC — tujuh jam meleset. Perbandingan umur di
    atas tetap dikerjakan naif-vs-naif; konversi hanya di batas penyimpanan.
    """
    if waktu is None or timezone.is_aware(waktu):
        return waktu
    return timezone.make_aware(waktu, timezone.get_current_timezone())


def simpan_sample(hasil: dict) -> None:
    """Catat satu hasil `sync_health` ke SyncHealthSample (riwayat/tren)."""
    from apps.connections.models import ServerProfile
    from apps.core.models import SyncHealthSample

    SyncHealthSample.objects.create(
        profile=ServerProfile.objects.filter(pk=hasil["profile_id"]).first(),
        profile_name=hasil["profile"],
        antre=hasil["antre"],
        antre_tertua=_aware(hasil["antre_tertua"]),
        antre_terbaru=_aware(hasil["antre_terbaru"]),
        watermark_get=_aware(hasil["watermark_get"]),
        feed_id=hasil["feed_id"],
        feed_waktu=_aware(hasil["feed_waktu"]),
        status=hasil["status"],
        error_message=hasil["error"],
    )

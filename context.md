# Context — Arunika POS (Sukses Crown Toys)

Ringkasan arsitektur + status untuk planning lanjutan. Django + Inertia.js + Vue 3, data dari MS SQL Server legacy (multi-server: grosir/gudang/retail).

## Stack & jalan

- Backend: Django 5 (`config/settings.py`), Inertia-Django 1.2 (`defer`/`optional` tersedia), pyodbc → MS SQL "ODBC Driver 17".
- Frontend: Vue 3.5 + `@inertiajs/vue3` 2.0 (punya komponen `<Deferred>`), Pinia, Tailwind 4, Vite 6. Build: `npm run build` → `frontend/dist/`.
- DB Django (auth/config/log/session): SQLite `db.sqlite3` (WAL aktif).
- 1 koneksi MS SQL aktif global (bukan per-tipe), switcher di navbar. `core/mssql.get_active_profile()`.
- Opsional: tiap `ServerProfile` bisa punya `report_source` (server replica untuk laporan, disinkron via CDC — lihat bagian "Reporting replica" di bawah). `core/mssql.get_report_source(profile)`.

### Mode serving (PENTING — lintas device)
- **Dev/HMR (lokal saja)**: `.env` `DJANGO_VITE_DEV=1`, jalankan `npm run dev` + runserver, akses `localhost:8000`. Vite hardcode `localhost:5173` → TIDAK bisa dari device lain.
- **Prod-asset (lintas device/Tailscale)**: `.env` `DJANGO_VITE_DEV=0` + `npm run build`, Django serve aset dari origin sendiri (`:8000/static/assets/...`). Akses dari device manapun yang bisa jangkau `:8000`. **Setelah tiap edit frontend wajib `npm run build`.**
- Produksi Windows: `waitress-serve --threads=32 --listen=0.0.0.0:8000 config.wsgi:application` (1 proses → cache per-proses konsisten). Lihat `PRODUCTION.md`.

## Peta menu (42) → sumber data

Route prefix `/admin-panel/`. View di `apps/monitoring/views.py` (kecuali connections di `apps/connections/views.py`). Menu def: `apps/core/menus.py`.

**SEMUA 42 menu sudah REAL** (migrasi Fase 3-7 selesai) — `frontend/mock/*.js` sudah dihapus total, tidak ada lagi import `@/mock` di `frontend/pages`. Laporan penjualan/pembelian pakai `apps/transactions/reports.py` (SQL builder per laporan + pagination server-side + export XLSX via `openpyxl`).

## Service backend (reusable)

`apps/transactions/services.py`: `dashboard_summary(profile, day=None)`. Helper `_f`, `_dictify`.

`apps/transactions/reports.py`: SQL builder generik per laporan (`penjualan_detail`, `penjualan_nota`, `penjualan_customer`, `penjualan_user`, `penjualan_periode`, `retur_penjualan`, `pembelian`, `retur_pembelian`, `opname`, `kas`, `shift`, `promo`, `voucher`, `fmi_penjualan`, `fmi_stok`) — tiap fungsi terima dict filter `f`, return `(inner_sql, params)` untuk dibungkus pagination di `apps/core/reporting.py`.

`apps/core/reporting.py`: `parse_report_params(request, sorts, default_sort, max_range_days=MAX_RANGE_DAYS)` (validasi tanggal, default bulan berjalan, tolak rentang > `max_range_days`), `run_paged(cur, inner_sql, params, f)` / `run_all(cur, inner_sql, params, f)` (COUNT + OFFSET/FETCH vs tanpa paging), `xlsx_response(filename, columns, rows)` (openpyxl), `opt(rows, value_key, label_key)` → `[{value,label}]`.

`apps/inventory/services.py` (movement engine, raw tables):
- `_movement_sql` (9-way UNION ALL: t_penjualan/pembelian(+retur), t_mutasi_stok, t_opname_stok, dll).
- `_movement_sums` — agregasi DI SQL (GROUP BY + HAVING buang serba-nol). **JANGAN stream jutaan row ke Python.**
- `_k(kd)` — normalisasi key (strip+upper) untuk collation CI. `_cached(profile,name,build,ttl=,force=)` TTL 600s. `invalidate_master_cache(profile_id, prefix=)`. `warm_master_cache(profile,ttl)` — isi ulang semua key berat dalam satu koneksi, dipanggil scheduler.
- Public: `list_divisi`, `search_barang`, `stock_card`, `stock_levels(profile,kd_divisi,date_from,date_to,search,kd_kategori)`, `stok_akhir_per_tanggal(profile,tanggal,kd_divisi)`, `barang_histori(...)`.

`apps/master_data/services.py`: `list_products`, `list_categories`, `list_customers`, `list_barang_edit`, `update_harga`(write), `update_status`(write), `compare_harga_jual`, `sync_harga_jual`(write). Semua cap TOP 500.

## Reporting replica (CDC, opsional)

Laporan berat (`penjualan_detail` dkk, join ke `t_penjualan_detail` 3M+ baris) tadinya SELECT langsung ke server legacy — bersaing lock dengan transaksi kasir live, dan lambat (~1 menit). Solusi opsional: `ServerProfile.report_source` menunjuk ke server SQL Server kedua yang disinkron dari legacy via **Change Data Capture** (bukan transactional replication biasa — `t_penjualan_detail` adalah heap tanpa primary key karena computed column `total` dibuat dengan ANSI_NULLS/QUOTED_IDENTIFIER salah; CDC `fn_cdc_get_all_changes_*` tidak butuh PK, replication butuh).

- `apps/transactions/cdc_sync.py`: `CDC_TABLE_SPECS` (tabel → capture instance + key), `backfill_table()` (copy penuh awal), `sync_table()`/`sync_all()` (incremental by LSN, resumable via `apps/core/models.CdcSyncCursor`). Tabel header (`t_penjualan`, `m_barang`, dst.) di-upsert per baris by key asli; tabel detail tanpa key andal (`t_penjualan_detail`, dst.) disinkron dengan re-fetch seluruh baris current milik parent (`no_transaksi`/`no_retur`) yang berubah — bukan cocokkan baris satu-satu.
- `manage.py sync_cdc [--profile ID] [--backfill]` — jalankan `--backfill` sekali (atau saat rebuild replica), lalu jadwalkan tanpa `--backfill` tiap 1-2 menit (Task Scheduler di Windows; tidak ada Celery/task queue di stack ini).
- `apps/monitoring/views.py` `_report_view`/`_report_export`: baca via `mssql.get_report_source(profile) or profile` — otomatis pakai replica kalau `report_source` diset, fallback ke legacy kalau belum. Jalur WRITE (`update_harga`, `sync_entity`, dst.) TIDAK pernah pakai `report_source` — selalu ke `profile` langsung.
- **Prasyarat di server legacy (kerjaan DBA, bukan kode)**: `EXEC sys.sp_cdc_enable_db;` lalu `sys.sp_cdc_enable_table` per tabel di `CDC_TABLE_SPECS` (nama capture instance default `dbo_<table>`, sesuaikan dict kalau DBA pakai nama custom). Replica butuh skema tabel yang sama, disiapkan manual di server kedua.
- Staleness: laporan dari replica bisa lag ~1-2 menit dari transaksi terbaru (tergantung jadwal `sync_cdc`) — trade-off sadar demi tidak membebani legacy server, bukan bug.

## Sinkronisasi antar-server: yang legacy, dan yang kita miliki sendiri

**Jalur legacy (tidak diganti, tidak disentuh).** SQL Agent job di `msdb` tiap server (dump di `scripts/job/`). Trigger legacy menulis ke `tbl_tmp_post`, cursor T-SQL menyusun string, ~20 `REPLACE()` berantai (spasi→`4D4`, `.`→`qttt`) meng-escape-nya, `xp_cmdshell` memanggil `curl` ke endpoint PHP di `solidtechs.com` (sink-nya MySQL — query-nya `INSERT IGNORE`), dan arah baliknya **mengeksekusi tiap baris unduhan sebagai SQL mentah** (`exec (@query)`). Dua batasan keras: web legacy itu **tidak bisa diakses/diubah** (bukan milik kita) dan **trigger-nya tidak boleh disentuh** (masih dipakai aplikasi POS lama). Jadi jalur toko→pusat dan pusat→toko tetap milik job legacy; yang bisa kita lakukan hanyalah memantaunya.

> **`tbl_tmp_post` bukan acuan kesehatan.** Job legacy menghapusnya begitu terkirim (`UPDATE ... SET status='sent'` lalu `DELETE ... WHERE status='sent'`, [job_post_grosirPusat.sql:132](scripts/job/job_post_grosirPusat.sql)). Jadi tabel itu residu sesaat tanpa riwayat, dan "antrean kosong" punya tiga tafsir yang tidak bisa dibedakan dari tabel itu sendiri: benar-benar terkirim, toko sedang tutup, atau trigger berhenti menulis. Dua penopang dipakai: kolom `bukti` (memakai keaktifan `tbl_log_transaksi`, yang tidak dihapus job legacy, untuk memisahkan "terkirim" dari "tidak tahu" — "sepi" ditampilkan netral, bukan hijau) dan `_stuck()` (baris tertua yang sama persis di dua `SyncHealthSample` berturut-turut sementara `feed_id` bertambah = ada yang menumpuk dan tak ada yang mengangkut; satu-satunya deteksi yang tak bisa dikelabui penghapusan, dan menangkap pengirim yang baru mati jauh sebelum ambang umur 2 jam). Yang TETAP sahih dibaca dari tabel ini adalah timbunan yang tak pernah terkirim — RTL PUSAT ber-`status='waiting'` sejak 2022 terlihat justru karena tak satu pun pernah dihapus.

**Kesehatan Sync (`apps/monitoring/services_sync.py`, menu superadmin-only `sync_health`).** Job legacy tidak melapor ke mana pun, jadi kalau ia berhenti bekerja tidak ada yang berubah di layar siapa pun — saat halaman ini dibuat, antrean RTL PUSAT ternyata menumpuk **1.043.804 baris sejak 2022-05-13** (semua `status='waiting'`, tak satu pun pernah terkirim) dan watermark tariknya beku di 2024-10-22; RTL RUMAK 8.175 baris; watermark GUDANG beku sejak 2025-02-28. Empat tahun tanpa ada yang tahu. Halaman ini membaca tiga jejak per server — kedalaman `tbl_tmp_post` + umur baris tertua, umur `tbl_waktu_get`, ujung `tbl_log_transaksi` — dan menyatakannya sebagai satu status (terburuk dari dua sumbu: antrean & watermark). **Kuerinya wajib seek**: jumlah antrean dari `sys.dm_db_partition_stats`, tertua/terbaru lewat `TOP 1 ... ORDER BY id [DESC]` (id IDENTITY + clustered PK). Bentuk polos `COUNT(*)`/`MIN(waktu)` memindai sejuta baris × 13 server tiap poll; versi seek selesai ~8 detik. `SyncHealthSample` mencatat riwayatnya tiap tick scheduler (`SYNC_HEALTH_ENABLED`).

**Fan-out master data gudang → toko (`apps/transactions/feed_sync.py`, `manage.py sync_feed`).** Jalur milik sendiri, berjalan berdampingan dengan job legacy. Mengirim **data**, bukan SQL: nilai lewat parameter pyodbc, nama tabel/kolom dicocokkan dengan `FEED_TABLE_SPECS` + katalog server tujuan. Tidak butuh web legacy sama sekali — aplikasi ini sudah memegang koneksi langsung ke semua server.

- **Sumbernya `tbl_log_transaksi`, bukan `tbl_tmp_post`.** Keduanya diisi trigger yang sama, tapi `tbl_tmp_post` dihapus job legacy begitu terkirim, jadi poller menit-an kehilangan mayoritas barisnya. `tbl_log_transaksi` tidak dihapus job mana pun, `id`-nya IDENTITY + clustered PK → cursor `WHERE id > ?` adalah seek (`FeedSyncCursor` per pasangan sumber–tujuan).
- **Feed itu BUKAN append-only mutlak — pemeliharaan DB bisa memangkasnya, dan sudah pernah.** Terukur: **1.469.155 id lenyap dalam satu blok utuh semalam 15–16 Mei 2024** di lini PUSAT, saat database dipisah untuk meringankannya. Sisa lubang di seluruh feed hanya 19, tiga di antaranya berukuran 999/990/967 — lompatan identity-cache biasa saat layanan SQL Server restart, bukan penghapusan. Dua akibatnya tidak memunculkan error apa pun dan dulu tampil **`ok` dengan ketinggalan 0**: (a) cursor mendahului ujung feed → `WHERE id > cursor` tak pernah mengembalikan baris lagi, cabang itu berhenti mengirim **selamanya**; (b) cursor tertinggal di belakang baris tertua yang masih ada → sync jalan terus tapi baris di antaranya lenyap permanen. `services_sync._periksa_cursor()` memeriksa kedua ujung dan menandai keduanya **mati** dengan pesan yang berbeda; `_stuck()` juga menangkap feed yang mundur antar-sampel, karena kalau tidak, pemangkasan justru mematikan deteksi itu tanpa suara. Ketinggalan dilaporkan apa adanya (bisa negatif) — `max(0, …)` yang dulu dipakai justru menyamarkan kasus terparah jadi baris paling sehat.
- **Format `formatted_data`**: `val__<kolom>__<nilai>` dipisah `;`, dan baris `__update` menandai kunci dengan prefiks **`key__`**. Nilai bisa mengandung `;` dan `__` (nama barang) → pisah record dengan batas `;(?=(?:key|val)__)`, potong tiap record di `__` pertama sesudah prefiks. Nilai kosong dan NULL tidak terbedakan; tidak bisa diperbaiki tanpa mengubah trigger.
- **Kunci menurut spec, bukan menurut payload.** Kalau `key__` di payload yang menentukan, satu baris `m_barang_satuan` yang hanya membawa `kd_barang` menghasilkan `WHERE kd_barang = ?` dan **satu perubahan harga menimpa seluruh satuan barang itu**. Kunci yang menyempit harus jadi kegagalan terlihat, bukan WHERE yang melebar.
- **`divisi_id` bukan kolom** — trigger menambahkannya ke hampir semua payload sebagai penanda asal, padahal `m_barang_satuan`/`m_merk` tak punya kolom itu. Kolom payload selalu diiris dengan `sys.columns` server tujuan; tanpa itu setiap INSERT gagal.
- **`m_barang_divisi` sengaja di luar daftar-izin** — membawa `stok_awal`/`stok_min`/`harga_beli_awal` yang milik tiap toko. Kalau dibutuhkan, daftarkan dengan `columns` eksplisit, jangan `None`. Tabel `t_*` tidak pernah difan-out.
- **`m_supplier` sengaja di luar daftar-izin, dan ini aturan tetap** — yang membeli adalah GUDANG, jadi gudang yang menyimpan daftar supplier lengkap; server toko grosir/ecer hanya memakai segelintir supplier miliknya sendiri (PAGESANGAN: **3 baris**). Pernah difan-out sekali dan akibatnya harus dipulihkan manual dengan menyalin ulang isi PAGESANGAN ke tiap toko. Ke AMPHOREUS supplier TETAP ikut (`hub_sync.SEED_TABLES`) — pusat itu milik kita sendiri dan laporan pembelian gudang butuh namanya. Arahnya yang penting: gudang → pusat boleh, gudang → toko tidak pernah.
- **Disaring ≠ dead-letter.** Tabel di luar daftar-izin cuma dihitung (`disaring`), tidak disimpan: pada uji nyata 2.566 dari 3.000 baris, dan mencatat semuanya akan menimbun ribuan baris tiap tick sampai `SyncDeadLetter` berhenti berarti. Dead-letter idealnya KOSONG.
- **Run pertama tidak memutar ulang riwayat**: cursor baru ditetapkan di `MAX(id)` saat itu, bukan 0. `--from-id` untuk sengaja mengulang.
- **Efek samping terukur**: menerapkan 434 baris ke sebuah server menaikkan antrean `tbl_tmp_post` server itu dari 4 → ~1.244, karena trigger legacy di server TUJUAN ikut menyala. Antrean keluar tiap toko akan naik sebanding; itu terlihat di Kesehatan Sync dan bukan kerusakan, tapi jadi alasan fan-out dimulai dari satu toko dulu.
- `FEED_SYNC_ENABLED` default **0**. Deploy tidak boleh langsung memindahkan data.

### Fan-out master data gudang → 8 grosir (`apps/transactions/feed_sync.py`)

Aktif untuk ANDARIA, DRAGON, KOTA MAS, PAGESANGAN, PRAYA, PUSAT, RUMAK, TANJUNG (`FEED_SYNC_TARGETS`). Retail di luar lingkup — jangan mengosongkan `FEED_SYNC_TARGETS`, karena kosong berarti "semua profil kecuali sumber" dan itu ikut menyeret server retail.

Dua bug yang ditemukan saat menguji ke `testgudang`, keduanya **tidak memunculkan error apa pun**, dan keduanya ditemukan hanya karena verifikasinya membandingkan kolom per kolom, bukan sekadar "jalan tanpa exception":

- **`cur.rowcount` tidak boleh menentukan apakah sebuah baris sudah ada.** Kode lama melakukan UPDATE lalu `if cur.rowcount: return`. Tabel di server toko punya trigger legacy, trigger AFTER UPDATE di SQL Server tetap menyala walau UPDATE mengenai NOL baris, dan `INSERT INTO tbl_tmp_post` di dalam trigger membuat `rowcount` terbaca 1 — jadi INSERT-nya dilewatkan diam-diam. Terukur: 131 dari 406 baris tidak pernah sampai, tanpa error, tanpa dead-letter, dan semuanya terhitung "diterapkan". AMPHOREUS tidak bertrigger sehingga jalur pusat tidak pernah bergejala. Sekarang keberadaan baris ditentukan lewat SELECT eksplisit, dan bentuk kodenya disamakan di `feed_sync` dan `hub_sync`.
- **Feed itu PEMBERITAHUAN, bukan sumber data.** Trigger legacy memotong sebagian kolom saat menyusun `formatted_data`: `m_barang.keterangan` di feed tidak pernah lebih dari 30 karakter padahal kolomnya `varchar(50)` dan tabelnya menyimpan 45 (total payload cuma 335 karakter, jadi ini pemotongan per kolom, bukan batas panjang). Menulis dari payload akan MEMENDEKKAN keterangan yang sudah benar di toko. Sekarang payload hanya dipakai untuk tahu kunci mana yang berubah; nilainya dibaca ulang dari tabel asli di sumber. Efek sampingnya bagus: tiga edit pada barang yang sama dalam satu batch jadi satu tulisan.

Hasil akhir uji: **406 baris di testgudang dan 409 baris di RUMAK, nol beda, nol hilang**, idempoten (jumlah baris identik sesudah run kedua, nol kunci ganda). Harga tidak bergerak sama sekali — 174 `m_barang_satuan` yang tersentuh semuanya sudah identik dengan gudang, sesuai catatan bahwa harga antar-server memang sama.

Efek samping trigger **tergantung cabang**: `testgudang` antreannya naik 4 → 1.244, `RUMAK` tetap 0 karena `m_barang` di sana tidak punya trigger sama sekali.

## AMPHOREUS — pusat data milik sendiri (`apps/transactions/hub_sync.py`)

Satu database pusat di `SERVER-RETAIL`/`AMPHOREUS` berisi data **gudang + 8 grosir** (retail di luar lingkup). Diisi langsung lewat pyodbc dari feed `tbl_log_transaksi` tiap cabang — tanpa web legacy, tanpa `xp_cmdshell`, tanpa escape buatan tangan, tanpa pernah menjalankan SQL kiriman. Job SQL Agent lama tetap jalan berdampingan. Perintah: `init_hub` (skema, idempoten) dan `sync_hub` (tarik perubahan).

- **Skema dibangkitkan, bukan ditulis tangan** (`hub_schema.py`, acuan GUDANG lewat `sys.columns`) — 24 `CREATE TABLE` yang disalin manual akan menyimpang dalam hitungan bulan. Tiga cacat skema legacy sengaja tidak diwarisi: computed column `total` (definisinya rusak, lihat `indexes.py`) tidak dibawa, kolom IDENTITY diratakan (nomornya milik cabang), dan tabel header/master dapat **primary key betulan**. `init_hub` tidak pernah ALTER/DROP: kolom baru di cabang dilaporkan sebagai `kolom_baru` lalu berhenti — menyesuaikan tabel berisi data adalah keputusan manusia.
- **`kd_sumber` wajib, dari `ServerProfile.kode_sumber`.** Tidak ada satu pun kolom di data legacy yang menandai server asal: `divisi_id` di feed bernilai DAA000/DAA004 di SEMUA cabang, `m_divisi.kd_divisi` juga DAA000 di semua cabang. Dan `no_transaksi` bisa sama antar-server (RUMAK & RTL RUMAK sama-sama punya `TR2608010005`). Tanpa `kd_sumber` di PK, nota dua cabang saling menimpa dan omzet salah tanpa satu pun error. Cabang tanpa kode dilewati, bukan ditebak dari nama profil.
- **Tabel detail tidak dapat PK** — satu nota sah punya dua baris untuk `kd_barang` yang sama (dua harga/diskon). Gantinya clustered index `(kd_sumber, parent)`, karena satu-satunya tulisan yang pernah terjadi adalah "hapus semua baris nota X, salin ulang dari cabang".
- **Detail digantungkan pada feed HEADER, bukan feed detail.** Terukur: PRAYA menghasilkan 285 `t_penjualan__insert` dan **nol** `t_penjualan_detail__insert` dalam 2.000 baris feed, sementara GUDANG menghasilkan 93.333 baris feed detail. Cakupan trigger berbeda tiap cabang dan trigger tak boleh disentuh. Karena itu tiap header yang tersentuh selalu menyeret detailnya diambil ulang (`spec["details"]`). Tanpa ini pusat berisi nota tanpa baris — laporan tetap jalan, jumlah nota tetap benar, omzetnya saja nol. Terbukti memperbaiki: 29 → 313 nota per batch, dan 285/285 nota cocok persis dengan cabang.
- **Aksi KOSONG bukan aksi tak dikenal.** Untuk tabel detail aksinya memang tak dipakai sama sekali (selalu ambil-ulang seluruh nota), dan feed nyata penuh baris detail tanpa sufiks aksi (133 dari 2.000 di PRAYA). Untuk tabel **berkunci** aksi kosong juga aman: `_terapkan_header` tidak pernah peduli insert atau update — ia SELECT dulu, lalu UPDATE atau INSERT. Kelonggaran ini dulu hanya diberikan ke tabel detail, dan akibatnya **42 baris `t_pembelian` ANDARIA tanpa sufiks aksi masuk dead-letter** padahal tak ada yang salah dengannya. Yang tetap ditolak: aksi non-kosong yang tak dikenal.
- **Riwayat mulai kosong**: cursor baru ditetapkan di `MAX(id)` feed saat itu, bukan 0. `--from-id` untuk sengaja mengambil ke belakang. `init_hub --seed-master` menyalin katalog sekali (~500rb baris) — tanpa itu tiap transaksi menunjuk `kd_barang` yang tak ada padanannya di pusat.
- **Celah yang diketahui — tiga, semuanya butuh rekonsiliasi berkala (pekerjaan terpisah):** (1) feed hanya memuat `__insert`/`__update`, jadi nota yang DIHAPUS di cabang tertinggal sebagai hantu di pusat (detailnya aman — ambil-ulang mengembalikan nol baris); (2) feed yang dipangkas melewati cursor tak bisa dipulihkan dari feed — Kesehatan Sync sekarang memberitahu, tapi memberitahu bukan menambal; (3) **header ditulis dari payload, bukan dibaca ulang dari cabang.** `_terapkan_header` memakai nilai `formatted_data` apa adanya sementara `feed_sync._baca_dari_sumber` sudah membaca ulang dari tabel asli justru karena trigger MEMOTONG kolom. Terukur di pusat: baris `m_barang` ber-`kd_sumber=PRAYA` mentok **30 karakter untuk `nama` DAN `keterangan`** padahal kedua kolomnya `varchar(50)` dan baris GUDANG mencapai 47 — nama barang tersimpan terpotong. Header transaksi tidak bergejala (PUSAT: `t_penjualan` 20 kolom × 25 nota, `t_pembelian` 18 kolom × 9 nota, nol beda), jadi cakupannya tabel master.
- ~~Kesehatan Sync menampilkan bagian kedua untuk pusat: ketinggalan (`MAX(id)` feed − cursor), posisi cursor, dead-letter 24 jam.~~ **Diganti** — lihat bagian berikutnya. `HUB_SYNC_ENABLED` default **0** dan penjadwalannya sudah dilepas.

## Harga GUDANG → toko mendekati realtime (`apps/transactions/harga_sync.py`)

`feed_sync` sudah menyebarkan `m_barang_satuan`, tapi dua hal membuatnya tak cukup untuk harga grosir: jadwalnya **30 menit** (menumpang `HARGA_SNAPSHOT_INTERVAL_SECONDS`) dan ia **hanya melihat apa yang ditulis trigger** — perubahan lewat SQL langsung tak pernah menyeberang. Modul ini tidak membaca feed sama sekali; ia membandingkan harga apa adanya.

Terukur, dan inilah yang membuatnya layak: `SELECT kd_barang, kd_satuan, harga_jual FROM m_barang_satuan` = **55.365 baris / 1,90 dtk** di GUDANG (ANDARIA lewat Tailscale 1,78 dtk). Sapuan penuh 9 server = **36,5 dtk**. Perubahan nyata cuma **1–125 harga/hari** (dari `BarangHargaChange`), dan sapuan penuh pertama menemukan **hanya 17 SKU** yang benar-benar beda di seluruh 8 toko.

Dua lapis, dan keduanya perlu:

- **Thread sendiri, 60 detik** (`_loop_harga`, BUKAN tick 30 menit — menurunkan tick bersama akan membuat pemanas cache master dan sapuan kesehatan ikut jalan tiap menit di sebelas server).
- **Dorongan seketika** dari jalur tulis Arunika (`_sebar_harga` di `apps/monitoring/views.py`, dipanggil sesudah `master.update_harga` pada jalur satu-barang dan Terapkan Massal). Menutup jendela 60 detik untuk perubahan yang lewat aplikasi ini.

Aturan yang masing-masing dibayar pengukuran atau bug:

- **Mode cepat vs penuh.** Cepat = bandingkan GUDANG dengan salinan sapuan sebelumnya di memori proses (1 pembacaan). Penuh = bandingkan dengan keadaan NYATA tiap toko. **Sapuan pertama sesudah restart selalu penuh**: salinan kosong akan terbaca "55.365 harga baru saja berubah" dan membanjiri delapan toko. Mode cepat juga menganggap "sudah didorong" = "sudah sampai", jadi toko yang mati saat perubahan lewat akan melewatkan harga itu selamanya — `HARGA_SYNC_FULL_MINUTES` yang menambalnya, jangan dibuat terlalu jarang.
- **Jangan pakai `master._harga_map()`** — di-cache ~10 menit; poller 60 detik yang membaca cache 10 menit adalah poller 10 menit yang berpura-pura cepat.
- **`bind_varchar` wajib** sebelum daftar `IN` SKU (alasan yang sama dengan `hub_pull`).
- **`_norm()` (strip + upper) wajib** saat membandingkan kunci. Tanpa itu `'lyg005 '` vs `'LYG005'` terbaca berubah tiap sapuan dan didorong ulang ke delapan toko tiap 60 detik selamanya.
- **`_sebar_harga` tidak pernah menggagalkan permintaan.** Harga SUDAH tersimpan di sumber saat ia dipanggil; menggagalkan respons karena satu toko mati membuat pengguna mengira simpanannya batal lalu mengulanginya.
- **Terapkan Massal mengumpulkan dulu, menyebar sekali di akhir** — per barang di dalam loop berarti 8 koneksi × jumlah barang.
- **Master non-harga (nama barang, merek) juga disamakan langsung** — `hub_master.sync_master_toko()`, sekali sehari, ikut slot harian pencocokan (`MASTER_TOKO_ENABLED`). `feed_sync` sudah menyebarkannya lewat `tbl_log_transaksi`, tapi itu jalur memo yang sama yang ditinggalkan untuk arah cabang → AMPHOREUS, dan tak ada yang membandingkan — nama barang yang gagal menyeberang tidak akan pernah ketahuan. **TIDAK PERNAH MENGHAPUS di toko**: barang lokal toko yang tak ada di gudang dibiarkan (dilaporkan sebagai `hapus_dilewati`), karena itu data milik toko dan nota-nota lamanya masih menunjuk ke sana. `m_barang_satuan` sengaja di luar daftar — itu milik `harga_sync`, dan menyapunya dua kali cuma menambah tulisan yang menyalakan trigger legacy. `m_supplier` juga di luar, alasannya beda: supplier urusan gudang (lihat daftar-izin di atas). Daftarnya diturunkan dari `FEED_TABLE_SPECS` supaya satu tempat saja yang menentukan apa yang boleh menyeberang ke toko.
- **Ini satu-satunya jalur baru yang menulis ke SERVER TOKO**, dan tiap tulisan menyalakan trigger legacy di sana → `tbl_tmp_post` toko → job legacy → sink PHP/MySQL. Karena itu yang didorong hanya SKU yang berubah, tidak pernah seluruh tabel. `HARGA_SYNC_ENABLED` default **0**.

## AMPHOREUS diisi tarik-langsung, bukan feed (`apps/transactions/hub_pull.py`)

`hub_sync` (feed `tbl_log_transaksi`) **tidak lagi dijadwalkan**. Filenya masih ada — `HUB_TABLE_SPECS` dipakai bersama dan angkanya masih perlu jadi pembanding — tapi pengisi pusat sekarang `hub_pull`, yang membaca tabel transaksi ASLI tiap cabang. `tbl_log`, `tbl_log_transaksi`, dan `tbl_tmp_post` tetap dipantau Kesehatan Sync dan itu urusan terpisah.

Tiga cacat feed yang memaksa penggantian, semuanya terukur: cursor ANDARIA tertinggal **1,7 juta baris** (18–100 hari untuk mengejar); feed BISA dipangkas dan yang lenyap di depan cursor tak bisa dipulihkan (PUSAT −1.471.184 id, PRAYA dipotong dari depan sampai id 2.658.002); dan nilai dari feed TERPOTONG trigger (`m_barang` PRAYA mentok 30 karakter padahal kolomnya `varchar(50)`).

**Tidak ada penanda perubahan di legacy** — nol kolom `rowversion` di seluruh database. `hub_pull` tidak membutuhkannya: ia tidak mendeteksi perubahan, ia menyalin ulang rentang tanggal apa adanya. Yang membuatnya murah adalah sekat `g_tutup_buku`:

| tingkat | rentang | jadwal | perintah / env |
|---|---|---|---|
| arsip | `tanggal <= tutup_buku` | sekali, manual | `pull_hub --mode arsip` |
| cocok | tutup buku .. H-N | sekali sehari | `HUB_MATCH_ENABLED` |
| segar | N hari terakhir | tiap tick | `HUB_PULL_ENABLED` |

Terukur di lapangan: sapuan segar 7 hari untuk **9 cabang = 169 detik**; pencocokan harian seluruh armada = **16 detik** (satu `GROUP BY` per tabel per cabang mengembalikan satu baris per hari — 0,13–0,15 dtk untuk 900–2.000 hari, bahkan lewat Tailscale). Tutup buku sangat berbeda antar cabang: GUDANG 2017 (nol baris arsip) sampai PUSAT 2025-12-31 (445.167 nota).

Aturan yang masing-masing dibayar pengukuran:

- **`g_tutup_buku` dibaca `MAX(tanggal)`, bukan `TOP 1 ORDER BY periode DESC`.** Bentuknya `(periode, tanggal)` dengan mayoritas baris sentinel `2001-01-01`, dan periode terbesar belum tentu yang berisi tanggal asli (TANJUNG: periode 7325 = 2001-01-01, periode 7324 = 2024-02-16). Dibaca ulang tiap run, tidak pernah di-cache.
- **Rentang memakai `tanggal` OR `tanggal_server`.** 13 dari 927 baris GUDANG dan 13 dari 8.742 baris PUSAT punya `tanggal_server` beda HARI dari `tanggal` — nota bertanggal mundur yang diinput belakangan. Menyaring `tanggal` saja melewatkannya tanpa suara.
- **Batas jendela dari `GETDATE()` server, tidak pernah dari `MAX(tanggal)`.** ANDARIA punya nota bertanggal **7252-01-09**. Baris semacam itu dipagari `TANGGAL_MAKS` dan **dilaporkan** sebagai `anomali_tanggal` (ANDARIA 1, PAGESANGAN 3), tidak ditelan diam-diam.
- **Nota yang lenyap di cabang ikut dihapus di pusat** — yang tidak pernah bisa dilakukan feed (`__insert`/`__update` saja). Sapuan pertama menemukan **7 nota hantu di PRAYA dan 1 di PUSAT**.
- **`bind_varchar()` wajib sebelum daftar `IN` panjang** (`hub_sync.bind_varchar`, dipakai `_ambil_ulang_detail` dan jalur hapus). pyodbc mengikat `str` sebagai NVARCHAR, kolom kunci legacy `varchar`; konversi implisit membatalkan index seek dan SQL Server memindai tabel sekali untuk TIAP nilai. Terukur ANDARIA (`t_penjualan_detail`, 1,46 juta baris, indeks ADA): IN(50) **6,23 dtk → 0,01 dtk**, IN(500) **timeout 60 dtk → 0,18 dtk**. Ongkos yang linear terhadap jumlah parameter adalah tandanya. Wajib direset `setinputsizes(None)` sesudahnya.
- **Master ikut GUDANG saja** (`hub_master.py`). Kolom `kd_sumber` tetap ada di PK master, yang berubah hanya siapa yang mengisinya. Master tidak punya penanda perubahan apa pun, jadi dibandingkan penuh. `pull_master --purge-lain` membersihkan baris cabang lain, default dry-run dan menuntut `--hapus-beneran` terpisah.
- **Arsip dipotong per BULAN dan punya titik lanjut** (`HubPullState.arsip_sampai`, ditulis sesudah tiap potongan di-commit). Keduanya dibayar oleh run pertama: satu tahun PUSAT = ~90rb header + ~600rb detail dalam satu transaksi lewat WAN, dan jaringan putus di potongan **32 dari 48** sehingga **285.809 header** harus disalin ulang dari nol. Hasilnya tetap benar tanpa titik lanjut (semuanya idempoten) — yang hilang jam kerjanya, dan itu yang mahal. Titik lanjut dibaca lewat `timezone.localtime()` dulu: nilainya tersimpan UTC sementara batas potongan naif jam lokal, dan selisih 8 jam bisa membuat potongan yang belum selesai terbaca sudah lalu dilewati diam-diam.
- **`pull_all` menjalankan semua cabang SEBELUM satu pun ringkasan tercetak** (ia list comprehension). Karena itu tiap baris kemajuan wajib menyebut nama cabangnya — tanpa itu, baris `[32/48] GAGAL` tak bisa ditelusuri ke cabang mana pun, dan pembacanya (termasuk penulis kodenya sendiri) akan salah menuduh cabang yang tercetak di bawahnya.
- **Round-trip, bukan volume, yang menentukan kecepatan.** Semua server lewat Tailscale yang me-relay ke Singapura. Bentuk awal mengirim ~5.000 perjalanan bolak-balik per 500 nota (cek-lalu-UPDATE per baris = 1.000, DELETE satu per nota = 500, `executemany` tanpa `fast_executemany` = ~3.500); sekarang ~10. Terukur **29 → 671 header/detik**; bagian PUSAT yang semula >1 jam lalu putus jadi **4 menit 29 detik**. `fast_executemany` dipasang di `core/mssql.py` sehingga seluruh aplikasi ikut. Pola yang harus dicurigai kalau ada yang lambat lagi: loop Python yang memanggil `cur.execute` per baris.
- **Satu blip koneksi tidak lagi menjatuhkan satu cabang** (`COBA_ULANG`). PRAYA gagal `[08001] wait operation timed out` lalu konek 0,7 detik kemudian tanpa ada yang berubah. Aman diulang karena tiap mode idempoten dan hanya mengerjakan sisanya.
- **Hasil sapuan pertama (2026-08-06)**: arsip ~947.000 header + pencocokan 708.896 header untuk 9 cabang, **30.205 nota hantu dibersihkan**, master 196.221 baris dari GUDANG dalam 23,6 detik, dan 1.858 baris master cabang lain dibuang. `hari_beda` turun dari 218–2.113 menjadi **0** (PRAYA 1: perubahan nyata). Itu pembuktiannya — cocok hari-per-hari, bukan "jalan tanpa error".
- **Yang belum tertutup**: agregat pencocokan hanya melihat header (tidak ada kolom nilai di header — uangnya di detail), jadi nota lama yang qty/harga detailnya diubah tanpa header tersentuh tidak terdeteksi tingkat 2. Jendela segar tidak terpengaruh.

## Perubahan harga harian (snapshot diff-only)

Harga bisa diubah langsung di POS/server tanpa lewat aplikasi ini (`BarangUpdateLog` cuma menangkap perubahan lewat aplikasi). Untuk memantau semua perubahan harga per hari: `manage.py snapshot_harga [--profile ID] [--prune-days N]` membaca `m_barang_satuan` server (reuse `master._harga_map`) dan membandingkannya dengan baseline tersimpan di SQLite.

- Diff-only, bukan snapshot penuh: `apps/core/models.BarangHargaState` menyimpan harga terkini per SKU (di-update di tempat, ukuran tetap ~jumlah SKU × server), `BarangHargaChange` hanya diisi saat harga beda (append-only, tumbuh ∝ jumlah perubahan). Menghindari ledakan baris kalau full-snapshot 54rb produk × hari.
- Idempotent: run kedua di hari sama tanpa perubahan → 0 baris. SKU baru → seed state tanpa log.
- Default target = koneksi aktif (`mssql.get_active_profile()`); `--profile` untuk server lain. `--prune-days` untuk retensi log.
- **Penjadwalan: in-process, tak perlu Task Scheduler.** `apps/core/scheduler.py` `start_scheduler()` dipanggil dari `config/wsgi.py` (hanya ke-load saat serving via runserver/waitress, bukan saat `migrate`/`shell`). Daemon thread cek tiap `HARGA_SNAPSHOT_INTERVAL_SECONDS` (default 30 mnt) dan jalan **sekali per hari kalender** untuk koneksi aktif, dijaga penanda `HargaSnapshotRun` per (profile, tanggal). Server mati seharian → hari itu dilewati (sesuai maksud "saat server berjalan saja"). Env: `HARGA_SNAPSHOT_ENABLED` (default 1), `HARGA_SNAPSHOT_HOUR` (default 0 = kesempatan pertama tiap hari). `manage.py snapshot_harga` tetap ada untuk manual/one-off atau kalau mau pakai Task Scheduler.
- Tampil di halaman **Pergerakan Harga** (`pergerakan_harga_index` → `PergerakanHarga.vue`), default perubahan HARI INI dengan toggle "Semua Riwayat", filter tanggal/kode/koneksi + info "snapshot terakhir". Halaman yang sama punya tab **Saran Harga**: seluruh katalog server terpilih yang harga jual satuan dasarnya beda dari nominal di `keterangan` (`master.list_saran_harga`, padanan server-side dari parser di UpdateBarang.vue), bisa diterapkan per baris/massal (endpoint `harga-bulk`) dan dibuka di modal edit yang sama dengan Update Barang (`BarangEditModal.vue` + endpoint `update-barang/detail`). Edit/terapkan hanya aktif bila baris berasal dari koneksi aktif — endpoint tulis selalu menulis ke koneksi aktif server-side.

## Tabel legacy tersedia (sudah dicek di server aktif)

`m_barang`, `m_barang_satuan`, `m_barang_promo`(+`_detail`), `m_barang_divisi_diskon`, `m_voucher`, `m_kas`, `m_customer`, `m_supplier`, `m_divisi`, `m_kategori`, `m_pegawai`.
`t_penjualan`(+`_detail`,`_retur`,`_retur_detail`), `t_pembelian`(+`_detail`,`_retur`,`_retur_detail`), `t_opname_stok`, `t_mutasi_stok`, `t_mutasi_kas`, `t_penambahan_kas`, `t_pegawai_ganti_shift`(+`_detail`), `t_absensi`, `g_tutup_buku`.
Kolom asli WAJIB dicek via INFORMATION_SCHEMA sebelum tulis SQL (nama kolom legacy tak standar).

## Gotcha / aturan wajib

- **Collation CI**: SQL Server anggap `'LYG005'`=`'lyg005'` & abaikan trailing space; dict Python tidak. Semua join key `kd_*` di Python WAJIB `_k()`.
- **Tanpa view/UDF/SP legacy** (PRD §5.3) — query langsung tabel, parameterized.
- **Agregasi di SQL**, bukan Python (movement bisa jutaan row).
- **Indexing**: auto-ensured per koneksi aktif/registrasi (`apps/transactions/indexes.py`, hook di `get_active_profile` + `connections_save`), bisa dimatikan via env `POS_AUTO_INDEX=0`. Hasil dicatat `ActivityLog`. Tombol "Cek Indexing" manual di halaman Kelola Server (`Admin/Connections/Index.vue`) untuk re-check on-demand + lihat status per index — pelengkap, bukan pengganti auto-trigger. `ensure_indexes()` return `(failed, results)`.
- **.env Windows**: jangan `Set-Content -Encoding utf8` (bikin BOM rusak key pertama & mojibake). Pakai append UTF-8 tanpa BOM.
- **Inertia POST = JSON**: `request.POST` kosong; baca via `apps/core/http.get_data()`.
- **Tutup buku** server aktif lama (mis. Lotim 2024-01-12) → movement besar; sarankan klien tutup buku untuk percepat.
- **Cache TTL bersama** (`core/cache.py`, `_cached`/`invalidate_master_cache`, 600s) dipakai `apps/inventory/services.py` DAN `apps/master_data/services.py` — satu dict, satu invalidasi. JANGAN cache kolom yang berubah tiap transaksi kasir (mis. `m_barang_stok_akhir`) atau query bertingkat search-term (key bisa membengkak).
- **Cache dingin = biaya sebenarnya di profil WAN.** Terukur ANDARIA: kunjungan pertama ~30 detik, berikutnya <5 detik. Karena itu `apps/core/scheduler.py` memanaskan cache master tiap tick (`warm_master_cache`, `MASTER_WARM_ENABLED`) dengan TTL 3× jeda tick — entri diganti sebelum kedaluwarsa, jadi tak ada celah waktu di mana seorang pengguna menemukan cache kosong. Konsekuensinya: **key cache jangan pernah memuat parameter yang dipilih pengguna** (dulu `universe:<kd_divisi>` → tiap divisi baru = 30 detik lagi). Cache katalog penuh sekali, saring di Python (`_universe_for`).
- **Filter tanggal report/listing**: dorong ke SQL (`WHERE tanggal >= ?`) kalau fungsinya tak perlu histori sebelum `date_from` untuk saldo berjalan (lihat `barang_histori` vs `stock_card` di `apps/inventory/services.py`) — jangan tarik semua baris ke Python lalu buang.
- **Filter/fetch halaman Inventory** (`Stock.vue`, `BarangHistori.vue`): pakai `frontend/composables/useReportFilters.js` + `frontend/components/report/DateRangeFilter.vue`, jangan hand-roll `reactive`+`router.get` lagi. Halaman laporan (`ReportView`) punya pola pagination server-side sendiri di `apps/core/reporting.py` — jangan campur dua pola ini.
- **No `v-html`/dynamic `<component :is>`** dari string backend untuk konten sel laporan — pakai slot `cell-<key>` yang sudah ada di `DataTable.vue`.

## Scalability (Fase 0 SUDAH dikerjakan)

Target 200–500 request. Sudah: `waitress`+`whitenoise` (requirements), env-driven DEBUG/SECRET_KEY/ALLOWED_HOSTS, `GZipMiddleware` (payload 5MB→~500KB), `SESSION_SAVE_EVERY_REQUEST=False` (killer #1 SQLite), SQLite WAL (`connection_created` signal), `conn.timeout=60` di `core/mssql.py`. `pyodbc.pooling=True` sudah ada.
Sisa (di luar scope sekarang): Redis/multi-proses, pagination server-side ReportView, HTTPS/reverse proxy.

## Pola deferred (shell dulu, data menyusul) — SUDAH TERBUKTI

View: bungkus kerja berat dalam fungsi, `props={"key": defer(fn)}`. Frontend: `<Deferred data="key">` + `#fallback` `<LoadingCard>`. Contoh live: `stock_index`+`Stock.vue`, `dashboard`+`Dashboard.vue`, `barang_histori_index`+`BarangHistori.vue`.
`ReportView.vue` OWN `AdminLayout` → untuk 13 halaman ReportView, `<Deferred>` harus di DALAM ReportView (title/filter tetap instan). Lihat implementation_plan.md.

## Progress implementasi

- ✅ Fase 0–6: semua 42 menu real (`frontend/mock/*` sudah dihapus), pagination server-side + export XLSX di laporan, indexing diperluas (~30 index) + audit trail `ActivityLog`, redesign UI ("mecha" theme, token warna `rx-red`/`rx-yellow` di `frontend/css/main.css`).
- ⬜ Fase 7: verifikasi + load test — commit terakhir sebelum sesi ini ("Frontend, backend, masih error mwahaha") mengindikasikan masih ada bug runtime belum diselesaikan setelah redesign UI; belum diverifikasi `npm run build` bersih di kondisi terbaru.
- 🔶 Fase 8 (opsional, performa — lihat "Reporting replica" di atas): kode sisi app (`report_source`, `cdc_sync.py`, `sync_cdc`, wiring `_report_view`) sudah ada di branch `feature/cdc-reporting-replica`, teruji lewat Django check + smoke test lokal (fungsi CDC SQL Server-nya sendiri tidak bisa diuji tanpa server asli). Belum dikerjakan: enable CDC di server legacy (DBA), siapkan skema di server kedua, `--backfill` awal, dan verifikasi end-to-end (load test, cocokkan angka replica vs legacy).

## Di luar scope

Write master Produk/Pelanggan (stub tetap), Redis, pagination server-side, HTTPS.

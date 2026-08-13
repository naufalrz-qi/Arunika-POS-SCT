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

## Peta menu → sumber data

Route prefix `/admin-panel/`. View di `apps/monitoring/views.py` (kecuali connections di `apps/connections/views.py`). Menu def: `apps/core/menus.py`.

Jumlahnya **67 per 2026-08-11** (`len(ALL_MENUS)`, diukur), naik dari 42 saat audit kesiapan ditulis. Angka di paragraf ini sudah dua kali tertinggal dari kenyataan (tertulis 42, lalu 58, aslinya 62 sebelum lima menu terakhir) — **hitung ulang dari `ALL_MENUS`**, jangan percaya angka di sini maupun di `KESIAPAN-FITUR.md`.

**SEMUA menu sudah REAL** (migrasi Fase 3-7 selesai) — `frontend/mock/*.js` sudah dihapus total, tidak ada lagi import `@/mock` di `frontend/pages`. Laporan penjualan/pembelian pakai `apps/transactions/reports.py` (SQL builder per laporan + pagination server-side + export XLSX via `openpyxl`).

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

## Layar kasir: penjualan, order, cetak faktur (`apps/monitoring/views_kasir.py`)

Tiga layar transaksi berbagi satu berkas Vue dan satu mesin penomoran. Yang perlu diingat sebelum mengubahnya:

- **Penjualan & Penjualan Order = satu `Kasir/Penjualan.vue`**, dibedakan prop `mode`. Isiannya memang sama persis; yang beda cuma tabel tujuan (`t_penjualan(+_total)` vs `t_penjualan_order`) dan ada/tidaknya uang berpindah (Bayar/Kembali & Cetak hanya di mode nota). `localStorage` keranjang di-key per mode — kalau tidak, keranjang order menimpa keranjang nota milik orang yang sama.
- **Awalan nomor order `OJ` TETAP, bukan dari `m_divisi.kepala_nota`** (`pj.AWALAN_ORDER`). Di server testing seluruh 7.209 baris `t_penjualan_order` berawalan `OJ` sementara `kepala_nota` divisinya `SC`. Mengambilnya dari `kepala_nota` membuat penomoran order bercabang dua dan urutan legacy patah. Efek sampingnya menguntungkan: layar order tetap jalan walau `kepala_nota` belum diisi.
- **Order terbuka ditandai `no_transaksi = no_order` + `status = 0`.** Penyaring `daftar_order`/`buat_nota` membaca yang pertama, bukan `status` — ada 25 baris legacy berstatus 1 padahal belum diambil. Order yang salah tanda tidak menimbulkan galat apa pun; ia cuma lenyap dari daftar order terbuka.
- **`t_penjualan_order.tanggal_server` tak punya DEFAULT** (beda dari `t_penjualan`), jadi ia ditulis eksplisit sebagai `GETDATE()`. Dibiarkan berarti NULL, padahal 7.209 baris legacy semuanya terisi. Kedua tabel order **tanpa trigger**: order tidak mengurangi stok dan tidak ikut terkirim ke pusat — memang benar, barangnya belum keluar. Tak ada `t_penjualan_order_total`.
- **`detail.jenis` ditulis 1** (`pj.JENIS_BARIS`). Legacy memakai 1 pada seluruh 2.990.259 baris `t_penjualan_detail`; 68 baris ber-`jenis` 0 semuanya tulisan Arunika sendiri sebelum ini diperbaiki. Artinya tak diketahui dari skema — tiru satu-satunya nilai yang dipakai data sungguhan.
- **Cetak Faktur merender fakturnya sendiri**, tidak mengarahkan ke `/kasir/penjualan/<no>/cetak`: rute itu milik menu Penjualan, jadi orang yang hanya diberi menu Cetak Faktur akan terpental dari halaman cetaknya sendiri. `NotaCetak.vue` dipakai ulang sebagai komponen dengan `:auto="false"`, plus `@media print` **tak ber-scope** di `Faktur.vue` untuk menyembunyikan sidebar/navbar AdminLayout.
- **Endpoint `cari-barang`/`cari-customer` dipasang ULANG di bawah tiap layar** (lihat `urls_kasir.py`). Izin diberikan per-prefix oleh `menu_key_for_path`, jadi endpoint bersama membuat kotak cari mati bagi orang yang cuma punya salah satu layar — dan yang terlihat cuma "pencarian tak jalan", bukan pesan izin. Menaruhnya di luar semua prefix menu lebih buruk lagi: path tanpa menu dianggap bebas, dan endpoint ini membocorkan nama barang, harga, serta isi nota.
- **Ganti satuan di baris keranjang** (`pj.satuan_barang` → `<layar>/satuan` → `frontend/composables/useSatuan.js`): mengganti satuan WAJIB ikut mengganti harga — 541 barang punya >1 satuan dengan harga berbeda per satuan (1001: PCS 4.800, LSN isi 12 57.600), jadi mempertahankan harga lama berarti menjual selusin seharga satu tanpa satu pun tanda di layar. Daftarnya diambil saat kotak satuan **disentuh**, bukan saat barang ditambahkan: memindai barang tak boleh menambah round-trip (di profil WAN itulah biayanya), sedangkan ganti satuan jarang. Hasil di-cache per `kd_barang`. Baris `m_barang_satuan` ber-`status` 0 tetap ditampilkan — kotak cari pun begitu, dan arti status di tabel itu tak terdokumentasi.
- **Navigasi sel tabel** (`frontend/composables/useGridNav.js`, dipakai `Penjualan.vue` + `Transaksi.vue`): ↑↓ pindah baris pada kolom yang sama, ←→ pindah kolom **hanya bila kursor sudah di ujung teks**, Enter maju ke sel berikutnya lalu pulang ke kotak entri, Ctrl+Del hapus baris. Karena itu sel angka di tabel `type="text" inputmode="decimal"`, bukan `type="number"`: pada `type=number` `selectionStart` selalu null, jadi "ujung teks" tak bisa diketahui dan angka jadi mustahil disunting. Konsekuensinya koma desimal ala Indonesia benar-benar bisa terketik — semua pembacaan angka di kedua layar lewat helper `angka()`, sebab `Number("1,5")` adalah NaN yang diam-diam menghilangkan satu baris dari total.

## Tautan user legacy: PER KONEKSI (`apps/auth_app/tautan.py`)

`kd_user`/`kd_divisi`/`kd_pegawai` **tidak ada di model `User`** — ia baris di `TautanUser`, satu per (user × koneksi).

- **Kenapa**: `kd_user` dibuat berurutan (`UAA000`, `UAA001`, …) oleh tiap server SENDIRI-SENDIRI, jadi kode yang sama menunjuk orang berbeda di server berbeda. Terukur antara dua server: dari 11 kode yang ada di keduanya, **10 milik orang lain** — `UAA002` adalah KASIR01 di satu server dan YIQ di server lain. Satu `kd_user` di akun admin sudah salah begitu ia berpindah koneksi, dan admin memang berpindah (14 profil).
- **Tak ada fallback.** `tautan_wajib(user, profile)` menolak kalau tautan koneksi itu belum ada; ia TIDAK meminjam tautan koneksi lain. Peminjaman tak menimbulkan galat apa pun — kodenya valid di server tujuan, lolos FK, langsung terkirim ke pusat oleh trigger — cuma atas nama orang yang tak menyentuhnya. Untuk layar yang sekadar MENAMPILKAN, pakai `tautan_untuk()` yang memulangkan `KOSONG`.
- **Resolusinya eksplisit**, profil dioper sebagai argumen. Properti yang diam-diam membaca profil aktif dari thread-local akan jatuh ke `is_default` di perintah `manage.py` dan thread penjadwal — persis peminjaman yang dilarang di atas, cuma lebih sulit dilihat.
- **Kasir/supervisor bukan kasus khusus**: mereka terkunci ke satu server, jadi tautannya kebetulan cuma satu baris. Satu mekanisme, bukan dua.
- **Menu yang MENULIS hilang sebelum dibuka, bukan menolak sesudah terisi.** Flag `butuh_tautan` di `apps/core/menus.py` menandai **tujuh** layar (`kasir_penjualan`, `kasir_penjualan_order`, `kasir_retur_penjualan`, `kasir_pembelian`, `kasir_pembelian_order`, `kasir_retur_pembelian`, `koreksi_stok`) — daftar ini pernah tertulis "enam" selama Order Pembelian sudah lama ada, jadi baca `KEYS_BUTUH_TAUTAN` alih-alih memercayai angka di kalimat ini; `menus_for()` membuangnya kalau `tautan.lengkap(user, profil_aktif)` palsu. Karena `admin_network_guard._menu_allowed` membaca fungsi yang sama, URL yang diketik langsung ikut tertutup — termasuk `/save` dan `/cari-barang` lewat pencocokan prefix. Empat hal yang sengaja begitu:
  - **Superadmin ikut digerbangi.** Penyaringnya berjalan SESUDAH cabang peran, bukan sebelum. Ia juga tak bisa menyimpan tanpa `kd_user` di koneksi itu; membiarkan menunya terlihat hanya menunda penolakan sampai keranjang terisi.
  - **Cek Stok & Cetak Faktur TIDAK ditandai.** Keduanya cuma membaca. Mencabutnya membuat kasir tanpa tautan tak punya satu pun halaman kasir, dan `landing_for()` lalu mengantarnya ke Bantuan — yang ada di `/admin-panel` dan tertutup penjaga Tailscale dari jaringan toko. Jalan buntu.
  - **Pesannya beda dari "menu belum dibuka".** `middleware._pesan_tautan()` memulangkan kalimat `tautan.pesan_belum_tertaut()` yang sama persis dengan yang dipakai `tautan_wajib`, dan `ditolak()` merendernya tanpa redirect. Pesan generik akan mengirim orangnya ke Kelola Menu padahal yang kurang ada di Kelola Tautan User. Kalau menunya memang tak diberikan, pesan menu yang berlaku (dicek lewat `menus_for(user, abaikan_tautan=True)`).
  - **`assignable_menus()` tidak disentuh.** Kelola Menu adalah matriks pemberian yang tak bergantung koneksi; menyembunyikan barisnya di sana justru membuat superadmin tak bisa memberikan layar itu sebelum tautannya sempat dibuat.
  - **Tanpa koneksi aktif = tidak digerbangi.** Ketiadaan server masalah lain dan sudah punya suaranya sendiri (banner galat koneksi); menyembunyikan menu di situ akan menuduh orang belum ditautkan padahal yang kurang servernya.
  - Hasil `tautan_lengkap()` di-memo pada instance user berkunci id profil — `menus_for()` dipanggil tiga kali per permintaan (penjaga, prop bersama, `landing_for`). Dijaga `apps/monitoring/test_menu_tautan.py`.
- **`kd_pegawai` bukan syarat simpan**, di server maupun di layar. `Penjualan.vue` dulu mewajibkannya sehingga akun bertautan lengkap-tanpa-pegawai melihat tombol Simpan mati selamanya tanpa penjelasan; kini gerbangnya `kd_user && kd_divisi`, sama dengan `tautan_wajib`, dan bannernya membedakan kedua keadaan itu.
- **Layarnya `/admin-panel/tautan-user`** (superadmin saja, seperti Kelola Menu). Pilihan kode dibaca dari server yang bersangkutan saat barisnya dibuka — per koneksi, karena memuat 14 profil di muka berarti 42 query MS SQL lintas Tailscale yang kebanyakan takkan dilihat. Isian bebas 6 karakter dihapus: `UAA0O2` (huruf O) dulu bisa tersimpan diam-diam.
- Migrasi `auth_app/0006` memindahkan tautan lama ke `user.server_profile` (atau profil `is_default` untuk admin yang tak punya server).

## Notif per akun (`apps/core/models.log_untuk` + `nav/NotifMenu.vue`)

Tidak ada model notifikasi tersendiri: isinya irisan `ActivityLog`, yang sudah mencatat 19 jenis aksi. Yang benar-benar ditanyakan orang cuma "ada yang baru sejak terakhir saya lihat?", dan itu dijawab satu kolom `User.notif_dibaca_at` — bukan tabel status-baca per baris.

- **Satu aturan untuk TIGA layar.** `log_untuk(user)` memulangkan queryset yang disaring `username=user.username` kecuali superadmin, dan dipakai kartu Aktivitas Terbaru di dashboard, kotak notif di navbar, DAN halaman Log Aktivitas. Sebelumnya hanya dashboard yang menyaring; `/admin-panel/logs` memperlihatkan jejak semua orang kepada admin mana pun dengan alasan "ini layar audit, aksesnya sudah dijaga menu". Alasan itu tidak berlaku — menu `logs` bukan `superadmin_only`, jadi ia bisa diberikan kepada siapa saja. Pengauditannya tetap utuh, di tangan superadmin.
- **Disaring lewat `username`, bukan FK.** Kolom itu didenormalisasi supaya jejak tetap terbaca setelah akunnya dihapus; menyaring lewat relasi akan menyembunyikan baris-baris itu dari superadmin juga.
- **Rute tandai-dibaca `POST /notif/baca` ada di AKAR, bukan `/admin-panel`.** `admin_network_guard` menutup seluruh `/admin-panel` dengan penjaga Tailscale sedangkan kasir di toko tidak ada di rentang CGNAT — lonceng menempel di navbar setiap halaman termasuk layar kasir, jadi menaruh rutenya di sana akan mematikannya persis untuk orang yang paling sering melihatnya, dan gejalanya cuma "lencana tak pernah hilang". Notif milik AKUN: ia tak bergantung koneksi maupun menu. Dijaga `apps/monitoring/test_notif.py`.
- **Penyaring `?user=` hanya dituruti untuk superadmin.** Kalau tidak, admin bisa membaca jejak siapa pun hanya dengan mengetik namanya di URL. Penyaringnya juga didorong ke SQL: menyaring 300 baris yang sudah terpotong akan menjawab "tak ada" untuk orang yang jejaknya nyata tapi lebih tua dari baris ke-300. Daftar user-nya pun dibangun dari tabel `User`, bukan dari 300 baris yang terkirim (yang menyempit diam-diam saat log bertambah).
- **Lencananya dinol-kan secara optimistis** saat lonceng ditekan, tapi angka baru dari server SELALU menang (`watch(belumServer)`). Tanpa itu, notif yang datang sesudah lonceng dibuka tertutup topeng lokal dan lencananya tak menyala lagi sampai halaman dimuat ulang penuh.
- **`ToastContainer` kini juga dipasang di `Auth/Login.vue` dan `Ditolak.vue`.** Keduanya tak memakai `AdminLayout`, jadi `flash_error` yang ditulis tepat sebelum redirect ke `/login` di-`pop()` oleh `inertia_share` pada render Login lalu hilang tanpa jejak — persis pesan "sesi Anda berakhir" yang paling perlu terbaca.
- `frontend/utils/labels.js` sempat basi setahun: memuat `transaksi`/`tutup_buku`/`batal` yang tak dipancarkan kode mana pun dan tak memuat tujuh slug yang sungguh ditulis. Slug tak terpetakan tampil apa adanya, jadi kegagalannya tak pernah terlihat sebagai galat. Cek ulang dengan `grep -rn 'log_activity(request, ' apps/ --include=*.py`.

## Panel info layar kasir (`penjualan.info_customer/piutang_customer/histori_nota`)

Tiga keterangan yang selama ini hanya ada di `/admin-panel` — dan panel itu tertutup penjaga Tailscale, jadi dari jaringan toko memang tak terjangkau. Sebelumnya memilih member hanya menampilkan nama + kode; `alamat` sudah ikut terambil API lalu dibuang, sedangkan `point`/`limit_kredit`/`disc` tak pernah diminta sama sekali walau sudah lama diisi lewat layar master.

- **Rumus uangnya TIDAK ditulis ulang.** `piutang_customer` dan `histori_nota` memanggil `reports._nota_net()` yang sama dengan seluruh laporan penjualan. Menyalin rumusnya berarti dua definisi "total nota" yang akan berbeda diam-diam pada nota berdiskon header (`h.diskon1-4` fraksi, bukan rupiah — lihat docstring `_nota_net`).
- **Tanpa penyaring tanggal sama sekali** (`_base_where({"skip_date_predicate": True})`). Piutang yang jatuh tempo delapan bulan lalu justru yang paling perlu terlihat saat orangnya berdiri di depan kasir, dan ia akan hilang dari rentang bawaan mana pun.
- **Penyaringnya didorong ke DALAM `_nota_net`**, mengikuti `reports.nota_pelanggan`: index `(kd_customer, tanggal)` dan `IX_tpenjualan_user_tanggal (kd_user, tanggal)` lalu dipakai untuk MENYARING, bukan memindai lalu membuang. Index kedua sudah ada di `indexes.py` sejak lama dan sebelum ini tak satu pun query memakainya sebagai predikat.
- **Satu round-trip untuk tiga blok.** `{layar}/info-customer` memulangkan profil + piutang + nota terakhir sekaligus; tiga endpoint berarti tiga perjalanan WAN untuk satu klik, dan di profil jauh jumlah round-trip-lah biayanya.
- **`CAA000` (UMUM) tidak dijemput**, dijaga di server DAN di layar. Ia bawaan hampir setiap nota tunai, jadi memanggilnya berarti satu perjalanan sia-sia di awal hampir tiap nota.
- **Histori kasir dijemput sekali saat bloknya pertama DIBUKA**, bukan saat halaman dimuat — dan menutup-membuka lagi tidak mengulang perjalanannya.
- **`kd_user` diambil dari tautan, tak pernah dari payload layar.** Kalau layar boleh menyebut kodenya sendiri, siapa pun membaca nota orang lain dengan mengganti satu parameter di URL.
- **Endpoint didaftarkan ULANG per layar** (`penjualan`, `penjualan-order`) seperti `cari-barang`/`cari-customer`, dan di sini bocorannya lebih besar: ia membawa piutang, batas kredit, dan nota terakhir seseorang, sedangkan path yang tak cocok menu mana pun dianggap BEBAS.
- **Kolom uangnya dicabut di SERVER** lewat `_tanpa_harga` + `_UANG_INFO_KASIR` di `views.py`. Panel ini berdiri di luar `/admin-panel`, jadi ia melewatkan seluruh penyaringan berbasis spec laporan — nama field di daftar itu satu-satunya yang menahannya. `profil` sebuah dict tunggal, jadi ia dibungkus list dulu; kalau tidak, `limit_kredit` lolos justru di satu-satunya tempat panel ini menyebut rupiah langsung.
- **Limit kredit memperingatkan, tidak memblokir.** Kapan batas kredit boleh dilewati adalah keputusan orang di depan kasir, bukan keputusan layar.
- **Bentuknya TAB, di bawah tabel keranjang — bukan tumpukan kartu di bawah form.** Lima tab (Member / Piutang / Nota Pelanggan / Nota Saya / Pintasan) di kolom kiri yang lebar, tinggi petaknya TETAP (`h-44`) supaya isi tab yang panjang tak menggeser apa pun. Versi pertama menumpuk tiga kartu di bawah kartu Input Data, artinya piutang berada di bawah lima belas isian dan baru terlihat kalau seseorang menggulung layar — padahal yang perlu melihatnya sedang berdiri melayani orangnya. Kartu Pintasan yang dulu berdiri sendiri jadi salah satu tab, jadi panel ini menggantikan sesuatu alih-alih menambah.
- **Jumlahnya tercetak di label tab** (`3` di sebelah "Piutang", merah kalau melewati limit), jadi "ada nota belum lunas" terbaca tanpa membuka tabnya. **Tab tidak berpindah sendiri** saat pelanggan dipilih: memindahkan panel di bawah tangan orang yang sedang mengetik lebih mengganggu daripada menolong — cukup angkanya yang menarik perhatian.
- Blok keterangan member sengaja TIDAK ikut ditaruh di dalam kotak Customer: kotak itu berdiri di tengah lima belas isian, dan blok yang tingginya berubah-ubah di sana membuat isian di bawahnya melompat tiap kali pelanggan berganti.

## Koreksi Stok (`apps/transactions/opname.py` + `Admin/Inventory/KoreksiStok.vue`)

Halaman sendiri (`/admin-panel/inventory/koreksi-stok`), bukan modal di layar Opname: satu sesi balancing menyentuh ratusan baris — terukur di gudang, 410 baris ber-keterangan sama dalam satu sesi. Opname Stok tetap murni laporan.

Bentuknya beda dari setiap jalur tulis lain, dan bedanya dipaksa database lama — semuanya diukur langsung di server (PAGESANGAN 4.917 baris, PUSAT, testgudang 6.699 baris):

- **`trig_update_stok_opname_stok` tidak aman multi-baris.** Isinya `SELECT @barang = inserted.kd_barang … FROM inserted` — assignment skalar dari sebuah tabel. Satu `INSERT` berisi banyak baris hanya diproses untuk SATU baris, tanpa galat. **Karena itu `buat_koreksi` menulis satu baris per `execute`, dan jangan pernah digabung "supaya efisien".** Trigger `DELETE` sama skalarnya, jadi pembatalan pun harus satu per satu. Catatan mekanisme yang perlu diluruskan: yang digeser trigger ini **bukan** stok yang dibaca Arunika, melainkan `m_barang_stok_akhir` dengan `kd_divisi` di-hardcode `'-'` — cache legacy yang sudah rusak. Angka stok kita datang dari mesin movement yang membaca `t_opname_stok` langsung, jadi 3 baris tetap terhitung 3 dengan cara penulisan mana pun. Aturan satu-baris-per-`execute` tetap berlaku (lihat § "Database legacy" — ia berlaku untuk semua tabel bertrigger skalar, bukan cuma tabel ini), tapi alasannya kehati-hatian terhadap sisi legacy, bukan stok kita sendiri yang hilang.
- **Tabelnya datar**: satu `no_transaksi` = satu baris = satu barang. Tak ada tabel detail. Koreksi lima barang berarti lima nomor.
- **EMPAT jenis koreksi, dan namanya bukan karangan kita.** View legacy `mon_t_opname_stok` yang memberi label: `0 Hilang`, `1 Rusak`, `2 Lain-Lain(+)`, `3 Lain-Lain (-)`. Nilai `4` pernah ada di data lama (1 baris di PAGESANGAN) tapi tak punya label sama sekali — sampah, bukan jenis kelima.
- **Arah tidak pernah jadi pilihan terpisah** — ia melekat pada jenisnya, karena trigger yang memutuskan: `IF @status <> 2 SET @jumlah = @jumlah * -1`. Jadi hanya Lain-Lain(+) yang menambah; Hilang, Rusak, dan Lain-Lain(−) sama-sama mengurangi. Menyediakan pilihan arah sendiri berarti mengizinkan "Rusak, stok bertambah". Bahwa jenisnya perlu berlabel jelas juga bukan dugaan: di gudang ada 30 baris ber-status 3 (Lain-Lain −) yang keterangannya diketik **"RUSAK"** — operator memilih jenis yang salah lalu menuliskan maksudnya sebagai teks bebas.
- **`kd_divisi` DIPILIH operator, bukan ditebak — dan ini kebalikan dari kesan pertama.** Toko memang berisi satu divisi (`DAA000` di RTL PUSAT/PUSAT/PAGESANGAN), tapi **gudang berisi lima**, dan di sana seluruh 6.698 baris opname ada di `DAA001` (PERGUDANGAN) sementara `DAA000` (UMUM) tak punya satu pun. Mengambil "divisi aktif pertama" berarti mencatat koreksi gudang ke divisi yang tak pernah dipakai. Ia satu-satunya nilai yang datang dari layar, jadi ia diperiksa terhadap `m_divisi` sebelum dipakai.
- **`kepala_nota` disimpan per DIVISI, bukan per server.** Di gudang: `UM`/`GP`/`GO`/`KN`/`FR`. Nomor opname di sana memang berawalan `GP` (6.698) dan `GO` (1) — mengikuti divisi barisnya. Jadi awalannya diambil `awalan_untuk(cur, kd_divisi)` dengan divisi yang DIPILIH, bukan `awalan_untuk(cur)`.
- **`tanggal_server` tak punya DEFAULT** tapi 0 dari 4.917 baris lama bernilai NULL — aplikasi lama menulisnya sendiri, jadi kita juga. Jebakan yang sama dengan `t_penjualan_order`.
- **`keterangan` wajib, `varchar(50)`, dipotong bukan ditolak.** Itu satu-satunya tempat sebab koreksi tercatat ("BALANCE STOK RETUR", "pernah tdk aktif"), dan 3.474 dari 4.917 baris lama membiarkannya kosong. Layar **Neraca Opname pernah ada dan sudah DIHAPUS** (2026-08-10): premisnya — opname parsial menyembunyikan pasangan plus-minus — diukur dan tak terbukti. Dari 7.078 keluarga di dua server, hanya 29 punya lebih dari satu anggota dan 21 punya pasangan sama sekali; seluruh menu menghasilkan lima temuan. Jangan dibangun ulang tanpa mengukur ulang angka itu.
- **Aksesnya `admin_only`** (flag di `apps/core/menus.py`, dipakai `opname`, `koreksi_stok`, dan ketiga layar tulis kas): dicentang di Kelola Menu pun tak berlaku bagi kasir/supervisor. Beda dari menu admin biasa yang memang boleh diberikan ke supervisor. Ditegakkan di `menus_for()` — dibaca juga oleh `admin_network_guard`, jadi URL yang diketik langsung ikut tertutup, termasuk `/opname/save` lewat pencocokan prefix.
- **`kd_user` `char(6) NOT NULL`**, sedangkan akun admin/superadmin umumnya belum ditautkan ke user legacy. Layar mengatakannya di awal (prop `kd_user`) alih-alih menolak setelah lima puluh baris terisi. Tautannya diisi di Kelola Tautan User — memalsukan kd_user berarti koreksi tercatat atas nama orang lain. Ada pula FK `FK_t_opname_stok_m_barang`, jadi kd_barang karangan ditolak database.

Layarnya (grid ala aplikasi desktop, mesin navigasinya `useGridNav.js` yang sama dengan layar nota):

- **Yang diketik STOK FISIK, bukan selisih.** Itu yang benar-benar dipunyai operator setelah menghitung rak; menyuruhnya menghitung selisih sendiri menambah satu langkah aritmetika yang bisa salah. Kolom Selisih tetap bisa diketik langsung — untuk Rusak/Hilang ia tahu "3 rusak" tanpa menghitung ulang rak. Keduanya saling mengisi dua arah, dan jenis bawaan mengikuti tanda selisih.
- **Daftar barang TIDAK dikirim di muka.** Universe barang×divisi ~55rb baris sudah pernah membunuh Stok Akhir sebagai tabel baca-saja (15,6 MB JSON); grid berisi kotak isian di tiap baris jauh lebih berat. Barisnya masuk lewat kotak pindai, plus tombol "Muat semua hasil" yang dibatasi `_BATAS_MUAT` (300) dan mengatakan kalau terpotong.
- **Stok sistemnya gratis**: diambil dari payload kolumnar yang sudah dicache & dihangatkan scheduler lewat `inv.cek_stok()` — bukan query baru.
- **Satuan WAJIB ikut hasil pencarian** (`pj.satuan_banyak`, dijaga `test_koreksi_cari.py`). `inv.cek_stok()` hanya mengembalikan kd_barang/nama/stok_akhir/stok_min — tak ada kd_satuan. Versi pertama layar ini mengambil satuan saat dropdown-nya disentuh, dan itu membuatnya buntu: `kd_satuan` wajib terisi sebelum baris bisa disimpan, jadi 300 baris berarti 300 dropdown × 1 round-trip sebelum Simpan bisa ditekan sekali pun. Satu query `IN` dengan `bind_varchar` melayani 300 barang dalam 0,060 dtk. Jangan kembalikan ke pengambilan per baris.
- **Tata letak: kotak pindai + hasil cari DI ATAS tabel, baris baru disisipkan di atas.** Kebalikan dari layar nota — dan sengaja. Di layar nota barisnya sedikit sehingga kotak di bawah tabel wajar; di sini 300 baris membuat apa pun yang di bawah tabel praktis tak terjangkau.
- **Divisi dikunci begitu ada baris.** Ia menentukan angka stok yang sudah tampil, jadi menggantinya di tengah jalan membuat seluruh selisih yang sudah diketik salah tanpa satu pun tanda di layar.
- **Setelah simpan hanya barisnya yang dibersihkan** — divisi & keterangan bertahan, karena satu sesi balancing disimpan bertahap.
- **Jenis mengikuti tanda selisih di `@change`, bukan `@input`**, dan berhenti mengikuti begitu operator memilih sendiri: mengikutinya tiap ketukan tombol membuat kotak jenis berkedip sepanjang pengetikan, dan menimpa pilihan Rusak/Hilang yang sudah dibuat.
- **Ganti satuan ikut membaca ulang stok fisik yang sudah diketik.** Stok sistem dibagi `m_barang_satuan.jumlah`, dan qty ditulis dalam satuan pilihan (trigger yang mengalikan balik lewat `GetKuantitasSatuanTerkecil`). Tanpa pembacaan ulang itu, "10" yang tadinya 10 PCS mendadak berarti 10 LUSIN dan selisihnya melonjak 12 kali lipat tanpa satu pun tanda di layar.
- Baris berselisih nol tidak dikirim — ia cuma menambah nomor dan baris laporan tanpa menggeser apa pun.

## CRUD master & kas (`master_crud.py`, `barang.py`, `kas.py`)

Tiga jalur tulis baru, semuanya diukur di server sebelum ditulis.

**Kode master itu `{huruf}{blok}{NNN}`, dan BLOKNYA BERGULIR.** `MAA000` … `MAA999` lalu `MAB000`. Bukan teori: `m_merk` sudah di `MAB483` dan `m_model` di `MAB296` di testgudang. Awalan tetap seperti `("SAA", None, 3)` yang dipakai supplier karena itu punya langit-langit yang pasti tercapai — ia sekarang memakai `penomoran.kode_master_berikutnya`. Polanya disaring `LIKE 'X[A-Z][A-Z][0-9][0-9][0-9]'`, **bukan** `LIKE 'X%'`: `m_kategori` memuat satu baris `KAATES` dan `m_voucher` satu baris `1`, dan `MAX()` tanpa saringan mengembalikan `KAATES` (huruf > angka secara leksikal) sehingga penomorannya diam-diam mengulang dari 001.

**Tidak ada `DELETE`, dan itu bukan kehati-hatian berlebih.** `m_merk`/`m_kategori`/`m_model`/`m_warna`/`m_jenis_bahan` punya FK `ON DELETE CASCADE` ke `m_barang`, sedangkan `m_barang` → `m_barang_satuan` justru `NO_ACTION`. Menghapus satu merk MENGHAPUS barang-barang "kosong" di bawahnya lalu gagal begitu ketemu barang bersatuan — penghapusan separuh jadi. Pembatalan memakai kolom `status`.

**Arti `status` dibaca dari data.** 0 = nonaktif di mana-mana, tapi "aktif" tidak selalu 1: seluruh 38 baris `m_biaya` bernilai **2**. Karena itu opsinya ada di spec (`pilihan`), bukan di-hardcode. Efek sampingnya memperbaiki bug lama: isian kosong dulu jatuh ke 0, jadi **setiap pelanggan baru lahir nonaktif** — ikut bucket 286 baris `m_customer` berstatus 0.

**`m_supplier` tak punya kolom `status` sama sekali** (13 kolom). Jadi supplier tak bisa dinonaktifkan, dan karena DELETE tak boleh, ia memang tak bisa dibatalkan. Jangan "perbaiki" dengan menambah kolom — skema ini dipakai bersama aplikasi POS lama.

**`t_mutasi_kas.kd_kas_tujuan` itu KAS, walau tipenya berkata lain.** Ia `varchar(10)` bertipe `JR_KODE_ACCOUNT` (sama dengan `m_jurnal.kd_index`) sedangkan `kd_kas_sumber` `char(6)` — semuanya mengarah ke "tujuannya sebuah akun", dan itu keliru. Tiga VIEW legacy (`v_t_mutasi_kas`, `mon_t_mutasi_kas`, `v_g_kas_histori_detail`) sama-sama join `= m_kas.kd_kas`. **Pelajaran yang sama dengan empat jenis koreksi opname: arti kolom legacy ada di `sys.sql_modules`, bukan di skema tabelnya.**

**Bukti nyata ada untuk biaya operasional dan pendapatan.** `t_biaya_operasional` punya 9.563 baris di grosirPusat (`SC2603200006` = `{kepala_nota}{YYMMDD}{NNNN}`, `no_bukti` yang kosong ditulis `-`), dan `t_pendapatan` 6 baris berbentuk sama persis (`SC2203310001`). `t_penambahan_kas` dan `t_mutasi_kas` **nol baris di setiap server yang bisa dijangkau** — bentuk nomornya mengikuti konvensi tetangga, sama seperti Order Pembelian dulu.

**Pendapatan Lain-Lain ditambahkan belakangan untuk menutup asimetri.** Kas Harian sudah membaca `t_pendapatan` di dalam `_kas_union` sejak lama, tapi `kas.py` cuma bisa menulis tiga dari empat dokumen kas — angka pendapatan bisa dilihat, tak bisa dimasukkan. Karena mesin kas digerakkan `SPEC`/`FORM` dan route-nya sudah generik (`kas/input/<jenis>`), penambahannya **tak butuh view atau route baru**: satu entri `SPEC`, satu `FORM`, satu `LOOKUP`, satu `penomoran.JENIS`, satu menu. Kolomnya kembaran `biaya` kecuali `kd_biaya` → `kd_pendapatan`, dan `m_pendapatan` cuma berisi satu baris (`PAA000` "UMUM") di semua server. Ia **bertrigger `insert_temp_m_t_pendapatan`** seperti biaya operasional, jadi barisnya masuk antrean kirim ke pusat seketika — itu alasan menunya `admin_only` + `butuh_tautan`.

**Kelola Barang khusus gudang** (dulu "Tambah Barang"; layar Update Barang berganti nama jadi **Update Harga**, key menunya ikut berganti sehingga ada migrasi `auth_app/0008` yang menulis ulang `User.allowed_menu_keys` — tanpa itu menunya lenyap diam-diam dari akun yang hak aksesnya diatur satu per satu). Struktur di Kelola Barang, harga di Update Harga: `ubah_barang` **tak pernah** menulis `harga_jual` baris yang sudah ada, karena itu akan melewati `update_harga` beserta validasi harga bulat, hitung ulang margin, pembatalan cache, riwayat, dan sebar ke 8 toko. **Tambah barang khusus gudang**, memakai gerbang `services._is_gudang`/`BukanServerGudang` yang sudah ada. `kd_barang` **diketik operator**, tak ada polanya untuk ditebak (`OCT6555`, `6941057402239B`, `JM14062-MU`, `000-06`, `049`) — yang dilakukan modul memeriksa bentroknya. Baris `m_barang_divisi` **opsional**: 22.927 dari 53.865 barang tak punya satu pun, dan mesin stok membaca pergerakan, bukan tabel itu. `status_pinjam` nol di SELURUH 53.865 baris jadi ia tak pernah jadi kotak isian; `tanggal_daftar` terisi di seluruh baris dan tak punya default constraint, jadi wajib ditulis. `_sebar_harga` sengaja TIDAK dipanggil — toko belum punya baris barangnya, dan fan-out `m_barang`/`m_barang_satuan` sudah dikerjakan trigger feed.

## Tabel legacy tersedia (sudah dicek di server aktif)

`m_barang`, `m_barang_satuan`, `m_barang_promo`(+`_detail`), `m_barang_divisi_diskon`, `m_voucher`, `m_kas`, `m_customer`, `m_supplier`, `m_divisi`, `m_kategori`, `m_pegawai`.
`t_penjualan`(+`_detail`,`_retur`,`_retur_detail`,`_order`,`_order_detail`), `t_pembelian`(+`_detail`,`_order`,`_order_detail`,`_order_spare_part`(+`_detail`),`_retur`,`_retur_detail`), `t_opname_stok`, `t_mutasi_stok`, `t_mutasi_kas`, `t_penambahan_kas`, `t_pegawai_ganti_shift`(+`_detail`), `t_absensi`, `g_tutup_buku`.
Kolom asli WAJIB dicek via INFORMATION_SCHEMA sebelum tulis SQL (nama kolom legacy tak standar).
**Daftar ini pernah tidak lengkap**: `t_pembelian_order` sudah ada sejak awal tapi tak tercatat di sini, dan ketiadaannya sempat dibaca sebagai "tabelnya memang tak ada". Sebelum menyimpulkan sebuah tabel tak ada, tanyakan `INFORMATION_SCHEMA.TABLES` — jangan tanyakan berkas ini.

## Hutang Supplier & laporan Order (`reports.hutang`, `reports.order_penjualan`/`order_pembelian`)

Tiga laporan yang ditambahkan setelah membandingkan katalog laporan legacy (`g_mon_menu_detail`, **116 laporan** dalam 39 grup) dengan menu Arunika. Cara membandingkannya penting untuk diulang: **jumlah baris tiap tabel adalah penyaringnya.** Sebagian besar permukaan legacy — seluruh kluster HRD/absensi/cuti/SP/gaji, aset & penyusutan, kendaraan, persewaan & jasa, surat berharga, prive, tagihan, komisi pegawai, nota kosong, koin/point — **nol baris di GUDANG maupun PUSAT**. Menunya lengkap, datanya tak pernah ada. Jangan mengejar fitur legacy tanpa menghitung barisnya lebih dulu.

**Hutang Supplier adalah cermin Piutang**, dan itu bukan kebetulan: pasangan helper-nya (`_nota_net()` ↔ `_pembelian_nota()`) sudah ada, jadi bedanya hanya nama tabel/kolom. Diverifikasi terhadap `mon_t_hutang_aktif` untuk Januari 2025 di GUDANG: **119 nota, nol selisih nilai.**

- `_pembelian_nota()` tak membawa `tanggal_jatuh_tempo` (Piutang mendapatnya dari `_nota_net`). Diambil lewat join balik ke `t_pembelian`, **bukan** dengan menambah kolom di helper yang dipakai tiga laporan lain.
- **`t_hutang_cicilan` nol baris di setiap server**, jadi kolom Cicilan selalu nol dan seluruh 9.652 pembelian kredit gudang tampil belum lunas. Itu keadaan data — pembayaran hutang memang tak pernah dicatat — bukan cacat laporan. Layarnya mengatakannya lewat banner (slot `#peringatan` di `ReportPage.vue`) yang **hilang sendiri** begitu ada yang mulai mencatat.

**Laporan Order menutup lubang "ditulis lalu hilang".** Arunika sudah MENULIS kedua order sejak lama, tapi `t_penjualan_order`/`t_pembelian_order` tak muncul sekali pun di `reports.py`.

- Grain **per order (header)**, bukan per baris seperti `mon_t_penjualan_order_edit` — yang dicari operator adalah order yang belum jadi nota.
- **"Terbuka" datang dalam dua bentuk**: `no_transaksi = no_order` (penanda jalur tulis kita, 38 di PUSAT) dan `no_transaksi` kosong (peninggalan aplikasi lama, 20 di PUSAT). Digabung karena artinya sama; kolom `no_transaksi` tetap ditampilkan apa adanya. Kolom `status` (0/1) **bukan** penandanya — 16 baris status=0 vs 38 order terbuka di server yang sama.
- Nilainya lewat `_ghb()` seperti laporan nota, **bukan** `SUM(qty*harga)` polos. Di GUDANG cuma 4 baris detail order yang berdiskon, tapi keempatnya mode **rupiah flat** (`602`, `901`, `6`, `2`) — persis kasus yang membuat aritmetika flat lama salah. Dicek manual: `OJ2109300007` = (52500−602)×20 + (24500−901)×20 + 670.000 = **2.179.940**, cocok.
- **`t_pembelian_order` nol baris di semua server**, jadi laporannya kosong sampai layar Order Pembelian kita sendiri mengisinya. Justru itu alasannya ada: tanpa ini satu-satunya jalur tulis ke tabel itu tak punya layar baca sama sekali.

## Laba Rugi (`apps/transactions/laba_rugi.py` + `inventory.services.nilai_persediaan`)

Pengganti `GetRekapHarian` legacy. **Angkanya sengaja TIDAK sama dengan aplikasi lama**, dan layarnya mengatakan itu lewat banner permanen — kalau banner itu dihapus, selisihnya akan dibaca sebagai salah hitung.

**Legacy tak bisa dipakai karena dua hal, keduanya diukur di GUDANG.** (1) `GetRekapHarian` timeout >60 dtk; `GetHargaAverageBarangPerTanggal` sendiri **171 detik** (kursor bersarang per barang + UDF skalar per nota atas 593rb baris). (2) Metodenya **LIFO**, yang dilarang PSAK 14 / IAS 2 sejak revisi 2008, dan ia menilai stok hasil **opname masuk Rp 0** — di GUDANG itu 14,3 juta unit dari 92 juta unit arus masuk.

Prototipe set-based dari metode legacy sempat dibuat dan **cocok 99,77%** (5.987 dari 6.001 barang, 2,4 dtk vs 171 dtk; 14 sisanya lapisan bertanggal sama yang di legacy memang tak deterministik). Jadi ketidakcocokan angka bukan karena kita gagal menirunya — melainkan karena metodenya sengaja diganti.

**Metode penggantinya: rata-rata tertimbang per barang** (`_harga_pokok_rata`), atas arus yang **membawa biaya perolehan saja** — saldo awal + pembelian netto − retur pembelian. Opname, mutasi, dan retur penjualan menggeser kuantitas tanpa menimbulkan biaya, jadi mereka mengubah stok on-hand tapi bukan dasar harganya; unitnya otomatis dinilai pada rata-rata yang sama, bukan Rp 0.

**Kuantitas disaring divisi, harga TIDAK.** Satu barang punya satu biaya perolehan bagi perusahaan, tak berubah karena disimpan di gudang mana — dan efeknya Laba Rugi tiap divisi **menjumlah tepat** ke Laba Rugi server (diuji: selisih Rp 0,02 atas Rp 10,5 miliar). Ini kebalikan dari Stok per Divisi, yang angkanya memang bergeser saat difilter.

**Periode seluruhnya sebelum tutup buku DITOLAK** (`PeriodeTertutup`), tidak digeser. Legacy menggeser `@awal` diam-diam; di PUSAT tutup bukunya 2025-12-31, jadi permintaan "November 2025" di sana berubah jadi Januari 2026 tanpa sepatah kata. Periode yang *melintasi* tutup buku tetap digeser, tapi lewat `notice` yang tampil di layar.

**Jangan pakai `_purchase_prices()` untuk valuasi.** Fungsi itu membagi pembilang DAN penyebutnya dengan `bs.jumlah` sehingga faktornya saling menghilangkan, dan hasilnya harga per satuan **beli** — sementara kuantitas yang mengalikannya dalam satuan **terkecil**. Terbukti pada `AMP013` (beli per `SAA005`, `jumlah = 10`): Rp 11.601,35 vs harga benar Rp 1.160,13, **rasio tepat 10,00×**. Kolom `nominal` di layar Stok Akhir menggelembung karenanya; belum diperbaiki.

**Laporan periode lampau tidak reproducible persis.** Baris bertanggal lampau masih berdatangan lewat sync: terukur saat modul ini ditulis, 3 pembelian + 1 retur bertanggal Juli masuk ke GUDANG dalam 6 jam dan menggeser persediaan akhir Juli **Rp 97 juta**. Sifat datanya, bukan cacat laporan — jangan mengejar selisih terhadap angka yang dicatat kemarin.

Acuan angka (GUDANG, Juli 2026, saat ditulis): persediaan awal 7.610.410.176 · akhir 6.924.568.973 · HPP 3.626.959.894 · laba kotor 1.553.594.031 · margin 29,99% **terhadap penjualan bersih** (legacy menyebut `laba/HPP` sebagai "Rasio Kontribusi" — itu markup, bukan margin).

## Order Pembelian (`SPEC["pembelian_order"]` di `apps/transactions/transaksi.py`)

Layar tulis pertama yang tabelnya **tidak punya satu pun baris lama untuk ditiru**: `t_pembelian_order` kosong di setiap server yang terjangkau (testgudang 0, PUSAT 0 padahal `t_pembelian` 12.605 baris). Semua jalur tulis lain bisa dicocokkan dengan data sungguhan; yang ini tidak. Jadi keputusannya bersandar pada skema, view legacy, dan konvensi tabel kembarannya — dan itu perlu diingat kalau suatu saat angkanya tak cocok dengan aplikasi lama.

- **Ia PUNYA trigger `insert_temp_m_*`, sedangkan `t_penjualan_order` tak punya satu pun.** Artinya order pembelian **ikut terkirim ke pusat** begitu disimpan, order penjualan tidak. Jangan menyamakan keduanya hanya karena namanya bersaudara.
- **Kolom pembayarannya `kd_jenis_bayar`**, satu-satunya di seluruh SPEC yang begitu. Ia tetap menunjuk `m_jenis_bayar.kd_jenis` — dibuktikan view `mon_t_pembelian_order_edit` — jadi pilihannya dipakai ulang; `buat()` mengisi ctx dengan kedua nama alih-alih menambah kunci SPEC.
- **Tiga kolom yang tak punya padanan di tabel lain**: `no_pp_order`, `jaminan`, `tanggal_terima`. Labelnya diambil dari view legacy yang sama ("No. PP Order", "Jaminan / U.M.", "Penerimaan"), bukan dikarang. Layar menampilkannya lewat prop `kolom_order` yang disimpulkan dari `s["header"]`, bukan dari `jenis === "pembelian_order"` di Vue.
- **Awalan `OB`, TETAP**, mengikuti alasan `AWALAN_ORDER` (`OJ`): penomoran order tak boleh bercabang mengikuti divisi, dan layarnya tetap jalan walau `kepala_nota` belum diisi. Ini KEPUTUSAN, bukan temuan — tak ada data untuk membuktikannya, dan nomor yang sudah terbit tak bisa ditarik.
- **Order terbuka ditandai `no_transaksi = no_order`**, bukan `status`. Konvensi `t_penjualan_order` yang terbukti di 7.209 baris; di sana `status` justru yang gagal (25 baris berstatus 1 padahal belum diambil, lenyap dari daftar tanpa galat). Penandanya disimpulkan dari header (`"no_transaksi" in header and kunci != "no_transaksi"`) supaya tak ada kunci SPEC ketiga yang bisa lupa diisi. Aman pula terhadap `no_transaksi` yang di tabel ini NOT NULL — beda dari `t_penjualan_order` yang nullable.
- **`tanggal_server` di sini PUNYA DEFAULT `GETDATE()`**, beda dari `t_penjualan_order` yang tidak. Jadi ia tak perlu ditulis eksplisit.
- **Detailnya tanpa `point1`** (ada di `t_pembelian_detail`, tidak di sini) dan tanpa `total` (kolom terhitung di kedua tabel — menyebutnya membuat INSERT ditolak).
- Dijaga `apps/transactions/test_pembelian_order.py`, yang menguji BENTUK SQL-nya: tanpa data lama, itu satu-satunya yang bisa diuji tanpa server.

## Nilai bawaan layar tulis kasir

`pj.bawaan_form(profile, jenis)` kini melayani **semua** layar tulis, bukan cuma nota. Sebelumnya keempat layar `Transaksi.vue` membuka dengan Jenis Bayar dan Kas KOSONG padahal keduanya NOT NULL ber-FK: simpan pertama selalu gagal dengan galat foreign key, dan galat itu tak terbaca sebagai "ada isian yang belum dipilih".

- Kunci sisi jual (`kd_customer`, `kd_voucher`) **dibuang** untuk jenis beli, bukan dikosongkan — kunci kosong di layar supplier terbaca seperti pilihan yang gagal dimuat. Tak ada "supplier umum": memilih pemasok memang keputusan.
- Layar hanya mengisi isian yang MASIH kosong (`watch` pada prop deferred). Prop deferred datang setelah cat pertama, jadi menimpa apa adanya akan menghapus pilihan orang yang sudah keburu mengetik.
- Ancar-ancar nomor ikut ditampilkan di keempat layar, seperti layar nota — dipakai kasir untuk mencocokkan lembar fisik.

## Separasi menu kasir

Section `pos` dipecah tiga: `pos_jual` / `pos_beli` / `pos_lain`, pola yang sama dengan Master Data. **Tetap satu tab navbar "Kasir"** (`NAV_GROUPS` di `useNav.js`) — menjadikannya tiga tab memaksa kasir berpindah tab untuk pekerjaan yang ia lakukan berselang-seling.

- `default_keys_for` dulu membandingkan `m["section"] != "pos"`. Begitu section dipecah, pembandingan itu diam-diam jadi selalu benar dan SELURUH menu kasir masuk ke bawaan admin. Diganti himpunan bernama `SECTIONS_POS`.
- **Urutan di `ALL_MENUS` menentukan halaman pendaratan, bukan urutan sidebar.** `landing_for()` mengambil menu bawaan peran yang pertama; sidebar mengurutkan sub-grupnya dari `NAV_GROUPS`. Karena itu Cek Stok tetap berdiri di awal daftar walau tampil di grup "Lainnya" paling bawah — ia satu-satunya layar kasir yang tak menulis dan tak pernah tertutup gerbang tautan, jadi ia tempat mendarat yang selalu ada. Memindahkannya ke bawah diam-diam mengubah ke mana setiap kasir mendarat setelah login (dan sempat terjadi: tiga tes menangkapnya).
- "Terima Pembelian" jadi **"Pembelian"**; kuncinya tetap `kasir_pembelian` karena kunci tersimpan di `allowed_menu_keys` tiap user — menggantinya mencabut layar itu dari semua orang yang menunya sudah diatur satu per satu.

## Database legacy: milik bersama, bukan milik Arunika (`docs/skema/`)

Setiap server toko dipakai bertiga: aplikasi POS lama, job SQL Agent di `scripts/job/`, dan sink PHP/MySQL pusat yang bukan milik kita. Setiap FK, trigger, dan baris `tbl_tmp_post` di sana adalah kontrak dengan ketiganya. **Karena itu jawaban bawaan untuk "haruskah skema/trigger-nya diperbaiki" adalah TIDAK.** Pertahanan Arunika ada di hak akses dan disiplin jalur tulis, bukan di mengubah DDL yang tak bisa kita uji terhadap aplikasi lama.

Dump lengkap dua DB acuan ada di `docs/skema/skema-testGudang.txt` dan `docs/skema/skema-grosirPusat.txt` — tabel, kolom, PK/unique, seluruh FK beserta aturannya, check, default, dan definisi penuh setiap trigger. Regenerasi kapan saja: `python scripts/dump_skema_aturan.py`. Semua angka di bawah diukur langsung 2026-08-09 (testGudang / grosirPusat).

### FK: 129 / 131, dan hampir semuanya cascade

- **`ON UPDATE CASCADE` nyaris universal** (128 dari 129 di testGudang, 118 dari 131 di grosirPusat). Mengubah `kd_barang`, `kd_satuan`, `kd_divisi`, `kd_supplier`, atau `kd_customer` di tabel master merambat ke belasan tabel transaksi sekaligus, dan tiap baris yang tersentuh membangunkan trigger feed sehingga seluruhnya tersembur ke pusat. **Jangan pernah UPDATE kolom `kd_*` di tabel master.** Perubahan kode = baris baru + nonaktifkan yang lama.
- **`ON DELETE CASCADE` di 66 / 60 FK, dan merambat dua tingkat.** `m_merk`/`m_kategori`/`m_model`/`m_warna`/`m_jenis_bahan` → **`m_barang`** → **`m_barang_divisi_diskon`**. Di sisi transaksi: `t_penjualan` → `_detail`, `_detail_pegawai`, `_total`, `t_piutang_cicilan`, `t_tagihan_detail`; pola yang sama untuk `_retur`, `_order`, `t_pembelian_retur`, `t_mutasi_stok`.
- **Cascade itu justru sering diblokir tetangganya, dan itu lebih buruk daripada kalau ia konsisten.** `m_barang` → `m_barang_satuan`/`_divisi`/`_supplier`/`_formula` semuanya `NO_ACTION`, jadi DELETE di `m_merk` gagal begitu ada satu barang bersatuan — tapi berhasil menghapus barang-barang "kosong" sebelum sampai ke sana. Hasilnya penghapusan separuh jadi, bukan galat bersih.
- **116 / 111 FK ber-status `not_trusted`** (dibuat atau di-enable `WITH NOCHECK`). Data historis boleh melanggarnya dan optimizer tak memercayainya. **Jangan pernah menyimpulkan "kan ada FK-nya" lalu mengganti `LEFT JOIN` jadi `INNER JOIN`.**
- **Tabel detail tak bisa dikunci PK.** `t_penjualan_detail`, `t_pembelian_detail`, `t_penjualan_retur_detail`, `t_mutasi_stok_detail`, `t_tagihan_detail` tanpa PK — dan datanya memang sudah melanggar: 3 grup duplikat `(no_transaksi, kd_barang, kd_satuan)` di `t_penjualan_detail` (570.190 baris), 19 grup di `t_pembelian_detail`. Menambah PK akan gagal; memaksanya berarti membuang baris transaksi asli. Uniqueness dijaga di aplikasi, bukan di DB.

### Trigger: 217 / 176, dua keluarga dengan sifat berlawanan

- **207 / 168 di antaranya trigger feed sync** (`insert_temp_m_*`, `update_temp_m_*`, `delete_temp_m_*`) yang menulis ke `tbl_tmp_post` + `tbl_log_transaksi`. Semuanya **set-based** (`… SELECT … FROM inserted`), jadi aman multi-baris. **Jangan disentuh** — itu jalur hidup sinkronisasi legacy. Dua di antaranya sudah disabled di testGudang: `update_temp_m_t_pembelian_order` dan `update_temp_m_t_penjualan_order`.
- **Trigger stok (7 / 5) semuanya skalar** — `SELECT @barang = inserted.kd_barang … FROM inserted` — jadi satu `INSERT` banyak baris hanya memproses satu baris sembarang, tanpa galat.
- **Tapi korbannya tabel yang memang sudah mati.** Semua trigger stok memanggil `sp_update_stok_akhir` dengan `@divisi` **di-hardcode `'-'`**, dan prosedur itu hanya menulis `m_barang_stok_akhir`. Isi tabel itu sekarang: testGudang 31.773 baris **seluruhnya `kd_divisi = '-'`** (total −4.714.672), grosirPusat 22.703 baris `'-'` + 1 baris nyata. Jadi bug multi-barisnya nyata, tapi tak ada angka yang dipakai Arunika yang berubah karenanya — mesin stok kita membaca `t_opname_stok`/`t_penjualan_detail` langsung.
- **Dua dari trigger stok itu bahkan no-op.** `trig_update_stok_barang_awal` (di `m_barang_divisi`) badannya dikomentari seluruhnya; `trig_update_stok_pembelian` (`FOR DELETE` di `t_pembelian`) menjalankan cursor tapi `EXEC`-nya dikomentari. Jangan berasumsi "ada triggernya berarti ada efeknya" — buka definisinya di `docs/skema/`.
- **`m_barang_stok_akhir` rusak TAPI masih dibaca legacy.** View `mon_g_stok_barang_per_divisi_new` dan fungsi `GetStokPerUkuranNew` + `GetStokBarangPerSupplier` mengambil dari sana. Ketiganya karena itu **haram dipakai dari Arunika**, sejalan dengan aturan "tanpa view/UDF/SP legacy".
- **`trig_insert_penjualan_detail_pegawai` juga skalar**, dan ini satu-satunya trigger skalar yang menulis ke tabel hidup: `INSERT` ke `t_penjualan` memanggil `sp_insert_t_penjualan_detail_pegawai` untuk satu `no_transaksi` saja. Efeknya nol hari ini — `t_penjualan_detail_pegawai` 0 baris di kedua server, karena SP-nya butuh baris `t_absensi` yang cocok — tapi mekanismenya hidup dan akan mulai kehilangan data begitu absensi terisi.

**Aturannya, berlaku untuk SEMUA jalur tulis, bukan cuma Koreksi Stok: satu baris per `execute` ke `t_opname_stok`, `t_penjualan`, `t_penjualan_detail`, `t_pembelian_detail`, dan kedua `*_retur_detail`.** Jangan pernah digabung "supaya efisien".

### testGudang ≠ grosirPusat, dan bedanya struktural

Bukan cuma isi data — DDL-nya memang beda, jadi jalur tulis yang sama bisa berperilaku beda tergantung koneksi aktif:

- **testGudang punya 19 FK yang tak ada di grosirPusat**, semuanya ke `m_divisi`, `m_customer`, `m_jurnal` (mis. `t_penjualan → m_divisi`, `t_opname_stok → m_divisi`).
- **grosirPusat punya 21 FK yang tak ada di testGudang**: 9 ke `m_pegawai`, 9 FK Django (`auth_*`, `django_admin_log` — sisa eksperimen), dan `t_pembelian_detail → t_pembelian` **ON DELETE CASCADE**. Konsekuensinya `DELETE FROM t_pembelian` menghapus detailnya di grosirPusat tapi meninggalkan detail yatim di testGudang.
- **grosirPusat juga tak punya `trig_update_stok_pembelian_detail`**, sedangkan testGudang punya. Dan sebaliknya, **testGudang tak punya `delete_temp` untuk `t_penjualan` maupun `t_penjualan_detail`** (grosirPusat punya): karena keduanya terhubung `ON DELETE CASCADE`, menghapus satu nota di testGudang melenyapkan header+detail tanpa pernah dikabarkan ke pusat — data pusat menyimpang permanen.
- Tak satu pun FK bernama sama yang aturannya berbeda. Perbedaannya selalu "ada" versus "tidak ada".

**Karena itu validasi referensi dilakukan di aplikasi, jangan digantungkan pada FK.** "Kalau INSERT-nya sukses berarti kodenya valid" hanya benar di sebagian server.

### Hak akses: BELUM dikerjakan, dan ini pekerjaan nomor satu

Keempat belas `ServerProfile` memakai login `sa`/`SA`. Artinya Arunika secara teknis mampu `DROP TABLE`, mematikan trigger, dan menjalankan `DELETE FROM m_merk` yang cascade sampai `m_barang` — kemampuan yang tak satu pun fiturnya butuhkan.

Satu-satunya `DELETE` yang Arunika kirim ke server toko adalah `_write_snapshot` di `apps/inventory/services.py`, dan itu ke tabel snapshot bikinan sendiri. Semua `DELETE` lain (`cdc_sync`, `feed_sync`, `hub_pull`, `hub_master`, `hub_sync`) menyasar AMPHOREUS atau replica, bukan server toko. Jadi login berhak-terbatas benar-benar muat:

```sql
CREATE LOGIN arunika_app WITH PASSWORD = '...';
CREATE USER arunika_app FOR LOGIN arunika_app;
ALTER ROLE db_datareader ADD MEMBER arunika_app;
GRANT INSERT, UPDATE ON SCHEMA::dbo TO arunika_app;
GRANT EXECUTE ON SCHEMA::dbo TO arunika_app;
DENY DELETE ON SCHEMA::dbo TO arunika_app;   -- lalu GRANT balik khusus tabel snapshot Arunika
```

Nol perubahan skema, nol risiko ke legacy, dan seluruh bahaya cascade di atas mati di akar alih-alih dijaga kedisiplinan kode. **Aturan turunannya, berlaku sejak sekarang: Arunika TIDAK PERNAH `DELETE` di server toko** — pembatalan memakai kolom `status`/soft-delete. Skrip sekali-pakai di `scripts/` yang butuh hak lebih harus memakai kredensial terpisah secara sadar, bukan mewarisi kuasa penuh aplikasi.

### Belum diperbaiki (jangan dianggap sudah)

- **Kolom `stok` di Master Produk salah.** `list_products()` (`apps/master_data/services.py`, sekitar baris 164) masih mengisi kolom itu dari `m_barang_stok_akhir` — cache `'-'` yang rusak di atas — dengan komentar "must stay live" yang sudah tidak berlaku. Layar lain (`reports.py`, `inventory/services.py`) sudah pindah ke movement engine; yang ini terlewat. Perbaikannya: ambil dari `inv.cek_stok()`/payload kolumnar seperti layar lain, atau buang kolomnya.
- **Login `arunika_app` belum dibuat**; semua profil masih `sa`.

## Gotcha / aturan wajib

- **Empat aturan keras terhadap DB legacy** (alasan & angkanya di § "Database legacy: milik bersama"): (1) tak pernah `DELETE` di server toko — pakai soft-delete; (2) tak pernah `UPDATE` kolom `kd_*` di tabel master — `ON UPDATE CASCADE` ada di 128 dari 129 FK; (3) satu baris per `execute` untuk tabel bertrigger skalar (`t_opname_stok`, `t_penjualan`, `t_penjualan_detail`, `t_pembelian_detail`, `*_retur_detail`); (4) validasi referensi di aplikasi — FK-nya beda antar server dan 116 di antaranya `not_trusted`.
- **Collation CI**: SQL Server anggap `'LYG005'`=`'lyg005'` & abaikan trailing space; dict Python tidak. Semua join key `kd_*` di Python WAJIB `_k()`.
- **Tanpa view/UDF/SP legacy** (PRD §5.3) — query langsung tabel, parameterized. Tiga yang paling menggoda dan paling salah: view `mon_g_stok_barang_per_divisi_new`, fungsi `GetStokPerUkuranNew` dan `GetStokBarangPerSupplier` — ketiganya membaca `m_barang_stok_akhir` yang rusak.
- **Agregasi di SQL**, bukan Python (movement bisa jutaan row).
- **Indexing MANUAL sepenuhnya** (`apps/transactions/indexes.py`). Tombol "Cek Index" per koneksi di Kelola Server (`Admin/Connections/Index.vue`) atau `manage.py ensure_indexes`; `ensure_indexes()` return `(failed, results)` sehingga statusnya terlihat per index. **Pembangunan otomatis DIHAPUS** (2026-08-10) beserta `ensure_indexes_async`, thread latarnya, dan env `POS_AUTO_INDEX`: hook-nya dulu ada di `get_active_profile()`, jadi sekadar MERESOLUSI koneksi aktif menulis DDL ke database legacy milik bersama — tulisan yang tak diminta siapa pun sebagai akibat sebuah pembacaan, dan gagalnya hanya muncul di log server. Menyimpan profil koneksi pun tak lagi memicunya: menekan Simpan di form bukan pernyataan niat mengubah skema server orang lain.
- **.env Windows**: jangan `Set-Content -Encoding utf8` (bikin BOM rusak key pertama & mojibake). Pakai append UTF-8 tanpa BOM.
- **Inertia POST = JSON**: `request.POST` kosong; baca via `apps/core/http.get_data()`.
- **Tutup buku** server aktif lama (mis. Lotim 2024-01-12) → movement besar; sarankan klien tutup buku untuk percepat.
- **Cache TTL bersama** (`core/cache.py`, `_cached`/`invalidate_master_cache`, 600s) dipakai `apps/inventory/services.py` DAN `apps/master_data/services.py` — satu dict, satu invalidasi. JANGAN cache kolom yang berubah tiap transaksi kasir atau query bertingkat search-term (key bisa membengkak). Contoh lamanya `m_barang_stok_akhir` — tapi tabel itu kini bukan soal cache melainkan soal jangan-dibaca-sama-sekali (§ "Database legacy").
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

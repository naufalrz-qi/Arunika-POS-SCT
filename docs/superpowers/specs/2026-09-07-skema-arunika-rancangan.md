# Rancangan Skema Arunika

**Tanggal:** 2026-09-07 · **Branch:** `dev-original` · **Status:** rancangan, belum ada kode

Dokumen ini adalah keluaran Fase 0. Ia punya dua tugas yang sama pentingnya:

1. **Rancangan** — menetapkan bentuk database milik Arunika sendiri, supaya aplikasi ini bisa
   berdiri tanpa server POS legacy mana pun.
2. **Jejak penciptaan mandiri** — mencatat *dari mana* tiap tabel berasal. Perlindungan hak
   cipta yang sebenarnya bukan berkas `LICENSE`, melainkan bukti bahwa karya ini dirancang
   sendiri. Yang membuktikannya adalah dokumen seperti ini, bukan pernyataan.

---

## 1. Metode, dan batas yang tidak dilanggar

Tiap tabel di bawah diturunkan dari **pertanyaan bisnis**: apa yang perlu diketahui sebuah
usaha grosir mainan untuk menjalankan gudang, delapan cabang, dan kasirnya. Bukan dari DDL
legacy.

Skema legacy tetap dibaca — tapi hanya untuk satu tujuan, dan tujuan itu disebutkan di muka:
**interoperabilitas.** Arunika harus tetap bisa membaca data SCT yang sudah ada lewat lapisan
adapter, dan itu mustahil tanpa mengetahui bentuk sumbernya. Membaca antarmuka sebuah sistem
supaya bisa bekerja dengannya adalah tujuan yang sah dan lazim.

**Yang tidak boleh, dan tidak dilakukan:**

- **Menyalin definisi trigger, view, atau stored procedure legacy.** Itu kode sumber, dan kode
  sumber jelas berhak cipta. Nama kolom seperti `kd_barang` bukan risikonya — kata pendek
  fungsional tak bisa dimonopoli siapa pun. Menyalin badan `mon_t_opname_stok` adalah risikonya.
- **Menurunkan rancangan ini dari DDL legacy.** Termasuk lewat jalan pintas teknis:
  `hub_schema.baca_kolom()` membaca `sys.columns` server legacy dan **tidak boleh dipakai di
  sini**. Mesinnya boleh ditiru; sumber kebenarannya tidak.
- **Membawa serta data SCT.** Isi tabel milik SCT, bukan milik penulis dokumen ini.

Pemetaan ke tabel legacy memang dicatat di §7, dan itu memang bagian dari adapter — bukan
asal-usul rancangan. Urutannya penting: rancang dulu dari kebutuhan, petakan kemudian.

---

## 2. Bukti penyaringan: hitung barisnya sebelum membuat tabelnya

Skema legacy punya **157 tabel** di GUDANG. Rancangan ini menargetkan **±25**. Selisihnya bukan
penyederhanaan yang gegabah — ia hasil hitungan.

Dari dump skema di `docs/skema/skema-testGudang.txt`:

| Kelompok | Jumlah tabel |
|---|---|
| **Nol baris** | **73** (46%) |
| 1–40 baris | 40 |
| >40 baris | 44 |

Yang nol baris mencakup seluruh kluster yang menunya ada tapi datanya tidak pernah ada:
`m_aset`, `m_kendaraan`, `t_absensi`, `t_gaji`, `m_jabatan_gaji`, `m_pegawai_komisi`,
`m_barang_sewa`, `m_jenis_perawatan`, `m_surat`, `m_hari_libur_agama`, dan seterusnya. Ini
sejalan dengan temuan yang sudah tercatat di `context.md`: katalog laporan legacy berisi **116
laporan dalam 39 grup**, dan sebagian besarnya menunjuk ke tabel yang nol baris di GUDANG
maupun PUSAT.

> ### ⚠ Jebakan yang hampir menyesatkan penyaringan ini
>
> Dump itu berasal dari **`testGUdang` — server uji, bukan produksi.** Di sana
> `t_biaya_operasional`, `t_pendapatan`, `t_penambahan_kas`, dan `t_mutasi_kas` semuanya **0
> baris** — padahal `apps/transactions/kas.py` jelas menulis ke keempatnya dan layar Kas Harian
> membacanya setiap hari.
>
> **Nol baris di server uji bukan bukti fitur tak terpakai.** Karena itu penyaring yang dipakai
> di sini bukan jumlah baris sendirian, melainkan **irisan dua sumber**: tabel yang dirujuk
> kode aplikasi (terukur: 72 nama, 1.003 rujukan) **dan** jumlah barisnya. Tabel yang dirujuk
> kode tetap masuk walau nol baris di server uji.
>
> **Wajib diulang terhadap GUDANG produksi sebelum rancangan ini dibekukan.** Angka di atas
> adalah sinyal kuat, bukan vonis.

---

## 3. Konvensi penamaan

Ditetapkan sekali di sini supaya konsisten, dan sengaja berbeda dari kebiasaan legacy:

| Aturan | Alasan |
|---|---|
| Tanpa awalan `m_` / `t_` | Master vs transaksi sudah jelas dari namanya sendiri |
| Tanpa awalan `kd_` pada kolom | `barang.kode`, bukan `kd_barang` |
| Nama tabel **tunggal**, huruf kecil | `barang`, `penjualan`, `pergerakan_stok` |
| Baris rincian bersufiks `_baris` | `penjualan_baris`, bukan `_detail` |
| **Kunci pengganti** `id` di tiap tabel | Kode bisnis bisa berubah; kunci tidak boleh |
| Kode bisnis di kolom `kode`, ber-`UNIQUE` | Dipakai manusia, bukan dipakai relasi |
| Waktu: `dibuat_pada`, `diubah_pada` | Selalu ditulis aplikasi, tak pernah trigger |

**Kunci pengganti adalah keputusan yang paling berbeda dari legacy, dan alasannya terukur.**
Kode master legacy memakai blok bergulir `{huruf}{blok}{NNN}` — `MAA999` menggulung ke `MAB000`,
dan `m_merk` sudah sampai `MAB483`. Pola itu memaksa tiap kueri `MAX()` memakai bentuk `LIKE
'X[A-Z][A-Z][0-9][0-9][0-9]'`; salah sedikit, penomorannya bercabang. Dengan `id` sebagai kunci
dan `kode` sekadar label, seluruh kelas masalah itu tidak pernah ada.

---

## 4. Dua konsolidasi besar

Ini inti rancangan. Keduanya bukan selera — keduanya **sudah dibuktikan oleh kode Arunika yang
ada sekarang**, yang selama ini bekerja keras merekonstruksi bentuk yang seharusnya memang ada.

### 4.1 `pergerakan_stok` — satu buku besar, bukan sembilan tabel

Di legacy, pergerakan stok tersebar di sembilan sumber: penjualan, retur penjualan, pembelian,
retur pembelian, mutasi, opname, dan saldo awal. Tak ada satu pun tabel yang menyatakan "stok
berpindah". Akibatnya `_movement_sql` ([apps/inventory/services.py:127](../../../apps/inventory/services.py))
harus menyatukan sembilan blok `UNION ALL` **setiap kali ada yang bertanya soal stok**.

Yang menarik: keluaran kesembilan blok itu sudah **satu bentuk kolom yang seragam**.

```
(kd_divisi, tanggal, no_transaksi, transaksi, kd_barang, debet, kredit, kd_satuan, harga, jenis)
```

Itu definisi sebuah buku besar. Kodenya sudah menemukan bentuk yang benar; skema legacy saja
yang tak pernah menyediakan tempat untuk menyimpannya.

Maka di sini ia jadi **tabel nyata, append-only**:

```
pergerakan_stok
  id            bigint identity   PK
  divisi_id     FK divisi
  barang_id     FK barang
  satuan_id     FK satuan
  tanggal       date
  masuk         decimal(18,3)     -- dalam satuan dasar
  keluar        decimal(18,3)     -- dalam satuan dasar
  harga         decimal(18,2)     -- harga per satuan dasar saat pergerakan
  jenis         varchar(20)       -- saldo_awal | penjualan | retur_jual | pembelian |
                                  -- retur_beli | mutasi_masuk | mutasi_keluar | koreksi
  sumber_tipe   varchar(20)       -- nama dokumen sumber
  sumber_id     bigint            -- id dokumen sumber
  no_rujukan    varchar(30)       -- nomor dokumen, untuk manusia
  dicatat_pada  datetime2
```

Konsekuensinya berlapis, dan semuanya baik:

- **Kueri stok jadi satu seek terindeks**, bukan UNION sembilan arah atas jutaan baris.
- **Saldo awal bukan tabel terpisah** — ia baris `jenis = 'saldo_awal'`. Legacy menyimpannya di
  `m_barang_divisi.stok_awal`, yang membuatnya harus jadi blok UNION tersendiri dengan aturan
  tanggal yang berbeda dari delapan blok lain.
- **Snapshot stok kemungkinan besar tak diperlukan lagi.** `pos_stok_snapshot` dan
  `pos_stok_snapshot_base` ada semata karena agregasi ulang seluruh histori itu mahal. Dengan
  buku besar terindeks, alasannya hilang. **Jangan dibuang sebelum diukur** — buktikan dulu di
  Fase 2, jangan diasumsikan.
- Satuan disimpan **sudah dikonversi ke satuan dasar**, dengan `satuan_id` sebagai catatan
  satuan asal input. Legacy menyimpan qty dalam satuan input dan mengalikannya kembali lewat
  trigger `GetKuantitasSatuanTerkecil` — sumber salah hitung 12× kalau satuan berubah di tengah
  jalan.

### 4.2 `jurnal_kas` — satu buku besar kas, bukan empat tabel

Legacy memisahkan `t_biaya_operasional`, `t_pendapatan`, `t_penambahan_kas`, dan `t_mutasi_kas`.
Tapi `apps/transactions/kas.py` sudah menggerakkan keempatnya dari **satu `SPEC` dict dengan
satu route generik** — dan penambahan dokumen kas keempat terbukti tidak butuh view atau route
baru sama sekali. Kodenya sudah memperlakukan mereka sebagai satu hal.

```
jurnal_kas
  id            bigint identity   PK
  nomor         varchar(30)       UNIQUE
  tanggal       date
  divisi_id     FK divisi
  kas_id        FK kas            -- kas sumber
  kas_tujuan_id FK kas NULL       -- hanya untuk mutasi antar-kas
  jenis         varchar(20)       -- biaya | pendapatan | penambahan | mutasi
  kategori_id   FK kategori_biaya NULL
  jumlah        decimal(18,2)
  keterangan    varchar(200)
  dibuat_oleh   int               -- id user aplikasi
  dibuat_pada   datetime2
```

Sekalian membereskan satu cacat legacy yang sudah tercatat: `t_mutasi_kas.kd_kas_tujuan`
bertipe `varchar(10)`/`JR_KODE_ACCOUNT` — seolah menunjuk akun jurnal — padahal tiga view
legacy membuktikan ia menunjuk `m_kas`. Di sini ia FK ke `kas`, dan tipenya tidak lagi
berbohong.

---

## 5. Daftar tabel

### A. Katalog produk (8)

| Tabel | Isi | Catatan |
|---|---|---|
| `barang` | id, **kode** (unique), nama, keterangan, merek_id, kategori_id, model_id, warna_id, bahan_id, satuan_dasar_id, aktif, dibuat_pada | `kode` diketik operator — tak ada pola yang bisa ditebak (`OCT6555`, `6941057402239B`, `JM14062-MU`, `049`) |
| `barang_satuan` | barang_id, satuan_id, **isi** (konversi ke satuan dasar), harga_jual · PK(barang_id, satuan_id) | `isi`, bukan `jumlah` — namanya menyebutkan artinya |
| `satuan` | id, kode, nama | PCS, LUSIN, DUS |
| `merek` · `kategori` · `model` · `warna` · `bahan` | id, kode, nama, aktif | Lima tabel referensi, satu mesin CRUD |

Lima ini adalah **atribut produk** saja. Tabel referensi legacy lainnya tidak hilang, hanya
pindah ke bagian yang sesuai artinya: `satuan` di atas, `kota` di §B, `kas` di §C,
`kategori_biaya` di §G. Sisa yang belum ditempatkan (`m_negara`, `m_ket`, `m_gudang`, dan
kerabatnya) **belum diputuskan** — hitung barisnya di produksi dulu, jangan dibuang atas dasar
dugaan.

Tetap tabel terpisah, bukan satu tabel `referensi` berkolom `jenis`: FK sungguhan lebih murah
daripada pemeriksaan di aplikasi, dan lima tabel kecil tidak berbiaya apa pun. Konsekuensinya
`master_crud.py` yang sudah menggerakkan 13 tabel dari satu mesin tetap punya bentuk kerja yang
sama — pola itu memang benar, yang salah cuma tabel-tabel yang dilayaninya.

### B. Mitra & wilayah (3)

| Tabel | Isi |
|---|---|
| `pelanggan` | id, kode, nama, alamat, kota, telepon, hp, email, kontak, batas_piutang, diskon_persen, aktif |
| `pemasok` | id, kode, nama, alamat, kota, telepon, hp, email, kontak, bank, rekening, aktif |
| `kota` | id, kode, nama, kode_telepon, negara |
| `negara` · `bank` | id, kode, nama, aktif |

> **Koreksi dari data nyata (Fase 4 irisan 1).** Rancangan awal menyebut
> `pelanggan.tempo_hari`. **Dibuang** setelah `m_customer` diperiksa lewat
> INFORMATION_SCHEMA: 19 kolom, tak satu pun menyimpan tempo pembayaran
> (`limit_kredit` ada, dan itu jadi `batas_piutang`). Memasangnya berarti kolom
> yang selamanya kosong di mode legacy — adapter tak punya apa pun untuk
> diisikan. Tambahkan kalau kelak ada layar yang benar-benar memakainya.

`pemasok` dapat kolom `aktif` — legacy `m_supplier` **tidak punya kolom status sama sekali**
(13 kolom), sehingga pemasok tak bisa dinonaktifkan dan, karena DELETE dilarang, tak bisa
dibatalkan sama sekali.

### C. Organisasi (2)

| Tabel | Isi | Catatan |
|---|---|---|
| `divisi` | id, kode, nama, awalan_nota | GUDANG punya 5 divisi — bukan satu |
| `kas` | id, kode, nama, jenis (tunai/bank) | |

### D. Persediaan (3)

| Tabel | Isi |
|---|---|
| `pergerakan_stok` | §4.1 — buku besar |
| `koreksi_stok` | id, nomor, tanggal, divisi_id, jenis, keterangan, dibuat_oleh, dibuat_pada |
| `koreksi_stok_baris` | id, koreksi_id, barang_id, satuan_id, qty, harga |

Empat jenis koreksi dipertahankan karena memang mencerminkan kebutuhan nyata — hilang, rusak,
lain-lain(+), lain-lain(−) — tapi **arahnya melekat pada jenisnya**, tidak pernah jadi pilihan
terpisah. Menyediakan pilihan arah sendiri berarti mengizinkan "Rusak, stok bertambah". Di
gudang legacy ada 30 baris berstatus Lain-Lain(−) yang keterangannya diketik "RUSAK" — operator
memilih jenis yang salah lalu menuliskan maksudnya sebagai teks bebas. Labelnya harus jelas di
layar.

### E. Penjualan (6)

| Tabel | Isi |
|---|---|
| `penjualan` | id, **nomor** (unique), tanggal, divisi_id, pelanggan_id, jenis_bayar, subtotal, diskon, pajak, total, dibayar, status, dibuat_oleh, dibuat_pada |
| `penjualan_baris` | id, penjualan_id, barang_id, satuan_id, qty, harga, diskon, total |
| `penjualan_retur` + `penjualan_retur_baris` | bentuk sama, merujuk penjualan asal |
| `penjualan_order` + `penjualan_order_baris` | order terbuka; `status` sebagai penanda sungguhan |

Order terbuka ditandai kolom `status` yang berarti apa adanya. Legacy menandainya dengan
`no_transaksi = no_order` karena kolom `status`-nya tidak bisa dipercaya — 16 baris `status=0`
berbanding 38 order terbuka di server yang sama. Order yang salah tanda tidak menimbulkan galat
apa pun; ia cuma lenyap dari daftar.

### F. Pembelian (6)

`pembelian` · `pembelian_baris` · `pembelian_retur` · `pembelian_retur_baris` ·
`pembelian_order` · `pembelian_order_baris` — bentuk cermin dari penjualan, dengan `pemasok_id`
menggantikan `pelanggan_id` dan `harga_beli` menggantikan `harga_jual`.

### G. Kas & keuangan (4)

| Tabel | Isi |
|---|---|
| `jurnal_kas` | §4.2 — buku besar kas |
| `kategori_biaya` | id, kode, nama, aktif |
| `piutang_cicilan` | id, penjualan_id, tanggal, jumlah, kas_id, dibuat_oleh |
| `hutang_cicilan` | id, pembelian_id, tanggal, jumlah, kas_id, dibuat_oleh |

**Total: 32 tabel.** Sedikit di atas target ±25, dan tiap kelebihannya adalah pasangan
header–baris yang memang tak bisa digabung. Dibanding 157 tabel legacy, ini **20%**.

---

## 6. Yang sengaja tidak diwarisi

Tiap baris di bawah adalah keputusan rancangan, dan tiap keputusan punya bukti terukur di repo
ini. Inilah bagian yang membuktikan rancangan ini hasil penilaian sendiri, bukan salinan.

| Cacat legacy | Bukti | Keputusan |
|---|---|---|
| Pergerakan stok tersebar 9 tabel | `_movement_sql` menyatukannya tiap kueri | Satu buku besar (§4.1) |
| Empat tabel kas untuk satu konsep | `kas.py` menggerakkan semuanya dari satu `SPEC` | Satu jurnal (§4.2) |
| Valuasi LIFO — dilanggar PSAK 14; stok opname dinilai Rp 0 | `laba_rugi.py`; legacy makan 171 dtk | Rata-rata tertimbang, biaya eksplisit |
| `t_penjualan_detail` heap tanpa PK | Memaksa CDC dipakai menggantikan replikasi biasa | PK sungguhan di tiap tabel |
| Computed column `total` rusak (ANSI_NULLS/QUOTED_IDENTIFIER salah) | `CREATE INDEX` gagal, error 1935 | Tanpa computed column; total dihitung kueri |
| `m_barang_stok_akhir` cache stok rusak | 22.592 dari 22.703 baris negatif, min −7.187.049 | Tak ada tabel cache stok |
| Trigger skalar menggeser stok satu baris dari INSERT multi-baris | `trig_update_stok_opname_stok`, tanpa galat | **Tanpa trigger.** Aplikasi yang menulis |
| Kode master blok bergulir `MAA999`→`MAB000` | `m_merk` sudah di `MAB483` | Kunci pengganti + kode tampilan |
| `m_supplier` tanpa kolom status | 13 kolom, tak bisa dinonaktifkan | `pemasok.aktif` |
| `tanggal_server` tanpa DEFAULT | `t_penjualan_order`, `t_opname_stok` — aplikasi lama menulisnya sendiri | `dibuat_pada` selalu ditulis aplikasi |
| 73 tabel nol baris | §2 | Tidak dibuat |

**Tanpa trigger sama sekali** adalah keputusan tunggal yang paling berpengaruh. Semua kerusakan
paling sulit dilacak di sistem legacy berasal dari trigger: yang menggeser stok satu baris saja,
yang membuat `cur.rowcount` berbohong sehingga 131 dari 406 baris hilang tanpa jejak, yang
memotong nilai pada 30 karakter, yang menyalakan antrean kirim di server tujuan. Logika yang
tersembunyi di database adalah logika yang tak bisa diuji, tak bisa ditelusuri, dan tak bisa
di-review.

---

## 7. Pemetaan ke legacy (untuk adapter — bukan asal-usul rancangan)

Dibuat **sesudah** §5 rampung, semata supaya `adapter.py` bisa menyajikan bentuk di atas dari
server legacy SCT. Arahnya satu: baru → lama.

| Bentuk Arunika | Sumber legacy |
|---|---|
| `pergerakan_stok` | iTVF berisi UNION 9 blok yang sekarang ada di `_movement_sql` |
| `barang` | `m_barang` + `m_kategori`/`m_merk`/`m_model`/`m_warna` |
| `barang_satuan` | `m_barang_satuan` (`jumlah` → `isi`) |
| `penjualan` / `penjualan_baris` | `t_penjualan` (+`t_penjualan_total`) / `t_penjualan_detail` |
| `jurnal_kas` | UNION dari `t_biaya_operasional`, `t_pendapatan`, `t_penambahan_kas`, `t_mutasi_kas` |
| `pelanggan` · `pemasok` · `divisi` · `kas` | `m_customer` · `m_supplier` · `m_divisi` · `m_kas` |

Semua iTVF dipasang di schema **`arunika.*`**, tidak pernah `dbo.*`: terpisah jelas dari objek
milik vendor, dan bisa dibuang dengan satu `DROP SCHEMA` tanpa meninggalkan jejak di database
SCT.

### 7.1 `penjualan.total` — kolom, bukan tabel samping

`penjualan` di §E memberi `total` sebuah **kolom biasa**. Legacy memisahkannya ke
`t_penjualan_total`: tabel 1:1 dua kolom, PK `(no_transaksi)`, FK ke `t_penjualan` dengan
`ON DELETE CASCADE`. Pemisahan itu tidak membeli apa pun — ia satu nilai per nota, tanpa
kardinalitas yang membenarkan tabel tersendiri.

**Yang membuatnya bukan sekadar kerapian: cakupannya tidak seragam antar-server.** Terukur dari
dump:

| Server | `t_penjualan` | `t_penjualan_total` | Nota tanpa baris total |
|---|---|---|---|
| testGUdang | 52.801 | 52.801 | **0** |
| grosirPusat | 474.587 | 259.250 | **215.337 (45%)** |

Dua tabel yang seharusnya 1:1 ternyata meleset hampir separuh di satu server dan pas di server
lain. Penjelasan yang paling mungkin: nota berawalan lain di database yang sama adalah kiriman
sync dari cabang lain, dan yang menyeberang cuma kepalanya. Kolom `total` yang wajib membuat
seluruh kelas divergensi ini tidak bisa terjadi.

**Adapter tidak boleh berasumsi barisnya ada.** Bentuk yang benar sudah dipakai jalur baca
Arunika hari ini ([apps/transactions/penjualan.py:717](../../../apps/transactions/penjualan.py))
— `LEFT JOIN t_penjualan_total`, lalu hitung sendiri kalau `NULL`:

```python
total = float(h[19]) if h[19] is not None else total_nota(items, dh, diskon_uang, pajak)
```

`INNER JOIN` di sini akan **menghilangkan 45% nota dari laporan di grosirPusat tanpa satu pun
galat** — omzet turun separuh, tak ada yang error. Ada test yang menjaganya
(`test_penjualan.py:220`, kasus `h[19] = None`); adapter wajib punya padanannya.

---

## 7.2 Hasil spike Fase 2 (2026-09-07, server uji lokal)

Dua asumsi berisiko yang bisa menggugurkan rancangan ini sudah diuji terhadap SQL Server 2022
lokal (`testgudang`, `t_penjualan_detail` 569.831 baris). **Keduanya lulus, dan keduanya
memberi hasil yang berlawanan dengan dugaan.**

**Spike 1 — alias `DATABASES` runtime.** `apps/core/db_alias.py` mendaftarkan sebuah
`ServerProfile` sebagai alias, lalu `migrate --database=cabang_SPIKE` membuat 12 tabel di
database MS SQL kosong. Idempoten (run kedua nol migrasi), 3/3 CHECK constraint benar-benar
ditegakkan server, indeks terbentuk. Satu jebakan ditemukan: `connections.configure_settings()`
menolak dict tanpa kunci `default`, jadi yang dikirim harus salinan settings yang ada plus alias
baru.

**Spike 2 — iTVF.** Kekhawatiran rencana adalah predikat tak akan turun ke dalam blok UNION.
Yang terukur justru sebaliknya:

| Varian | sering (1.704 baris) | jarang (2 baris) |
|---|---|---|
| UNION tulis-tangan, parameter apa adanya | 0,1208 dtk | 0,1018 |
| UNION tulis-tangan + `bind_varchar` | **0,0187** | 0,0112 |
| **iTVF, parameter WAJIB** | **0,0192** | 0,0108 |
| iTVF, parameter OPSIONAL (`@p IS NULL OR`) | 0,0967 | 0,0791 |

Dua kesimpulan:

1. **iTVF setara dengan SQL tulis-tangan, bukan lebih lambat.** Ia di-inline
   (`SQL_INLINE_TABLE_VALUED_FUNCTION`, diperiksa lewat `sys.objects`).
2. **Parameter bertipe di tanda tangan fungsi memperbaiki jebakan NVARCHAR dengan
   sendirinya.** Itulah kenapa iTVF menyamai varian `bind_varchar` tanpa memanggilnya: nilainya
   dikonversi sekali di batas fungsi alih-alih meracuni predikat tiap cabang.

**Parameter opsional dilarang** — 5× lebih lambat. Satu badan fungsi tidak bisa melayani banyak
bentuk filter dengan rencana optimal, jadi tiap bentuk filter dapat fungsinya sendiri.

**Verifikasi identitas.** `apps/bisnis/adapter.py` membangkitkan badan fungsi dari
`_movement_sql` sendiri (38 parameter dipetakan otomatis, nol transkripsi tangan). Hasilnya
terhadap server yang sama: **jumlah dan isi baris identik**, dan 18× lebih cepat (0,1186 →
0,0066 dtk). Dicopot bersih tanpa sisa objek maupun schema.

> **Temuan sampingan yang berlaku untuk kode yang jalan HARI INI, di luar lingkup rancangan
> ini:** `bind_varchar` dipakai di `harga_sync`, `penomoran`, `penjualan`, dan `hub_sync` —
> **tapi tidak di `apps/inventory/services.py`**. Artinya filter `kd_barang`/`kd_divisi` pada
> mesin stok mengikat NVARCHAR sekarang juga, dengan ongkos terukur 6,5× di LAN lokal. Efeknya
> akan jauh lebih besar lewat WAN. Sudah ditandai sebagai pekerjaan terpisah.

## 7.3 Penempatan adapter BERUBAH (Fase 4)

§7 semula menempatkan iTVF di schema `arunika` **di dalam database legacy**. Itu sudah
diganti: seluruh objek adapter kini hidup di **database Arunika terpisah** pada instans yang
sama, schema `arunika_src`, membaca legacy lintas-database. **Nol objek dibuat di database
legacy** — dibuktikan dengan membandingkan `sys.objects`/`sys.schemas`/`sys.views` sebelum dan
sesudah: 1217/21/273 → 1217/21/273.

Konsekuensi teknisnya satu, dan ia tidak mengumumkan dirinya: tiap nama tabel legacy di badan
fungsi harus **berkualifikasi database**. Lupa mengualifikasi **tidak ketahuan saat `CREATE
FUNCTION`** — SQL Server menunda resolusi nama sampai fungsinya dipanggil, jadi pemasangannya
sukses dan kegagalannya muncul dari dalam sebuah laporan, entah kapan.
`adapter._kualifikasi()` mengerjakannya dan **berhenti dengan galat** kalau tak mengenali satu
rujukan pun.

Kecepatannya setara. Pengukuran pertama sempat menunjukkan 20× lebih lambat — itu **kompilasi
rencana sekali jalan**, bukan regresi:

| | panggilan pertama | steady state |
|---|---|---|
| legacy langsung (pyodbc) | 0,0098 dtk | 0,0060–0,0091 |
| iTVF lintas-db lewat Django | 0,0062 | **0,0047–0,0064** |
| iTVF lintas-db lewat pyodbc | 0,0350 | 0,0048–0,0075 |

**Dua konvensi parameter hidup berdampingan** sejak `mssql-django` masuk: `core/mssql.cursor()`
memakai `?`, `django.db.connections[alias]` memakai `%s`. Salah pilih gagal jauh dari sebabnya
— galatnya muncul di pemformat SQL debug Django sebagai `TypeError: not all arguments
converted during string formatting`, tanpa menyebut placeholder sama sekali. Karena itu
`adapter.panggil()` menuntut gayanya disebut.

Terpasang dan terverifikasi identik: **12 view** (8 master + `satuan`, `divisi`, `barang`
53.865, `barang_satuan` 54.232) **+ 1 iTVF** `pergerakan_stok`.

## 7.4 Nilai uang nota: memakai fungsi legacy, bukan menulis ulang formulanya

§7.1 menyisakan satu pertanyaan terbuka: 45% nota di `grosirPusat` tak punya baris
`t_penjualan_total`, jadi dari mana nilainya? Jawabannya ternyata **sudah ada di database
legacy**, sebagai fungsi skalar.

| Fungsi | Terukur |
|---|---|
| `dbo.GetTotalPenjualan(no_transaksi)` | **200/200 cocok persis** dengan `t_penjualan_total.total`, di dua server |
| | dan tetap **menjawab** untuk nota yang tak punya baris total (300/300 bernilai > 0) |
| `dbo.GetTotalDiskonPenjualan` | bukan-nol di 300/300 nota berdiskon; mencakup diskon baris **dan** `diskon_uang` |
| `dbo.GetTotalPajakPenjualan` | ada; nol di seluruh data uji |

Maka `penjualan.total` = `COALESCE(t.total, GetTotalPenjualan(...))`, dan hasilnya diverifikasi
di grosirPusat: **300/300 cocok** untuk nota bertotal tersimpan, **300/300 terisi** untuk yang
tidak. Celah 45% itu tertutup tanpa satu baris formula uang ditulis ulang.

**Memanggil fungsi vendor adalah interoperabilitas; menyalin isinya yang tidak boleh.**
Definisinya tidak pernah dibaca untuk menulis modul ini — yang dibaca hanya metadata
(`sys.parameters`, `is_inlineable`) dan keluarannya.

`subtotal` diturunkan, dan identitasnya **dibuktikan bukan diasumsikan**:
`total + diskon − pajak == SUM(qty × harga_jual)`, diuji 50/50 nota berdiskon. `CROSS APPLY`
membuat tiap fungsi dipanggil sekali per baris, jadi `subtotal` tak berbiaya tambahan.

### Ongkosnya, dan kenapa tidak bisa digratiskan

Ketiga fungsi itu `is_inlineable = True` — **tapi compatibility level database legacy 100**,
sementara inlining scalar UDF butuh ≥ 150. Jadi ia jalan baris-per-baris. Terukur atas 5.000
nota:

| | detik | |
|---|---|---|
| kolom tersimpan saja | 0,0153 | |
| fungsi untuk SEMUA baris | 0,6510 | 42,5× |
| `COALESCE` — fungsi hanya saat NULL | 0,2142 | **14,0×** |

Memanggil fungsi atas seluruh 215.337 nota bercelah **melewati timeout 60 detik**. Karena itu
laporan wajib tetap terpaginasi/tersaring; jalur export bervolume besar perlu diukur tersendiri
sebelum dipakai di mode ini.

Menaikkan compatibility level akan menggratiskannya. Itu **mengubah database legacy** dan bisa
menggeser rencana eksekusi aplikasi POS lama — keputusan pemilik server, bukan keputusan kita,
dan di luar batasan "jangan ganggu legacy".

### Keputusan akhir: dibangkitkan dari `_nota_net()`, bukan memanggil UDF

Pendekatan UDF di atas **tidak dipakai**, dan yang membatalkannya bukan teori melainkan dua
pengukuran:

1. **Terlalu lambat untuk agregat.** Agregat menyentuh setiap baris, dan tiap baris memanggil
   dua fungsi tanpa syarat. 2025 setahun: **36,2 dtk**. 2024–2026: **79,6 dtk**.
2. **Angkanya berbeda dari laporan Arunika yang sudah berjalan.** `_nota_net()` tidak memotong
   nominal voucher; UDF legacy memotongnya — **Rp 73.700.000 pada 1.396 nota** di grosirPusat.
   Bentuk baru yang memihak sisi berbeda berarti dua angka omzet untuk data yang sama.

Badan view `penjualan` karena itu **dibangkitkan dari `reports._nota_net()`**
(`adapter.badan_penjualan`), teknik yang sama dengan `pergerakan_stok`. Hasilnya menyelesaikan
keduanya sekaligus:

| | UDF | dibangkitkan dari `_nota_net()` |
|---|---|---|
| 2025 setahun (118.547 nota) | 36,2 dtk, **beda** | **6,59 dtk, IDENTIK** |
| 2024–2026 (264.203 nota) | 79,6 dtk, **beda** | **9,97 dtk, IDENTIK** |
| 2025 harian (365 baris) | — | **6,55 dtk, IDENTIK** |

1,0–1,3× dari jalur lama. Nol panggilan fungsi skalar.

**Perbedaan voucher tidak diselesaikan — ia dipindahkan.** Sesudah ini ia satu perubahan di
dalam `_nota_net()` yang merambat ke KEDUA jalur sekaligus, bukan dua formula yang harus
diingat untuk disamakan. Keputusannya tetap milik pemilik data. Bukti yang tersedia condong ke
"potong": `m_voucher` adalah tabel JENIS (denominasi 25K/50K/100K) **tanpa pelacakan
per-lembar** — tak ada nomor seri, tanggal terbit, atau penanda terpakai. Instrumen prepaid
yang dijual wajib dilacak per lembar; yang tidak dilacak adalah kupon diskon promo, dan diskon
promo mengurangi pendapatan.

> **Dua hal yang ditemukan saat memverifikasinya, keduanya berlaku HARI INI pada laporan yang
> sudah berjalan:**
>
> * **Nota tanpa baris detail tak terlihat di laporan penjualan mana pun.** `_nota_net()`
>   meng-INNER JOIN ke `t_penjualan_detail`, jadi nota berbaris nol lenyap. grosirPusat: 1 nota
>   (`CT2202150001`). Bukan bawaan adapter — perilaku yang sudah ada.
> * **`kd_voucher` adalah kolom WAJIB yang diisi penanda "tanpa voucher".** Tiga baris
>   bernominal 0 (`V1`, `V2`, dan `VAA000` yang bernama `-`) dipakai **473.199 nota** di
>   grosirPusat — hampir seluruhnya. Voucher sungguhan hanya `001`+`002`+`003`, dan jumlah
>   pemakaiannya 534+517+345 = **1.396**, persis angka dampak voucher di atas.
>
>   `VOUCHER BELANJA 300K` dan `500K` juga bernominal 0 dan `status = 1`, jadi kasir bisa
>   memilihnya dan tak ada yang terpotong — tapi **pemakaiannya nol**, jadi ini baris yang
>   disiapkan lalu tak jadi dipakai, bukan kerusakan yang perlu ditindak. (Dokumen ini sempat
>   menyebutnya "bug data"; pemeriksaan pemakaian membatalkan sebutan itu.)

### `penjualan_baris.total`

Kolom `t_penjualan_detail.total` adalah computed column yang definisinya rusak di legacy
(ANSI_NULLS/QUOTED_IDENTIFIER salah, memblokir `CREATE INDEX`, error 1935). **Cacat itu
menghalangi pembuatan indeks, bukan `SELECT`** — nilainya terbaca dan benar. Diperiksa:
selisih `SUM(d.total)` terhadap `GetTotalPenjualan` persis sebesar diskon tingkat-nota
(540.000 − 539.500 = 500 = `diskon_uang`), jadi `d.total` adalah nilai baris **sesudah** diskon
baris.

## 7.5 Laporan ketiga, dan dua temuan yang mengubah bentuknya

Laporan ketiga yang pindah adalah **FMI Penjualan** — yang pertama membaca sampai ke *baris*
nota, bukan cuma kepalanya. Memindahkannya membongkar dua hal yang tak terlihat dari dua
laporan sebelumnya, karena keduanya kebetulan agregat rentang-penuh.

### Temuan 1: `MIN(h.tanggal)` mengunci seluruh riwayat

`arunika_src.penjualan` dibangkitkan dari `_nota_net("1=1")`, jadi **seluruh penyaringan
terjadi di luar view**. Di dalamnya, kolom kepala diambil dengan `MIN(h.tanggal)`,
`MIN(h.kd_customer)`, dan seterusnya — dan `MIN()` adalah agregat, sehingga predikat tanggal di
luar **tidak bisa turun ke bawah `GROUP BY`**. Akibatnya tiap pembacaan mengagregasi 474.595
nota lebih dulu, lalu membuang yang tak diminta:

| | sebelum | sesudah |
|---|---|---|
| `COUNT(*)` sebulan lewat `arunika_src.penjualan` | 1,59 dtk | **0,06 dtk** |
| `COUNT(*)` setahun lewat `arunika_src.penjualan` | 1,79 dtk | **0,46 dtk** |

Ongkosnya dulu **rata**, berapa pun sempit rentangnya — tanda khas pekerjaan yang dikerjakan
lalu dibuang.

Perbaikannya satu baris konseptual: **jadikan kolom kepala kunci `GROUP BY`, bukan `MIN()`.**
Keduanya memulangkan angka yang sama persis karena `no_transaksi` adalah PRIMARY KEY
`t_penjualan` — diperiksa, bukan diasumsikan: 474.595 baris / 474.595 distinct di grosirPusat,
52.801 / 52.801 di testGUdang, dan `PK_m_penjualan` memang berkunci tunggal `no_transaksi`.
Terisolasi, perubahan itu sendiri **1,95 dtk → 0,06 dtk (32×)** dengan hasil identik.

Jalur laporan lama ikut untung, walau tak pernah jadi tujuannya — di sana predikat memang sudah
di dalam subquery, tapi kunci grup yang eksplisit tetap memberi rencana yang lebih baik:

| laporan (legacy, `COUNT(*)`, 1 bulan) | `MIN()` | kunci `GROUP BY` |
|---|---|---|
| Penjualan per Pelanggan | 0,49 dtk | **0,06 dtk** |
| Penjualan per Periode | 0,53 dtk | **0,08 dtk** |

Dibandingkan baris per baris atas lima laporan yang menanam `_nota_net` (Penjualan per
Pelanggan, per Nota, per Periode, Piutang, Klasifikasi Pelanggan), satu bulan dan satu tahun:
**identik**, kecuali satu baris yang berbeda di ULP terakhir float (6.397.048.323,160003 vs
…160001 — urutan penjumlahan, bukan nilai).

`_pembelian_nota()` sengaja dibiarkan memakai bentuk `MIN()`: belum ada view adapter pembelian,
jadi predikatnya selalu sudah di dalam dan perubahan yang sama tak mengubah apa pun.

### Temuan 2: baris nota harus membawa tanggal & divisinya sendiri

Sesudah temuan 1, FMI masih 4,7× jalur legacy. Sebabnya bentuk kuerinya: ia men-join
`penjualan_baris` ke `penjualan` **hanya untuk mendapat satu kolom tanggal** — dan `penjualan`
adalah view yang menghitung seluruh nilai uang per nota. Tabel detail jadi diagregasi dua kali.

`arunika_src.penjualan_baris` karena itu kini membawa `tanggal` dan `divisi_kode` kepalanya.
Itu bukan denormalisasi yang kebablasan: ini bentuk **baca**, dan keduanya satu-satunya alasan
laporan tingkat-baris perlu menyentuh kepalanya sama sekali. `pergerakan_stok` — konsolidasi
besar §4.1 — sudah membawa `tanggal` dan `kd_divisi` di tiap barisnya dengan alasan yang sama.

FMI Penjualan, satu bulan di grosirPusat: **2,58 dtk → 1,11 dtk**.

### Ongkos akhir FMI Penjualan: 2,0×, dan sisanya harga bentuk ini

| | legacy | Arunika |
|---|---|---|
| grosirPusat, 1 bulan (4.583 baris) | 0,55 dtk | 1,11 dtk |
| grosirPusat, 1 tahun (12.328 baris) | 4,02 dtk | 9,05 dtk |
| testGUdang, 1 tahun (9.467 baris) | 0,93 dtk | 1,25 dtk |

Median dari lima putaran, bukan satu tembakan — sebaran satu bulan 0,52–0,61 dtk (legacy) vs
0,98–1,28 dtk (Arunika).

Barisnya identik di kedua server; satu-satunya selisih ada di ULP terakhir float, dan justru
**sisi Arunika yang lebih bersih** (`1452159,65` vs `1452159,6499999997`) karena ia menjumlahkan
kolom tersimpan alih-alih menghitung ulang GHB per baris.

Selisih 2× itu bukan akses data yang lebih mahal. Tiap bagiannya diukur sendiri dan praktis
sama — bagian baris 0,07 vs 0,07 dtk, `barang` + `EXISTS` 0,07 vs 0,03 dtk. Yang 2× adalah
langkah **JOIN + GROUP BY**-nya (0,23 vs 0,10 dtk), karena kunci join dan kunci grup di bentuk
Arunika adalah kolom ber-`RTRIM`, bukan kolom `char` mentah yang punya indeks. Itu harga yang
sudah diterima saat adapter ini dirancang, bukan cacat yang masih bisa dikejar.

### `penjualan_baris.total` menggantikan `_line_net()`, dan itu diuji per baris

Bentuk Arunika tak memulangkan diskon1–4 per baris, jadi ekspresi GHB empat langkah tak bisa
disusun ulang. Ia juga tak perlu: **0 baris berbeda dari 2.990.368 di grosirPusat dan 570.190 di
testGUdang**, selisih `SUM` Rp 0,00 di keduanya. Termasuk 87 baris yang menyimpan diskon sebagai
fraksi dan yang berharga ≤ 0 — justru baris-baris yang membuat `_ghb` harus ada.

Ini menguatkan catatan §7.4 tentang `d.total`, yang sebelumnya hanya diperiksa lewat selisih
total satu nota.

### Lima view referensi barang

`arunika_src.barang` sejak awal memulangkan `merek_kode`, `kategori_kode`, `model_kode`,
`warna_kode`, dan `bahan_kode` — tanpa tempat untuk memulangkannya jadi nama. Kelimanya kini
ada (`merek`, `kategori`, `model_barang`, `warna`, `bahan`), sebentuk dengan `satuan` dan
`negara`, dan ketujuhnya memakai satu pembantu `_referensi()` supaya "aktif = status 1" tak
punya tujuh salinan.

`status` diperiksa di kedua server untuk kelimanya — 1 = aktif, tak ada jebakan `m_biaya` (yang
memakai 2). Jumlah barisnya cocok dengan sumbernya: kategori 862, merek 1.473, model 1.290,
warna 531, bahan 33.

Ini juga bahan untuk §8 butir 2: kesebelas tabel referensi legacy yang diringkas jadi lima
memang berisi, bukan kluster nol-baris.

### Sisa 21 laporan: apa yang sebenarnya menghalangi

Catatan sesi sebelumnya menyebut sisanya "pengulangan mekanis". Itu **tidak akurat**, dan
selisihnya bisa dipetakan: dari 24 spec laporan, 3 sudah pindah dan **18 terhalang entitas yang
belum ada di `arunika_src`**, bukan terhalang penulisan SQL.

| Yang dibutuhkan | Laporan yang menunggunya |
|---|---|
| `t_pembelian` + `t_pembelian_detail` | Pembelian, per Supplier, per Periode, Hutang, Laba HPP |
| `m_userx` | Penjualan per Nota, per User, Laba HPP, Retur Pembelian |
| `m_pegawai` | Penjualan Detail, Retur Penjualan, Shift |
| `t_penjualan_retur` / `t_pembelian_retur` (+ detail) | Retur Penjualan, Retur Pembelian |
| `t_*_order` (+ detail) | Order Penjualan, Order Pembelian |
| `t_biaya_operasional` | Biaya Operasional, Biaya per Kategori |
| `t_piutang_cicilan`, `t_hutang_cicilan` | Piutang, Hutang |
| `t_opname_stok` | Opname |
| `m_barang_promo` (+ detail) | Promo |

Tiga sisanya terhalang **kolom**, bukan tabel — kelasnya lebih murah:

* **Laporan Voucher** — butuh `voucher_kode` di `arunika_src.penjualan`. Kolomnya sudah ada di
  keluaran `_nota_net()`, tinggal dipulangkan.
* **Master Produk** — butuh `ukuran`, `pabrik`, `status_pinjam` di `arunika_src.barang`. Lima
  nama referensinya sudah beres (di atas).
* **Klasifikasi Pelanggan** — kolomnya lengkap, tapi layar itu **bukan `_report_view`**: ia
  kolumnar dengan export dua-sheet sendiri, jadi `inner_arunika` di spec-nya tak akan pernah
  dibaca. Memindahkannya berarti menyentuh `tx.klasifikasi_kolumnar`, bukan menambah satu spec.

## 8. Yang harus diverifikasi sebelum rancangan ini dibekukan

Belum dikerjakan, dan tak boleh dilewati:

1. **Ulangi hitungan baris §2 terhadap GUDANG produksi.** Yang dipakai sekarang server uji, dan
   §2 sudah menunjukkan bagaimana itu bisa menyesatkan.
2. **Pastikan 11 tabel referensi legacy memang cukup diringkas jadi lima.** Hitung barisnya;
   jangan buang yang terpakai.
3. **Ukur apakah `pos_stok_snapshot` masih perlu ada** sesudah buku besar jadi tabel nyata.
   Jangan dibuang atas dasar dugaan.
4. ~~Periksa `t_penjualan_total`.~~ **Selesai — lihat §7.1.**
5. **Tetapkan kebijakan pembatalan.** Legacy tak punya DELETE sama sekali (`ON DELETE CASCADE`
   dari `m_merk`/`m_kategori` menjangkau `m_barang`), jadi pembatalan berupa `status = 0`.
   Rancangan ini perlu menyatakan sikapnya sendiri secara tersurat — dan buku besar append-only
   berarti pembatalan adalah **baris pembalik**, bukan penghapusan.

---

## 9. Hak cipta

Rancangan dan seluruh isi dokumen ini adalah karya Naufal Rifqi Zuhrian, 2026. Lihat
[LICENSE](../../../LICENSE).

Hak cipta itu **tidak mencakup** skema MS SQL legacy yang dirujuk di §7, yang tetap milik
pemiliknya masing-masing, maupun data bisnis apa pun milik perusahaan yang mengoperasikan
perangkat lunak ini.

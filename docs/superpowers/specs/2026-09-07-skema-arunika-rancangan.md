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
| `penjualan` | id, **nomor** (unique), tanggal, divisi_id, pelanggan_id, **voucher_id (NULL-able)**, **kas_id (NULL-able)**, jenis_bayar, subtotal, diskon, pajak, total, dibayar, status, dibuat_oleh, dibuat_pada |
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
| ~~`t_pembelian` + `t_pembelian_detail`~~ | **selesai — lihat §7.8** (per Supplier & per Periode pindah; Pembelian dan Hutang masih menunggu hal lain) |
| ~~`m_userx`~~ | **selesai — §7.11** (per Nota & per User pindah; Laba HPP terhalang diskon 4 slot, Retur Pembelian pindah) |
| ~~`m_pegawai`~~ | **selesai — §7.11** (Retur Penjualan pindah; Penjualan Detail terhalang diskon 4 slot, Shift nol baris) |
| ~~`t_penjualan_retur` / `t_pembelian_retur`~~ | **selesai — §7.12** |
| ~~`t_penjualan_order`~~ | **selesai — §7.12.** `t_pembelian_order` nol baris di kedua server |
| ~~`t_opname_stok`~~ | **selesai — §7.12** |
| ~~`t_biaya_operasional`~~ | **selesai — lihat §7.9** (jadi `jurnal_kas`; Kas Harian ikut, §7.10) |
| `t_piutang_cicilan`, `t_hutang_cicilan` | Piutang (5 baris grosirPusat), Hutang (**nol baris**) |
| ~~`t_opname_stok`~~ | **selesai — §7.12** |
| `m_barang_promo` (+ detail) | Promo (**nol baris di kedua server**) |

Tiga sisanya terhalang **kolom**, bukan tabel — kelasnya lebih murah:

* **Laporan Voucher** — ~~butuh `voucher_kode`~~ **selesai, lihat §7.6.**
* **Master Produk** — SATU-SATUNYA sisa yang terhalang pengetahuan, bukan data. Butuh
  `ukuran`, `pabrik`, `status_pinjam` di `arunika_src.barang`, dan
  ketiganya ternyata **bukan penambahan kolom biasa** — lihat §7.6.
* **Klasifikasi Pelanggan** — ~~bukan `_report_view`~~ **selesai, lihat §7.7.**

## 7.7 Laporan kelima: satu layar, enam kueri, tiga rute

Klasifikasi Pelanggan bukan "satu laporan lagi". Ia tak punya satu `inner` untuk diganti:

| Rute | Kueri |
|---|---|
| Layar (kolumnar) | agregat per pelanggan |
| Export (2 sheet) | agregat yang sama + favorit massal |
| Panel detail (JSON) | profil pelanggan, favorit satu orang, nota terakhir |

Kelimanya pindah sekaligus, dan itu syarat bukan preferensi: memindahkan yang di layar saja tak
memunculkan galat apa pun — ia cuma membuat **layar membaca bentuk baru sementara file Excel
membaca yang lama**, dari dua kueri yang tak pernah dibandingkan siapa pun. Yang paling mudah
tertinggal justru `profil_pelanggan`: di jalur lama ia `SELECT` mentah ke `m_customer` yang
ditulis langsung di dalam view, satu-satunya rujukan legacy layar ini yang tak lewat
`reports.py`.

Gerbangnya juga beda bentuk. `inner_arunika` hanya dibaca `_report_view`, jadi memasangnya di
spec ini akan menyesatkan — ada test yang menahannya. Yang dipakai `_arunika_siap(profile)`:
dua syarat yang tak bergantung laporan (saklar env + profil punya database Arunika).

**`jenis_bayar` akhirnya ada.** Panel detail menampilkan Kredit/Tunai/Lunas, dan di legacy
ketiganya tinggal di `t_penjualan.status` — kolom yang sama yang orang kira penanda batal.
§5.E sudah mencantumkan `jenis_bayar` sejak awal; sekarang ia benar-benar ada, **terpisah** dari
`status`, sehingga nota batal punya tempatnya sendiri dan penjualan kredit tak pernah salah
dilabeli.

### Hasil: identik, dan layar utamanya justru 2× lebih cepat

grosirPusat, rentang dua tahun (2024–2025):

| Kueri | legacy | Arunika | |
|---|---|---|---|
| agregat utama (3.937 baris) | 6,85 dtk | **3,30 dtk** | identik |
| favorit massal (18.588 baris) | 14,62 dtk | 16,24 dtk | identik |
| favorit satu pelanggan | 0,05 dtk | 1,81 dtk | identik |
| nota satu pelanggan | 0,01 dtk | 2,26 dtk | identik |
| profil pelanggan | 0,00 dtk | 0,00 dtk | identik |

testGUdang identik di kelimanya.

> **Jebakan saat memverifikasinya.** Favorit massal semula terbaca "2.595 baris berbeda" padahal
> isinya sama persis. Sebabnya `ORDER BY y.customer, y.rn` — dan **ribuan pelanggan bernama
> kosong**, sehingga urutan antar-mereka tak ditentukan apa pun. Diurut ulang menurut kunci,
> keduanya 18.588 baris identik. Ini cacat jalur lama juga: urutan baris sheet kedua file Excel
> tidak reproducible. Sengaja belum diubah di sini — memperbaikinya berarti mengubah urutan file
> yang sudah dipakai orang, dan itu perubahan tersendiri.

### Temuan 3: `RTRIM` di kolom kunci membuat penyaring kehilangan gunanya

Panel detail 2 dtk per klik, dan sebabnya bukan apa yang kelihatan. Kolom kunci di view
ber-`RTRIM` (`pelanggan_kode` = `RTRIM(kd_customer)`), dan `RTRIM(kolom) = ?` **tidak bisa
dipakai menyeek indeks**. Proyeksi kolom yang persis sama di grosirPusat:

| Penyaring | Waktu | Baris |
|---|---|---|
| `tanggal` satu hari (tak ber-RTRIM) | 0,01 dtk | 299 |
| `divisi_kode` + `tanggal` satu hari | 0,01 dtk | 299 |
| `pelanggan_kode` saja (ber-RTRIM) | **2,72 dtk** | 885 |

Baris terakhir memulangkan **lebih sedikit** baris dari pekerjaan ~270× lebih besar. Artinya
selektivitas seluruhnya datang dari rentang tanggal; kunci ber-`RTRIM` tidak menyumbang apa pun.
Baris kedua tampak baik-baik saja hanya karena tanggalnya yang menyaring, bukan divisinya.

Panel detail memakai rentang pilihan pengguna (bawaan 730 hari), jadi ongkosnya **sebanding
periode, bukan sebanding satu pelanggan** — dan di situlah 2 dtik itu.

### Keputusannya: `RTRIM` pada `char`, tidak pada `varchar`

Pertanyaannya tampak seperti pilihan selera — rapi vs cepat. Ternyata bukan, dan yang
menyelesaikannya satu pemeriksaan tipe kolom. Kunci legacy ada **dua jenis**:

| Jenis | Dipadatkan mesin? | Spasi ekor artinya | Keputusan |
|---|---|---|---|
| `char(n)` | ya | artefak penyimpanan | **RTRIM** |
| `varchar(n)` | tidak pernah | **data yang memang ditulis aplikasi** | jangan RTRIM |

Jadi `RTRIM` pada `varchar` bukan sekadar mahal — ia **salah**: ia membuang karakter yang benar-
benar ada di data. Dan yang mahal itu hanya kolom-kolom `varchar`, karena justru merekalah kunci
utama yang dipakai untuk pencarian titik: `kd_customer`, `no_transaksi`, `kd_barang`.

Bahwa `RTRIM` tetap perlu pada `char` juga terukur, bukan hipotesis: `t_penjualan.kd_voucher`
benar-benar berspasi ekor pada **277.070 dari 474.595 baris** grosirPusat (penanda `V1`/`V2`
yang cuma dua huruf di kolom `char(6)`), dan `m_supplier.kd_supplier` pada 150 dari 517 baris
testGUdang — kasus `'01'` → `'01    '` yang sudah dicatat sejak awal.

Hasilnya:

| | sebelum | sesudah |
|---|---|---|
| penyaring `pelanggan_kode` (proyeksi kolom uang) | 2,72 dtk | **0,03 dtk** |
| panel detail — favorit satu pelanggan | 1,81 dtk | **0,10 dtk** |
| panel detail — nota satu pelanggan | 2,26 dtk | **0,01 dtk** (sama dengan legacy) |

Kelima laporan yang sudah pindah tetap identik di kedua server.

**Aturan lama sengaja seragam, dan itu bukan kelalaian yang diperbaiki — itu pertukaran yang
berubah karena harganya baru terukur.** Alasan aslinya kuat: memutuskan per kolom berarti
menyimpan pengetahuan tentang skema milik vendor, yang bisa berubah. Dua hal menjawabnya:

1. Aturan barunya tetap **aturan**, ditentukan tipe kolom, bukan daftar nama.
2. Pengecualiannya tetap ditulis eksplisit (`master_src.TANPA_RTRIM`, 8 kolom) dan
   **diperiksa terhadap server sungguhan** oleh `manage.py cek_arunika` langkah [5]: kalau
   vendor mengubah salah satu `varchar` jadi `char`, pemeriksa itu yang memberi tahu — bukan
   baris yang diam-diam hilang dari laporan berbulan-bulan kemudian.

Pertahanan lapis terakhirnya sudah ada sejak dulu di tempat yang benar: `_k()` di
`apps/inventory/services.py`, yang memang lahir karena ketidakcocokan kunci seperti itu pernah
menjatuhkan baris tanpa suara.

## 7.6 Laporan keempat, dan satu angka yang memang berbeda

**Laporan Voucher** pindah dengan satu kolom: `voucher_kode` di `arunika_src.penjualan`.
Nilainya sudah dipulangkan `_nota_net()` sejak awal; yang kurang cuma jalur keluarnya. Di sisi
skema mandiri ia jadi `penjualan.voucher_id` yang **NULL-able** — dan itu perbedaan yang
disengaja: di legacy `kd_voucher` kolom **wajib** yang diisi penanda "tanpa voucher"
(`V1`/`V2`/`VAA000`, 473.199 nota). "Tanpa voucher" tidak perlu punya baris master.

Adapter **tidak** memperbaiki penanda itu, dan itu aturan yang lebih besar dari kasus ini:
*adapter menyajikan bentuk lain dari data yang sama, bukan pendapat lain tentang datanya.*
Memetakan penanda ke NULL terasa lebih rapi dan langsung memecah laporan Voucher, yang
menghitung "dipakai" sebagai `kd_voucher <> ''` — ketiga penanda itu memang sudah muncul di
layar hari ini dengan pemakaian ratusan ribu.

### Satu-satunya laporan yang angkanya tidak persis sama

`V1` terhitung **21.257** di jalur lama dan **21.256** di bentuk Arunika. Selisihnya satu nota,
dan nota itu punya nama: **`CT2202150001`** (15 Feb 2022, `kd_voucher = 1`) — satu-satunya nota
grosirPusat yang tak punya baris detail sama sekali, yang sudah dicatat di §7.4.
`arunika_src.penjualan` dibangkitkan dari `_nota_net()` yang meng-INNER JOIN ke detail, jadi ia
tak pernah muncul.

Nota itu **sudah tak terlihat di setiap laporan penjualan yang ada sekarang**. Laporan Voucher
lama satu-satunya yang menghitungnya, karena ia membaca `t_penjualan` langsung. Mengubah INNER
JOIN itu jadi LEFT akan menggeser angka di seluruh laporan penjualan yang sudah terkirim demi
satu nota kosong berumur empat tahun — jadi tidak dilakukan. Kalau nota tanpa baris memang harus
terlihat, tempat memutuskannya `_nota_net()`, sekali, untuk kedua jalur.

Ongkosnya 0,16 → 1,04 dtk. Hitungan "dipakai" sepanjang masa (halaman ini tak punya filter
tanggal), jadi ia menyentuh 474.595 nota lewat view yang menghitung uang — padahal tak satu pun
kolom uang dipakai di sini. Delapan baris, jarang dibuka; diterima.

### Master Produk: tiga kolomnya bukan penambahan biasa

Diukur di `m_barang`, kedua server, bukan dibaca dari nama kolomnya:

| Kolom | Tipe | Terisi | Nilai berbeda | Sebaran |
|---|---|---|---|---|
| `status_pinjam` | `tinyint` | 100% | **1** | `0` di seluruh 53.612 / 53.865 baris |
| `pabrik` | `tinyint` | 100% | 3 | `0` ×49.323, `2` ×4.288, `1` ×1 |
| `ukuran` | `float` | 100% | 14 | `2` ×29.523, `1` ×14.576, `4` ×3.472, … `11` |

Layar Master Produk menampilkan ketiganya sebagai kolom teks berlabel "Ukuran", "Pabrik", dan
"Status Pinjam", dua di antaranya bisa diurut. Yang sebenarnya dilihat pengguna adalah angka
kecil tanpa arti: `status_pinjam` konstan, `pabrik` bendera 0/1/2.

`ukuran` berbeda, dan penyaringan `sys.sql_modules` yang membedakannya: ia dirujuk keluarga
`GetStokPerUkuran`, `GetStokPerUkuranTotal`, `mon_m_barang_stok_per_ukuran` — jadi ia **dimensi
sungguhan** yang dipakai pelaporan stok legacy, bukan kolom terlantar. Empat belas nilai integer
kecil berarti ia **kode kelas ukuran**, bukan ukuran itu sendiri; arti tiap kodenya tidak ada di
skema. `pabrik` dan `status_pinjam` sebaliknya cuma muncul di CRUD/CDC generik dan `v_m_barang`
— tak ada satu pun objek yang memberi mereka arti.

Jadi Master Produk **bukan** "tambah tiga kolom". Ia tiga keputusan terpisah, dan hanya satu
yang bisa diputuskan dari data yang ada:

1. `status_pinjam` — konstan di kedua server, tak dipakai objek mana pun. Kandidat kuat §6.
2. `pabrik` — bendera tanpa arti yang bisa ditemukan. Perlu ditanyakan ke pemilik data, bukan
   ditebak.
3. `ukuran` — dimensi nyata dengan kodifikasi yang tak terdokumentasi. **Harus dipetakan lebih
   dulu**; menyalinnya sebagai `float` ke skema baru berarti mewarisi kode tanpa arti.

## 7.8 Sisi pembelian: cermin, dan itu memang tujuannya

`pembelian` + `pembelian_baris` ada, dan bentuknya sengaja cermin penjualan sampai ke cara
badannya dibangkitkan — `adapter.badan_pembelian` dari `reports._pembelian_nota()`, teknik yang
sama, satu sumber kebenaran untuk formula uang, nol transkripsi. Keduanya kini berbagi satu
penjaga (`_dari_nota`), sehingga "bentuk fungsi sumbernya berubah" dilaporkan sekali untuk
kedua sisi.

Dua laporan langsung pindah, **identik di kedua server**, dengan ongkos 0,7–1,3× — beberapa
justru lebih cepat dari jalur lama:

| | legacy | Arunika |
|---|---|---|
| Pembelian per Periode, setahun (328 baris) | 0,28 dtk | 0,26 dtk |
| Pembelian per Supplier, setahun (178 baris, testGUdang) | 0,14 dtk | 0,14 dtk |

`_pembelian_nota()` ikut mendapat perbaikan `MIN()` → kunci `GROUP BY` yang §7.5 sengaja tunda
(waktu itu belum ada view pembelian, jadi belum ada yang menyaring dari luar). Syaratnya
diperiksa ulang di sisi ini: `no_transaksi` PRIMARY KEY `t_pembelian`, 11.697/11.697 dan
15.730/15.730 distinct. Dibanding baris per baris di jalur legacy atas Pembelian per Supplier,
per Periode, dan Hutang: identik.

### `t_pembelian.status` adalah cara bayar — dan yang membuktikannya bukan tebakan

Kolom ini gampang dibaca sebagai penanda batal (nilainya 0 dan 1). Yang menjawabnya view legacy
`mon_t_pembelian`: ia memanggil `GetConvertStatus(beli.status)` lalu memberinya nama kolom
**"Pembayaran"** — UDF yang sama yang dipakai penjualan (0=Kredit, 1=Tunai, 2=Lunas). Jadi
pembelian mewarisi penggabungan yang persis sama, dan di bentuk baru keduanya dipisah seperti di
`penjualan`. Aturan lamanya berlaku lagi: **arti kolom legacy sering ada di VIEW, bukan di
skema.**

`t_pembelian.kd_jenis` adalah hal lain (JAA000/JAA001 → `m_jenis_bayar`) dan sengaja belum
dipetakan — belum ada laporan yang membutuhkannya.

### Nota tanpa baris detail, sekarang di kedua sisi

`_pembelian_nota()` meng-INNER JOIN ke detail persis seperti `_nota_net()`, jadi nota pembelian
berbaris nol juga tak muncul: **2 di grosirPusat, 3 di testGUdang**. Sama seperti sisi jual, itu
perilaku yang sudah berlaku di seluruh laporan pembelian hari ini, bukan sesuatu yang dibawa
adapter. `manage.py cek_arunika` sekarang memakai satu peta `_DARI_SUBQUERY_NOTA` untuk kedua
entitas, sehingga jumlah barisnya dibandingkan terhadap subquery yang benar-benar membangun
view — bukan terhadap tabel kepala mentah, yang justru akan melaporkan selisih saat view-nya
BENAR.

### Yang masih menghalangi dua laporan pembelian lainnya

* **Hutang** — butuh `t_hutang_cicilan`, yang **nol baris di setiap server yang bisa dijangkau**.
  Memindahkannya berarti membuat entitas untuk tabel yang tak pernah diisi; nilainya nol sampai
  ada yang mencatat pembayaran hutang di sana.
* ~~**Pembelian (tingkat baris)**~~ — **selesai, §7.13.** Layarnya menampilkan **delapan kolom diskon**
  (`diskon_item1–4` + `diskon_total1–4`), sementara §5.E/§5.F merancang **satu** kolom `diskon`.
  Itu bukan kelalaian rancangan, tapi juga bukan keputusan yang boleh diambil diam-diam.

### Berapa dalam rantai diskon 4 slot itu sebenarnya dipakai?

Diukur di kedua server, dan jawabannya bernuansa:

| | baris | diskon1 | diskon2 | diskon3 | diskon4 |
|---|---|---|---|---|---|
| `t_penjualan_detail` (grosirPusat) | 2.990.368 | 49.181 | 0 | 0 | 0 |
| `t_penjualan` (grosirPusat) | 474.595 | 2.302 | 0 | 0 | 0 |
| `t_pembelian_detail` (testGUdang) | 74.236 | 954 | **10** | 0 | 0 |
| `t_pembelian` (testGUdang) | 15.730 | 505 | **2** | **1** | 0 |

Jadi slot kedua dan ketiga **bukan nol** — kecil, tapi ada, dan **10 baris pembelian benar-benar
merantai dua diskon sekaligus**. Meringkas 4 slot jadi 1 karenanya tidak lossless untuk
*rinciannya*.

Yang TIDAK hilang adalah **nilainya**: `t_pembelian_detail.total` sudah sama dengan
`_line_net('harga_beli')` — **0 beda dari 150.920 baris**, identitas yang sama yang sudah
dibuktikan di sisi jual (0 dari 2.990.368 + 570.190). Jadi laporan uang aman; yang butuh
keputusan hanyalah layar yang menampilkan rinciannya.

## 7.9 `jurnal_kas` ada, dan konsolidasi §4.2 terbukti

Empat tabel legacy jadi satu entitas, persis seperti yang §4.2 tetapkan. Dua laporan pindah —
Biaya Operasional dan Biaya per Kategori — **identik di seluruh 9.564 baris** grosirPusat,
termasuk dengan kedua filter kategori, kode kategori asing, dan kata kunci pencarian. Ongkos
0,9–1,3×.

Yang **tidak** ikut: lengan penjualan di `_kas_union()`. Itu proyeksi buku kas harian (penjualan
tunai memang menambah kas), bukan dokumen kas — penjualan sudah punya entitasnya sendiri. Layar
Kas Harian kelak menyatukan keduanya; view ini berisi dokumen saja.

Mutasi kas jadi **satu baris per dokumen**, bukan dua. Dua baris (keluar dari sumber, masuk ke
tujuan) adalah bentuk *buku*, dan itu urusan layar; dokumennya satu, dan `kas_tujuan_kode` yang
menyatakan ke mana. Tipenya pun tak lagi berbohong — di legacy `t_mutasi_kas.kd_kas_tujuan`
bertipe `varchar(10)`/`JR_KODE_ACCOUNT` seolah menunjuk akun jurnal.

`t_penambahan_kas` dan `t_mutasi_kas` **nol baris di kedua server**. Lengannya tetap ada:
`kas.py` menulis ke keduanya, dan §2 sudah mencatat kenapa nol baris di server uji bukan bukti
fitur tak terpakai.

`kategori` hanya bermakna untuk baris `biaya`. Baris pendapatan legacy menunjuk `m_pendapatan` —
tabel lain, satu baris di kedua server — dan sengaja belum dipetakan: memaksanya masuk
`kategori_biaya` berarti menyatakan pendapatan adalah sejenis biaya.

### Baris detail yatim: 118 di testGUdang, nol di grosirPusat

`penjualan_baris` dan `pembelian_baris` meng-INNER JOIN kepalanya (untuk membawa `tanggal` dan
`divisi_kode`, §7.5 temuan 2). Konsekuensinya baru terlihat sekarang: **118 baris
`t_pembelian_detail` di testGUdang tidak punya kepala sama sekali**, jadi ia tak muncul di view.

Itu bukan kehilangan: baris tanpa kepala tak punya tanggal maupun divisi, sehingga ia memang tak
pernah masuk laporan mana pun — termasuk di jalur legacy, yang juga men-join kepalanya.
`cek_arunika` kini memakai acuan "baris detail **yang berkepala**" untuk kedua entitas, sehingga
ia melaporkan keadaan sebenarnya alih-alih menuduh view yang benar.

Bersama nota tanpa baris detail (§7.6, §7.8), ini pasangan cacat referensial yang saling
berlawanan di data yang sama — dan keduanya baru terlihat karena bentuk baru memaksa
membandingkan jumlah baris terhadap acuan yang eksplisit.

## 7.10 Kas Harian: enam lengan jadi tiga, dan kolom Kas yang isinya `-`

Layar kas harian adalah pembaca terberat `jurnal_kas`, dan yang pertama menuntut §4.2 membayar
janjinya. Ia juga bespoke seperti Klasifikasi Pelanggan: tiga rute yang harus pindah bersama —
baris (layar + export), ringkasan (saldo awal pra-rentang, bukan agregat `inner` biasa), dan
**pilihan kas di kotak filter**, yang seperti `profil_pelanggan` dulu adalah `SELECT` mentah ke
`m_kas` di dalam `views.py`, satu-satunya rujukan legacy layar ini yang tak lewat `reports.py`.

Enam `UNION ALL` jadi tiga. Empat lengan dokumen kas runtuh jadi **satu** `SELECT` atas
`jurnal_kas`; yang tersisa mutasi (dibaca dua kali: keluar dari kas sumber, masuk ke kas tujuan)
dan penjualan tunai. Dua baris untuk satu dokumen mutasi memang bentuk **buku**, dan di sinilah
tempatnya — entitasnya menyimpan satu baris per dokumen, layar yang memekarkannya.

Hasilnya identik, dan lebih murah di setiap rentang yang diuji:

| Server | Rentang | Baris | Legacy | Arunika |
|---|---|---:|---:|---:|
| grosirPusat | 2025 setahun | 118.582 | 9,51 dtk | 5,57 dtk (0,6×) |
| grosirPusat | 2024–2025, satu kas | 5.502 | 9,30 dtk | 4,70 dtk (0,5×) |
| grosirPusat | Agustus 2026 | 10 | 7,39 dtk | 5,22 dtk (0,7×) |
| testGUdang | 2024–2026 | 22.330 | 5,18 dtk | 1,08 dtk (0,2×) |
| testGUdang | 2026, satu kas | 3.129 | 4,85 dtk | 0,74 dtk (0,2×) |

Nol beda pada seluruh baris, dan ringkasan (`jml_baris`/`total_masuk`/`total_keluar`/
`saldo_awal`/`saldo_akhir`) identik di kelimanya.

Sebagian besar selisihnya bukan dari lengan kas melainkan dari lengan **penjualan**, diukur
terpisah di testGUdang (2024–2026, hasil sama 22.329 nota / Rp 139.951.316.871):

    _nota_net + predikat kd_kas, di dalam       1,73 dtk
    _nota_net tanpa predikat kd_kas             1,45 dtk
    lewat `arunika_src.penjualan`               0,46 dtk

Bolak-balik dua putaran memberi angka yang sama, jadi ini bukan cache yang hangat. Predikat
`kd_kas` menyumbang sekitar seperlimanya; sisanya bentuk view itu sendiri, dan mekanismenya
belum diisolasi — dicatat sebagai pengukuran, bukan sebagai penjelasan.

### `penjualan.kas_id`: satu kolom yang memang kurang

`arunika_src.penjualan` tak punya cara menyebut kas mana yang menerima uangnya, dan tanpa itu
lengan penjualan tak bisa ditulis sama sekali. §5.E sekarang mencantumkan `kas_id` (NULL-able).
Ini bukan pelunakan §4.2: buku besar kas tetap berisi **dokumen** kas saja, dan penjualan tunai
tetap bukan salah satunya — yang ditambahkan hanya tali yang menyatakan ke kas mana sebuah nota
bermuara, persis seperti `piutang_cicilan.kas_id` yang sudah ada di §5.G sejak awal.

Di legacy kolom itu tidak pernah kosong: `t_penjualan.kd_kas` terisi pada **seluruh** 474.595
baris grosirPusat dan 52.801 testGUdang. Artinya penyaring `kd_kas <> ''` di jalur lama — yang
dimaksudkan memilih "penjualan tunai saja" — tak pernah membuang apa pun, dan kedelapan nota
**kredit** grosirPusat ikut terhitung sebagai uang masuk. Bentuk baru memakai `IS NOT NULL`,
yang di sana menyatakan hal yang sama dan di pemasangan Arunika sungguhan akhirnya punya arti.

### Kolom Kas menampilkan `-` di setiap baris, di sebelas database

Nama kas di jalur lama adalah
`COALESCE(NULLIF(keterangan, ''), NULLIF(kd_index, ''), kd_kas)`. `kd_index` (110/1101) adalah
nomor akun bagan perkiraan dan sengaja tidak diwarisi — dan membuangnya **tidak mengubah satu
baris pun**, karena cabang pertama selalu menang. `m_kas.keterangan` bernilai `'-'` — bukan
kosong — di **seluruh 11 database yang bisa dijangkau**: GUDANG, kedelapan grosir, dan dua
salinan uji lokal.

Konsekuensinya yang perlu diketahui pemilik data: kolom **Kas** menampilkan `-` pada setiap
baris, dan kotak filternya menawarkan dua pilihan yang keduanya berlabel `-` di PUSAT dan
PAGESANGAN, satu-satunya server yang punya dua akun kas. `kd_index` dan `cabang` pun identik
antar akun di sana, jadi **tak ada satu kolom pun di `m_kas` yang membedakan kedua akun itu
selain kodenya sendiri**.

Perilaku itu dipertahankan apa adanya sepanjang perpindahan, dan itu keputusan: migrasinya harus
bisa dibuktikan identik dulu.

**Sesudah itu, labelnya diganti jadi `kode` — selesai, sebagai perubahan tersendiri.** Rantai
`COALESCE` dibuang seluruhnya, bukan dipendekkan: kedua cabang di depannya sudah terbukti tidak
membedakan apa pun, jadi mempertahankannya cuma menyisakan jalur mati yang mengundang orang
menghidupkannya lagi. Keempat tempat yang membentuk label ini pindah bersama — dua jalur baris
(`kas_harian`, `kas_harian_arunika`) dan dua kotak filter (`_opt_kas`, `opsi_kas_arunika`) —
karena kotak pilihan yang isinya berbeda dari kolom Kas di tabel yang sama justru lebih
membingungkan daripada keduanya jelek dengan cara yang sama. Urutannya ikut pindah ke `kode`:
mengurutkan menurut kolom yang seluruh isinya `'-'` bukan urutan sama sekali.

Terukur di testGUdang, setahun 2025: **10.144 baris, kedua jalur identik**, label unik `KAA000`
di keduanya, dan kotak filter memulangkan `KAA000` di kedua jalur. Tak ada angka yang berubah —
`kd_kas` tetap nilai yang dikirim filter, hanya teks yang dibaca manusia yang berubah.

### Yang tidak diperbaiki, dan sebaiknya diputuskan

Buku kas ini punya lengan **penjualan** tapi tidak punya lengan **pembelian**. Terukur di
grosirPusat: 11.673 pembelian tunai (`t_pembelian.status = 1`), semuanya dengan `kd_kas` terisi,
tak satu pun mengurangi kas. Angka ringkasan setahun 2025 memperlihatkan akibatnya telanjang —
`total_masuk` Rp 29,06 miliar berbanding `total_keluar` Rp 10,63 **juta**. `t_piutang_cicilan`
(5 baris) dan `t_hutang_cicilan` (0) juga di luar union, jadi pelunasan piutang tak pernah
tampak sebagai uang masuk.

Keenam lengan itu pilihan kami sendiri, bukan warisan: `t_arus_kas` tidak ada di legacy. Jadi
ini bukan cacat vendor yang diwarisi, melainkan kelalaian yang bisa diperbaiki — tapi
memperbaikinya **mengubah angka sebuah laporan keuangan**, jadi ia keputusan pemilik data dan
sengaja tidak diselipkan ke dalam perpindahan ini.

## 7.11 Aktor: dua entitas, dan satu jebakan yang nyaris terulang

§5 hanya merancang `dibuat_oleh int` — id user aplikasi. Itu tidak cukup, dan laporan yang
membuktikannya Penjualan Detail: ia menampilkan **`petugas` dan `sales` berdampingan**, dari
`m_userx` dan `m_pegawai`. Dua peran berbeda, dan tak ada satu kolom pun di legacy yang
menghubungkan sebuah baris `m_userx` ke sebuah baris `m_pegawai` — menggabungkannya berarti
menebak. Jadi dua entitas: `pengguna` dan `pegawai`.

`dibuat_oleh` tetap seperti rancangan, dan justru karena keduanya tidak sama: yang satu identitas
di server legacy, yang lain akun panel ini. `TautanUser` ada persis supaya yang satu bisa
ditelusuri ke yang lain.

### `status <> 0`, dan grosirPusat yang membuktikannya

Godaannya menulis `status = 1`, mengikuti `m_divisi`. Itu salah, dan bentuknya **persis jebakan
`m_biaya` di §f6e4fc3** — kali ini tertangkap sebelum mendarat:

| | status 1 | status 2 | total | kalau ditulis `= 1` |
|---|---|---|---|---|
| `m_pegawai` testGUdang | 5 | 5 | 10 | 5 mati |
| `m_pegawai` grosirPusat | 4 | **17** | 21 | **17 mati** |
| `m_userx` (keduanya) | semua | — | 11 / 39 | — |

Jawabannya di VIEW, seperti biasa: setiap view yang menyentuh `m_pegawai` menyaring `<> 0` —
`GetAbsenSemuaPegawai`(2), `GetKodeShiftPegawai`, `GetPegawaiTidakMasuk`, `mon_t_awal_kerja`,
`mon_t_hutang_pegawai_detail`, `v_t_pegawai_ganti_shift_detail`, `v_t_kendaraan_tanggung_jawab`.
Jadi 1 dan 2 sama-sama aktif; 0 yang mati. Sesudah dipasang: 10/10 dan 21/21 aktif.

Aturan lama berlaku lagi, dan ini kejadian kedua berturut-turut: **satu server yang seragam tidak
cukup untuk menyimpulkan arti sebuah kolom status.**

### Sales di baris, bukan di kepala

`kd_pegawai` adalah kolom `t_penjualan_detail`, jadi `sales_kode` tinggal di `penjualan_baris`.
Satu nota boleh memuat barang yang dijual orang berbeda; memindahkannya ke kepala akan terlihat
lebih rapi dan diam-diam membuang kemungkinan yang datanya izinkan.

Yang **tidak** diwarisi: dari 23 kolom `m_pegawai` diambil tiga (kode, nama, aktif). Sisanya rekam
kepegawaian — foto, KTP, agama, tempat/tanggal lahir, status kawin, status lembur — dan §6 sudah
menyatakan seluruh cabang HR tidak diwarisi. `m_userx.passwd`/`passweb` tidak diproyeksikan sama
sekali: kolom yang tak ada di view tak bisa bocor lewat view. `m_pegawai.kd_divisi` ditunda sampai
ada laporan yang benar-benar membacanya.

### Penjualan per User, dan label kas yang akhirnya punya arti

Laporan pertama yang membaca entitas aktor. `arunika_src.penjualan` mendapat `pengguna_kode`;
`_nota_net()` sudah memulangkan `kd_user` sejak awal, adapter cuma belum memproyeksikannya.
Identik baris-per-baris di **kedua** server, tiga rentang, dan tak lebih mahal di satu pun:

| | baris | legacy | Arunika |
|---|---|---|---|
| testGUdang setahun | 10.144 | 1,09 dtk | 0,84 dtk |
| testGUdang dua tahun | 19.158 | 1,90 dtk | 1,71 dtk |
| grosirPusat setahun | 117.495 | 3,76 dtk | 3,36 dtk |
| grosirPusat dua tahun | 233.723 | 6,37 dtk | 6,38 dtk |

Label kas (§7.10) ikut diputuskan di sesi yang sama, dan grosirPusat memperlihatkan kenapa itu
bukan kosmetik belaka: server itu punya **dua** akun kas, `KAA000` dan `KAA001`, yang `keterangan`
(`'-'`), `kd_index` (`1101`), dan `cabang` (`MATARAM`) -nya **identik**. Kotak filternya dulu
menawarkan dua pilihan yang keduanya berbunyi `-`. Sekarang keduanya bisa dibedakan.

## 7.12 Empat laporan lagi, dan batas yang akhirnya kelihatan

Penjualan per Nota, Opname, Order Penjualan, dan kedua laporan retur pindah. **Sisa 9 dari 24
spec.** Semua diukur baris-per-baris di kedua server, nol beda.

### Tiga temuan yang berulang, dan satu yang baru

**`MIN(tanggal)` mengunci riwayat — lagi.** §7.5 menemukannya di `_nota_net()`; ia muncul utuh di
`_order_net()`, dan dengan sebab yang persis sama: view dibangkitkan dengan `"1=1"`, jadi seluruh
penyaringan terjadi di luar, dan agregat menghalangi predikat tanggal turun ke bawah `GROUP BY`.
testGUdang sebulan **2,72 → 0,13 dtk (21×)** sesudah kolom kepala jadi kunci `GROUP BY`. Syaratnya
diperiksa dulu: `no_order` unik 40.975/40.975 dan 7.209/7.209.

**Dokumen tanpa baris detail — lagi.** 4 order testGUdang (grosirPusat nol). Jalur legacy pun
meng-INNER JOIN, jadi keempatnya memang tak pernah muncul di laporan mana pun; `penjualan_order`
tinggal didaftarkan di `_DARI_SUBQUERY_NOTA`.

**Kolom `status` yang ternyata klasifikasi — kejadian KETIGA.** Sesudah `m_biaya` dan
`m_pegawai`, giliran `m_jenis_bayar`, dan kali ini yang menggoda justru helper kami sendiri:
`_referensi()` memetakan `aktif = (status = 1)`, yang akan mematikan 3 dari 5 baris di testGUdang
dan 3 dari 6 di grosirPusat. Pengelompokannya identik di kedua server — 1 = TUNAI/BON/DEBIT
(lunas seketika), 2 = BG/CEK/KREDIT (tertunda) — dan tak satu view pun menyaringnya.

> **Aturan, bukan anekdot.** Tiga kali berturut-turut sebuah kolom bernama `status` ternyata bukan
> bendera aktif. Sebelum memetakannya: hitung sebarannya di **kedua** server, lalu cari view yang
> menyaringnya. Kalau tak ada yang menyaring, ia bukan bendera hidup-mati.

**Baru: perbandingan butuh urutan TOTAL.** Retur Penjualan sempat melaporkan 19 baris berbeda.
Bukan data — dua baris dalam satu retur dengan barang dan qty sama tapi harga berbeda, dan
`ORDER BY` pembandingnya tidak menentukan urutan di antara keduanya. Dengan harga + nilai sebagai
tiebreaker: nol. Alat ukur yang urutannya tak total melaporkan selisih yang tidak ada.

### Yang tersisa, dan kenapa bukan soal usaha

| Laporan | Penghalang |
|---|---|
| **Penjualan Detail**, **Laba HPP**, **Pembelian** | **diskon 4 slot** — satu keputusan, tiga laporan |
| Master Produk | kodifikasi `ukuran` (14 nilai) & arti `pabrik` tak ada di skema — §7.6 |
| Order Pembelian, Promo, Hutang, Shift | tabelnya **nol baris di kedua server** |
| Piutang | 5 baris, hanya grosirPusat |

Yang paling berharga di sini koreksi terhadap perkiraan sebelumnya: diskon 4 slot dikira
menghalangi **satu** laporan. Ternyata **tiga**. Penjualan Detail menampilkan kedelapan slot
(DD1–DD4, DT1–DT4) sebagai kolom, dan Laba HPP memakainya ganda — `_disk4("h")` di sisi jual
*dan* `_disk4("pd")` + `ppnbm` di sisi beli. Itu menjadikannya keputusan dengan daya ungkit
tertinggi yang tersisa.

Empat laporan bertabel kosong sengaja **tidak** dibangun. Adapternya bisa ditulis; yang tak bisa
adalah membuktikannya — "identik" atas nol baris lawan nol baris tidak menyatakan apa pun, dan
kode yang tak pernah dijalankan atas satu baris pun rusak diam-diam saat data pertama masuk.
Mereka menunggu **data**, bukan menunggu kode.

## 7.13 Keputusan diskon diambil, dan tiga laporan terakhir ikut pindah

**Sisa 6 dari 24 spec**, dan keenamnya terhalang hal yang bukan kode.

Keputusannya ternyata tak memaksa memilih antara setia dan bersih, karena bentuk
baca dan model native adalah dua hal berbeda:

* **Mode legacy memaparkan keempat slot apa adanya**, jadi Penjualan Detail dan
  Pembelian tidak berubah satu piksel pun dan tetap bisa dibuktikan identik.
* **Model native menyimpan satu `diskon_persen`.**

Yang membuat itu aman bukan selera melainkan pengukuran di kedua server: sisi
jual **tak pernah** memakai lebih dari satu slot — diskon2, 3, dan 4 nol pada
seluruh 570.190 + 2.990.368 baris detail dan 52.801 + 474.595 kepala nota.
Rantai dua diskon hanya ada di sisi beli (10 baris detail + 2 kepala, semuanya
testGUdang), dan baris-baris itu **tetap terbaca utuh** karena mode legacy
membaca kolom aslinya. Yang dibatasi hanya data yang kelak ditulis Arunika
sendiri — dan di sana belum ada satu baris pun.

### Tarif bukan rupiah, dan itu dua kali nyaris salah

`pembelian.pajak` adalah pajak dalam RUPIAH (hasil `_pembelian_nota()`),
sementara layar Pembelian menampilkan **tarifnya**. Hal yang sama muncul lagi di
Laba HPP, yang menyusun harga net dari tarif pajak nota. Keduanya kini kolom
terpisah di view — `pajak` dan `pajak_persen` — bukan satu nama yang artinya
bergantung pembacanya.

### Satu ULP yang tidak bisa dihilangkan tanpa menyentuh jalur lama

Laba HPP identik pada **15 dari 16 kolom, bit per bit**. `margin` berbeda pada
**65 dari 139.794 baris, maksimum 8,88e-16** — satu ULP double. Seluruh
masukannya bit-identik; yang berbeda urutan evaluasi ekspresi tak-dibulatkan di
dalam `ROUND`. Tipe kolom kedua jalur diperiksa, sama-sama `float`, jadi ini
bukan salah pemetaan tipe. Tak sampai ke pengguna: kolomnya `format: "persen"`.
Obatnya membulatkan lewat `decimal` di **kedua** jalur — perubahan pada jalur
lama juga, jadi sengaja bukan bagian migrasi.

### Alat ukurnya sendiri, dua kali

Perbandingan baris-per-baris butuh urutan **total**, dan SQL `ORDER BY` tidak
bisa memberikannya: collation SQL Server mengabaikan spasi ekor, sehingga
`'SEPEDA X'` dan `'SEPEDA X '` seri dan tertukar bebas. Ditambah kolom yang
tidak masuk `ORDER BY` (satuan), itu melaporkan 19 lalu 8 selisih yang seluruhnya
tidak ada. Pembandingnya sekarang mengurutkan di **Python** atas tuple lengkap —
menghapus seluruh kelas positif-palsu sekaligus, alih-alih menambah tiebreaker
tiap kali tertipu.

### Sisa enam, dan tak satu pun soal usaha

| Laporan | Penghalang |
|---|---|
| Master Produk | kodifikasi `ukuran` (14 nilai) & arti `pabrik` tak ada di skema — §7.6 |
| Order Pembelian, Promo, Hutang, Shift | tabelnya **nol baris di kedua server** |
| Piutang | 5 baris, hanya grosirPusat |

#### Koreksi, 2026-09-20

Daftar di atas sudah tertinggal dari kode, dan itu terungkap saat seseorang bertanya
"laporan mana yang belum pindah?" — tak ada satu pun tempat di repo yang bisa
menjawabnya. Dua hal yang perlu diluruskan:

1. **Master Produk sudah pindah.** `rpt.master_produk_arunika` terpasang di
   `_MASTER_PRODUK`; tiga kolom bermasalah dipapar apa adanya dan `status_pinjam`
   dipulangkan konstan 0. Arti `ukuran` dan `pabrik` tetap pertanyaan terbuka, tapi ia
   bukan lagi penghalang laporannya.
2. **Tiga laporan lain tak pernah tercatat di sini sama sekali**, dan penghalangnya
   berbeda jenis dari yang di tabel — bukan menunggu data, melainkan belum punya jalur:

   | Laporan | Penghalang |
   |---|---|
   | Nota Tanggal Mundur | **sengaja**: bentuk Arunika tak menyimpan cap waktu server asal. `dibuat_pada` adalah waktu baris masuk Arunika, bukan jam server legacy — memberinya kembaran berarti memajang angka yang terlihat benar dan tidak benar |
   | Transaksi Barang | UNION 9 tabel gerakan stok legacy (`_TX_BLOCKS`); entitas `pergerakan_stok` ada di rancangan (§4.1) tapi belum punya adapter baca laporan |
   | Laba Rugi | modul tersendiri (`apps/transactions/laba_rugi.py`), bukan spec `reports.py`, dan ikut menambal `t_piutang_cicilan` — lihat §7.10 |

   Seluruh keluarga stok (Stok Akhir, Stok per Divisi, Mutasi Stok, Stok Awal, Barang
   Histori, FMI Stok) juga masih legacy penuh: semuanya lewat mesin stok
   `apps/inventory/services.py`, jadi tak punya `inner` untuk ditukar. §8.3 sudah
   menyimpulkan `pos_stok_snapshot` "masih perlu, dan bukan sedikit"; memindahkan
   keluarga itu proyek tersendiri, bukan satu spec.

Peta yang dibaca manusia sekarang tinggal di `KESIAPAN-FITUR.md` § "Kembaran Arunika
per laporan", dan dijaga test supaya tidak ikut basi seperti tabel di atas.

#### Catatan, 2026-09-21: sumber `penjualan.dibayar` akhirnya ada

`dibayar` sudah berdiri di §5.E sejak awal dan tetap kosong sepanjang itu, karena
legacy tak punya sumbernya: `t_penjualan` tak punya kolom uang-diterima, jadi
`adapter.badan_penjualan` tak bisa memulangkan apa pun untuknya, dan `muat._rencana`
— yang digerakkan kolom VIEW, bukan field model — memang tak pernah menulisnya.

Sekarang sumbernya ada: layar kasir mencatat uang yang diterima ke
`apps.core.models.BayarNota` di pangkal (kunci `profile` + `no_transaksi`, karena
nomor nota bertabrakan antar server). Yang **belum** dikerjakan, dan disengaja:

- `dibayar` **tidak** ditambahkan ke `master_src._MASTER["penjualan"]["kolom"]`.
  Menambahkannya memaksa badan `legacy` mengisi konstanta — nol atau NULL untuk
  setiap baris — dan itu persis kategori "angka yang terlihat benar dan tidak benar"
  yang membuat Nota Tanggal Mundur ditolak di atas. Nol di kolom uang-diterima tak
  bisa dibedakan dari "memang dibayar nol".
- `kembalian` tidak ditambahkan sama sekali. Ia `dibayar - total`, dan menurunkannya
  dari total versi server itulah yang membuat angkanya tak bisa dikarang dari luar.

Yang tersisa saat jalur tulis Arunika benar-benar dibangun (§8.4 butir 3-4 masih
terbuka): isi `Penjualan.dibayar` dari `BayarNota` di jalur tulis itu, bukan lewat
adapter — adapter membaca legacy, dan angka ini tak pernah ada di sana.

## 8. Yang harus diverifikasi sebelum rancangan ini dibekukan

1. ~~Ulangi hitungan baris §2 terhadap GUDANG produksi.~~ **Selesai — §8.1.**
2. ~~Pastikan 11 tabel referensi legacy cukup diringkas jadi lima.~~ **Selesai — §8.2.**
3. ~~Ukur apakah `pos_stok_snapshot` masih perlu ada.~~ **Selesai — §8.3.**
4. ~~Periksa `t_penjualan_total`.~~ **Selesai — lihat §7.1.**
5. **Kebijakan pembatalan** — §8.4, dinyatakan; belum ada jalur tulis yang mewujudkannya.

### 8.1 testGUdang memang mewakili GUDANG, dan grosirPusat memang bukan

Dihitung dari `sys.dm_db_partition_stats` — metadata, bukan `COUNT(*)`: hampir gratis dan tak
mengunci apa pun di server yang sedang dipakai orang.

| tabel | testGUdang | grosirPusat | **GUDANG (produksi)** |
|---|---|---|---|
| `m_barang` | 53.710 | 53.457 | **55.223** |
| `t_penjualan` | 52.801 | 474.595 | **56.711** |
| `t_penjualan_detail` | 569.831 | 2.990.368 | **600.825** |
| `t_pembelian_detail` | 74.210 | 150.920 | **79.906** |
| `t_penjualan_order` | 40.975 | 7.209 | **44.568** |
| `t_penjualan_retur` | 4.242 | 57 | **4.472** |
| `t_pembelian_retur` | 759 | 2.935 | **777** |
| `t_biaya_operasional` | 0 | 9.564 | **0** |
| `t_mutasi_stok` | 650 | 0 | **650** |
| `m_supplier` | 517 | 3 | **523** |
| `m_userx`/`m_pegawai`/`m_divisi`/`m_kas` | 11/10/5/1 | 39/21/1/2 | **11/10/5/1** |

**testGUdang adalah salinan GUDANG yang masih segar** — tiap tabel dalam ~7% dari produksi, dan
tabel kecilnya identik baris per baris. Hitungan §2 karena itu sah.

Yang lebih berguna justru kolom tengahnya: **grosirPusat bukan "GUDANG yang lebih besar",
melainkan bentuk yang berbeda.** Ia punya 8,4× penjualan tapi 6× LEBIH SEDIKIT order; `m_supplier`
3 baris lawan 523 (aturan "gudang yang membeli", terkonfirmasi); dan dua tabel yang **nol di satu
sisi dan ribuan di sisi lain** — `t_biaya_operasional` nol di GUDANG, `t_mutasi_stok` nol di
grosirPusat. Konsekuensi langsung: `jurnal_kas` hanya pernah teruji sungguhan di grosirPusat, dan
mutasi stok hanya di gudang. Menguji di keduanya bukan kehati-hatian berlebih — masing-masing
menutup lubang yang tak ditutup yang lain.

### 8.2 Tiga belas tabel referensi, semuanya sudah punya entitas — dan dua yang tak pernah ada

| tabel | baris (testGUdang / grosirPusat) | dipakai `m_barang` |
|---|---|---|
| `m_kategori` | 862 / 862 | **256 / 254** |
| `m_merk` | 1.475 / 1.473 | 1.409 / 1.407 |
| `m_model` | 1.290 / 1.290 | **118 / 117** |
| `m_warna` | 531 / 531 | 502 / 502 |
| `m_jenis_bahan` | 33 / 33 | 32 / 32 |
| `m_satuan`, `m_kota`, `m_negara`, `m_bank`, `m_biaya`, `m_voucher`, `m_kas`, `m_jenis_bayar` | 18/29/6/3/38/2/1/5 — 18/29/6/6/32/8/2/6 | — |

**"11 diringkas jadi 5" ternyata salah cara menyebutnya.** Tak ada yang diringkas: lima itu
*atribut produk* — satu-satunya yang dirujuk `m_barang` — dan sisanya **dipindahkan** ke bagian
yang sesuai artinya, persis seperti §5.A menuliskannya. Ketiga belasnya kini punya entitas.

**`m_ket` dan `m_gudang` TIDAK ADA di kedua server.** §5.A menyebut keduanya "belum ditempatkan";
ternyata tak ada yang perlu ditempatkan. Pertanyaan itu tertutup.

**Sisanya temuan kebersihan data, bukan rancangan:** `m_kategori` punya 862 baris tapi hanya 256
dipakai sebuah barang; `m_model` 1.290 lawan 118. Rancangan tak berubah karenanya — tapi layar
Kelola Referensi menawarkan ribuan pilihan yang tak satu pun barang memakainya.

### 8.3 `pos_stok_snapshot` masih perlu, dan bukan sedikit

Agregasi stok yang sama dijalankan dengan dan tanpa snapshot, lalu keduanya dibandingkan:

| | kunci | **net berbeda** | kotor berbeda | tanpa → dengan |
|---|---|---|---|---|
| testGUdang | 8.412 / 33.161 | **0** | 30.234 | 3,84 → 0,05 dtk (**71×**) |
| grosirPusat | 12.391 / 13.427 | **0** | 6.388 | 2,19 → 0,10 dtk (**23×**) |

**Saldo bersih identik di setiap kunci di kedua server**, dengan ongkos 23–71× lebih murah. Jadi:
dipertahankan.

Angka kedua yang perlu diketahui, dan sebelumnya tak tertulis di mana pun: **arus KOTOR sengaja
tidak direproduksi.** Snapshot meringkas riwayat sebelum tanggalnya jadi satu saldo awal, sehingga
`masuk`/`keluar` yang seluruhnya jatuh sebelum itu lenyap — dan baris yang netnya nol hilang sama
sekali dari hasil (30.234 kunci di testGUdang). Untuk saldo itu benar; untuk laporan yang
menanyakan *berapa yang masuk dan keluar*, tidak. **Pembaca semacam itu wajib
`use_snapshot=False`.**

Pertanyaan aslinya — apakah snapshot mubazir sesudah buku besar jadi tabel nyata — **belum bisa
dijawab**, dan bukan karena kelalaian: di mode legacy `pergerakan_stok` masih iTVF di atas UNION
sembilan sumber yang sama. Ia baru bisa diukur ulang ketika Arunika memegang baris sungguhan.

### 8.4 Kebijakan pembatalan

Dinyatakan sekarang, supaya tidak diputuskan diam-diam oleh jalur tulis pertama yang
membutuhkannya:

1. **Tabel referensi & master dibatalkan dengan `aktif = False`,** tidak pernah `DELETE`.
   Alasannya bukan meniru legacy melainkan sama dengan alasan legacy: baris transaksi menunjuk ke
   sana. Bedanya, di sini `aktif` ada di **setiap** tabel referensi — termasuk `pemasok`, yang di
   legacy tak punya kolom status sama sekali sehingga pemasok salah ketik tak bisa dibatalkan
   dengan cara apa pun.
2. **Dokumen transaksi dibatalkan dengan `status`,** dan `status` hanya berarti itu. Ia TERPISAH
   dari `jenis_bayar` — penggabungan keduanya di `t_penjualan.status` adalah cacat legacy yang
   §7.7 bongkar, dan yang membuat setiap penjualan kredit terbaca sebagai nota batal.
3. **`pergerakan_stok` append-only: pembatalan adalah BARIS PEMBALIK, bukan penghapusan.** Buku
   besar yang barisnya bisa hilang bukan buku besar. Membatalkan dokumen berarti menulis
   pergerakan berlawanan yang menunjuk dokumen asalnya.
4. **`DELETE` tidak dipakai di mana pun.** Bukan karena `ON DELETE CASCADE` seperti di legacy — FK
   di sini `PROTECT`, jadi cascade itu tak bisa terjadi — melainkan karena riwayat yang bisa
   dihapus tak bisa diaudit.

Butir 3 dan 4 **belum ada jalur tulis yang mewujudkannya**; keduanya kontrak untuk kode yang akan
menulis ke tabel Arunika sendiri, dan di sana belum ada satu baris pun.

---

## 9. Hak cipta

Rancangan dan seluruh isi dokumen ini adalah karya Naufal Rifqi Zuhrian, 2026. Lihat
[LICENSE](../../../LICENSE).

Hak cipta itu **tidak mencakup** skema MS SQL legacy yang dirujuk di §7, yang tetap milik
pemiliknya masing-masing, maupun data bisnis apa pun milik perusahaan yang mengoperasikan
perangkat lunak ini.

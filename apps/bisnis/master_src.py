"""Adapter master: satu bentuk baca, dua sumber, nol objek di database legacy.

## Di mana objeknya tinggal

Seluruh VIEW di sini dibuat di **database Arunika**, bukan di database legacy.
Yang bermode legacy membacanya lintas-database (`[SOLID_SIM].[dbo].[m_customer]`);
yang berdiri sendiri membacanya dari tabelnya sendiri. Database legacy tidak
menerima satu objek pun -- bukan view, bukan schema, bukan tabel.

Terukur di server uji lokal, kueri yang sama dari database berbeda vs dari dalam
database legacy sendiri: **0,0232 vs 0,0181 dtk, 1.597 baris identik.** Selisih
itu ongkos tetap pada kueri kecil, dan harganya murah untuk tidak menyentuh apa
pun milik vendor.

> **Catatan yang perlu diketahui:** aplikasi ini SUDAH membuat dua tabel di dalam
> database legacy lewat jalur lain -- `pos_stok_snapshot` dan
> `pos_stok_snapshot_base` (`apps/inventory/services._ensure_snapshot_table`,
> masing-masing 8.412 dan 8.800 baris di server uji). Itu mendahului modul ini
> dan tidak ditambah olehnya. Kalau suatu hari "nol objek di legacy" mau ditegakkan
> sungguhan, keduanya yang harus pindah -- dan dokumen rancangan sudah
> mempertanyakan apakah snapshot masih perlu ada setelah `pergerakan_stok`
> menjadi tabel nyata.

## Kenapa VIEW, bukan iTVF

Fase 3 memilih iTVF untuk pergerakan stok karena parameter bertipe di tanda
tangannya menjaga index seek pada tabel ratusan ribu baris. Master tidak
menghadapi masalah itu: `m_supplier` 517 baris, `m_customer` 9.482, `m_kota` 29,
`m_kas` 1. VIEW polos cukup, dan jauh lebih mudah dibaca maupun dibuang.

Aturannya satu kalimat: **iTVF hanya ketika filter berparameter harus menembus
tabel besar; selebihnya VIEW.**

## Kenapa bentuknya memakai KODE, bukan id

Tabel Arunika berkunci `id` (kunci pengganti) supaya kode yang salah ketik bisa
diperbaiki tanpa memutus baris transaksi yang menunjuknya. Tapi sebuah view di
atas data legacy **tidak bisa mengarang id** -- di sana yang ada hanya
`kd_customer`, `kd_kota`, dan seterusnya.

Karena itu bentuk BACA memakai kode bisnis untuk tiap rujukan antar-entitas
(`kota_kode`, bukan `kota_id`). Kunci pengganti tetap ada, tapi ia urusan dalam
tabel Arunika sendiri -- bukan bagian dari kontrak yang dilihat pembaca. Itulah
sebabnya view untuk mode Arunika pun ada: ia menjoin `kota` untuk memunculkan
`kota_kode`, sehingga kedua mode menyajikan kolom yang persis sama.

## RTRIM: pada `char`, TIDAK pada `varchar`

Kunci legacy ada dua jenis, dan perlakuannya berbeda karena artinya berbeda:

* **`char(n)`** dipadatkan spasi oleh mesin. Kode pemasok yang sebenarnya `'01'`
  tersimpan sebagai `'01    '`; SQL Server menganggap keduanya sama, kunci dict
  Python tidak. Kolom seperti ini **di-RTRIM**. Bukan hipotesis: di grosirPusat
  `t_penjualan.kd_voucher` benar-benar berspasi ekor pada **277.070 dari 474.595
  baris** (penanda `V1`/`V2` yang cuma 2 huruf di kolom `char(6)`), dan
  `m_supplier.kd_supplier` pada 150 dari 517 baris di testGUdang.
* **`varchar(n)`** tidak pernah dipadatkan mesin. Spasi ekor di sana adalah DATA
  yang memang ditulis aplikasi, dan membuangnya berarti mengubah data. Kolom
  seperti ini **tidak di-RTRIM**: `kd_customer`, `no_transaksi`, `kd_barang`,
  `kd_telp`.

**Modul ini semula memakai aturan seragam: RTRIM semua kolom kode, termasuk yang
`varchar`.** Alasannya masuk akal -- memutuskan per kolom berarti menyimpan
pengetahuan tentang skema yang bukan milik kita. Yang membatalkannya bukan selera
melainkan pengukuran: `RTRIM(kolom) = ?` **tidak bisa dipakai menyeek indeks**,
jadi tiap penyaring berbasis kode berhenti menyaring dan berubah jadi pemindaian.
Proyeksi kolom yang persis sama di grosirPusat, lewat `arunika_src.penjualan`:

    penyaring `tanggal` satu hari (tak ber-RTRIM)    0,01 dtk     299 baris
    penyaring `pelanggan_kode` ber-RTRIM             2,72 dtk     885 baris
    penyaring `pelanggan_kode` tanpa RTRIM           0,03 dtk     885 baris

Yang tengah memulangkan LEBIH SEDIKIT baris dari pekerjaan ratusan kali lebih
besar. Panel detail Klasifikasi Pelanggan turun **1,81 -> 0,10 dtk** (favorit)
dan **2,26 -> 0,01 dtk** (nota) hanya karena baris ketiga.

Aturan barunya tetap aturan, bukan daftar: ia ditentukan TIPE kolom, bukan nama.
Dan kalau vendor suatu hari mengubah sebuah `varchar` jadi `char`, pertahanannya
sudah ada di tempat yang benar -- `_k()` di `apps/inventory/services.py`, yang
memang lahir karena ketidakcocokan kunci seperti itu pernah menjatuhkan baris
tanpa suara.

Predikat join **tidak** di-RTRIM, dan itu tak berubah: perbandingan `char` di SQL
Server sudah mengabaikan spasi ekor, sementara membungkus kolom dengan fungsi
justru membatalkan index seek -- persis masalah yang baru saja diukur di atas.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from __future__ import annotations

SKEMA = "arunika_src"


def _badan_penjualan(db_legacy: str) -> str:
    """Badan view `penjualan`, dibangkitkan dari `reports._nota_net()`.

    Impor lokal supaya `master_src` tidak menarik seluruh modul laporan saat
    diimpor -- dan supaya tak ada lingkaran impor.
    """
    from apps.bisnis import adapter

    return adapter.badan_penjualan(db_legacy)


def _badan_pembelian(db_legacy: str) -> str:
    """Badan view `pembelian`, dibangkitkan dari `reports._pembelian_nota()`."""
    from apps.bisnis import adapter

    return adapter.badan_pembelian(db_legacy)


def _case_jenis_biaya(kolom: str) -> str:
    """Token jenis biaya, dari satu sumber (`reports.JENIS_BIAYA`).

    Token, bukan label: bentuk baca memulangkan nilai yang stabil, dan teks
    layar dibentuk pembacanya -- sama seperti `status` dan `jenis_bayar`.

    Impor lokal: `master_src` tak boleh menarik modul laporan saat diimpor.
    """
    from apps.transactions import reports

    return reports.case_jenis_biaya(kolom, label=False)


def _referensi(tabel_legacy: str, kunci: str, tabel: str) -> dict:
    """Entitas referensi berbentuk kode + nama + bisa dinonaktifkan.

    Tujuh entri di bawah berbentuk persis begini. Ditulis sekali supaya
    "aktif = status 1" tidak punya tujuh salinan yang bisa menyimpang satu per
    satu -- tapi PEMAKAIANNYA tetap keputusan per tabel, bukan bawaan: nilai
    `status` diperiksa di grosirPusat dan testGUdang untuk ketujuhnya, tidak
    disimpulkan dari tabel sebelahnya. `m_biaya` membuktikan kenapa itu perlu:
    seluruh 38 barisnya bernilai **2**, jadi ia sengaja tidak memakai ini.
    """
    return {
        "kolom": ["kode", "nama", "aktif"],
        "legacy": f"SELECT RTRIM({kunci}), nama, CASE WHEN status = 1 THEN 1 ELSE 0 END "
                  f"FROM {{db}}.dbo.{tabel_legacy}",
        "arunika": f"SELECT kode, nama, CAST(aktif AS int) FROM dbo.{tabel}",
    }

# Tiap entri: kolom bentuk baca + satu badan SELECT per mode.
#
# Daftar kolom ditulis di `CREATE VIEW ... (kolom)` sehingga nama kolom di dalam
# badan SELECT tidak perlu dicocokkan satu per satu -- yang harus sama hanya
# URUTAN dan jumlahnya. Itu sengaja: satu tempat yang menentukan bentuk.
_MASTER: dict[str, dict] = {
    "negara": _referensi("m_negara", "kd_negara", "negara"),
    "kota": {
        "kolom": ["kode", "nama", "kode_telepon", "negara_kode", "aktif"],
        "legacy": "SELECT RTRIM(kd_kota), nama, kd_telp, RTRIM(kd_negara), "
                  "CASE WHEN status = 1 THEN 1 ELSE 0 END FROM {db}.dbo.m_kota",
        "arunika": "SELECT k.kode, k.nama, k.kode_telepon, n.kode, CAST(k.aktif AS int) "
                   "FROM dbo.kota k LEFT JOIN dbo.negara n ON n.id = k.negara_id",
    },
    "bank": {
        "kolom": ["kode", "nama", "keterangan", "aktif"],
        "legacy": "SELECT RTRIM(kd_bank), nama, keterangan, "
                  "CASE WHEN status = 1 THEN 1 ELSE 0 END FROM {db}.dbo.m_bank",
        "arunika": "SELECT kode, nama, keterangan, CAST(aktif AS int) FROM dbo.bank",
    },
    "pelanggan": {
        "kolom": ["kode", "nama", "alamat", "kota_kode", "telepon", "hp", "email",
                  "kontak", "keterangan", "batas_piutang", "diskon_persen", "aktif"],
        # `limit_kredit` -> batas_piutang, `disc` -> diskon_persen. Tempo
        # pembayaran TIDAK dipetakan: `m_customer` punya 19 kolom dan tak satu
        # pun menyimpannya (lihat catatan di model Pelanggan).
        "legacy": "SELECT kd_customer, nama, alamat, RTRIM(kd_kota), telepon, hp, email, "
                  "kontak, keterangan, limit_kredit, disc, "
                  "CASE WHEN status = 1 THEN 1 ELSE 0 END FROM {db}.dbo.m_customer",
        "arunika": "SELECT p.kode, p.nama, p.alamat, k.kode, p.telepon, p.hp, p.email, "
                   "p.kontak, p.keterangan, p.batas_piutang, p.diskon_persen, CAST(p.aktif AS int) "
                   "FROM dbo.pelanggan p LEFT JOIN dbo.kota k ON k.id = p.kota_id",
    },
    "pemasok": {
        "kolom": ["kode", "nama", "alamat", "kota_kode", "telepon", "hp", "email",
                  "kontak", "keterangan", "bank_kode", "rekening", "aktif"],
        # `aktif` KONSTAN 1 di mode legacy, dan itu bukan penyederhanaan:
        # `m_supplier` punya 13 kolom dan tak satu pun berupa status, jadi di
        # sana pemasok memang tak bisa dinonaktifkan sama sekali.
        "legacy": "SELECT RTRIM(kd_supplier), nama, alamat, RTRIM(kd_kota), telepon, hp, email, "
                  "kontak, keterangan, RTRIM(kd_bank), rekening, 1 FROM {db}.dbo.m_supplier",
        "arunika": "SELECT s.kode, s.nama, s.alamat, k.kode, s.telepon, s.hp, s.email, "
                   "s.kontak, s.keterangan, b.kode, s.rekening, CAST(s.aktif AS int) "
                   "FROM dbo.pemasok s LEFT JOIN dbo.kota k ON k.id = s.kota_id "
                   "LEFT JOIN dbo.bank b ON b.id = s.bank_id",
    },
    "kas": {
        "kolom": ["kode", "nama", "no_rekening", "bank_kode", "kota_kode", "telepon",
                  "kontak", "saldo_awal", "keterangan", "aktif"],
        # Kolom manusiawi `m_kas` bernama `cabang` -- tabel itu tak punya `nama`
        # sama sekali.
        "legacy": "SELECT RTRIM(kd_kas), cabang, no_rekening, RTRIM(kd_bank), RTRIM(kd_kota), "
                  "telepon, kontak, saldo_awal, keterangan, "
                  "CASE WHEN status = 1 THEN 1 ELSE 0 END FROM {db}.dbo.m_kas",
        "arunika": "SELECT s.kode, s.nama, s.no_rekening, b.kode, k.kode, s.telepon, "
                   "s.kontak, s.saldo_awal, s.keterangan, CAST(s.aktif AS int) "
                   "FROM dbo.kas s LEFT JOIN dbo.bank b ON b.id = s.bank_id "
                   "LEFT JOIN dbo.kota k ON k.id = s.kota_id",
    },
    "kategori_biaya": {
        "kolom": ["kode", "nama", "keterangan", "jenis", "aktif"],
        # ## `m_biaya.status` BUKAN bendera aktif -- ia JENIS BIAYA
        #
        # Versi pertama entri ini memetakannya `aktif = (status = 2)`, dengan
        # alasan yang terdengar meyakinkan: seluruh 38 baris `m_biaya` di
        # testGUdang memang bernilai 2. Itu salah, dan grosirPusat yang
        # membuktikannya -- di sana 6 baris bernilai 1 dan 26 bernilai 2,
        # sehingga keenamnya akan dipulangkan sebagai NONAKTIF.
        #
        # Artinya ada di view legacy, seperti biasa: `mon_m_biaya` menamai hasil
        # CASE atas kolom ini **`Jenis`**, `mon_rl_biaya_penjualan` menyaring
        # `status = 1`, dan `mon_rl_biaya_adm_dan_umum` menyaring `status = 2`.
        # Keduanya dua bagian biaya di laporan laba rugi.
        #
        # `aktif` karena itu KONSTAN 1 di mode legacy: `m_biaya` punya lima kolom
        # dan tak satu pun berupa status hidup-mati -- persis seperti
        # `m_supplier`.
        "legacy": lambda db: (
            "SELECT RTRIM(kd_biaya), nama, keterangan, "
            + _case_jenis_biaya("status") + ", 1 "
            f"FROM [{db}].dbo.m_biaya"
        ),
        "arunika": "SELECT kode, nama, keterangan, jenis, CAST(aktif AS int) "
                   "FROM dbo.kategori_biaya",
    },
    "voucher": {
        "kolom": ["kode", "nama", "nominal", "keterangan", "aktif"],
        "legacy": "SELECT RTRIM(kd_voucher), nama, nominal, keterangan, "
                  "CASE WHEN status = 1 THEN 1 ELSE 0 END FROM {db}.dbo.m_voucher",
        "arunika": "SELECT kode, nama, nominal, keterangan, CAST(aktif AS int) FROM dbo.voucher",
    },
    # --- Katalog ----------------------------------------------------------
    "satuan": _referensi("m_satuan", "kd_satuan", "satuan"),
    # Lima referensi barang. `arunika_src.barang` sudah memulangkan `merek_kode`,
    # `kategori_kode`, `model_kode`, `warna_kode`, dan `bahan_kode` sejak awal --
    # tanpa view ini kelima kode itu tak punya tempat untuk dipulangkan jadi
    # nama, dan tiap laporan yang menampilkan "Kategori" tetap terpaku ke tabel
    # legacy. Nama `m_model` -> `model_barang` dan `m_jenis_bahan` -> `bahan`
    # mengikuti nama modelnya, bukan nama legacy-nya.
    "merek": _referensi("m_merk", "kd_merk", "merek"),
    "kategori": _referensi("m_kategori", "kd_kategori", "kategori"),
    "model_barang": _referensi("m_model", "kd_model", "model_barang"),
    "warna": _referensi("m_warna", "kd_warna", "warna"),
    "bahan": _referensi("m_jenis_bahan", "kd_jenis_bahan", "bahan"),
    "divisi": {
        "kolom": ["kode", "nama", "awalan_nota", "aktif"],
        # `kepala_nota` -> awalan_nota. Namanya diganti karena artinya memang itu:
        # awalan nomor dokumen, dan ia PER DIVISI, bukan per server -- GUDANG
        # punya lima divisi dengan awalan berbeda.
        "legacy": "SELECT RTRIM(kd_divisi), nama, kepala_nota, "
                  "CASE WHEN status = 1 THEN 1 ELSE 0 END FROM {db}.dbo.m_divisi",
        "arunika": "SELECT kode, nama, awalan_nota, CAST(aktif AS int) FROM dbo.divisi",
    },
    # --- Aktor ------------------------------------------------------------
    #
    # Dua entitas, bukan satu. `m_userx` adalah yang MENGETIK dokumen dan
    # `m_pegawai` yang MENJUAL, dan laporan Penjualan Detail menampilkan
    # keduanya berdampingan (`petugas` dan `sales`). Tak ada satu kolom pun di
    # legacy yang menghubungkan sebuah baris `m_userx` ke sebuah baris
    # `m_pegawai`, jadi menggabungkannya berarti menebak.
    #
    # ## `status <> 0`, dan itu diperiksa bukan ditebak
    #
    # Godaannya menulis `status = 1`, seperti `m_divisi` di atas. Itu SALAH di
    # sini, dan bentuk datanya persis jebakan `m_biaya`: `m_pegawai.status` di
    # testGUdang bernilai 1 pada lima baris dan 2 pada lima baris lainnya.
    # `status = 1` akan memulangkan separuh pegawai sebagai NONAKTIF.
    #
    # Jawabannya di view legacy, seperti biasa: SETIAP view yang menyentuh tabel
    # ini menyaring `<> 0` -- `GetAbsenSemuaPegawai`, `GetAbsenSemuaPegawai2`,
    # `GetKodeShiftPegawai`, `GetPegawaiTidakMasuk`, `mon_t_awal_kerja`,
    # `mon_t_hutang_pegawai_detail`, `v_t_pegawai_ganti_shift_detail`,
    # `v_t_kendaraan_tanggung_jawab`. Jadi 1 dan 2 sama-sama aktif; 0 yang mati.
    # `m_userx` mengikuti pola yang sama (`mon_t_kendaraan_pengisian_bbm`).
    "pengguna": {
        "kolom": ["kode", "nama", "aktif"],
        # `passwd` dan `passweb` sengaja TIDAK diproyeksikan. Tak satu laporan
        # pun membutuhkannya, dan kolom yang tak ada di view tak bisa bocor
        # lewat view.
        "legacy": "SELECT RTRIM(kd_user), nama, "
                  "CASE WHEN status <> 0 THEN 1 ELSE 0 END FROM {db}.dbo.m_userx",
        "arunika": "SELECT kode, nama, CAST(aktif AS int) FROM dbo.pengguna",
    },
    "pegawai": {
        "kolom": ["kode", "nama", "aktif"],
        # Tiga kolom dari 23. Sisanya rekam kepegawaian (foto, KTP, agama,
        # tanggal lahir, status kawin/lembur) yang §6 sudah nyatakan tidak
        # diwarisi bersama seluruh cabang HR-nya.
        "legacy": "SELECT RTRIM(kd_pegawai), nama, "
                  "CASE WHEN status <> 0 THEN 1 ELSE 0 END FROM {db}.dbo.m_pegawai",
        "arunika": "SELECT kode, nama, CAST(aktif AS int) FROM dbo.pegawai",
    },
    "barang": {
        "kolom": ["kode", "nama", "keterangan", "merek_kode", "kategori_kode",
                  "model_kode", "warna_kode", "bahan_kode", "satuan_dasar_kode", "aktif"],
        # `m_barang` TIDAK punya kolom satuan dasar; ia diturunkan dari baris
        # `m_barang_satuan` yang berfaktor 1. `MIN(kd_satuan)` bukan pilihan
        # sembarangan: sebagian barang punya LEBIH DARI SATU satuan berfaktor 1
        # (mis. PENAL02 -> SAA000 dan SAA006), dan mengambil semuanya akan
        # menggandakan barisnya. Faktornya sama-sama 1, jadi pilih satu -- cara
        # yang PERSIS sama dengan blok [0] `_movement_sql`. Berbeda sedikit saja
        # di sini, stok dan katalog akan bercabang tanpa satu pun galat.
        "legacy": "SELECT b.kd_barang, b.nama, b.keterangan, RTRIM(b.kd_merk), "
                  "RTRIM(b.kd_kategori), RTRIM(b.kd_model), RTRIM(b.kd_warna), "
                  "RTRIM(b.kd_jenis_bahan), "
                  "(SELECT MIN(RTRIM(bs.kd_satuan)) FROM {db}.dbo.m_barang_satuan bs "
                  "WHERE bs.kd_barang = b.kd_barang AND bs.jumlah = 1), "
                  "CASE WHEN b.status = 1 THEN 1 ELSE 0 END FROM {db}.dbo.m_barang b",
        "arunika": "SELECT b.kode, b.nama, b.keterangan, mk.kode, kt.kode, mo.kode, "
                   "wa.kode, bh.kode, sd.kode, CAST(b.aktif AS int) "
                   "FROM dbo.barang b "
                   "LEFT JOIN dbo.merek mk ON mk.id = b.merek_id "
                   "LEFT JOIN dbo.kategori kt ON kt.id = b.kategori_id "
                   "LEFT JOIN dbo.model_barang mo ON mo.id = b.model_id "
                   "LEFT JOIN dbo.warna wa ON wa.id = b.warna_id "
                   "LEFT JOIN dbo.bahan bh ON bh.id = b.bahan_id "
                   "LEFT JOIN dbo.satuan sd ON sd.id = b.satuan_dasar_id",
    },
    # --- Penjualan --------------------------------------------------------
    #
    # Nilai uangnya datang dari FUNGSI SKALAR legacy, bukan dari formula yang
    # ditulis ulang di sini. Itu keputusan sadar, dan alasannya di bawah.
    "penjualan": {
        "kolom": ["nomor", "tanggal", "divisi_kode", "pelanggan_kode", "voucher_kode",
                  "kas_kode", "subtotal", "diskon", "pajak", "total", "jenis_bayar", "status"],
        # ## Kenapa memanggil fungsi vendor, bukan menulis formulanya sendiri
        #
        # `t_penjualan_total` hanya menutup 55% nota di grosirPusat (259.258 dari
        # 474.595). Sisanya butuh nilai yang dihitung. Menulis ulang formulanya
        # di sini berarti SALINAN KEDUA logika uang -- dan salinan yang menyimpang
        # tidak memunculkan galat apa pun, hanya omzet yang berbeda.
        #
        # `dbo.GetTotalPenjualan` adalah formula otoritatifnya, dan itu diukur
        # bukan diduga: **200/200 nota cocok persis** dengan `t_penjualan_total`
        # di kedua server yang diperiksa, DAN ia tetap menjawab untuk nota yang
        # tak punya baris total.
        #
        # Memanggil fungsi vendor adalah interoperabilitas; menyalin isinya yang
        # tidak boleh. Definisinya tidak pernah dibaca untuk menulis modul ini.
        #
        # ## Ongkosnya, dan kenapa COALESCE
        #
        # Ketiga fungsi ini `is_inlineable = True`, TAPI compatibility level
        # database legacy **100** sementara inlining butuh >= 150. Jadi ia jalan
        # baris-per-baris. Terukur atas 5.000 nota:
        #
        #     kolom tersimpan saja              0,0153 dtk
        #     fungsi untuk SEMUA baris          0,6510 dtk   (42,5x)
        #     COALESCE, fungsi hanya saat NULL  0,2142 dtk   (14,0x)
        #
        # Menaikkan compatibility level akan menggratiskannya -- dan itu MENGUBAH
        # DATABASE LEGACY serta bisa menggeser rencana eksekusi aplikasi lama.
        # Keputusan pemilik server, bukan keputusan kita.
        #
        # `CROSS APPLY` memastikan tiap fungsi dipanggil SEKALI per baris, bukan
        # sekali per kemunculan -- `subtotal` diturunkan dari ketiganya tanpa
        # panggilan tambahan.
        #
        # ## subtotal diturunkan, dan identitasnya dibuktikan
        #
        # `total + diskon - pajak == SUM(qty * harga_jual)` -- diuji 50/50 nota
        # berdiskon. Jadi `subtotal` adalah nilai kotor sebelum diskon apa pun.
        "legacy": _badan_penjualan,
        "arunika": "SELECT p.nomor, p.tanggal, d.kode, pl.kode, v.kode, ks.kode, "
                   "p.subtotal, p.diskon, p.pajak, p.total, p.jenis_bayar, p.status "
                   "FROM dbo.penjualan p "
                   "INNER JOIN dbo.divisi d ON d.id = p.divisi_id "
                   "LEFT JOIN dbo.pelanggan pl ON pl.id = p.pelanggan_id "
                   "LEFT JOIN dbo.voucher v ON v.id = p.voucher_id "
                   "LEFT JOIN dbo.kas ks ON ks.id = p.kas_id",
    },
    "penjualan_baris": {
        "kolom": ["penjualan_nomor", "tanggal", "divisi_kode",
                  "barang_kode", "satuan_kode", "sales_kode", "qty", "harga", "total"],
        # ## Kenapa baris membawa tanggal & divisi kepalanya
        #
        # Bukan denormalisasi yang kebablasan -- ini bentuk BACA, dan `tanggal`
        # + `divisi_kode` adalah satu-satunya alasan sebuah laporan tingkat-baris
        # perlu menyentuh kepalanya sama sekali. Tanpa keduanya, tiap laporan
        # baris harus men-join `arunika_src.penjualan`, yang menghitung SELURUH
        # nilai uang per nota (GHB atas tiap baris detail) cuma untuk memulangkan
        # satu kolom tanggal -- tabel detail diagregasi dua kali.
        #
        # Terukur di grosirPusat lewat FMI Penjualan, sesudah `_nota_net` sendiri
        # sudah diperbaiki: 2,58 dtk lewat view penjualan vs 0,59 dtk jalur
        # legacy untuk satu bulan. Bentuk ini yang menutup selisih itu.
        #
        # Konsisten pula dengan `pergerakan_stok`: buku besar itu memang membawa
        # `tanggal` dan `kd_divisi` di tiap barisnya.
        # `d.total` adalah computed column yang definisinya rusak di legacy
        # (ANSI_NULLS/QUOTED_IDENTIFIER salah, memblokir CREATE INDEX, error
        # 1935). Cacat itu menghalangi PEMBUATAN INDEKS, bukan SELECT -- nilainya
        # tetap benar dan terbaca. Diperiksa: selisih SUM(d.total) terhadap
        # GetTotalPenjualan persis sebesar diskon tingkat-nota (540.000 - 539.500
        # = 500 = diskon_uang), jadi `d.total` = nilai baris SESUDAH diskon baris.
        #
        # `sales_kode` ada di BARIS karena di legacy pun begitu: `kd_pegawai`
        # adalah kolom `t_penjualan_detail`. RTRIM karena `char(6)`, dan
        # NULLIF('') supaya baris tanpa sales memulangkan NULL alih-alih string
        # kosong -- jalur legacy meng-LEFT JOIN-nya, jadi ketiadaan sales itu
        # sah dan harus terbaca sebagai ketiadaan, bukan sebagai kode kosong.
        "legacy": "SELECT d.no_transaksi, h.tanggal, RTRIM(h.kd_divisi), "
                  "d.kd_barang, RTRIM(d.kd_satuan), NULLIF(RTRIM(d.kd_pegawai), ''), "
                  "d.qty, d.harga_jual, d.total "
                  "FROM {db}.dbo.t_penjualan_detail d "
                  "INNER JOIN {db}.dbo.t_penjualan h ON h.no_transaksi = d.no_transaksi",
        "arunika": "SELECT p.nomor, p.tanggal, dv.kode, b.kode, s.kode, pg.kode, "
                   "pb.qty, pb.harga, pb.total "
                   "FROM dbo.penjualan_baris pb "
                   "INNER JOIN dbo.penjualan p ON p.id = pb.penjualan_id "
                   "INNER JOIN dbo.divisi dv ON dv.id = p.divisi_id "
                   "INNER JOIN dbo.barang b ON b.id = pb.barang_id "
                   "INNER JOIN dbo.satuan s ON s.id = pb.satuan_id "
                   "LEFT JOIN dbo.pegawai pg ON pg.id = pb.sales_id",
    },
    # --- Pembelian --------------------------------------------------------
    #
    # Cermin penjualan, sampai ke cara badannya dibangkitkan. Yang berbeda cuma
    # sisi lawannya: `pemasok_kode` menggantikan `pelanggan_kode`, dan tak ada
    # voucher -- voucher adalah alat jual, bukan alat beli.
    "pembelian": {
        "kolom": ["nomor", "tanggal", "divisi_kode", "pemasok_kode",
                  "subtotal", "diskon", "pajak", "total", "jenis_bayar", "status"],
        "legacy": _badan_pembelian,
        "arunika": "SELECT p.nomor, p.tanggal, d.kode, pm.kode, "
                   "p.subtotal, p.diskon, p.pajak, p.total, p.jenis_bayar, p.status "
                   "FROM dbo.pembelian p "
                   "INNER JOIN dbo.divisi d ON d.id = p.divisi_id "
                   "LEFT JOIN dbo.pemasok pm ON pm.id = p.pemasok_id",
    },
    "pembelian_baris": {
        "kolom": ["pembelian_nomor", "tanggal", "divisi_kode",
                  "barang_kode", "satuan_kode", "qty", "harga", "total"],
        # `tanggal` + `divisi_kode` dibawa baris, alasan sama dengan
        # `penjualan_baris`: tanpa keduanya tiap laporan tingkat-baris harus
        # men-join view kepala yang menghitung seluruh nilai uang per nota,
        # hanya demi satu kolom tanggal.
        #
        # `d.total` sudah nilai baris sesudah diskon baris, dan identitasnya
        # terhadap `_line_net('harga_beli')` diuji per baris: **0 beda dari
        # 150.920** di grosirPusat.
        "legacy": "SELECT d.no_transaksi, h.tanggal, RTRIM(h.kd_divisi), "
                  "d.kd_barang, RTRIM(d.kd_satuan), d.qty, d.harga_beli, d.total "
                  "FROM {db}.dbo.t_pembelian_detail d "
                  "INNER JOIN {db}.dbo.t_pembelian h ON h.no_transaksi = d.no_transaksi",
        "arunika": "SELECT p.nomor, p.tanggal, dv.kode, b.kode, s.kode, pb.qty, pb.harga, pb.total "
                   "FROM dbo.pembelian_baris pb "
                   "INNER JOIN dbo.pembelian p ON p.id = pb.pembelian_id "
                   "INNER JOIN dbo.divisi dv ON dv.id = p.divisi_id "
                   "INNER JOIN dbo.barang b ON b.id = pb.barang_id "
                   "INNER JOIN dbo.satuan s ON s.id = pb.satuan_id",
    },
    # --- Kas ---------------------------------------------------------------
    "jurnal_kas": {
        "kolom": ["nomor", "tanggal", "divisi_kode", "kas_kode", "kas_tujuan_kode",
                  "jenis", "kategori_kode", "jumlah", "keterangan"],
        # ## Empat tabel legacy, satu buku besar
        #
        # Konsolidasi Sec 4.2, dan ia BUKAN penyederhanaan yang dikarang di sini:
        # `apps/transactions/kas.py` sudah menggerakkan keempat tabel itu dari
        # satu `SPEC` dengan satu route generik.
        #
        # Yang TIDAK ikut: lengan penjualan di `_kas_union()`. Itu proyeksi buku
        # kas harian (penjualan tunai memang menambah kas), bukan dokumen kas --
        # penjualan sudah punya entitasnya sendiri. Layar Kas Harian kelak
        # menyatukan keduanya; view ini tetap berisi dokumen saja.
        #
        # `t_penambahan_kas` dan `t_mutasi_kas` NOL BARIS di kedua server yang
        # bisa dijangkau. Lengannya tetap ada: `kas.py` menulis ke keduanya, dan
        # dokumen rancangan Sec 2 sudah mencatat kenapa nol baris bukan bukti
        # fitur tak terpakai.
        #
        # `kd_jenis` (JAA000/...) sengaja tak dipetakan: ia cara bayar, dan belum
        # ada laporan kas yang memintanya.
        "legacy": lambda db: (
            "SELECT no_transaksi, tanggal, RTRIM(kd_divisi), RTRIM(kd_kas), NULL, "
            "'biaya', RTRIM(kd_biaya), nominal, COALESCE(keterangan, '') "
            f"FROM [{db}].dbo.t_biaya_operasional"
            " UNION ALL "
            "SELECT no_transaksi, tanggal, RTRIM(kd_divisi), RTRIM(kd_kas), NULL, "
            "'pendapatan', NULL, nominal, COALESCE(keterangan, '') "
            f"FROM [{db}].dbo.t_pendapatan"
            " UNION ALL "
            "SELECT no_transaksi, tanggal, NULL, RTRIM(kd_kas), NULL, "
            "'penambahan', NULL, nominal, COALESCE(keterangan, '') "
            f"FROM [{db}].dbo.t_penambahan_kas"
            " UNION ALL "
            # SATU baris per dokumen mutasi, bukan dua. Dua baris adalah bentuk
            # BUKU (keluar dari sumber, masuk ke tujuan) dan itu urusan layar
            # kas; dokumennya satu, dan `kas_tujuan_kode` yang menyatakan ke mana.
            "SELECT no_transaksi, tanggal, NULL, RTRIM(kd_kas_sumber), RTRIM(kd_kas_tujuan), "
            "'mutasi', NULL, nominal, COALESCE(keterangan, '') "
            f"FROM [{db}].dbo.t_mutasi_kas"
        ),
        "arunika": "SELECT j.nomor, j.tanggal, dv.kode, ks.kode, kt.kode, j.jenis, kb.kode, "
                   "j.jumlah, j.keterangan "
                   "FROM dbo.jurnal_kas j "
                   "LEFT JOIN dbo.divisi dv ON dv.id = j.divisi_id "
                   "INNER JOIN dbo.kas ks ON ks.id = j.kas_id "
                   "LEFT JOIN dbo.kas kt ON kt.id = j.kas_tujuan_id "
                   "LEFT JOIN dbo.kategori_biaya kb ON kb.id = j.kategori_id",
    },
    "barang_satuan": {
        "kolom": ["barang_kode", "satuan_kode", "isi", "harga_jual"],
        # `jumlah` -> isi. Nama legacy itu berkali-kali terbaca sebagai kuantitas
        # stok, padahal artinya berapa satuan dasar di dalam satu satuan ini.
        "legacy": "SELECT kd_barang, RTRIM(kd_satuan), jumlah, harga_jual "
                  "FROM {db}.dbo.m_barang_satuan",
        "arunika": "SELECT b.kode, s.kode, bs.isi, bs.harga_jual "
                   "FROM dbo.barang_satuan bs "
                   "INNER JOIN dbo.barang b ON b.id = bs.barang_id "
                   "INNER JOIN dbo.satuan s ON s.id = bs.satuan_id",
    },
}

# Kolom kode yang SENGAJA tidak di-RTRIM, dengan sumber legacy-nya.
#
# Ditulis eksplisit supaya menghapus satu `RTRIM` lagi tak bisa jadi kelalaian:
# ia harus lewat sini dulu. Nilainya dipakai dua arah --
# `test_master_src` memastikan tak ada kolom kode LAIN yang kehilangan RTRIM-nya,
# dan `manage.py cek_arunika` memeriksa tiap sumber di bawah memang masih
# `varchar` di server sungguhan. Kalau vendor mengubahnya jadi `char`, pemeriksa
# itu yang memberi tahu -- bukan baris yang diam-diam hilang dari laporan.
TANPA_RTRIM = {
    ("kota", "kode_telepon"): ("m_kota", "kd_telp"),
    ("pelanggan", "kode"): ("m_customer", "kd_customer"),
    ("barang", "kode"): ("m_barang", "kd_barang"),
    ("barang_satuan", "barang_kode"): ("m_barang_satuan", "kd_barang"),
    ("penjualan", "nomor"): ("t_penjualan", "no_transaksi"),
    ("penjualan", "pelanggan_kode"): ("t_penjualan", "kd_customer"),
    ("penjualan_baris", "penjualan_nomor"): ("t_penjualan_detail", "no_transaksi"),
    ("penjualan_baris", "barang_kode"): ("t_penjualan_detail", "kd_barang"),
    ("pembelian", "nomor"): ("t_pembelian", "no_transaksi"),
    ("pembelian_baris", "pembelian_nomor"): ("t_pembelian_detail", "no_transaksi"),
    ("pembelian_baris", "barang_kode"): ("t_pembelian_detail", "kd_barang"),
    ("jurnal_kas", "nomor"): ("t_biaya_operasional", "no_transaksi"),
}

MODE = ("legacy", "arunika")

# Tabel legacy yang menentukan JUMLAH BARIS tiap entitas.
#
# Ditulis eksplisit, bukan diturunkan dari badan view -- dan itu sesudah mencoba
# menurunkannya lalu gagal. Rujukan `{db}.dbo.X` yang PERTAMA di badan `barang`
# adalah `m_barang_satuan` (di dalam subquery satuan dasar), bukan `m_barang`,
# sehingga pemeriksa membandingkan 53.865 baris dengan 54.232 dan melaporkan
# selisih yang tidak ada. Rujukan TERAKHIR sama tak bisa dipercaya: di
# `penjualan` yang terakhir justru sebuah fungsi, bukan tabel.
#
# Daftar kedua memang berisiko menyimpang dari yang pertama. Karena itu ada test
# yang memastikan tiap nilai di sini benar-benar muncul di badan view-nya, dan
# tiap entitas punya satu.
SUMBER_UTAMA = {
    "negara": "m_negara",
    "kota": "m_kota",
    "bank": "m_bank",
    "pelanggan": "m_customer",
    "pemasok": "m_supplier",
    "kas": "m_kas",
    "kategori_biaya": "m_biaya",
    "voucher": "m_voucher",
    "satuan": "m_satuan",
    "merek": "m_merk",
    "kategori": "m_kategori",
    "model_barang": "m_model",
    "warna": "m_warna",
    "bahan": "m_jenis_bahan",
    "divisi": "m_divisi",
    "pengguna": "m_userx",
    "pegawai": "m_pegawai",
    "barang": "m_barang",
    "penjualan": "t_penjualan",
    "penjualan_baris": "t_penjualan_detail",
    "pembelian": "t_pembelian",
    "pembelian_baris": "t_pembelian_detail",
    # Jumlah barisnya gabungan empat tabel -- lihat `_JUMLAH_GABUNGAN` di
    # `cek_arunika`, yang menjumlahkan keempatnya sebagai acuan.
    "jurnal_kas": "t_biaya_operasional",
    "barang_satuan": "m_barang_satuan",
}


def badan_legacy(nama: str, db_legacy: str) -> str:
    """Badan SELECT mode legacy sebuah entitas, sudah diselesaikan jadi teks.

    Sebagian badan berupa string ber-`{db}`, sebagian berupa fungsi pembangkit
    (`penjualan`, dari `reports._nota_net()`). Pemanggil yang ingin MEMBACA
    SQL-nya -- test, alat diagnosa -- memakai ini alih-alih menyentuh `_MASTER`
    langsung, supaya tak perlu tahu bentuk mana yang dipakai entitas mana.
    """
    badan = _MASTER[nama]["legacy"]
    return badan(db_legacy) if callable(badan) else badan.format(db=f"[{db_legacy}]")


def ddl(nama: str, mode: str, db_legacy: str | None = None) -> str:
    """`CREATE VIEW` untuk satu entitas pada satu mode."""
    if mode not in MODE:
        raise ValueError(f"mode tak dikenal: {mode!r}")
    spec = _MASTER[nama]
    badan = spec[mode]
    if mode == "legacy":
        if not db_legacy:
            raise ValueError(f"{nama}: mode legacy butuh nama database sumber.")
        if "]" in db_legacy:
            raise ValueError(f"Nama database tak bisa dikutip aman: {db_legacy!r}")
        # Badan bisa berupa string ber-`{db}` ATAU fungsi pembangkit. Yang kedua
        # dipakai saat SQL-nya harus berasal dari satu sumber kebenaran yang
        # sudah ada di kode -- `penjualan` dibangkitkan dari `reports._nota_net()`
        # supaya formula uangnya tidak punya salinan kedua.
        badan = badan(db_legacy) if callable(badan) else badan.format(db=f"[{db_legacy}]")
    kolom = ", ".join(f"[{k}]" for k in spec["kolom"])
    return f"CREATE VIEW [{SKEMA}].[{nama}] ({kolom}) AS\n{badan}"


def pasang(cur, mode: str, db_legacy: str | None = None) -> list[str]:
    """Buat schema + seluruh view. Idempoten: yang sudah ada dibuat ulang.

    Dibuat ulang, bukan dilewati: sebuah view adalah definisi, bukan data, jadi
    menggantinya tidak berisiko kehilangan apa pun -- sementara MELEWATI-nya
    berarti perubahan pemetaan diam-diam tidak pernah sampai ke server.
    """
    cur.execute(f"IF SCHEMA_ID('{SKEMA}') IS NULL EXEC('CREATE SCHEMA [{SKEMA}]')")
    dibuat = []
    for nama in _MASTER:
        cur.execute(
            f"IF OBJECT_ID('{SKEMA}.{nama}', 'V') IS NOT NULL DROP VIEW [{SKEMA}].[{nama}]"
        )
        cur.execute(ddl(nama, mode, db_legacy))
        dibuat.append(nama)
    return dibuat


def copot(cur) -> None:
    """Buang seluruh jejak adapter master. Tak menyentuh tabel apa pun."""
    for nama in _MASTER:
        cur.execute(
            f"IF OBJECT_ID('{SKEMA}.{nama}', 'V') IS NOT NULL DROP VIEW [{SKEMA}].[{nama}]"
        )
    cur.execute(f"IF SCHEMA_ID('{SKEMA}') IS NOT NULL DROP SCHEMA [{SKEMA}]")


def daftar() -> list[str]:
    return list(_MASTER)

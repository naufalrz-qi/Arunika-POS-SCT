"""Skema bisnis Arunika — dirancang sendiri, bukan turunan skema POS legacy.

Berkas ini adalah **sumber kebenaran tunggal** bentuk database milik Arunika.
Rancangannya beserta alasan tiap keputusan ada di
`docs/superpowers/specs/2026-09-07-skema-arunika-rancangan.md`.

## Asal-usul

Tiap tabel di sini diturunkan dari pertanyaan bisnis — apa yang perlu diketahui
sebuah usaha grosir untuk menjalankan gudang, cabang, dan kasirnya — bukan dari
DDL legacy. Skema legacy hanya dibaca untuk keperluan **interoperabilitas**:
Arunika harus tetap bisa membaca data yang sudah ada lewat lapisan adapter
(`apps/bisnis/adapter.py`), dan itu mustahil tanpa mengetahui bentuk sumbernya.

Yang TIDAK dilakukan, dan tidak boleh: menyalin definisi trigger/view/procedure
legacy, dan menurunkan rancangan ini dari `sys.columns` server legacy.
`hub_schema.baca_kolom()` khususnya tidak boleh dipakai di sini — fungsi itu
membaca katalog server legacy, dan memakainya berarti membangkitkan karya
turunan.

## Dua keputusan yang membentuk seluruh berkas ini

**1. `PergerakanStok` adalah satu buku besar.** Di legacy, pergerakan stok
tersebar di sembilan tabel dan tidak ada satu pun yang menyatakan "stok
berpindah", sehingga `apps/inventory/services._movement_sql` harus menyatukan
sembilan blok `UNION ALL` setiap kali ada yang bertanya soal stok. Yang menarik:
keluaran kesembilan blok itu sudah satu bentuk kolom yang seragam. Kodenya sudah
menemukan bentuk yang benar; skema legacy saja yang tak pernah menyediakan
tempat menyimpannya. Di sini ia jadi tabel nyata, append-only, terindeks.

**2. Tanpa trigger, sama sekali.** Hampir semua kerusakan tersulit di sistem
legacy berasal dari trigger: yang menggeser stok satu baris saja dari INSERT
multi-baris tanpa galat, yang membuat `cur.rowcount` berbohong sehingga 131 dari
406 baris hilang tanpa jejak, yang memotong nilai pada 30 karakter. Logika yang
tersembunyi di database adalah logika yang tak bisa diuji dan tak bisa
di-review. Semua penulisan di sini lewat aplikasi.

## Catatan teknis

Nama tabel sengaja TIDAK diberi awalan schema. Namespace `arunika.*` yang
disebut dokumen rancangan berlaku untuk **iTVF adapter di server legacy**, di
mana pemisahan dari objek `dbo.*` milik vendor memang perlu. Database milik
Arunika sendiri seluruhnya milik kita, jadi `dbo` bawaan sudah benar — dan model
tanpa kualifikasi schema tetap bisa diuji di SQLite tanpa server apa pun.

Hak Cipta (c) 2026 Naufal Rifqi Zuhrian. Lihat LICENSE.
"""
from django.db import models


class Referensi(models.Model):
    """Induk abstrak untuk tabel referensi: kode + nama + bisa dinonaktifkan.

    `aktif` ada di sini karena ketiadaannya di legacy terbukti menyakitkan:
    `m_supplier` tidak punya kolom status sama sekali (13 kolom), dan karena
    DELETE juga dilarang (ON DELETE CASCADE dari tabel referensi menjangkau
    barang), sebuah pemasok yang salah ketik tidak bisa dibatalkan dengan cara
    apa pun.
    """

    kode = models.CharField(max_length=20, unique=True)
    nama = models.CharField(max_length=100)
    aktif = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["kode"]

    def __str__(self):
        return f"{self.kode} {self.nama}"


class Merek(Referensi):
    class Meta(Referensi.Meta):
        abstract = False
        db_table = "merek"


class Kategori(Referensi):
    class Meta(Referensi.Meta):
        abstract = False
        db_table = "kategori"


class ModelBarang(Referensi):
    """Dinamai `ModelBarang`, bukan `Model`.

    Konsep bisnisnya "model barang", tapi `Model` polos di basis kode Django
    akan bertabrakan makna dengan `models.Model` di tiap pembacaan berikutnya.
    """

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "model_barang"


class Warna(Referensi):
    class Meta(Referensi.Meta):
        abstract = False
        db_table = "warna"


class Bahan(Referensi):
    class Meta(Referensi.Meta):
        abstract = False
        db_table = "bahan"


class Satuan(Referensi):
    """PCS, LUSIN, DUS. Konversinya per barang, bukan global — lihat BarangSatuan."""

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "satuan"


class Divisi(Referensi):
    """Unit penyimpanan/penjualan di dalam satu server.

    `awalan_nota` bukan hiasan: nomor dokumen diawali per divisi, bukan per
    server. GUDANG punya lima divisi, dan seluruh opname-nya duduk di satu
    divisi tertentu — mengambil "divisi pertama" adalah cara yang sudah terbukti
    salah.
    """

    awalan_nota = models.CharField(max_length=5, blank=True)

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "divisi"


class Barang(models.Model):
    """Katalog produk.

    `kode` diketik operator dan tidak punya pola yang bisa ditebak — di data
    nyata bentuknya berkisar dari `049` sampai `6941057402239B` dan `JM14062-MU`.
    Karena itu ia `unique` tapi bukan primary key: yang jadi kunci adalah `id`,
    supaya kode yang salah ketik masih bisa diperbaiki tanpa memutus satu pun
    baris transaksi yang sudah menunjuk barang ini.

    Itu sekaligus menghindari seluruh kelas masalah penomoran legacy, yang
    memakai blok bergulir `{huruf}{blok}{NNN}` — `MAA999` menggulung ke `MAB000`
    — sehingga tiap kueri `MAX()` harus memakai pola `LIKE 'X[A-Z][A-Z][0-9][0-9][0-9]'`
    dan salah sedikit berarti penomoran bercabang dua.
    """

    kode = models.CharField(max_length=30, unique=True)
    nama = models.CharField(max_length=100)
    keterangan = models.CharField(max_length=100, blank=True)

    merek = models.ForeignKey(Merek, null=True, blank=True, on_delete=models.PROTECT)
    kategori = models.ForeignKey(Kategori, null=True, blank=True, on_delete=models.PROTECT)
    model = models.ForeignKey(ModelBarang, null=True, blank=True, on_delete=models.PROTECT)
    warna = models.ForeignKey(Warna, null=True, blank=True, on_delete=models.PROTECT)
    bahan = models.ForeignKey(Bahan, null=True, blank=True, on_delete=models.PROTECT)

    # Satuan terkecil. Seluruh kuantitas di PergerakanStok disimpan dalam satuan
    # ini, sudah dikonversi -- lihat catatan di sana.
    satuan_dasar = models.ForeignKey(Satuan, on_delete=models.PROTECT, related_name="barang_dasar")

    aktif = models.BooleanField(default=True)
    dibuat_pada = models.DateTimeField(auto_now_add=True)
    diubah_pada = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "barang"
        ordering = ["kode"]

    def __str__(self):
        return f"{self.kode} {self.nama}"


class BarangSatuan(models.Model):
    """Satuan jual sebuah barang beserta konversi dan harganya.

    `isi`, bukan `jumlah`: nilainya adalah berapa satuan dasar yang ada di dalam
    satu satuan ini (1 LUSIN = 12 PCS). Nama `jumlah` di legacy membuat kolom ini
    berkali-kali dibaca sebagai kuantitas stok, yang bukan artinya sama sekali.

    `PROTECT` pada kedua FK disengaja. Di legacy, relasi ke tabel referensi
    memakai ON DELETE CASCADE, sehingga menghapus satu merek akan menyeret
    barang-barangnya ikut hilang -- itulah kenapa di sana DELETE dilarang total
    dan pembatalan harus berupa kolom status.
    """

    barang = models.ForeignKey(Barang, on_delete=models.CASCADE, related_name="satuan")
    satuan = models.ForeignKey(Satuan, on_delete=models.PROTECT)
    isi = models.DecimalField(max_digits=18, decimal_places=3, default=1)
    harga_jual = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = "barang_satuan"
        constraints = [
            models.UniqueConstraint(fields=["barang", "satuan"], name="uq_barang_satuan"),
            models.CheckConstraint(condition=models.Q(isi__gt=0), name="ck_barang_satuan_isi_positif"),
        ]

    def __str__(self):
        return f"{self.barang_id}/{self.satuan_id} isi={self.isi}"


class JenisPergerakan(models.TextChoices):
    SALDO_AWAL = "saldo_awal", "Saldo Awal"
    PENJUALAN = "penjualan", "Penjualan"
    RETUR_JUAL = "retur_jual", "Retur Penjualan"
    PEMBELIAN = "pembelian", "Pembelian"
    RETUR_BELI = "retur_beli", "Retur Pembelian"
    MUTASI_MASUK = "mutasi_masuk", "Mutasi Masuk"
    MUTASI_KELUAR = "mutasi_keluar", "Mutasi Keluar"
    KOREKSI = "koreksi", "Koreksi Stok"


class PergerakanStok(models.Model):
    """Buku besar stok: satu baris per perpindahan, append-only.

    Inilah tabel yang membuat skema ini berbeda secara mendasar dari legacy, di
    mana pergerakan stok harus direkonstruksi dari sembilan tabel setiap kali
    ada yang bertanya.

    **Kuantitas disimpan dalam satuan DASAR barang, sudah dikonversi.**
    `satuan` hanya mencatat satuan apa yang diketik operator. Legacy menyimpan
    qty dalam satuan input dan mengalikannya kembali lewat trigger; akibatnya,
    mengganti satuan pada baris yang sudah diisi mengubah arti angka yang sama
    -- "10" yang tadinya 10 PCS mendadak berarti 10 LUSIN, selisih 12 kali
    lipat, tanpa satu pun tanda di layar.

    **Saldo awal adalah baris di sini**, bukan tabel tersendiri
    (`jenis = saldo_awal`). Legacy menyimpannya sebagai kolom di tabel lain,
    yang memaksanya jadi blok UNION kesembilan dengan aturan tanggal yang
    berbeda dari delapan blok lainnya.

    **Pembatalan adalah baris pembalik, bukan penghapusan.** Buku besar yang
    barisnya bisa hilang bukan buku besar.
    """

    divisi = models.ForeignKey(Divisi, on_delete=models.PROTECT)
    barang = models.ForeignKey(Barang, on_delete=models.PROTECT)
    satuan = models.ForeignKey(Satuan, on_delete=models.PROTECT)

    tanggal = models.DateField()
    masuk = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    keluar = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    harga = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    jenis = models.CharField(max_length=20, choices=JenisPergerakan.choices)
    sumber_tipe = models.CharField(max_length=20, blank=True)
    sumber_id = models.BigIntegerField(null=True, blank=True)
    no_rujukan = models.CharField(max_length=30, blank=True)

    dicatat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pergerakan_stok"
        indexes = [
            # Pertanyaan yang paling sering: saldo satu barang di satu divisi
            # sampai tanggal tertentu. Urutan kolomnya mengikuti itu.
            models.Index(fields=["barang", "divisi", "tanggal"], name="ix_gerak_barang_divisi_tgl"),
            models.Index(fields=["divisi", "tanggal"], name="ix_gerak_divisi_tgl"),
            models.Index(fields=["sumber_tipe", "sumber_id"], name="ix_gerak_sumber"),
        ]
        constraints = [
            # Satu baris menyatakan SATU arah. Baris bermuatan dua arah membuat
            # setiap agregasi harus memutuskan sendiri artinya, dan dua tempat
            # yang memutuskan berbeda tidak akan pernah menghasilkan galat --
            # hanya dua angka yang berbeda.
            models.CheckConstraint(
                condition=models.Q(masuk=0) | models.Q(keluar=0),
                name="ck_gerak_satu_arah",
            ),
            models.CheckConstraint(
                condition=models.Q(masuk__gte=0) & models.Q(keluar__gte=0),
                name="ck_gerak_tak_negatif",
            ),
        ]

    def __str__(self):
        arah = f"+{self.masuk}" if self.masuk else f"-{self.keluar}"
        return f"{self.tanggal} {self.jenis} {arah}"


class StatusPenjualan(models.TextChoices):
    AKTIF = "aktif", "Aktif"
    BATAL = "batal", "Batal"


class JenisBayar(models.TextChoices):
    """Cara nota ini dibayar.

    Kolom TERPISAH dari `status`, dan itu memperbaiki penggabungan yang jadi
    sumber salah baca di legacy: di sana `t_penjualan.status` dipakai untuk
    KEDUANYA sekaligus (0=Kredit, 1=Tunai, 2=Lunas), sehingga tak ada tempat
    untuk menyatakan nota batal sama sekali -- dan siapa pun yang membacanya
    sebagai penanda batal akan melabeli setiap penjualan kredit sebagai batal.

    `LUNAS` memang bukan cara bayar, melainkan kredit yang sudah selesai. Ia
    tetap ada karena itulah yang tersimpan di data yang harus tetap terbaca;
    memecahnya jadi `kredit` + kolom pelunasan adalah keputusan yang butuh data
    cicilan, dan `t_piutang_cicilan` belum punya padanan di sini.
    """

    KREDIT = "kredit", "Kredit"
    TUNAI = "tunai", "Tunai"
    LUNAS = "lunas", "Lunas"


class Penjualan(models.Model):
    """Kepala nota penjualan.

    `total` adalah **kolom biasa**, dan itu keputusan yang dibayar mahal oleh
    legacy: di sana ia dipisah ke tabel 1:1 `t_penjualan_total`, dan cakupannya
    ternyata tidak seragam antar-server. Terukur di `grosirPusat`: 474.587 nota
    berbanding 259.250 baris total -- **215.337 nota (45%) tanpa pasangannya**,
    padahal keduanya diikat foreign key. Sebuah `INNER JOIN` di sana memangkas
    separuh omzet dari laporan tanpa satu pun galat.
    """

    nomor = models.CharField(max_length=30, unique=True)
    tanggal = models.DateField()
    divisi = models.ForeignKey(Divisi, on_delete=models.PROTECT)
    pelanggan_id = models.BigIntegerField(null=True, blank=True)  # FK menyusul di irisan berikutnya

    # NULL = nota ini tidak memakai voucher, dan itu bedanya dari legacy:
    # di sana `kd_voucher` kolom WAJIB yang diisi penanda "tanpa voucher"
    # (`V1`, `V2`, `VAA000` yang bernama `-`) pada 473.199 dari 474.595 nota
    # grosirPusat. Voucher sungguhan cuma tiga kode, 1.396 pemakaian.
    #
    # Penanda itu bukan sekadar jelek dipandang: laporan Voucher legacy
    # menghitung "dipakai" sebagai `kd_voucher <> ''`, jadi ketiga baris penanda
    # muncul di layar dengan pemakaian ratusan ribu. Adapter TIDAK memperbaiki
    # itu -- ia memulangkan apa adanya supaya laporan yang dipindahkan tetap
    # cocok angka. Yang diperbaiki adalah bentuk baru ini, tempat "tanpa
    # voucher" memang tidak perlu punya baris master.
    # Rujukan bertali teks: `Voucher` didefinisikan di bawah, di bagian kas.
    voucher = models.ForeignKey("Voucher", null=True, blank=True, on_delete=models.PROTECT)

    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    diskon = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    pajak = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    dibayar = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    jenis_bayar = models.CharField(max_length=10, choices=JenisBayar.choices, default=JenisBayar.TUNAI)
    status = models.CharField(max_length=10, choices=StatusPenjualan.choices, default=StatusPenjualan.AKTIF)
    dibuat_oleh = models.IntegerField(null=True, blank=True)  # id user aplikasi
    dibuat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "penjualan"
        indexes = [
            models.Index(fields=["tanggal"], name="ix_jual_tgl"),
            models.Index(fields=["divisi", "tanggal"], name="ix_jual_divisi_tgl"),
            models.Index(fields=["pelanggan_id", "tanggal"], name="ix_jual_pelanggan_tgl"),
        ]

    def __str__(self):
        return self.nomor


class PenjualanBaris(models.Model):
    """Baris nota.

    Sengaja TANPA unique constraint pada (penjualan, barang): satu nota yang sah
    bisa memuat barang yang sama dua kali dengan harga atau diskon berbeda.
    Legacy tak punya primary key sama sekali di tabel ini -- yang berlebihan ke
    arah sebaliknya, dan itulah yang dulu memaksa sinkronisasi memakai CDC alih-
    alih replikasi biasa. Di sini kuncinya `id`, dan itu cukup.
    """

    penjualan = models.ForeignKey(Penjualan, on_delete=models.CASCADE, related_name="baris")
    barang = models.ForeignKey(Barang, on_delete=models.PROTECT)
    satuan = models.ForeignKey(Satuan, on_delete=models.PROTECT)

    qty = models.DecimalField(max_digits=18, decimal_places=3)
    harga = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    diskon = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = "penjualan_baris"
        indexes = [models.Index(fields=["barang"], name="ix_jual_baris_barang")]

    def __str__(self):
        return f"{self.penjualan_id} {self.barang_id} x{self.qty}"



# --- Pembelian -------------------------------------------------------------
#
# Cermin penjualan, dan sengaja cermin: bentuk yang sama berarti satu cara
# membaca, satu cara menulis laporan, dan satu tempat memperbaiki kalau salah.
# Yang berbeda cuma sisi lawannya -- pemasok menggantikan pelanggan.


class Pembelian(models.Model):
    """Kepala nota pembelian.

    `jenis_bayar` datang dari `t_pembelian.status`, dan itu BUKAN tebakan:
    view legacy `mon_t_pembelian` memanggil `GetConvertStatus(beli.status)` lalu
    memberinya nama kolom **"Pembayaran"** -- UDF yang sama yang dipakai
    penjualan (0=Kredit, 1=Tunai, 2=Lunas). Jadi pembelian mewarisi penggabungan
    yang persis sama: satu kolom dipakai untuk cara bayar, dan tak ada tempat
    untuk menyatakan nota batal. Di sini keduanya dipisah, sama seperti di
    `Penjualan`.

    `t_pembelian.kd_jenis` adalah hal LAIN (JAA000/JAA001, merujuk
    `m_jenis_bayar`) dan sengaja belum dipetakan: belum ada laporan yang
    membutuhkannya, dan menebak arti kolom legacy adalah cara paling rapi untuk
    salah tanpa ketahuan.
    """

    nomor = models.CharField(max_length=30, unique=True)
    tanggal = models.DateField()
    divisi = models.ForeignKey(Divisi, on_delete=models.PROTECT)
    pemasok_id = models.BigIntegerField(null=True, blank=True)  # FK menyusul, spt pelanggan_id

    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    diskon = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    pajak = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    jenis_bayar = models.CharField(max_length=10, choices=JenisBayar.choices, default=JenisBayar.TUNAI)
    status = models.CharField(max_length=10, choices=StatusPenjualan.choices, default=StatusPenjualan.AKTIF)
    dibuat_oleh = models.IntegerField(null=True, blank=True)
    dibuat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pembelian"
        indexes = [
            models.Index(fields=["tanggal"], name="ix_beli_tgl"),
            models.Index(fields=["divisi", "tanggal"], name="ix_beli_divisi_tgl"),
            models.Index(fields=["pemasok_id", "tanggal"], name="ix_beli_pemasok_tgl"),
        ]

    def __str__(self):
        return self.nomor


class PembelianBaris(models.Model):
    """Baris nota pembelian. Tanpa unique constraint pada (pembelian, barang),
    alasan sama dengan `PenjualanBaris`."""

    pembelian = models.ForeignKey(Pembelian, on_delete=models.CASCADE, related_name="baris")
    barang = models.ForeignKey(Barang, on_delete=models.PROTECT)
    satuan = models.ForeignKey(Satuan, on_delete=models.PROTECT)

    qty = models.DecimalField(max_digits=18, decimal_places=3)
    harga = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    diskon = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = "pembelian_baris"
        indexes = [models.Index(fields=["barang"], name="ix_beli_baris_barang")]

    def __str__(self):
        return f"{self.pembelian_id} {self.barang_id} x{self.qty}"


# --- Master: wilayah, mitra, kas -------------------------------------------
#
# Ditambahkan di Fase 4 irisan 1. Bentuknya diturunkan dari kebutuhan, lalu
# DICOCOKKAN dengan kolom legacy yang benar-benar ada (diperiksa lewat
# INFORMATION_SCHEMA, bukan diingat). Dua koreksi yang lahir dari pemeriksaan itu
# tercatat di masing-masing kelas.


class Negara(Referensi):
    class Meta(Referensi.Meta):
        abstract = False
        db_table = "negara"


class Kota(Referensi):
    """`kode_telepon` = kode area. Legacy menyebutnya `kd_telp`.

    Legacy `m_kota` TIDAK punya kolom `keterangan` (5 kolom), tak seperti tabel
    referensi lain yang seragam. Karena itu `Referensi` di sini dipakai apa
    adanya tanpa menambah keterangan -- menambahkannya berarti kolom yang tak
    pernah bisa diisi adapter.
    """

    kode_telepon = models.CharField(max_length=4, blank=True)
    negara = models.ForeignKey(Negara, null=True, blank=True, on_delete=models.PROTECT)

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "kota"


class Bank(Referensi):
    keterangan = models.CharField(max_length=50, blank=True)

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "bank"


class Mitra(models.Model):
    """Induk abstrak pelanggan & pemasok: keduanya orang/badan dengan alamat.

    Digabung karena kolomnya memang sama sembilan dari sepuluh, bukan demi
    kerapian. Yang berbeda tetap dipisah ke kelas turunannya.
    """

    kode = models.CharField(max_length=20, unique=True)
    nama = models.CharField(max_length=100)
    alamat = models.CharField(max_length=200, blank=True)
    kota = models.ForeignKey(Kota, null=True, blank=True, on_delete=models.PROTECT)
    telepon = models.CharField(max_length=20, blank=True)
    hp = models.CharField(max_length=20, blank=True)
    email = models.CharField(max_length=60, blank=True)
    kontak = models.CharField(max_length=50, blank=True)
    keterangan = models.CharField(max_length=200, blank=True)
    aktif = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["nama"]

    def __str__(self):
        return f"{self.kode} {self.nama}"


class Pelanggan(Mitra):
    """`batas_piutang` = `m_customer.limit_kredit`.

    Rancangan awal juga menyebut `tempo_hari`, dan itu DIBUANG setelah kolom
    `m_customer` diperiksa: 19 kolom, tak satu pun menyimpan tempo pembayaran.
    Memasangnya berarti kolom yang selamanya kosong di mode legacy -- adapter
    tak punya apa pun untuk diisikan ke sana. Tambahkan kalau suatu hari ada
    layar yang benar-benar memakainya.
    """

    batas_piutang = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    diskon_persen = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta(Mitra.Meta):
        abstract = False
        db_table = "pelanggan"


class Pemasok(Mitra):
    """**`aktif` di sini tidak punya padanan di legacy, dan itu disengaja.**

    `m_supplier` punya 13 kolom dan tak satu pun berupa status (diverifikasi
    lewat INFORMATION_SCHEMA). Karena DELETE juga dilarang di sana -- relasi
    tabel referensi memakai ON DELETE CASCADE yang menjangkau `m_barang` --
    sebuah pemasok yang salah ketik tidak bisa dibatalkan dengan cara APA PUN.
    Adapter mengisinya konstan aktif; skema Arunika sendiri bisa menonaktifkan.
    """

    bank = models.ForeignKey(Bank, null=True, blank=True, on_delete=models.PROTECT)
    rekening = models.CharField(max_length=30, blank=True)

    class Meta(Mitra.Meta):
        abstract = False
        db_table = "pemasok"


class Kas(Referensi):
    """Akun kas/rekening.

    Kolom manusiawinya di legacy bernama `cabang`, BUKAN `nama` -- `m_kas` tak
    punya kolom `nama` sama sekali. Di sini ia `nama`, apa adanya, dan
    pemetaannya dikerjakan adapter.
    """

    no_rekening = models.CharField(max_length=30, blank=True)
    bank = models.ForeignKey(Bank, null=True, blank=True, on_delete=models.PROTECT)
    kota = models.ForeignKey(Kota, null=True, blank=True, on_delete=models.PROTECT)
    telepon = models.CharField(max_length=20, blank=True)
    kontak = models.CharField(max_length=50, blank=True)
    saldo_awal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    keterangan = models.CharField(max_length=50, blank=True)

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "kas"


class JenisBiaya(models.TextChoices):
    """Bagian biaya di laporan laba rugi.

    Legacy menyimpannya di `m_biaya.status` -- kolom yang sama yang tampak
    seperti bendera aktif dan sempat dibaca begitu. Yang membantahnya view
    legacy sendiri: `mon_m_biaya` menamai hasil CASE-nya `Jenis`, dan dua view
    laba rugi menyaring `status = 1` dan `status = 2` sebagai dua bagian biaya.
    """

    PENJUALAN = "penjualan", "Operasional (Penjualan)"
    ADM_UMUM = "adm_umum", "Operasional (Adm. dan Umum)"
    PRODUKSI_LANGSUNG = "produksi_langsung", "Produksi (Biaya Langsung)"
    PRODUKSI_TAK_LANGSUNG = "produksi_tak_langsung", "Produksi (Biaya Tak Langsung)"


class KategoriBiaya(Referensi):
    """Jenis biaya operasional.

    Di legacy, "aktif" pada `m_biaya` bernilai **2, bukan 1** -- seluruh 38
    barisnya bernilai 2. Nilai ajaib seperti itu berhenti di sini: `aktif`
    adalah boolean, dan penerjemahannya urusan adapter.
    """

    keterangan = models.CharField(max_length=50, blank=True)

    # `jenis` adalah kolom TERSENDIRI, dan itu perbaikan bukan tambahan: di
    # legacy ia berbagi tempat dengan apa yang dikira bendera aktif. `aktif`
    # sendiri milik Arunika -- `m_biaya` tak punya padanannya sama sekali.
    jenis = models.CharField(max_length=24, choices=JenisBiaya.choices,
                             default=JenisBiaya.ADM_UMUM)

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "kategori_biaya"


class Voucher(Referensi):
    nominal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    keterangan = models.CharField(max_length=50, blank=True)

    class Meta(Referensi.Meta):
        abstract = False
        db_table = "voucher"

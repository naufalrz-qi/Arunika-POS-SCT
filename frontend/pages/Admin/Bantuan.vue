<script setup>
// Halaman referensi statis. SUMBER TUNGGAL semua definisi istilah — panduan
// alur kerja (PANDUAN-PENGGUNA.md) sengaja tidak mengulangnya, cukup menunjuk
// ke sini, supaya keduanya tak bisa saling menyimpang.
//
// Angka ambang di bawah disalin dari kode, bukan dikarang:
//   - Kritis/Overstock: apps/transactions/reports.py (_FMI_STOK_KRITIS_HARI=7,
//     _FMI_STOK_OVERSTOCK_HARI=90)
//   - Batas rentang laporan 92 hari: apps/core/reporting.py
//   - Cache perbandingan 10 menit: core/cache.py (_MASTER_TTL=600)
// Kalau salah satunya berubah, ubah juga di sini.
import { Link } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Banner from "@/components/ui/Banner.vue";

const istilah = [
  { t: "FMI", d: "Fast / Medium / Idle Moving — pengelompokan barang menurut kecepatan lakunya. Fast = cepat laku, Medium = sedang, Idle = nyaris tidak bergerak.", ke: "/admin-panel/analitik/fmi-penjualan", nama: "FMI Penjualan" },
  { t: "Divisi", d: "Pembagian tempat/unit penyimpanan stok di dalam satu server. Satu barang bisa punya stok berbeda di tiap divisi." },
  { t: "Opname", d: "Pencocokan stok fisik dengan stok di sistem. Selisihnya dicatat sebagai koreksi.", ke: "/admin-panel/inventory/opname", nama: "Opname Stok" },
  { t: "Mutasi", d: "Perpindahan stok antar divisi/gudang. Berbeda dari Opname: mutasi memindahkan, opname mengoreksi.", ke: "/admin-panel/inventory/mutasi-stok", nama: "Mutasi Stok" },
  { t: "Stok Awal", d: "Saldo pembukaan barang, dihitung dari tanggal tutup buku terakhir. Bukan pergerakan, jadi tidak ikut disaring oleh filter tanggal." },
  { t: "Stok Akhir", d: "Saldo pada satu titik waktu = stok awal + barang masuk − barang keluar.", ke: "/admin-panel/inventory/stock", nama: "Stok Akhir" },
  { t: "Tutup Buku", d: "Tanggal penguncian pembukuan. Jadi lantai perhitungan: sistem tidak menghitung mundur melewatinya. Tutup buku yang sudah lama membuat semua laporan stok berat." },
  { t: "HPP / Harga Pokok", d: "Dua sebutan untuk hal yang sama: modal barang. Dipakai untuk menghitung laba.", ke: "/admin-panel/laporan/penjualan-hpp", nama: "Laba per Barang" },
  { t: "Margin", d: "Selisih harga jual dengan harga pokok, dinyatakan sebagai persentase terhadap harga jual." },
  { t: "Replica Laporan", d: "Salinan data khusus untuk laporan berat, supaya tidak mengganggu kasir yang sedang bertransaksi. Angkanya bisa telat 1–2 menit dari server utama." },
  { t: "Ringkasan Stok Harian", d: "Rekap saldo stok yang dibuat otomatis tiap malam. Perhitungan stok memakainya sebagai titik awal supaya cepat. Kalau ringkasan ini belum siap, halaman tetap benar tapi jadi lambat." },
  { t: "Customer = Pelanggan", d: "Dua kata untuk hal yang sama; sebagian laporan memakai istilah \"Customer\", menu master memakai \"Pelanggan\". Sumbernya tabel pelanggan yang sama." },
  { t: "Satuan & faktor konversi", d: "Satu barang bisa punya beberapa satuan (pcs, lusin, dus). Faktor konversi menyatakan berapa satuan terkecil per satu satuan besar. Semua stok dihitung dalam satuan terkecil lalu ditampilkan kembali." },
  { t: "Fast Moving Bulan Ini", d: "Panel di Dashboard: barang paling laku bulan berjalan. Istilah yang sama dengan \"Fast\" pada FMI." },
  { t: "Segmen Pelanggan", d: "Nama kelompok pelanggan menurut kebiasaan belanjanya: Baru (belanja pertamanya belum lama), Aktif (masih rutin datang), Setia (rutin datang DAN sudah banyak nota), Mulai Jarang (sudah agak lama tidak datang), Hilang (sudah lama sekali tidak datang). Dipakai untuk menyusun daftar pelanggan yang perlu dihubungi.", ke: "/admin-panel/analitik/klasifikasi-pelanggan", nama: "Klasifikasi Pelanggan" },
  { t: "Jeda (hari)", d: "Berapa hari sejak pelanggan itu belanja terakhir. Semakin besar, semakin lama ia tidak datang. Angka inilah yang paling menentukan segmennya — pelanggan yang baru sekali datang tapi itu setahun lalu dihitung Hilang, bukan Baru." },
  { t: "Rata per Nota", d: "Total belanja dibagi jumlah notanya. Menjawab \"sekali datang biasanya belanja berapa\", yang bisa berbeda jauh dari total belanja: pelanggan dengan 20 nota kecil bisa bertotal sama dengan pelanggan satu nota besar." },
  { t: "Kelas Nilai", d: "Pengelompokan Besar/Sedang/Kecil berdasarkan Rata per Nota, bukan total belanja. Batasnya bisa diubah di panel filter." },
  { t: "Lama Jadi Pelanggan", d: "Berapa hari sejak belanja PERTAMA-nya. Dipakai membedakan pelanggan baru dari pelanggan lama yang kebetulan sedang jarang datang." },
  { t: "Identitas Barang", d: "Nama dan keterangan barang. Berbeda dari harga: harga boleh beda per server, tapi nama harus sama di semua cabang karena ia muncul di nota dan laporan. Karena itu hanya server GUDANG yang bisa mengubahnya; cabang lain menerimanya lewat Sinkronisasi Master Data.", ke: "/admin-panel/master/update-barang", nama: "Update Barang" },
  { t: "Saran Harga", d: "Usulan harga jual yang dihitung sistem. Sumbernya berbeda per jenis server: di toko retail dari nominal yang ditulis di kolom keterangan barang, di server lain dari harga jual di server gudang acuannya. Usulan saja — tidak otomatis dipakai." },
  { t: "Sumber Modal", d: "Server yang jadi acuan bagi server lain: untuk harga pokok, dan untuk saran harga di server non-retail. Diatur per koneksi di menu Koneksi Server. TIDAK wajib diisi. Kalau kosong — atau server acuannya sedang mati — yang hilang hanya kolom Modal & Margin dan daftar Saran Harga. Mencari barang dan mengubah harga tetap berjalan normal.", ke: "/admin-panel/connections", nama: "Koneksi Server" },
  { t: "UMUM / ECERAN / OBRAL", d: "Bukan nama orang, melainkan penampung transaksi untuk pembeli yang tidak dicatat identitasnya. Di halaman Klasifikasi Pelanggan ketiganya sengaja tidak ditampilkan — tidak ada yang bisa dihubungi. Akun marketplace (Shopee/Tokopedia/TikTok) juga dikecualikan karena itu kanal jualan, bukan orang." },
];
</script>

<template>
  <AdminLayout title="Bantuan & Istilah">
    <Card class="mb-4">
      <h2 class="mb-1 text-base font-semibold text-ink">Bantuan &amp; Istilah</h2>
      <p class="text-sm text-ink-muted">
        Halaman ini menjelaskan arti istilah dan angka yang muncul di aplikasi. Untuk langkah
        kerja sehari-hari, lihat dokumen <strong>Panduan Pengguna</strong> dari admin Anda.
      </p>
    </Card>

    <Card class="mb-4">
      <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">1. Istilah</h3>
      <dl class="space-y-3">
        <div v-for="i in istilah" :key="i.t" class="border-b border-border-default pb-3 last:border-0 last:pb-0">
          <dt class="text-sm font-semibold text-ink">{{ i.t }}</dt>
          <dd class="mt-0.5 text-sm text-ink-muted">
            {{ i.d }}
            <Link v-if="i.ke" :href="i.ke" class="ml-1 text-brand-400 hover:underline">Buka {{ i.nama }} →</Link>
          </dd>
        </div>
      </dl>
    </Card>

    <Card class="mb-4">
      <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">2. Cara membaca angka</h3>
      <ul class="space-y-2 text-sm text-ink-muted">
        <li>
          <strong class="text-ink">Stok per Divisi selalu menampilkan hari ini.</strong>
          Halaman itu untuk cek cepat. Untuk saldo pada tanggal lampau, pakai
          <Link href="/admin-panel/inventory/stock" class="text-brand-400 hover:underline">Stok Akhir</Link>.
        </li>
        <li>
          <strong class="text-ink">Batas rentang laporan 92 hari.</strong> Kalau Anda memilih rentang
          lebih panjang, sistem memangkasnya dan menampilkan banner biru. Itu pemberitahuan,
          bukan kegagalan — banner kuning barulah tanda ada masalah koneksi.
        </li>
        <li>
          <strong class="text-ink">Laporan dari replica bisa telat 1–2 menit</strong> dari transaksi
          yang baru saja terjadi di kasir.
        </li>
        <li>
          <strong class="text-ink">Status FMI Stok</strong> dihitung dari perkiraan sisa hari stok pada
          laju penjualan sekarang: <em>Kritis</em> = kurang dari 7 hari; <em>Overstock</em> = lebih dari
          90 hari, atau barang tidak pernah laku; <em>Sehat</em> = di antara keduanya.
        </li>
        <li>
          <strong class="text-ink">Angka stok berwarna merah</strong> berarti stoknya di bawah stok
          minimum yang disetel untuk barang tersebut.
        </li>
      </ul>
    </Card>

    <Card class="mb-4">
      <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        3. Aksi yang mengubah data di server
      </h3>
      <Banner
        variant="warning"
        message="Perbandingan pada halaman sinkronisasi dihitung dari data yang disimpan sementara hingga 10 menit. Muat ulang halaman sebelum menyinkronkan, supaya yang Anda timpa benar-benar yang Anda lihat."
        class="mb-3"
      />
      <ul class="space-y-2 text-sm text-ink-muted">
        <li><strong class="text-ink">Sinkronisasi Harga → "Sinkronkan Terpilih"</strong> menimpa harga jual di server tujuan. <strong>Tidak bisa dibatalkan.</strong></li>
        <li><strong class="text-ink">Sinkronisasi Master Data → "Sinkronkan Terpilih"</strong> menimpa <em>seluruh baris</em> di server tujuan, kecuali beberapa kolom yang sengaja dikecualikan (tanggal daftar barang, poin pelanggan). <strong>Tidak bisa dibatalkan.</strong></li>
        <li><strong class="text-ink">Update Barang</strong> dan <strong class="text-ink">Harga Massal</strong> mengubah harga di server yang sedang aktif.</li>
        <li><strong class="text-ink">Update Status</strong> mengubah ketersediaan barang.</li>
      </ul>
      <p class="mt-3 text-sm text-ink-muted">
        Semua perubahan tercatat di
        <Link href="/admin-panel/logs" class="text-brand-400 hover:underline">Log Aktivitas</Link>,
        <Link href="/admin-panel/master/riwayat-update-barang" class="text-brand-400 hover:underline">Riwayat Update Barang</Link>, dan
        <Link href="/admin-panel/master/sync-history" class="text-brand-400 hover:underline">Riwayat Sinkronisasi</Link>.
      </p>
    </Card>

    <Card>
      <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">4. Kalau bermasalah</h3>
      <ul class="space-y-2 text-sm text-ink-muted">
        <li><strong class="text-ink">Banner kuning</strong> = ada yang gagal (server tak terhubung, data tak terbaca). <strong class="text-ink">Banner biru</strong> = pemberitahuan biasa, data tetap benar.</li>
        <li><strong class="text-ink">Tiba-tiba diminta masuk lagi</strong> = sesi berakhir. Sesi berlaku 4 jam sejak Anda masuk, dan tidak diperpanjang oleh aktivitas. Masuk kembali, lalu ulangi perubahan terakhir.</li>
        <li><strong class="text-ink">Halaman berputar lama lalu muncul banner kuning</strong> = server yang dipilih di navbar tidak merespons. Coba pilih koneksi lain.</li>
        <li><strong class="text-ink">Stok terasa lambat</strong> dan muncul peringatan jalur lambat = rekap stok harian belum siap. Angkanya tetap benar. Hubungi admin aplikasi.</li>
        <li><strong class="text-ink">Menu yang Anda butuhkan tidak ada</strong> = belum diberikan untuk akun Anda. Minta ke superadmin.</li>
      </ul>
    </Card>
  </AdminLayout>
</template>

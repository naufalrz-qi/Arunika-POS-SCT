<script setup>
import { computed, onMounted } from "vue";

// Faktur untuk Epson LX-310 (dot matrix 9-pin).
//
// Yang dicetak dot matrix dengan cepat dan benar adalah TEKS monospace pada
// lebar kolom tetap. Kalau halaman ini memakai tabel/border/warna, driver
// Windows mengirimnya sebagai GRAFIS — hasilnya lambat, buram, dan boros pita.
// Karena itu seluruh isi di bawah dibangun sebagai teks selebar LEBAR karakter,
// dan CSS cetaknya membuang segala hiasan.
// `auto` mati saat berkas ini dipakai sebagai komponen di layar Cetak Faktur:
// di sana kasir mengetik nomor dulu, dan dialog cetak yang menyembul sendiri
// tiap kali hasil muncul membuat nomor berikutnya tak bisa diketik.
const props = defineProps({
  nota: { type: Object, required: true },
  auto: { type: Boolean, default: true },
});

// LX-310 mencetak 80 kolom pada 10 CPI, dan `@page` di bawah memang continuous
// form 9,5". Tata letak dua kolom (metadata kiri/kanan, keterangan berdampingan
// dengan blok total) hanya muat pada lebar ini — versi 40 kolom sebelumnya
// memaksa semuanya bertumpuk ke bawah. Ini SATU angka: mengecilkannya kembali
// ke 40 membuat seluruh tata letak mengalir ulang tanpa mengubah kode lain.
const LEBAR = 80;
const KIRI = 41; // lebar kolom kiri pada bagian dua-kolom

const rp = (v) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Number(v) || 0);

const kiriKanan = (kiri, kanan, lebar = LEBAR) => {
  const sisa = Math.max(1, lebar - kiri.length - kanan.length);
  return kiri + " ".repeat(sisa) + kanan;
};
const garis = (ch = "-") => ch.repeat(LEBAR);
const tengah = (t) => {
  const pad = Math.max(0, Math.floor((LEBAR - t.length) / 2));
  return " ".repeat(pad) + t;
};

// Bungkus per kata, jangan potong. Nama barang dan alamat sama-sama bisa
// melewati satu baris; memotongnya membuang justru bagian yang membedakan
// ("BONEKA BERUANG COKELAT BESAR" vs "... KECIL").
const bungkus = (teks, lebar = LEBAR) => {
  const out = [];
  let sisa = String(teks || "").trim();
  while (sisa.length > lebar) {
    let idx = sisa.lastIndexOf(" ", lebar);
    if (idx <= 0) idx = lebar;
    out.push(sisa.slice(0, idx).trim());
    sisa = sisa.slice(idx).trim();
  }
  if (sisa.length) out.push(sisa);
  return out;
};

// Label berlabuh di kolom yang sama supaya titik duanya sejajar satu garis.
const info = (label, nilai, lebarLabel) =>
  `${label.padEnd(lebarLabel)}: ${nilai}`;

// Satu baris dari dua kolom yang berdiri berdampingan.
const duaKolom = (kiri, kanan) => (kiri.padEnd(KIRI) + kanan).trimEnd();

const tanggalJam = (v) => {
  if (!v) return "";
  const s = String(v).replace("T", " ");
  const [tgl, jam = ""] = s.split(" ");
  const [y, m, d] = tgl.split("-");
  return y && m && d ? `${d}/${m}/${y} ${jam.slice(0, 5)}`.trim() : s.slice(0, 16);
};

const semua = computed(() => {
  const n = props.nota;
  const L = [];

  // 1. Kop — identitas perusahaan koneksi ini (core.InfoPerusahaan, dengan
  //    g_info_profile sebagai cadangan). Nama perusahaannya ditebalkan di
  //    template; lihat `kop` di bawah.
  L.push(tengah((n.toko || "SUKSES CROWN TOYS").slice(0, LEBAR)));
  for (const b of bungkus(n.alamat)) L.push(tengah(b));
  if (n.telepon) L.push(tengah(`Telp. ${n.telepon}`.slice(0, LEBAR)));
  L.push(garis("="));

  // 2. Metadata dua kolom. Kiri identitas notanya, kanan identitas pihaknya.
  //    Label "Kasir" sengaja diisi PEGAWAI yang melayani, mengikuti template —
  //    nama pemilik akun yang menulis nota (`n.kasir`) tetap ada di payload dan
  //    di laporan Penjualan per User untuk jejak audit, tapi tak dicetak.
  const kanan = [];
  kanan.push(info("Status", n.status_bayar || "LUNAS", 6));
  kanan.push(info("Cust", n.customer || n.kd_customer || "UMUM", 6));
  if (n.pegawai) kanan.push(info("Kasir", n.pegawai, 6));
  if (n.jatuh_tempo && n.kd_jenis && n.kd_jenis !== "JAA000")
    kanan.push(info("Tempo", tanggalJam(n.jatuh_tempo).split(" ")[0], 6));

  const kiri = [];
  kiri.push(info("Date", tanggalJam(n.tanggal), 12));
  kiri.push(info("No Transaksi", n.no_transaksi || "", 12));
  if (n.no_bukti) kiri.push(info("No Bukti", n.no_bukti, 12));

  for (let i = 0; i < Math.max(kiri.length, kanan.length); i++)
    L.push(duaKolom(kiri[i] || "", kanan[i] || ""));

  L.push("Item & Desc");
  L.push(garis());

  // 3. Detail barang. Kode barang TIDAK dicetak: ini struk untuk pelanggan, dan
  //    kode seperti `TY-001333` cuma berarti bagi orang dalam toko.
  for (const b of n.baris || []) {
    for (const t of bungkus(b.nama)) L.push(t);
    L.push(kiriKanan(`          ${rp(b.qty)} ${b.satuan} x ${rp(b.harga)}`, rp(b.bruto)));
    // Tanpa baris ini, "4 PCS x 5.600" di atas tidak akan menjumlah ke Sub
    // Total pada 49.181 baris legacy yang memang berdiskon.
    if (b.diskon)
      L.push(kiriKanan(`          Disc ${b.diskon_label || ""}`, `-${rp(b.diskon)}`));
  }
  L.push(garis());

  // 4. Dua kolom: keterangan & tanda tangan di kiri, uang di kanan.
  const uang = [];
  const jml = (n.baris || []).length;
  // Yang dijumlah BARISNYA, bukan qty-nya: satuan tiap baris bisa berbeda
  // (PCS, LUSIN, RTG), jadi menjumlahkan angka qty menghasilkan bilangan tanpa
  // satuan yang justru menyesatkan.
  if (jml) uang.push(info("Jumlah", `${jml} barang`.padStart(20), 13));
  uang.push(info("Sub Total", rp(n.bruto).padStart(20), 13));
  uang.push(info("Diskon", rp(n.diskon).padStart(20), 13));
  // Voucher berdiri sendiri, bukan dilebur ke Diskon: pelanggan yang menyerahkan
  // voucher Rp50.000 berhak melihat vouchernya tercatat.
  if (n.voucher) uang.push(info("Klaim Vou", rp(n.voucher).padStart(20), 13));
  // Hampir tak pernah terpakai (2 nota dari seluruh riwayat server).
  if (n.pajak_rp)
    uang.push(info(`Pajak ${(Number(n.pajak) * 100).toFixed(2)}%`, rp(n.pajak_rp).padStart(20), 13));
  uang.push(info("Total", rp(n.total).padStart(20), 13));
  if (n.bayar != null) {
    uang.push(info("Bayar", rp(n.bayar).padStart(20), 13));
    uang.push(info("Kembali", rp(n.kembali).padStart(20), 13));
  }

  // Kolom kiri: keterangan lalu ruang tanda tangan. Keterangan selalu punya
  // tempat walau kolomnya kosong di database — kasir menulis tangan di situ.
  const sisi = ["Keterangan :"];
  const ket = bungkus(n.keterangan, KIRI - 2);
  sisi.push(...ket);
  for (let i = ket.length; i < 2; i++) sisi.push(".".repeat(KIRI - 4));
  sisi.push("");
  sisi.push("   Penerima,");
  sisi.push("");
  sisi.push("");
  sisi.push("   " + ".".repeat(24));

  for (let i = 0; i < Math.max(sisi.length, uang.length); i++)
    L.push(duaKolom(sisi[i] || "", uang[i] || ""));

  L.push(garis("="));
  L.push(tengah("- TERIMA KASIH ATAS KUNJUNGAN ANDA -"));
  L.push("");
  return L;
});

// Baris pertama (nama perusahaan) berdiri sendiri supaya bisa ditebalkan:
// <pre> tak bisa menebalkan satu baris tanpa elemen khusus untuknya.
const kop = computed(() => semua.value[0] || "");
const badan = computed(() => semua.value.slice(1).join("\n"));

// Langsung buka dialog cetak: halaman ini hanya pernah dibuka untuk dicetak.
const cetakUlang = () => window.print();
onMounted(() => {
  if (props.auto) setTimeout(cetakUlang, 300);
});
</script>

<template>
  <div class="cetak">
    <pre><b class="kop">{{ kop }}</b>
{{ badan }}</pre>
    <button class="sembunyi-cetak" @click="cetakUlang">Cetak ulang</button>
  </div>
</template>

<style scoped>
.cetak {
  background: #fff;
  color: #000;
  padding: 8px;
}
/* Satu-satunya penebalan di seluruh struk, dan itu disengaja. Pada LX-310 bold
   jatuh ke double-strike (kepala mengetuk dua kali) — tetap TEKS, bukan grafis;
   yang memaksa halaman jadi grafis adalah tabel/border/warna. Menebalkan banyak
   baris membuat cetaknya terasa lambat tanpa menambah kejelasan. */
.kop {
  font-weight: 700;
}
pre {
  font-family: "Courier New", Courier, monospace;
  /* 80 kolom harus muat di lebar cetak 8" LX-310. 10pt Courier ≈ 6pt per
     karakter ≈ 169mm untuk 80 kolom — masih di dalam 241mm dikurangi margin. */
  font-size: 10pt;
  line-height: 1.15;
  margin: 0;
  white-space: pre;
}
@media print {
  /* Continuous form 9,5". Tanpa margin bawaan browser, kertas tak bergeser
     antar-nota — pada continuous form pergeseran itu menumpuk. */
  @page {
    size: 241mm 140mm;
    margin: 4mm;
  }
  .sembunyi-cetak {
    display: none;
  }
}
</style>

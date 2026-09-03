<script setup>
import { computed, onMounted } from "vue";

// Faktur untuk Epson LX-310 (dot matrix 9-pin).
//
// Yang dicetak dot matrix dengan cepat dan benar adalah TEKS monospace pada
// lebar kolom tetap. Kalau halaman ini memakai tabel/border/warna, driver
// Windows mengirimnya sebagai GRAFIS — hasilnya lambat, buram, dan boros pita.
// Karena itu seluruh isi di bawah dibangun sebagai satu blok <pre> selebar 40
// karakter, dan CSS cetaknya membuang segala hiasan.
// `auto` mati saat berkas ini dipakai sebagai komponen di layar Cetak Faktur:
// di sana kasir mengetik nomor dulu, dan dialog cetak yang menyembul sendiri
// tiap kali hasil muncul membuat nomor berikutnya tak bisa diketik.
const props = defineProps({
  nota: { type: Object, required: true },
  auto: { type: Boolean, default: true },
});

const LEBAR = 40;
const rp = (v) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Number(v) || 0);
const kiriKanan = (kiri, kanan) => {
  const sisa = Math.max(1, LEBAR - kiri.length - kanan.length);
  return kiri + " ".repeat(sisa) + kanan;
};
const garis = (ch = "-") => ch.repeat(LEBAR);
const tengah = (t) => {
  const pad = Math.max(0, Math.floor((LEBAR - t.length) / 2));
  return " ".repeat(pad) + t;
};

// Bungkus per kata, jangan potong. Nama barang dan alamat sama-sama rutin
// melewati 40 kolom; memotongnya membuang justru bagian yang membedakan
// ("BONEKA BERUANG COKELAT BESAR" vs "... KECIL").
const bungkus = (teks, lebar = LEBAR, indent = "") => {
  const out = [];
  let sisa = String(teks || "").trim();
  while (sisa.length > lebar) {
    let idx = sisa.lastIndexOf(" ", lebar);
    if (idx <= 0) idx = lebar;
    out.push(sisa.slice(0, idx).trim());
    sisa = indent + sisa.slice(idx).trim();
  }
  if (sisa.length) out.push(sisa);
  return out;
};

// Label metadata dirata supaya titik dua dan nilainya sejajar satu kolom.
const LABEL = 13;
const info = (label, nilai) => `${label.padEnd(LABEL)}: ${nilai}`;

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

  // 1. Kop toko — seluruhnya dari g_info_profile.
  L.push(tengah((n.toko || "SUKSES CROWN TOYS").slice(0, LEBAR)));
  for (const b of bungkus(n.alamat)) L.push(tengah(b));
  if (n.telepon) L.push(tengah(`Telp : ${n.telepon}`.slice(0, LEBAR)));
  L.push(garis("="));

  // 2. Metadata. Baris yang nilainya kosong tidak dicetak sama sekali —
  //    "No. Bukti :" yang menggantung cuma menambah tinggi struk.
  L.push(info("Tanggal", tanggalJam(n.tanggal)));
  L.push(info("No. Transaksi", n.no_transaksi || ""));
  if (n.no_bukti) L.push(info("No. Bukti", n.no_bukti));
  if (n.jenis_bayar) L.push(info("Jenis Bayar", n.jenis_bayar.slice(0, LEBAR - LABEL - 2)));
  if (n.jatuh_tempo && n.kd_jenis && n.kd_jenis !== "JAA000")
    L.push(info("Jatuh Tempo", tanggalJam(n.jatuh_tempo).split(" ")[0]));
  // Kode pelanggan TIDAK dicetak, alasan yang sama dengan kode barang: ia kode
  // internal, dan yang memegang kertas ini pembelinya.
  L.push(info("Pelanggan", (n.customer || n.kd_customer || "UMUM").slice(0, LEBAR - LABEL - 2)));
  // Hanya yang MELAYANI. `kasir` (pemilik akun yang menulis nota) tetap ada di
  // payload dan di laporan Penjualan per User untuk jejak audit — dua nama orang
  // di struk tak berarti apa-apa bagi pembeli.
  if (n.pegawai) L.push(info("Pegawai", n.pegawai.slice(0, LEBAR - LABEL - 2)));
  L.push(garis());

  // 3. Detail barang.
  for (const b of n.baris || []) {
    // Kode barang SENGAJA tak dicetak: ini struk untuk pelanggan, dan kode
    // seperti `TY-001333` atau `SBN336` cuma berarti bagi orang dalam toko.
    for (const t of bungkus(b.nama)) L.push(t);
    L.push(`     ${rp(b.qty)} ${b.satuan} x ${rp(b.harga)} = ${rp(b.bruto)}`);
    // Tanpa baris ini, "2 x 2.500 = 5.000" di atas tidak akan menjumlah ke
    // Sub Total pada 49.181 baris legacy yang memang berdiskon.
    if (b.diskon)
      L.push(`     Disc ${b.diskon_label || ""} = ${rp(b.diskon)}`.replace("  =", " ="));
  }
  L.push(garis());

  // 4. Ringkasan. `Diskon` sudah digabung di server (diskon baris + diskon
  //    header + diskon_uang) supaya kolom ini benar-benar menjumlah.
  // Pembeli menghitung barang saat menerima, apalagi nota grosir yang belasan
  // baris. Yang dijumlah adalah BARISNYA, bukan qty-nya: satuan tiap baris bisa
  // berbeda (PCS, LUSIN, RTG), jadi menjumlahkan angkanya menghasilkan bilangan
  // tanpa satuan yang justru menyesatkan.
  const jml = (n.baris || []).length;
  if (jml) L.push(kiriKanan("Jumlah", `${jml} barang`));
  L.push(kiriKanan("Sub Total", rp(n.bruto)));
  if (n.diskon) L.push(kiriKanan("Diskon", rp(n.diskon)));
  // Hampir tak pernah terpakai (2 nota dari seluruh riwayat server) — baris
  // "Pajak 0" cuma menambah tinggi struk.
  if (n.pajak_rp) L.push(kiriKanan(`Pajak ${(Number(n.pajak) * 100).toFixed(2)}%`, rp(n.pajak_rp)));
  L.push(kiriKanan("Total", rp(n.total)));
  if (n.bayar != null) {
    L.push(kiriKanan("Bayar", rp(n.bayar)));
    L.push(kiriKanan("Kembali", rp(n.kembali)));
  }
  L.push(garis("="));

  // 5. Keterangan. Selalu ada ruangnya, walau kolomnya kosong di database —
  //    kasir menulis tangan di situ (catatan kirim, nama pengambil, dsb).
  L.push("Keterangan :");
  const ket = bungkus(n.keterangan);
  for (const t of ket) L.push(t);
  for (let i = ket.length; i < 2; i++) L.push(".".repeat(LEBAR));

  // 6. Tanda tangan. Hanya penerima — struk ini bukti terima barang, dan
  //    tanda tangan toko di atasnya tak pernah dibubuhkan siapa pun.
  L.push("");
  L.push("  Penerima,");
  L.push("");
  L.push("");
  L.push(" ..............");
  L.push(garis("="));
  L.push(tengah("Terima kasih atas kunjungan Anda"));
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
   jatuh ke double-strike (kepala mengetuk dua kali) — tetap TEKS, cuma sedikit
   lebih lambat per baris. Yang memaksa halaman jadi grafis adalah
   tabel/border/warna, bukan ini. Menebalkan banyak baris membuat cetaknya
   terasa lambat tanpa menambah kejelasan. */
.kop {
  font-weight: 700;
}
pre {
  font-family: "Courier New", Courier, monospace;
  font-size: 11pt;
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

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

const teks = computed(() => {
  const n = props.nota;
  const baris = [];
  baris.push(tengah(n.toko || "NOTA PENJUALAN"));
  baris.push(garis("="));
  baris.push(`No : ${n.no_transaksi}`);
  baris.push(`Tgl: ${String(n.tanggal || "").replace("T", " ").slice(0, 16)}`);
  baris.push(`Cus: ${(n.customer || n.kd_customer || "").slice(0, 33)}`);
  baris.push(garis());
  for (const b of n.baris || []) {
    // Nama barang di barisnya sendiri: 40 kolom tak cukup untuk nama + angka.
    baris.push((b.nama || b.kd_barang).slice(0, LEBAR));
    baris.push(
      kiriKanan(`  ${b.qty} ${b.satuan} x ${rp(b.harga)}`, rp(b.total)),
    );
  }
  baris.push(garis());
  if (n.diskon_uang) baris.push(kiriKanan("Diskon (Rp)", rp(n.diskon_uang)));
  if (n.pajak) baris.push(kiriKanan("Pajak", String(n.pajak)));
  baris.push(kiriKanan("TOTAL", rp(n.total)));
  baris.push(garis("="));
  if (n.keterangan && n.keterangan !== "-") baris.push(`Ket: ${n.keterangan}`);
  baris.push("");
  baris.push(tengah("Terima kasih"));
  baris.push("");
  return baris.join("\n");
});

// Langsung buka dialog cetak: halaman ini hanya pernah dibuka untuk dicetak.
const cetakUlang = () => window.print();
onMounted(() => {
  if (props.auto) setTimeout(cetakUlang, 300);
});
</script>

<template>
  <div class="cetak">
    <pre>{{ teks }}</pre>
    <button class="sembunyi-cetak" @click="cetakUlang">Cetak ulang</button>
  </div>
</template>

<style scoped>
.cetak {
  background: #fff;
  color: #000;
  padding: 8px;
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

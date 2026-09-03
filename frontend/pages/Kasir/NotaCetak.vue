<script setup>
import { computed, onMounted, onUnmounted, ref, watchEffect } from "vue";

// Faktur kasir. Tiga kertas dipakai bergantian di toko, dan lebarnya berbeda
// jauh — jadi tata letaknya TIDAK bisa satu ukuran.
//
// Yang dicetak dot matrix dengan cepat dan benar adalah TEKS monospace pada
// lebar kolom tetap. Kalau halaman ini memakai tabel/border/warna, driver
// Windows mengirimnya sebagai GRAFIS — lambat, buram, boros pita. Karena itu
// seluruh isi dibangun sebagai teks selebar `lebar` karakter.
//
// `auto` mati saat berkas ini dipakai sebagai komponen di layar Cetak Faktur:
// di sana kasir mengetik nomor dulu, dan dialog cetak yang menyembul sendiri
// tiap kali hasil muncul membuat nomor berikutnya tak bisa diketik.
const props = defineProps({
  nota: { type: Object, required: true },
  auto: { type: Boolean, default: true },
});

// Lebar kolom dihitung dari lebar cetak, bukan ditebak: Courier lebarnya 0,6 ×
// ukuran font, jadi `kolom x 0,6 x pt x 0,3528mm` harus muat di dalam kertas
// dikurangi margin. Angka `pt` di bawah sudah dicocokkan begitu.
//
// UKUR DULU SEBELUM PERCAYA: ketiga ukuran kertas ini dari keterangan operator,
// bukan dari mengukur kertasnya sendiri. Kalau hasil cetak membungkus atau
// terlalu renggang, yang diubah cuma `kolom`/`pt` di sini — seluruh tata letak
// mengalir ulang sendiri, tak ada kode lain yang perlu disentuh.
const KERTAS = {
  thermal: {
    label: "Struk thermal 76 mm (TM-U220)",
    kolom: 40, pt: 8.5, halaman: "76mm auto", margin: "2mm",
  },
  nota: {
    label: "Nota 12 x 14 cm (LX-310)",
    kolom: 48, pt: 11, halaman: "120mm 140mm", margin: "4mm",
  },
  a5: {
    label: "1/2 A4 potrait 14,8 x 21 cm (LX-310)",
    kolom: 64, pt: 10, halaman: "148mm 210mm", margin: "5mm",
  },
};
const SIMPANAN = "arunika.kertas-nota";

// Pilihan kertas melekat pada MESINNYA, bukan pada akun atau nota: satu PC
// kasir punya satu printer, dan yang di meja sebelah bisa lain. Karena itu
// localStorage, bukan setelan server. `?kertas=` tetap menang supaya bisa
// dicoba sekali tanpa mengubah setelan mesin itu.
const bawaan = () => {
  const dariUrl = new URLSearchParams(window.location.search).get("kertas");
  if (dariUrl && KERTAS[dariUrl]) return dariUrl;
  try {
    const disimpan = localStorage.getItem(SIMPANAN);
    if (disimpan && KERTAS[disimpan]) return disimpan;
  } catch { /* mode privat: pakai bawaan, jangan menahan kasir */ }
  return "nota";
};
const kertas = ref(typeof window === "undefined" ? "nota" : bawaan());
watchEffect(() => {
  try {
    localStorage.setItem(SIMPANAN, kertas.value);
  } catch { /* kuota/mode privat: pilihannya cuma tak awet */ }
});

const setelan = computed(() => KERTAS[kertas.value] || KERTAS.nota);
const lebar = computed(() => setelan.value.kolom);
// Di bawah 60 kolom, dua kolom berdampingan tak cukup ruang: label dan angkanya
// mulai bertabrakan. Yang sempit dituruni ke bawah, bukan dipaksakan.
const duaKolomMuat = computed(() => lebar.value >= 60);
const kiriLebar = computed(() => Math.floor(lebar.value * 0.52));

const rp = (v) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Number(v) || 0);

const kiriKanan = (kiri, kanan, w) => {
  const sisa = Math.max(1, w - kiri.length - kanan.length);
  return kiri + " ".repeat(sisa) + kanan;
};
const garis = (ch, w) => ch.repeat(w);
const tengah = (t, w) => " ".repeat(Math.max(0, Math.floor((w - t.length) / 2))) + t;

// Bungkus per kata, jangan potong. Nama barang dan alamat rutin melewati satu
// baris; memotongnya membuang justru bagian yang membedakan ("BONEKA BERUANG
// COKELAT BESAR" vs "... KECIL").
const bungkus = (teks, w) => {
  const out = [];
  let sisa = String(teks || "").trim();
  while (sisa.length > w) {
    let idx = sisa.lastIndexOf(" ", w);
    if (idx <= 0) idx = w;
    out.push(sisa.slice(0, idx).trim());
    sisa = sisa.slice(idx).trim();
  }
  if (sisa.length) out.push(sisa);
  return out;
};

const info = (label, nilai, lw) => `${label.padEnd(lw)}: ${nilai}`;

const tanggalJam = (v) => {
  if (!v) return "";
  const s = String(v).replace("T", " ");
  const [tgl, jam = ""] = s.split(" ");
  const [y, m, d] = tgl.split("-");
  return y && m && d ? `${d}/${m}/${y} ${jam.slice(0, 5)}`.trim() : s.slice(0, 16);
};

const semua = computed(() => {
  const n = props.nota;
  const w = lebar.value;
  const L = [];
  const dua = (kiri, kanan) => (kiri.padEnd(kiriLebar.value) + kanan).trimEnd();

  // 1. Kop — identitas perusahaan koneksi ini (core.InfoPerusahaan, dengan
  //    g_info_profile sebagai cadangan). Nama perusahaannya ditebalkan.
  L.push(tengah((n.toko || "SUKSES CROWN TOYS").slice(0, w), w));
  for (const b of bungkus(n.alamat, w)) L.push(tengah(b, w));
  if (n.telepon) L.push(tengah(`Telp. ${n.telepon}`.slice(0, w), w));
  L.push(garis("=", w));

  // 2. Metadata. Label "Kasir" sengaja diisi PEGAWAI yang melayani, mengikuti
  //    template cetak toko — nama pemilik akun yang menulis nota tetap ada di
  //    payload dan di laporan Penjualan per User untuk jejak audit.
  const kanan = [
    info("Status", n.status_bayar || "LUNAS", 6),
    info("Cust", n.customer || n.kd_customer || "UMUM", 6),
  ];
  if (n.pegawai) kanan.push(info("Kasir", n.pegawai, 6));
  if (n.jatuh_tempo && n.kd_jenis && n.kd_jenis !== "JAA000")
    kanan.push(info("Tempo", tanggalJam(n.jatuh_tempo).split(" ")[0], 6));

  const kiri = [
    info("Date", tanggalJam(n.tanggal), 12),
    info("No Transaksi", n.no_transaksi || "", 12),
  ];
  if (n.no_bukti) kiri.push(info("No Bukti", n.no_bukti, 12));

  if (duaKolomMuat.value) {
    for (let i = 0; i < Math.max(kiri.length, kanan.length); i++)
      L.push(dua(kiri[i] || "", kanan[i] || ""));
  } else {
    // Sempit: label dipendekkan supaya nilainya tak terdorong ke luar kertas.
    L.push(info("Tgl", tanggalJam(n.tanggal), 6));
    L.push(info("No", n.no_transaksi || "", 6));
    if (n.no_bukti) L.push(info("Bukti", n.no_bukti, 6));
    for (const b of kanan) L.push(b);
  }

  L.push("Item & Desc");
  L.push(garis("-", w));

  // 3. Detail barang. Kode barang TIDAK dicetak: ini struk untuk pelanggan, dan
  //    kode seperti `TY-001333` cuma berarti bagi orang dalam toko.
  const jorok = duaKolomMuat.value ? "          " : "  ";
  for (const b of n.baris || []) {
    for (const t of bungkus(b.nama, w)) L.push(t);
    L.push(kiriKanan(`${jorok}${rp(b.qty)} ${b.satuan} x ${rp(b.harga)}`, rp(b.bruto), w));
    // Tanpa baris ini, "4 PCS x 5.600" di atas tidak akan menjumlah ke Sub
    // Total pada 49.181 baris legacy yang memang berdiskon.
    if (b.diskon)
      L.push(kiriKanan(`${jorok}Disc ${b.diskon_label || ""}`, `-${rp(b.diskon)}`, w));
  }
  L.push(garis("-", w));

  // 4. Blok uang.
  const lebarUang = duaKolomMuat.value ? w - kiriLebar.value : w;
  const uang = [];
  const baris = (label, nilai) => uang.push(kiriKanan(label, nilai, lebarUang));
  // Yang dijumlah BARISNYA, bukan qty-nya: satuan tiap baris bisa berbeda
  // (PCS, LUSIN, RTG), jadi menjumlahkan angka qty menghasilkan bilangan tanpa
  // satuan yang justru menyesatkan.
  const jml = (n.baris || []).length;
  if (jml) baris("Jumlah", `${jml} barang`);
  baris("Sub Total", rp(n.bruto));
  baris("Diskon", rp(n.diskon));
  // Voucher berdiri sendiri: `t_penjualan_total.total` sudah memotongnya, jadi
  // tanpa dipisah ia tercetak sebagai "Diskon" dan pelanggan yang menyerahkan
  // voucher Rp50.000 tak punya bukti vouchernya dipakai.
  if (n.voucher) baris("Klaim Vou", rp(n.voucher));
  // Hampir tak pernah terpakai (2 nota dari seluruh riwayat server).
  if (n.pajak_rp) baris(`Pajak ${(Number(n.pajak) * 100).toFixed(2)}%`, rp(n.pajak_rp));
  baris("Total", rp(n.total));
  if (n.bayar != null) {
    baris("Bayar", rp(n.bayar));
    baris("Kembali", rp(n.kembali));
  }

  // 5. Keterangan & tanda tangan. Keterangan selalu punya tempat walau kolomnya
  //    kosong di database — kasir menulis tangan di situ.
  const sisiLebar = duaKolomMuat.value ? kiriLebar.value : w;
  const sisi = ["Keterangan :"];
  const ket = bungkus(n.keterangan, sisiLebar - 2);
  sisi.push(...ket);
  for (let i = ket.length; i < 2; i++) sisi.push(".".repeat(Math.max(10, sisiLebar - 4)));
  sisi.push("", "   Penerima,", "", "", "   " + ".".repeat(Math.max(10, sisiLebar - 16)));

  if (duaKolomMuat.value) {
    for (let i = 0; i < Math.max(sisi.length, uang.length); i++)
      L.push(dua(sisi[i] || "", uang[i] || ""));
  } else {
    L.push(...uang, garis("-", w), ...sisi);
  }

  L.push(garis("=", w));
  L.push(tengah("- TERIMA KASIH ATAS KUNJUNGAN ANDA -".slice(0, w), w));
  L.push("");
  return L;
});

// Baris pertama (nama perusahaan) berdiri sendiri supaya bisa ditebalkan:
// <pre> tak bisa menebalkan satu baris tanpa elemen khusus untuknya.
const kop = computed(() => semua.value[0] || "");
const badan = computed(() => semua.value.slice(1).join("\n"));

// `@page` tak bisa ditulis di CSS scoped yang nilainya berubah-ubah, jadi satu
// elemen <style> dikelola sendiri. Ukuran halaman WAJIB ikut berganti: kalau
// tidak, kertas thermal dicetak pada bidang A4 dan tiap struk memakan satu
// lembar penuh.
let elGaya = null;
watchEffect(() => {
  if (typeof document === "undefined") return;
  if (!elGaya) {
    elGaya = document.createElement("style");
    document.head.appendChild(elGaya);
  }
  const s = setelan.value;
  elGaya.textContent =
    `@media print { @page { size: ${s.halaman}; margin: ${s.margin}; } }`;
});
onUnmounted(() => {
  elGaya?.remove();
  elGaya = null;
});

const cetakUlang = () => window.print();
onMounted(() => {
  if (props.auto) setTimeout(cetakUlang, 300);
});
</script>

<template>
  <div class="cetak">
    <label class="sembunyi-cetak pemilih">
      Kertas:
      <select v-model="kertas">
        <option v-for="(k, kunci) in KERTAS" :key="kunci" :value="kunci">{{ k.label }}</option>
      </select>
    </label>
    <pre :style="{ fontSize: setelan.pt + 'pt' }"><b class="kop">{{ kop }}</b>
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
.pemilih {
  display: block;
  margin-bottom: 8px;
  font: 13px system-ui, sans-serif;
  color: #000;
}
/* Satu-satunya penebalan di seluruh struk, dan itu disengaja. Pada LX-310 bold
   jatuh ke double-strike (kepala mengetuk dua kali) — tetap TEKS, bukan grafis;
   yang memaksa halaman jadi grafis adalah tabel/border/warna. */
.kop {
  font-weight: 700;
}
pre {
  font-family: "Courier New", Courier, monospace;
  line-height: 1.15;
  margin: 0;
  white-space: pre;
}
@media print {
  .sembunyi-cetak {
    display: none;
  }
}
</style>

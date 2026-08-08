<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { router } from "@inertiajs/vue3";
import { Deferred } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import { useGridNav } from "@/composables/useGridNav";
import { useSatuan } from "@/composables/useSatuan";

const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const formatRupiah = (v) => rp.format(angka(v));
// Sel angka di tabel kini type="text" (lihat useGridNav soal kursor), jadi
// koma desimal ala Indonesia benar-benar bisa terketik — dan Number("1,5")
// adalah NaN, yang diam-diam membuat satu baris hilang dari total.
const angka = (v) => Number(String(v ?? "").replace(",", ".")) || 0;

const props = defineProps({
  nota: { type: Object, default: null },
  // "nota" = penjualan langsung (uang berpindah), "order" = pesanan yang
  // menunggu diambil. Satu layar untuk keduanya; lihat _layar_penjualan().
  mode: { type: String, default: "nota" },
  base: { type: String, default: "/kasir/penjualan" },
  kd_user: { type: String, default: "" },
  kd_divisi: { type: String, default: "" },
  kd_pegawai: { type: String, default: "" },
  nota_terakhir: { type: String, default: "" },
});

const order = computed(() => props.mode === "order");
const judul = computed(() => (order.value ? "Penjualan Order" : "Penjualan"));
const sebutan = computed(() => (order.value ? "Order" : "Nota"));

const isi = computed(() => props.nota || {});
const opsi = computed(() => isi.value.opsi || {});
const bawaan = computed(() => isi.value.bawaan || {});

// --- Tab transaksi ----------------------------------------------------------
// Kasir sering melayani beberapa pembeli sekaligus: satu menunggu ambil barang,
// yang lain sudah siap bayar. Tiap tab adalah satu keranjang utuh, jadi "hold"
// bukan tombol tersendiri — cukup pindah tab. Disimpan di localStorage supaya
// keranjang tak hilang kalau layar ter-refresh atau browser tertutup.
// Kuncinya memuat mode: keranjang order dan keranjang nota tak boleh saling
// menimpa walau dibuka oleh orang yang sama.
const SIMPANAN = `arunika.${props.mode}.${props.kd_user || "anon"}`;
let urutan = 1;

function tabBaru() {
  return reactive({
    id: urutan++,
    baris: [],
    kd_customer: "", customer_nama: "",
    kd_jenis: "", kd_kas: "", kd_voucher: "",
    keterangan: "", no_order: "",
    tanggal: "", jatuh_tempo: "",
    diskon_uang: 0, pajak: 0, bayar: 0,
  });
}
const tabs = ref([tabBaru()]);
const aktif = ref(0);
const tab = computed(() => tabs.value[aktif.value] || tabs.value[0]);

function isiBawaan(t) {
  const b = bawaan.value;
  if (!b || !b.kd_customer) return;
  t.kd_customer = t.kd_customer || b.kd_customer;
  t.customer_nama = t.customer_nama || b.customer_nama || "";
  t.kd_jenis = t.kd_jenis || b.kd_jenis;
  t.kd_kas = t.kd_kas || b.kd_kas;
  t.kd_voucher = t.kd_voucher || b.kd_voucher;
  t.tanggal = t.tanggal || b.tanggal || "";
  t.jatuh_tempo = t.jatuh_tempo || b.jatuh_tempo || "";
}
watch(bawaan, () => tabs.value.forEach(isiBawaan), { immediate: true });

function tambahTab() {
  const t = tabBaru();
  isiBawaan(t);
  tabs.value.push(t);
  aktif.value = tabs.value.length - 1;
  fokusEntri();
}
function tutupTab(i = aktif.value) {
  if (tabs.value.length === 1) {
    tabs.value[0] = tabBaru();
    isiBawaan(tabs.value[0]);
  } else {
    tabs.value.splice(i, 1);
    aktif.value = Math.min(aktif.value, tabs.value.length - 1);
  }
  fokusEntri();
}
function keTab(i) {
  if (i >= 0 && i < tabs.value.length) {
    aktif.value = i;
    fokusEntri();
  }
}

// Simpan/pulihkan keranjang. Hanya isi keranjang — bukan hasil, bukan nomor.
watch(tabs, (v) => {
  try {
    localStorage.setItem(SIMPANAN, JSON.stringify(v.map((t) => ({ ...t }))));
  } catch { /* kuota penuh: keranjang tetap jalan, cuma tak awet */ }
}, { deep: true });

onMounted(() => {
  try {
    const lama = JSON.parse(localStorage.getItem(SIMPANAN) || "[]");
    const pakai = lama.filter((t) => (t.baris || []).length);
    if (pakai.length) {
      tabs.value = pakai.map((t) => reactive({ ...t, id: urutan++ }));
      aktif.value = 0;
    }
  } catch { /* simpanan rusak: mulai bersih, jangan menahan kasir */ }
  tabs.value.forEach(isiBawaan);
});

// --- Jatuh tempo mengikuti tanggal transaksi --------------------------------
watch(() => tab.value?.tanggal, (t) => {
  if (!t || !tab.value) return;
  const d = new Date(`${t}T00:00:00`);
  d.setDate(d.getDate() + 30);
  tab.value.jatuh_tempo = d.toISOString().slice(0, 10);
});

// --- Kotak entri di dalam tabel ---------------------------------------------
// Satu kotak untuk pemindai DAN pencarian, di dalam tabel seperti layar
// desktop lama: pemindai mengetik kode lalu Enter, tangan mengetik sepotong
// nama lalu ↑↓ Enter. Dulu keduanya kotak terpisah di dua kartu berbeda.
const entri = ref("");
const hasil = ref([]);
const sorot = ref(0);
const digeser = ref(false);   // kasir sudah memilih sendiri dengan ↑↓?
const pesan = ref("");
const kotakEntri = ref(null);
const wadahTabel = ref(null);
const fokusEntri = () => nextTick(() => kotakEntri.value?.focus?.());

let timer = null;
watch(entri, (q) => {
  clearTimeout(timer);
  sorot.value = 0;
  digeser.value = false;
  if (!q.trim()) {
    hasil.value = [];
    return;
  }
  timer = setTimeout(async () => {
    const { data } = await axios.get(`${props.base}/cari-barang`, { params: { cari: q } });
    hasil.value = data.rows || [];
  }, 250);
});

/**
 * Enter di kotak entri. Urutannya menentukan pemindai tetap aman:
 * pemindai mengetik lalu Enter dalam sekejap, sering SEBELUM hasil pencarian
 * sempat datang — kalau Enter selalu mengambil sorotan, barang yang masuk bisa
 * barang lain yang namanya kebetulan memuat kode itu.
 */
async function masukkan() {
  const q = entri.value.trim();
  if (!q) return;
  pesan.value = "";
  const sama = (b) => (b.kd_barang || "").toUpperCase() === q.toUpperCase();

  let b = null;
  if (digeser.value) b = hasil.value[sorot.value];              // 1. pilihan kasir
  if (!b) b = hasil.value.find(sama);                           // 2. kode persis
  if (!b) {                                                     // 3. jalur pemindai
    const { data } = await axios.get(`${props.base}/cari-barang`, { params: { kode: q } });
    b = (data.rows || [])[0];
  }
  if (!b) b = hasil.value[0];                                   // 4. hasil teratas
  if (!b) {
    pesan.value = `Barang "${q}" tidak ada.`;
    return;
  }
  tambah(b);
  entri.value = "";
  hasil.value = [];
  fokusEntri();
}

function pilihHasil(i) {
  const b = hasil.value[i];
  if (!b) return;
  tambah(b);
  entri.value = "";
  hasil.value = [];
  fokusEntri();
}

function entriKey(e) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!hasil.value.length) {
      // Tak ada hasil: ↑ masuk kembali ke baris terakhir keranjang, supaya
      // menyunting qty barang yang barusan dipindai tak perlu tetikus.
      if (e.key === "ArrowUp") fokusBarisTerakhir();
      return;
    }
    digeser.value = true;
    const n = hasil.value.length;
    sorot.value = (sorot.value + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    masukkan();
  }
}

function fokusBarisTerakhir() {
  const baris = wadahTabel.value?.querySelectorAll("tbody tr[data-baris]");
  if (!baris?.length) return;
  const kotak = baris[baris.length - 1].querySelector("[data-nav]");
  kotak?.focus();
  kotak?.select?.();
}

const navGrid = useGridNav(wadahTabel, {
  keEntri: fokusEntri,
  hapusBaris: (i) => hapus(i),
});
const satuan = useSatuan(props.base, "harga_jual");

// --- Customer ---------------------------------------------------------------
const cariCustomer = ref("");
const hasilCustomer = ref([]);
const sorotCust = ref(0);
let timerCust = null;
watch(cariCustomer, (q) => {
  clearTimeout(timerCust);
  sorotCust.value = 0;
  if (!q.trim()) {
    hasilCustomer.value = [];
    return;
  }
  timerCust = setTimeout(async () => {
    const { data } = await axios.get(`${props.base}/cari-customer`, { params: { cari: q } });
    hasilCustomer.value = data.rows || [];
  }, 250);
});
function pilihCustomer(c) {
  if (!c) return;
  tab.value.kd_customer = c.kd_customer;
  tab.value.customer_nama = c.nama;
  cariCustomer.value = "";
  hasilCustomer.value = [];
  fokusEntri();
}

// --- Order ------------------------------------------------------------------
const bukaOrder = ref(false);
const daftarOrder = ref([]);
const sorotOrder = ref(0);
async function bukaDaftarOrder() {
  if (order.value) return;   // order tidak mengambil order
  bukaOrder.value = true;
  sorotOrder.value = 0;
  const { data } = await axios.get("/kasir/penjualan/order");
  daftarOrder.value = data.rows || [];
}
async function ambilOrder() {
  const o = daftarOrder.value[sorotOrder.value];
  if (!o) return;
  const { data } = await axios.get("/kasir/penjualan/order", {
    params: { no_order: o.no_order },
  });
  const d = data.order;
  if (!d) return;
  // Order dituang ke TAB BARU, bukan menimpa keranjang yang sedang jalan.
  const t = tabBaru();
  isiBawaan(t);
  Object.assign(t, {
    no_order: d.no_order,
    kd_customer: d.kd_customer || t.kd_customer,
    customer_nama: d.customer_nama || t.customer_nama,
    kd_jenis: d.kd_jenis || t.kd_jenis,
    kd_kas: d.kd_kas || t.kd_kas,
    kd_voucher: d.kd_voucher || t.kd_voucher,
    keterangan: d.keterangan === "-" ? "" : d.keterangan,
    diskon_uang: d.diskon_uang, pajak: d.pajak,
    baris: d.items.map((i) => ({ ...i })),
  });
  tabs.value.push(t);
  aktif.value = tabs.value.length - 1;
  bukaOrder.value = false;
  fokusEntri();
}

// --- Baris ------------------------------------------------------------------
function tambah(b) {
  const ada = tab.value.baris.find(
    (x) => x.kd_barang === b.kd_barang && x.kd_satuan === b.kd_satuan);
  if (ada) {
    ada.qty = angka(ada.qty) + 1;
    return;
  }
  tab.value.baris.push({
    kd_barang: b.kd_barang, nama: b.nama, kd_satuan: b.kd_satuan,
    satuan: b.satuan, harga_jual: b.harga_jual ?? 0, qty: 1,
    diskon1: 0, diskon2: 0, diskon3: 0, diskon4: 0,
  });
}
const hapus = (i) => tab.value.baris.splice(i, 1);

// Cerminan ghb() di apps/transactions/penjualan.py — nilai di (-1,1) persen,
// selebihnya rupiah. HANYA pratinjau; yang disimpan dihitung ulang di server.
function ghb(harga, diskon) {
  if (harga <= 0) return harga;
  let v = harga;
  for (const d of diskon) {
    const n = angka(d);
    v = n > -1 && n < 1 ? v * (1 - n) : v - n;
  }
  return v;
}
const subtotal = (b) =>
  ghb(angka(b.harga_jual), [b.diskon1, b.diskon2, b.diskon3, b.diskon4]) * angka(b.qty);
const totalTab = (t) => {
  const net = (t.baris || []).reduce((s, b) => s + subtotal(b), 0);
  return net * (1 + angka(t.pajak)) - angka(t.diskon_uang);
};
const total = computed(() => totalTab(tab.value));
const kembali = computed(() => Math.max(0, angka(tab.value.bayar) - total.value));
const jumlahItem = computed(
  () => tab.value.baris.reduce((s, b) => s + angka(b.qty), 0));

// --- Simpan + cetak ---------------------------------------------------------
const menyimpan = ref(false);
// Nomor ASLI dari server. Ancar-ancar yang tampil sebelum simpan bisa bergeser
// kalau kasir lain mendahului — mencetak dengan nomor itu berarti mencetak
// nota milik orang lain.
const notaTerakhir = ref(props.nota_terakhir || "");
watch(() => props.nota_terakhir, (v) => { if (v) notaTerakhir.value = v; });
const siap = computed(
  () => Boolean(props.kd_user && props.kd_divisi && props.kd_pegawai)
    && tab.value.baris.length > 0 && tab.value.kd_customer
    && tab.value.kd_jenis && tab.value.kd_kas && tab.value.kd_voucher);

function simpan() {
  if (!siap.value || menyimpan.value) return;
  const t = tab.value;
  const jam = new Date();
  const hh = (n) => String(n).padStart(2, "0");
  menyimpan.value = true;
  router.post(`${props.base}/save`, {
    kd_customer: t.kd_customer, kd_jenis: t.kd_jenis, kd_kas: t.kd_kas,
    kd_voucher: t.kd_voucher, kd_pegawai: props.kd_pegawai,
    keterangan: t.keterangan, no_order: t.no_order,
    // Jam PC kasir, bukan jam server — tanggal_server diisi database sendiri.
    tanggal: `${t.tanggal}T${hh(jam.getHours())}:${hh(jam.getMinutes())}:${hh(jam.getSeconds())}`,
    jatuh_tempo: t.jatuh_tempo,
    diskon_uang: angka(t.diskon_uang),
    pajak: angka(t.pajak),
    status: 1,
    items: t.baris.map((b) => ({
      kd_barang: b.kd_barang, kd_satuan: b.kd_satuan, qty: angka(b.qty),
      harga_jual: angka(b.harga_jual),
      diskon1: angka(b.diskon1), diskon2: angka(b.diskon2),
      diskon3: angka(b.diskon3), diskon4: angka(b.diskon4),
    })),
  }, {
    preserveScroll: true,
    onSuccess: () => {
      tutupTab();              // keranjang selesai → tabnya ditutup
    },
    onFinish: () => {
      menyimpan.value = false;
      fokusEntri();
    },
  });
}
function cetak() {
  if (notaTerakhir.value && !order.value) {
    window.open(`/kasir/penjualan/${notaTerakhir.value}/cetak`, "_blank");
  }
}

// --- Papan ketik ------------------------------------------------------------
// Kasir bekerja dua tangan di keyboard dan pemindai, angka lewat numpad kanan.
// Semua yang sering dipakai punya pintasan; tetikus tak pernah wajib.
const PINTASAN = computed(() => [
  ["F2", "kotak barang"],
  ["F4", "cari customer"],
  ["↑↓ / Enter", "pindah sel tabel"],
  ["Ctrl+Del", "hapus baris"],
  ["Alt+S", `simpan ${sebutan.value.toLowerCase()}`],
  ["Alt+N", "transaksi baru"],
  ["Alt+W", "tutup transaksi"],
  ["Alt+1…9", "pindah transaksi"],
  ...(order.value ? [] : [["Alt+O", "ambil order"], ["Alt+P", "cetak nota terakhir"]]),
]);
function onKey(e) {
  if (e.key === "Escape") {
    bukaOrder.value = false;
    hasil.value = [];
    hasilCustomer.value = [];
    return;
  }
  if (bukaOrder.value && ["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) {
    e.preventDefault();
    if (e.key === "Enter") return ambilOrder();
    const n = daftarOrder.value.length;
    sorotOrder.value = (sorotOrder.value + (e.key === "ArrowDown" ? 1 : n - 1)) % (n || 1);
    return;
  }
  if (!e.altKey) {
    // F3 dipertahankan sebagai alias F2: dulu keduanya kotak yang berbeda, dan
    // jari kasir sudah telanjur hafal.
    if (e.key === "F2" || e.key === "F3") { e.preventDefault(); fokusEntri(); }
    else if (e.key === "F4") { e.preventDefault(); document.getElementById("kotak-cust")?.focus(); }
    return;
  }
  const k = e.key.toLowerCase();
  const aksi = {
    s: simpan, n: tambahTab, w: () => tutupTab(), o: bukaDaftarOrder, p: cetak,
  }[k];
  if (aksi) { e.preventDefault(); aksi(); return; }
  if (/^[1-9]$/.test(k)) { e.preventDefault(); keTab(Number(k) - 1); }
}
onMounted(() => {
  window.addEventListener("keydown", onKey);
  fokusEntri();
});
onUnmounted(() => window.removeEventListener("keydown", onKey));

const KELAS_SEL =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-right tabular-nums";
const KELAS_PILIH =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-sm";
</script>

<template>
  <AdminLayout :title="judul">
    <Banner
      v-if="!kd_user || !kd_divisi || !kd_pegawai"
      variant="warning"
      class="mb-4"
      message="Akun Anda belum ditautkan lengkap ke user legacy, divisi, dan pegawai — nota belum bisa dibuat. Minta pengelola aplikasi mengisinya di Manajemen User."
    />

    <Deferred data="nota">
      <template #fallback><LoadingCard message="Menyiapkan layar…" /></template>
      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />

      <!-- Tab transaksi: hold = cukup pindah tab. -->
      <div class="mb-3 flex flex-wrap items-center gap-1">
        <button
          v-for="(t, i) in tabs"
          :key="t.id"
          :class="[
            'rounded-control border px-3 py-1.5 text-sm',
            i === aktif ? 'border-brand-500 bg-brand-bg text-ink' : 'border-border-default text-ink-muted hover:bg-surface-2',
          ]"
          @click="keTab(i)"
        >
          <span class="font-mono text-xs opacity-60">Alt+{{ i + 1 }}</span>
          Transaksi {{ i + 1 }}
          <span v-if="t.no_order" class="ml-1 font-mono text-xs text-brand-600">{{ t.no_order }}</span>
          <span class="ml-1 text-xs opacity-70">({{ (t.baris || []).length }})</span>
        </button>
        <Button size="sm" variant="secondary" @click="tambahTab">+ Baru (Alt+N)</Button>
        <Button v-if="!order" size="sm" variant="secondary" @click="bukaDaftarOrder">
          Ambil Order (Alt+O)
        </Button>
      </div>

      <div class="grid gap-4 lg:grid-cols-3">
        <div class="space-y-4 lg:col-span-2">
          <Card>
            <div class="mb-2 flex items-center justify-between text-sm">
              <span class="text-ink-subtle">
                No. {{ sebutan }} (ancar-ancar):
                <strong class="font-mono text-ink">{{ bawaan.nomor || "—" }}</strong>
              </span>
              <span class="text-ink-subtle">Item: <strong class="text-ink">{{ jumlahItem }}</strong></span>
            </div>

            <!-- Cari & isi DI DALAM tabel, seperti layar desktop lama: baris
                 terakhir adalah kotak pindai/cari, hasilnya muncul sebagai
                 baris di bawahnya, dan seluruh sel bisa dijelajahi dengan
                 panah + Enter (lihat useGridNav). -->
            <div ref="wadahTabel" class="overflow-x-auto" @keydown="navGrid">
              <table class="w-full text-sm">
                <thead class="text-xs text-ink-subtle">
                  <tr class="border-b border-border-default">
                    <th class="px-2 py-1 text-left font-medium">Kode / Item</th>
                    <th class="w-32 px-2 py-1 text-left font-medium">Satuan</th>
                    <th class="w-24 px-2 py-1 text-right font-medium">Qty</th>
                    <th class="w-32 px-2 py-1 text-right font-medium">Harga</th>
                    <th class="w-28 px-2 py-1 text-right font-medium">Disc. 1</th>
                    <th class="px-2 py-1 text-right font-medium">Total</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(b, i) in tab.baris"
                    :key="`${b.kd_barang}-${b.kd_satuan}`"
                    data-baris
                    class="border-b border-border-default"
                  >
                    <td class="px-2 py-1">
                      <p class="text-ink">{{ b.nama }}</p>
                      <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</p>
                    </td>
                    <td class="px-2 py-1">
                      <!-- Ganti satuan = ganti harga (lihat useSatuan). Daftar
                           satuannya diambil saat kotak ini disentuh. -->
                      <select
                        data-nav
                        :value="b.kd_satuan"
                        :class="KELAS_PILIH"
                        @focus="satuan.muat(b)"
                        @change="satuan.ganti(b, $event.target.value)"
                      >
                        <option v-if="!satuan.opsi(b).length" :value="b.kd_satuan">
                          {{ b.satuan || b.kd_satuan }}
                        </option>
                        <option v-for="s in satuan.opsi(b)" :key="s.kd_satuan" :value="s.kd_satuan">
                          {{ satuan.label(s) }}
                        </option>
                      </select>
                    </td>
                    <td class="px-2 py-1">
                      <input v-model="b.qty" data-nav inputmode="decimal" :class="KELAS_SEL" />
                    </td>
                    <td class="px-2 py-1">
                      <input v-model="b.harga_jual" data-nav inputmode="decimal" :class="KELAS_SEL" />
                    </td>
                    <td class="px-2 py-1">
                      <input v-model="b.diskon1" data-nav inputmode="decimal" :class="KELAS_SEL" />
                    </td>
                    <td class="px-2 py-1 text-right tabular-nums">{{ formatRupiah(subtotal(b)) }}</td>
                    <td class="px-2 py-1 text-right">
                      <Button size="sm" variant="secondary" @click="hapus(i)">Hapus</Button>
                    </td>
                  </tr>

                  <!-- Baris entri: pemindai DAN pencarian, satu kotak. -->
                  <tr class="border-b-2 border-border-strong bg-surface-2/50">
                    <td class="px-2 py-2" colspan="5">
                      <input
                        ref="kotakEntri"
                        v-model="entri"
                        class="w-full rounded-control border border-border-strong bg-surface px-3 py-2 font-mono text-lg"
                        placeholder="Pindai / ketik kode atau nama barang… (F2)"
                        @keydown="entriKey"
                      />
                    </td>
                    <td class="px-2 py-2 text-right text-xs text-ink-subtle" colspan="2">
                      ↑↓ pilih · Enter masukkan
                    </td>
                  </tr>

                  <!-- Hasil pencarian, sebagai baris tabel juga. -->
                  <tr
                    v-for="(b, i) in hasil"
                    :key="`cari-${b.kd_barang}-${b.kd_satuan}`"
                    :class="['cursor-pointer border-b border-border-default text-sm',
                             i === sorot ? 'bg-brand-bg' : 'hover:bg-surface-2']"
                    @click="pilihHasil(i)"
                  >
                    <td class="px-2 py-1.5">
                      <p class="truncate text-ink">{{ b.nama }}</p>
                      <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }} · {{ b.satuan }}</p>
                    </td>
                    <td class="px-2 py-1.5 text-right text-xs text-ink-subtle" colspan="3">
                      <span v-if="b.harga_jual !== undefined">{{ formatRupiah(b.harga_jual) }}</span>
                    </td>
                    <td class="px-2 py-1.5 text-right text-xs text-ink-subtle" colspan="3">
                      Enter untuk masukkan
                    </td>
                  </tr>

                  <tr v-if="!tab.baris.length && !hasil.length">
                    <td colspan="7" class="px-2 py-4 text-center text-ink-subtle">
                      Pindai atau ketik nama barang di kotak di atas untuk memulai.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="pesan" class="mt-2 text-sm text-warning-fg">{{ pesan }}</p>
          </Card>

          <Card>
            <div class="grid grid-cols-2 gap-x-4 text-xs text-ink-subtle sm:grid-cols-3">
              <p v-for="[k, ket] in PINTASAN" :key="k">
                <kbd class="rounded bg-surface-2 px-1 font-mono">{{ k }}</kbd> {{ ket }}
              </p>
            </div>
          </Card>
        </div>

        <Card title="Input Data">
          <div class="space-y-3">
            <div class="grid grid-cols-2 gap-2 text-sm">
              <div>
                <p class="text-xs text-ink-muted">Divisi</p>
                <p class="text-ink">{{ isi.nama_divisi || kd_divisi || "—" }}</p>
              </div>
              <div>
                <p class="text-xs text-ink-muted">Pegawai</p>
                <p class="text-ink">{{ isi.nama_pegawai || kd_pegawai || "—" }}</p>
              </div>
            </div>

            <div>
              <label class="mb-1 block text-xs font-medium text-ink-muted">Customer (F4)</label>
              <p class="mb-1 text-sm text-ink">
                {{ tab.customer_nama || "—" }}
                <span class="font-mono text-xs text-ink-subtle">{{ tab.kd_customer }}</span>
              </p>
              <input
                id="kotak-cust"
                v-model="cariCustomer"
                class="w-full rounded-control border border-border-strong bg-surface px-2.5 py-1.5 text-sm"
                placeholder="Ketik nama… ↑↓ lalu Enter"
                @keydown.down.prevent="sorotCust = Math.min(sorotCust + 1, hasilCustomer.length - 1)"
                @keydown.up.prevent="sorotCust = Math.max(sorotCust - 1, 0)"
                @keydown.enter.prevent="pilihCustomer(hasilCustomer[sorotCust])"
              />
              <ul v-if="hasilCustomer.length" class="mt-1 max-h-48 overflow-y-auto rounded-control border border-border-default">
                <li
                  v-for="(c, i) in hasilCustomer"
                  :key="c.kd_customer"
                  :class="['cursor-pointer px-2 py-1.5 text-sm', i === sorotCust ? 'bg-brand-bg' : 'hover:bg-surface-2']"
                  @click="pilihCustomer(c)"
                >
                  <p class="text-ink">{{ c.nama }}</p>
                  <p class="truncate font-mono text-xs text-ink-subtle">{{ c.kd_customer }}</p>
                </li>
              </ul>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <Input v-model="tab.tanggal" type="date" label="Tanggal" />
              <Input v-if="!order" v-model="tab.jatuh_tempo" type="date" label="Jatuh Tempo" />
            </div>
            <div v-if="!order">
              <p class="text-xs font-medium text-ink-muted">No. Order</p>
              <p class="font-mono text-sm text-ink">{{ tab.no_order || "—" }}</p>
            </div>
            <Select v-model="tab.kd_jenis" label="Jenis Bayar" :options="opsi.jenis_bayar || []" />
            <Select v-model="tab.kd_kas" label="Kas" :options="opsi.kas || []" />
            <Select v-model="tab.kd_voucher" label="Voucher" :options="opsi.voucher || []" />
            <Input v-model="tab.keterangan" label="Keterangan" placeholder="-" />
            <Input v-model="tab.pajak" type="number" step="any" label="Pajak (fraksi, 0.05 = 5%)" />
            <Input v-model="tab.diskon_uang" type="number" label="Diskon (Rp)" />
          </div>

          <div class="mt-4 space-y-1 border-t border-border-default pt-3 text-sm">
            <div class="flex justify-between">
              <span class="text-ink-subtle">Grand Total</span>
              <strong class="text-xl tabular-nums text-ink">{{ formatRupiah(total) }}</strong>
            </div>
            <!-- Order belum dibayar: uang berpindah nanti, saat ordernya
                 diambil dan jadi nota. -->
            <template v-if="!order">
              <Input v-model="tab.bayar" type="number" label="Bayar" />
              <div class="flex justify-between">
                <span class="text-ink-subtle">Kembali</span>
                <strong class="tabular-nums text-ink">{{ formatRupiah(kembali) }}</strong>
              </div>
            </template>
            <p class="text-xs text-ink-subtle">
              Pratinjau; nilai yang disimpan dihitung ulang di server.
              <span v-if="!order">
                Bayar &amp; Kembali tak ikut tersimpan — kolomnya tak ada di database legacy.
              </span>
            </p>
          </div>

          <div class="mt-3 flex gap-2">
            <Button class="flex-1" :disabled="!siap" :loading="menyimpan" @click="simpan">
              Simpan {{ sebutan }} (Alt+S)
            </Button>
            <Button v-if="!order" variant="secondary" :disabled="!notaTerakhir" @click="cetak">
              Cetak (Alt+P)
            </Button>
          </div>
          <p v-if="notaTerakhir && !order" class="mt-2 text-xs text-ink-subtle">
            Nota terakhir: <strong class="font-mono">{{ notaTerakhir }}</strong>
          </p>
        </Card>
      </div>

      <!-- Ambil order: ↑↓ lalu Enter, Esc menutup. -->
      <div v-if="bukaOrder" class="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-8">
        <div class="w-full max-w-2xl rounded-control border border-border-strong bg-surface shadow-xl">
          <div class="border-b border-border-default px-4 py-2 text-sm">
            <strong class="text-ink">Ambil Order</strong>
            <span class="ml-2 text-ink-subtle">↑↓ pilih · Enter ambil · Esc tutup</span>
          </div>
          <ul class="max-h-96 divide-y divide-border-default overflow-y-auto">
            <li v-if="!daftarOrder.length" class="px-4 py-6 text-center text-sm text-ink-subtle">
              Tidak ada order yang belum diambil.
            </li>
            <li
              v-for="(o, i) in daftarOrder"
              :key="o.no_order"
              :class="['cursor-pointer px-4 py-2 text-sm', i === sorotOrder ? 'bg-brand-bg' : 'hover:bg-surface-2']"
              @click="sorotOrder = i; ambilOrder()"
            >
              <p class="font-mono text-ink">{{ o.no_order }}</p>
              <p class="text-xs text-ink-subtle">{{ o.customer || o.kd_customer }}</p>
            </li>
          </ul>
        </div>
      </div>
    </Deferred>
  </AdminLayout>
</template>

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

const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const formatRupiah = (v) => rp.format(Number(v) || 0);

const props = defineProps({
  nota: { type: Object, default: null },
  kd_user: { type: String, default: "" },
  kd_divisi: { type: String, default: "" },
  kd_pegawai: { type: String, default: "" },
  nota_terakhir: { type: String, default: "" },
});

const isi = computed(() => props.nota || {});
const opsi = computed(() => isi.value.opsi || {});
const bawaan = computed(() => isi.value.bawaan || {});

// --- Tab transaksi ----------------------------------------------------------
// Kasir sering melayani beberapa pembeli sekaligus: satu menunggu ambil barang,
// yang lain sudah siap bayar. Tiap tab adalah satu keranjang utuh, jadi "hold"
// bukan tombol tersendiri — cukup pindah tab. Disimpan di localStorage supaya
// keranjang tak hilang kalau layar ter-refresh atau browser tertutup.
const SIMPANAN = `arunika.nota.${props.kd_user || "anon"}`;
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
  fokusPindai();
}
function tutupTab(i = aktif.value) {
  if (tabs.value.length === 1) {
    tabs.value[0] = tabBaru();
    isiBawaan(tabs.value[0]);
  } else {
    tabs.value.splice(i, 1);
    aktif.value = Math.min(aktif.value, tabs.value.length - 1);
  }
  fokusPindai();
}
function keTab(i) {
  if (i >= 0 && i < tabs.value.length) {
    aktif.value = i;
    fokusPindai();
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

// --- Pemindai ---------------------------------------------------------------
const scan = ref("");
const pesan = ref("");
const kotakScan = ref(null);
const fokusPindai = () => nextTick(() => kotakScan.value?.focus?.());

async function pindai() {
  const kode = scan.value.trim();
  if (!kode) return;
  pesan.value = "";
  const { data } = await axios.get("/kasir/penjualan/cari-barang", { params: { kode } });
  const b = (data.rows || [])[0];
  if (!b) {
    pesan.value = `Kode "${kode}" tidak ada.`;
    return;
  }
  tambah(b);
  scan.value = "";
}

// --- Cari barang ------------------------------------------------------------
const cari = ref("");
const hasil = ref([]);
const sorotBarang = ref(0);
let timer = null;
watch(cari, (q) => {
  clearTimeout(timer);
  sorotBarang.value = 0;
  if (!q.trim()) {
    hasil.value = [];
    return;
  }
  timer = setTimeout(async () => {
    const { data } = await axios.get("/kasir/penjualan/cari-barang", { params: { cari: q } });
    hasil.value = data.rows || [];
  }, 250);
});
function pilihHasil() {
  const b = hasil.value[sorotBarang.value];
  if (!b) return;
  tambah(b);
  cari.value = "";
  hasil.value = [];
  fokusPindai();
}

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
    const { data } = await axios.get("/kasir/penjualan/cari-customer", { params: { cari: q } });
    hasilCustomer.value = data.rows || [];
  }, 250);
});
function pilihCustomer(c) {
  if (!c) return;
  tab.value.kd_customer = c.kd_customer;
  tab.value.customer_nama = c.nama;
  cariCustomer.value = "";
  hasilCustomer.value = [];
  fokusPindai();
}

// --- Order ------------------------------------------------------------------
const bukaOrder = ref(false);
const daftarOrder = ref([]);
const sorotOrder = ref(0);
async function bukaDaftarOrder() {
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
  fokusPindai();
}

// --- Baris ------------------------------------------------------------------
function tambah(b) {
  const ada = tab.value.baris.find(
    (x) => x.kd_barang === b.kd_barang && x.kd_satuan === b.kd_satuan);
  if (ada) {
    ada.qty = Number(ada.qty) + 1;
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
    const n = Number(d) || 0;
    v = n > -1 && n < 1 ? v * (1 - n) : v - n;
  }
  return v;
}
const subtotal = (b) =>
  ghb(Number(b.harga_jual), [b.diskon1, b.diskon2, b.diskon3, b.diskon4]) * Number(b.qty || 0);
const totalTab = (t) => {
  const net = (t.baris || []).reduce((s, b) => s + subtotal(b), 0);
  return net * (1 + (Number(t.pajak) || 0)) - (Number(t.diskon_uang) || 0);
};
const total = computed(() => totalTab(tab.value));
const kembali = computed(() => Math.max(0, (Number(tab.value.bayar) || 0) - total.value));
const jumlahItem = computed(
  () => tab.value.baris.reduce((s, b) => s + Number(b.qty || 0), 0));

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
  router.post("/kasir/penjualan/save", {
    kd_customer: t.kd_customer, kd_jenis: t.kd_jenis, kd_kas: t.kd_kas,
    kd_voucher: t.kd_voucher, kd_pegawai: props.kd_pegawai,
    keterangan: t.keterangan, no_order: t.no_order,
    // Jam PC kasir, bukan jam server — tanggal_server diisi database sendiri.
    tanggal: `${t.tanggal}T${hh(jam.getHours())}:${hh(jam.getMinutes())}:${hh(jam.getSeconds())}`,
    jatuh_tempo: t.jatuh_tempo,
    diskon_uang: Number(t.diskon_uang) || 0,
    pajak: Number(t.pajak) || 0,
    status: 1,
    items: t.baris.map((b) => ({
      kd_barang: b.kd_barang, kd_satuan: b.kd_satuan, qty: Number(b.qty),
      harga_jual: Number(b.harga_jual),
      diskon1: Number(b.diskon1) || 0, diskon2: Number(b.diskon2) || 0,
      diskon3: Number(b.diskon3) || 0, diskon4: Number(b.diskon4) || 0,
    })),
  }, {
    preserveScroll: true,
    onSuccess: () => {
      tutupTab();              // keranjang selesai → tabnya ditutup
    },
    onFinish: () => {
      menyimpan.value = false;
      fokusPindai();
    },
  });
}
function cetak() {
  if (notaTerakhir.value) {
    window.open(`/kasir/penjualan/${notaTerakhir.value}/cetak`, "_blank");
  }
}

// --- Papan ketik ------------------------------------------------------------
// Kasir bekerja dua tangan di keyboard dan pemindai, angka lewat numpad kanan.
// Semua yang sering dipakai punya pintasan; tetikus tak pernah wajib.
const PINTASAN = [
  ["Alt+S", "simpan nota"],
  ["Alt+N", "transaksi baru"],
  ["Alt+W", "tutup transaksi"],
  ["Alt+1…9", "pindah transaksi"],
  ["Alt+O", "ambil order"],
  ["Alt+P", "cetak nota terakhir"],
  ["F2 / F3", "pindai / cari barang"],
  ["F4", "cari customer"],
];
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
    if (e.key === "F2") { e.preventDefault(); fokusPindai(); }
    else if (e.key === "F3") { e.preventDefault(); document.getElementById("kotak-cari")?.focus(); }
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
  fokusPindai();
});
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <AdminLayout title="Buat Nota">
    <Banner
      v-if="!kd_user || !kd_divisi || !kd_pegawai"
      variant="warning"
      class="mb-4"
      message="Akun Anda belum ditautkan lengkap ke user legacy, divisi, dan pegawai — nota belum bisa dibuat. Minta pengelola aplikasi mengisinya di Manajemen User."
    />

    <Deferred data="nota">
      <template #fallback><LoadingCard message="Menyiapkan layar nota…" /></template>
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
        <Button size="sm" variant="secondary" @click="bukaDaftarOrder">Ambil Order (Alt+O)</Button>
      </div>

      <div class="grid gap-4 lg:grid-cols-3">
        <div class="space-y-4 lg:col-span-2">
          <Card>
            <div class="flex flex-wrap items-end gap-3">
              <div class="min-w-[16rem] flex-1">
                <label class="mb-1 block text-xs font-medium text-ink-muted">
                  Pindai / ketik kode barang <span class="text-ink-subtle">(Enter)</span>
                </label>
                <input
                  ref="kotakScan"
                  v-model="scan"
                  class="w-full rounded-control border border-border-strong bg-surface px-3 py-2 font-mono text-lg"
                  placeholder="kode barang…"
                  @keydown.enter.prevent="pindai"
                />
              </div>
              <div class="grid grid-cols-2 gap-x-4 text-xs text-ink-subtle">
                <p v-for="[k, ket] in PINTASAN" :key="k">
                  <kbd class="rounded bg-surface-2 px-1 font-mono">{{ k }}</kbd> {{ ket }}
                </p>
              </div>
            </div>
            <p v-if="pesan" class="mt-2 text-sm text-warning-fg">{{ pesan }}</p>
          </Card>

          <Card>
            <div class="mb-2 flex items-center justify-between text-sm">
              <span class="text-ink-subtle">
                No. Nota (ancar-ancar):
                <strong class="font-mono text-ink">{{ bawaan.no_transaksi || "—" }}</strong>
              </span>
              <span class="text-ink-subtle">Item: <strong class="text-ink">{{ jumlahItem }}</strong></span>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead class="text-xs text-ink-subtle">
                  <tr class="border-b border-border-default">
                    <th class="px-2 py-1 text-left font-medium">Kode / Item</th>
                    <th class="px-2 py-1 text-right font-medium">Qty</th>
                    <th class="px-2 py-1 text-right font-medium">Harga</th>
                    <th class="px-2 py-1 text-right font-medium">Disc. 1</th>
                    <th class="px-2 py-1 text-right font-medium">Total</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!tab.baris.length">
                    <td colspan="6" class="px-2 py-6 text-center text-ink-subtle">
                      Pindai barang untuk memulai.
                    </td>
                  </tr>
                  <tr v-for="(b, i) in tab.baris" :key="`${b.kd_barang}-${b.kd_satuan}`" class="border-b border-border-default">
                    <td class="px-2 py-1">
                      <p class="text-ink">{{ b.nama }}</p>
                      <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }} · {{ b.satuan }}</p>
                    </td>
                    <td class="px-2 py-1 text-right">
                      <input v-model="b.qty" type="number" min="0" step="any"
                             class="w-20 rounded-control border border-border-default bg-surface px-2 py-1 text-right"
                             @keydown.enter.prevent="fokusPindai" />
                    </td>
                    <td class="px-2 py-1 text-right">
                      <input v-model="b.harga_jual" type="number" min="0" step="any"
                             class="w-28 rounded-control border border-border-default bg-surface px-2 py-1 text-right"
                             @keydown.enter.prevent="fokusPindai" />
                    </td>
                    <td class="px-2 py-1 text-right">
                      <input v-model="b.diskon1" type="number" step="any"
                             class="w-24 rounded-control border border-border-default bg-surface px-2 py-1 text-right"
                             @keydown.enter.prevent="fokusPindai" />
                    </td>
                    <td class="px-2 py-1 text-right tabular-nums">{{ formatRupiah(subtotal(b)) }}</td>
                    <td class="px-2 py-1 text-right">
                      <Button size="sm" variant="secondary" @click="hapus(i)">Hapus</Button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Cari barang (F3)">
            <input
              id="kotak-cari"
              v-model="cari"
              class="w-full rounded-control border border-border-default bg-surface px-3 py-2"
              placeholder="Nama atau kode… ↑↓ lalu Enter"
              @keydown.down.prevent="sorotBarang = Math.min(sorotBarang + 1, hasil.length - 1)"
              @keydown.up.prevent="sorotBarang = Math.max(sorotBarang - 1, 0)"
              @keydown.enter.prevent="pilihHasil"
            />
            <ul v-if="hasil.length" class="mt-2 max-h-56 divide-y divide-border-default overflow-y-auto">
              <li
                v-for="(b, i) in hasil"
                :key="`${b.kd_barang}-${b.kd_satuan}`"
                :class="['flex items-center justify-between gap-2 px-1 py-1.5', i === sorotBarang ? 'bg-brand-bg' : '']"
              >
                <div class="min-w-0">
                  <p class="truncate text-sm text-ink">{{ b.nama }}</p>
                  <p class="font-mono text-xs text-ink-subtle">
                    {{ b.kd_barang }} · {{ b.satuan }}
                    <span v-if="b.harga_jual !== undefined"> · {{ formatRupiah(b.harga_jual) }}</span>
                  </p>
                </div>
                <Button size="sm" @click="tambah(b)">Tambah</Button>
              </li>
            </ul>
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
              <Input v-model="tab.jatuh_tempo" type="date" label="Jatuh Tempo" />
            </div>
            <div>
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
            <Input v-model="tab.bayar" type="number" label="Bayar" />
            <div class="flex justify-between">
              <span class="text-ink-subtle">Kembali</span>
              <strong class="tabular-nums text-ink">{{ formatRupiah(kembali) }}</strong>
            </div>
            <p class="text-xs text-ink-subtle">
              Pratinjau; nilai yang disimpan dihitung ulang di server. Bayar &amp;
              Kembali tak ikut tersimpan — kolomnya tak ada di database legacy.
            </p>
          </div>

          <div class="mt-3 flex gap-2">
            <Button class="flex-1" :disabled="!siap" :loading="menyimpan" @click="simpan">
              Simpan (Alt+S)
            </Button>
            <Button variant="secondary" :disabled="!notaTerakhir" @click="cetak">
              Cetak (Alt+P)
            </Button>
          </div>
          <p v-if="notaTerakhir" class="mt-2 text-xs text-ink-subtle">
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

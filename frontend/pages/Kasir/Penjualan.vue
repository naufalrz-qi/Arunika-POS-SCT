<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Deferred, router, useForm } from "@inertiajs/vue3";
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
});

const isi = computed(() => props.nota || {});
const opsi = computed(() => isi.value.opsi || {});
const bawaan = computed(() => isi.value.bawaan || {});

// --- Form kepala -----------------------------------------------------------
const form = useForm({
  kd_customer: "", kd_jenis: "", kd_kas: "", kd_voucher: "", kd_pegawai: "",
  keterangan: "", no_bukti: "", diskon_uang: 0, pajak: 0, status: 1, items: [],
});
const tanggal = ref("");
const jatuhTempo = ref("");

// --- Customer: dicari, bukan digulung ---------------------------------------
// 9.367 baris di m_customer. Dropdown sepanjang itu lebih lambat daripada
// mengetik tiga huruf, dan itulah keluhan yang membuat kotak ini ada.
const customerNama = ref("");
const cariCustomer = ref("");
const hasilCustomer = ref([]);
const bukaCustomer = ref(false);
let timerCust = null;
watch(cariCustomer, (q) => {
  clearTimeout(timerCust);
  if (!q.trim()) {
    hasilCustomer.value = [];
    return;
  }
  timerCust = setTimeout(async () => {
    const { data } = await axios.get("/kasir/penjualan/cari-customer", { params: { cari: q } });
    hasilCustomer.value = data.rows || [];
    bukaCustomer.value = true;
  }, 250);
});
function pilihCustomer(c) {
  form.kd_customer = c.kd_customer;
  customerNama.value = c.nama;
  cariCustomer.value = "";
  hasilCustomer.value = [];
  bukaCustomer.value = false;
}

// Terisi begitu bawaan tiba. Layar legacy membuka form yang SUDAH terisi —
// kasir tinggal memindai; mengosongkan lima dropdown tiap nota membuat
// pekerjaan yang seharusnya dua detik jadi belasan.
watch(bawaan, (b) => {
  if (!b || !b.kd_customer) return;
  form.kd_customer = form.kd_customer || b.kd_customer;
  form.kd_jenis = form.kd_jenis || b.kd_jenis;
  form.kd_kas = form.kd_kas || b.kd_kas;
  form.kd_voucher = form.kd_voucher || b.kd_voucher;
  form.status = b.status ?? 1;
  form.kd_pegawai = form.kd_pegawai || props.kd_pegawai;
  customerNama.value = customerNama.value || b.customer_nama || "";
  tanggal.value = tanggal.value || b.tanggal || "";
  jatuhTempo.value = jatuhTempo.value || b.jatuh_tempo || "";
}, { immediate: true });

// --- Pemindai + pencarian --------------------------------------------------
const scan = ref("");
const cari = ref("");
const hasil = ref([]);
const sedangCari = ref(false);
const pesanScan = ref("");
const kotakScan = ref(null);
let timer = null;

// Dicari lewat XHR, bukan kunjungan Inertia: yang berubah cuma daftar hasil,
// sedangkan router.get membangun ulang SELURUH prop layar tiap ketikan.
watch(cari, (q) => {
  clearTimeout(timer);
  if (!q.trim()) {
    hasil.value = [];
    return;
  }
  timer = setTimeout(async () => {
    sedangCari.value = true;
    try {
      const { data } = await axios.get("/kasir/penjualan/cari-barang", { params: { cari: q } });
      hasil.value = data.rows || [];
    } finally {
      sedangCari.value = false;
    }
  }, 250);
});

async function pindai() {
  const kode = scan.value.trim();
  if (!kode) return;
  pesanScan.value = "";
  const { data } = await axios.get("/kasir/penjualan/cari-barang", { params: { kode } });
  const b = (data.rows || [])[0];
  if (!b) {
    pesanScan.value = `Kode "${kode}" tidak ada.`;
    return;
  }
  tambah(b);
  scan.value = "";
}

// --- Baris nota ------------------------------------------------------------
const baris = ref([]);
function tambah(b) {
  const ada = baris.value.find(
    (x) => x.kd_barang === b.kd_barang && x.kd_satuan === b.kd_satuan);
  if (ada) {
    ada.qty = Number(ada.qty) + 1;
    return;
  }
  baris.value.push({
    kd_barang: b.kd_barang, nama: b.nama, kd_satuan: b.kd_satuan,
    satuan: b.satuan, harga_jual: b.harga_jual ?? 0, qty: 1,
    diskon1: 0, diskon2: 0, diskon3: 0, diskon4: 0,
  });
}
const hapus = (i) => baris.value.splice(i, 1);

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
const diskonUang = ref(0);
const pajak = ref(0);
const bayar = ref(0);
const subtotal = (b) =>
  ghb(Number(b.harga_jual), [b.diskon1, b.diskon2, b.diskon3, b.diskon4]) * Number(b.qty || 0);
const total = computed(() => {
  const net = baris.value.reduce((s, b) => s + subtotal(b), 0);
  return net * (1 + (Number(pajak.value) || 0)) - (Number(diskonUang.value) || 0);
});
const kembali = computed(() => Math.max(0, (Number(bayar.value) || 0) - total.value));
const jumlahItem = computed(() => baris.value.reduce((s, b) => s + Number(b.qty || 0), 0));

// --- Simpan + cetak --------------------------------------------------------
const notaTerakhir = ref("");
const siap = computed(
  () => Boolean(props.kd_user && props.kd_divisi) && baris.value.length > 0
    && form.kd_customer && form.kd_jenis && form.kd_kas && form.kd_voucher,
);
function simpan() {
  if (!siap.value) return;
  form.items = baris.value.map((b) => ({
    kd_barang: b.kd_barang, kd_satuan: b.kd_satuan, qty: Number(b.qty),
    harga_jual: Number(b.harga_jual), diskon1: Number(b.diskon1) || 0,
    diskon2: Number(b.diskon2) || 0, diskon3: Number(b.diskon3) || 0,
    diskon4: Number(b.diskon4) || 0,
  }));
  form.diskon_uang = Number(diskonUang.value) || 0;
  form.pajak = Number(pajak.value) || 0;
  const nomorTampil = bawaan.value.no_transaksi;
  form.post("/kasir/penjualan/save", {
    preserveScroll: true,
    onSuccess: () => {
      notaTerakhir.value = nomorTampil;
      baris.value = [];
      diskonUang.value = 0;
      pajak.value = 0;
      bayar.value = 0;
      nextTick(() => kotakScan.value?.focus?.());
    },
  });
}
function cetak() {
  if (notaTerakhir.value) {
    window.open(`/kasir/penjualan/${notaTerakhir.value}/cetak`, "_blank");
  }
}

// --- Pintasan papan ketik --------------------------------------------------
// Kasir bekerja dengan dua tangan di keyboard dan pemindai; memaksanya meraih
// tetikus untuk tiap nota adalah beda antara dua detik dan sepuluh.
const PINTASAN = [
  ["F2", "fokus ke kotak pindai"],
  ["F3", "fokus ke kotak cari"],
  ["F9", "simpan nota"],
  ["F10", "cetak nota terakhir"],
];
function onKey(e) {
  const map = {
    F2: () => kotakScan.value?.focus?.(),
    F3: () => document.getElementById("kotak-cari")?.focus(),
    F9: simpan,
    F10: cetak,
  };
  const aksi = map[e.key];
  if (aksi) {
    e.preventDefault();
    aksi();
  }
}
onMounted(() => {
  window.addEventListener("keydown", onKey);
  nextTick(() => kotakScan.value?.focus?.());
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
      <template #fallback>
        <LoadingCard message="Menyiapkan layar nota…" />
      </template>

      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />

      <div class="grid gap-4 lg:grid-cols-3">
        <div class="lg:col-span-2 space-y-4">
          <!-- Pemindai: fokus otomatis, Enter menambah baris. -->
          <Card>
            <div class="flex flex-wrap items-end gap-3">
              <div class="min-w-[16rem] flex-1">
                <label class="mb-1 block text-xs font-medium text-ink-muted">
                  Pindai / ketik kode barang <span class="text-ink-subtle">(Enter)</span>
                </label>
                <input
                  ref="kotakScan"
                  v-model="scan"
                  class="w-full rounded-control border border-border-strong bg-surface-1 px-3 py-2 font-mono text-lg"
                  placeholder="kode barang…"
                  @keydown.enter.prevent="pindai"
                />
              </div>
              <div class="text-xs text-ink-subtle">
                <p v-for="[k, ket] in PINTASAN" :key="k">
                  <kbd class="rounded bg-surface-2 px-1">{{ k }}</kbd> {{ ket }}
                </p>
              </div>
            </div>
            <p v-if="pesanScan" class="mt-2 text-sm text-warning-fg">{{ pesanScan }}</p>
          </Card>

          <!-- Baris nota -->
          <Card>
            <div class="mb-2 flex items-center justify-between text-sm">
              <span class="text-ink-subtle">
                No. Nota (ancar-ancar):
                <strong class="font-mono text-ink">{{ bawaan.no_transaksi || "—" }}</strong>
              </span>
              <span class="text-ink-subtle">Jumlah item: <strong class="text-ink">{{ jumlahItem }}</strong></span>
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
                  <tr v-if="!baris.length">
                    <td colspan="6" class="px-2 py-6 text-center text-ink-subtle">
                      Pindai barang untuk memulai.
                    </td>
                  </tr>
                  <tr v-for="(b, i) in baris" :key="`${b.kd_barang}-${b.kd_satuan}`" class="border-b border-border-default">
                    <td class="px-2 py-1">
                      <p class="text-ink">{{ b.nama }}</p>
                      <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }} · {{ b.satuan }}</p>
                    </td>
                    <td class="px-2 py-1 text-right">
                      <input v-model="b.qty" type="number" min="0" step="any" class="w-20 rounded-control border border-border-default bg-surface-1 px-2 py-1 text-right" />
                    </td>
                    <td class="px-2 py-1 text-right">
                      <input v-model="b.harga_jual" type="number" min="0" step="any" class="w-28 rounded-control border border-border-default bg-surface-1 px-2 py-1 text-right" />
                    </td>
                    <td class="px-2 py-1 text-right">
                      <input v-model="b.diskon1" type="number" step="any" class="w-24 rounded-control border border-border-default bg-surface-1 px-2 py-1 text-right" />
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
        </div>

        <!-- Kepala nota + total -->
        <div class="space-y-4">
          <Card title="Input Data">
            <div class="space-y-3">
              <!-- Divisi & Pegawai datang dari AKUN, jadi ditampilkan saja —
                   sama seperti layar legacy yang mengabukan keduanya. -->
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

              <div class="relative">
                <label class="mb-1 block text-xs font-medium text-ink-muted">Customer</label>
                <p class="mb-1 text-sm text-ink">
                  {{ customerNama || "—" }}
                  <span class="font-mono text-xs text-ink-subtle">{{ form.kd_customer }}</span>
                </p>
                <input
                  v-model="cariCustomer"
                  class="w-full rounded-control border border-border-strong bg-surface px-2.5 py-1.5 text-sm"
                  placeholder="Ketik nama untuk ganti…"
                  @focus="bukaCustomer = true"
                />
                <ul
                  v-if="bukaCustomer && hasilCustomer.length"
                  class="absolute z-10 mt-1 max-h-60 w-full overflow-y-auto rounded-control border border-border-strong bg-surface shadow-lg"
                >
                  <li
                    v-for="c in hasilCustomer"
                    :key="c.kd_customer"
                    class="cursor-pointer px-2 py-1.5 text-sm hover:bg-surface-2"
                    @click="pilihCustomer(c)"
                  >
                    <p class="text-ink">{{ c.nama }}</p>
                    <p class="truncate font-mono text-xs text-ink-subtle">
                      {{ c.kd_customer }} <span v-if="c.alamat">· {{ c.alamat }}</span>
                    </p>
                  </li>
                </ul>
              </div>

              <div class="grid grid-cols-2 gap-2">
                <Input v-model="tanggal" type="date" label="Tanggal" />
                <Input v-model="jatuhTempo" type="date" label="Jatuh Tempo" />
              </div>
              <Input v-model="form.no_bukti" label="No. Order" placeholder="-" />
              <Select v-model="form.kd_jenis" label="Jenis Bayar" :options="opsi.jenis_bayar || []" />
              <Select v-model="form.kd_kas" label="Kas" :options="opsi.kas || []" />
              <Select v-model="form.kd_voucher" label="Voucher" :options="opsi.voucher || []" />
              <Input v-model="form.keterangan" label="Keterangan" placeholder="-" />
              <Input v-model="pajak" type="number" step="any" label="Pajak (fraksi, 0.05 = 5%)" />
              <Input v-model="diskonUang" type="number" label="Diskon (Rp)" />
            </div>

            <div class="mt-4 space-y-1 border-t border-border-default pt-3 text-sm">
              <div class="flex justify-between">
                <span class="text-ink-subtle">Grand Total</span>
                <strong class="text-lg tabular-nums text-ink">{{ formatRupiah(total) }}</strong>
              </div>
              <Input v-model="bayar" type="number" label="Bayar" />
              <div class="flex justify-between">
                <span class="text-ink-subtle">Kembali</span>
                <strong class="tabular-nums text-ink">{{ formatRupiah(kembali) }}</strong>
              </div>
              <p class="text-xs text-ink-subtle">
                Angka ini pratinjau; nilai yang disimpan dihitung ulang di server.
                Bayar &amp; Kembali tidak ikut tersimpan — kolomnya tak ada di database legacy.
              </p>
            </div>

            <div class="mt-3 flex gap-2">
              <Button class="flex-1" :disabled="!siap" :loading="form.processing" @click="simpan">
                Simpan (F9)
              </Button>
              <Button variant="secondary" :disabled="!notaTerakhir" @click="cetak">
                Cetak (F10)
              </Button>
            </div>
            <p v-if="notaTerakhir" class="mt-2 text-xs text-ink-subtle">
              Nota terakhir: <strong class="font-mono">{{ notaTerakhir }}</strong>
            </p>
          </Card>

          <!-- Hasil cari: alternatif pemindai untuk barang tanpa label. -->
          <Card title="Cari barang">
            <input
              id="kotak-cari"
              v-model="cari"
              class="w-full rounded-control border border-border-default bg-surface-1 px-3 py-2"
              placeholder="Nama atau kode… (F3)"
            />
            <p v-if="sedangCari" class="mt-2 text-xs text-ink-subtle">Mencari…</p>
            <ul v-else-if="hasil.length" class="mt-2 max-h-72 divide-y divide-border-default overflow-y-auto">
              <li v-for="b in hasil" :key="`${b.kd_barang}-${b.kd_satuan}`" class="flex items-center justify-between gap-2 py-2">
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
            <p v-else-if="cari" class="mt-2 text-xs text-ink-subtle">Tidak ada yang cocok.</p>
          </Card>
        </div>
      </div>
    </Deferred>
  </AdminLayout>
</template>

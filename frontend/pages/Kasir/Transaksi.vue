<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { Deferred, useForm } from "@inertiajs/vue3";
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

// Sama dengan formatter di BaseTable.vue; tak ada util bersama untuk ini.
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const formatRupiah = (v) => rp.format(angka(v));
// Sel angka di tabel bertipe text (lihat useGridNav soal kursor), jadi koma
// desimal benar-benar bisa terketik — dan Number("1,5") adalah NaN.
const angka = (v) => Number(String(v ?? "").replace(",", ".")) || 0;

// Satu layar untuk Retur Penjualan, Terima Pembelian, dan Retur Pembelian.
// Bentuknya sama; yang berbeda datang sebagai prop dari SPEC di
// apps/transactions/transaksi.py — satu sumber kebenaran, bukan tiga salinan
// yang pelan-pelan berbeda.
const props = defineProps({
  nota: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  jenis: { type: String, required: true },
  label: { type: String, required: true },
  label_pihak: { type: String, default: "Pelanggan" },
  aksi_url: { type: String, required: true },
  pakai_pegawai: { type: Boolean, default: false },
  kd_user: { type: String, default: "" },
  kd_divisi: { type: String, default: "" },
});

const isi = computed(() => props.nota || {});
const opsi = computed(() => isi.value.opsi || {});

// --- Kotak entri di dalam tabel ---------------------------------------------
// Cari dan isi di satu tempat, seperti layar desktop lama. Dulu pencariannya
// satu kunjungan Inertia penuh (router.get) yang membangun ulang seluruh prop
// layar hanya untuk mengganti daftar hasil; kini endpoint JSON yang sama
// dipakai layar Penjualan, dipasang ulang di bawah tiap layar (lihat
// urls_kasir.py soal izin per-prefix).
const entri = ref(props.filters.cari || "");
const hasil = ref([]);
const sorot = ref(0);
const digeser = ref(false);
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
    const { data } = await axios.get(`${props.aksi_url}/cari-barang`, { params: { cari: q } });
    hasil.value = data.rows || [];
  }, 250);
});

/** Enter di kotak entri — urutan yang sama dengan layar Penjualan; lihat di
 *  sana kenapa pemindai tak boleh kalah cepat dari hasil pencarian. */
async function masukkan() {
  const q = entri.value.trim();
  if (!q) return;
  pesan.value = "";
  const sama = (b) => (b.kd_barang || "").toUpperCase() === q.toUpperCase();

  let b = null;
  if (digeser.value) b = hasil.value[sorot.value];
  if (!b) b = hasil.value.find(sama);
  if (!b) {
    const { data } = await axios.get(`${props.aksi_url}/cari-barang`, { params: { kode: q } });
    b = (data.rows || [])[0];
  }
  if (!b) b = hasil.value[0];
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
  const rows = wadahTabel.value?.querySelectorAll("tbody tr[data-baris]");
  if (!rows?.length) return;
  const kotak = rows[rows.length - 1].querySelector("[data-nav]");
  kotak?.focus();
  kotak?.select?.();
}

const navGrid = useGridNav(wadahTabel, {
  keEntri: fokusEntri,
  hapusBaris: (i) => hapus(i),
});
// Kolom harga di layar ini bernama `harga` (retur/pembelian), bukan harga_jual.
const satuan = useSatuan(props.aksi_url, "harga");

onMounted(fokusEntri);

// --- Baris nota (hanya di layar sampai disimpan) ---------------------------
const baris = ref([]);
function tambah(b) {
  const ada = baris.value.find(
    (x) => x.kd_barang === b.kd_barang && x.kd_satuan === b.kd_satuan);
  if (ada) {
    ada.qty = angka(ada.qty) + 1;
    return;
  }
  baris.value.push({
    kd_barang: b.kd_barang, nama: b.nama, kd_satuan: b.kd_satuan,
    satuan: b.satuan, harga: b.harga_jual, qty: 1,
    diskon1: 0, diskon2: 0, diskon3: 0, diskon4: 0,
  });
}
function hapus(i) {
  baris.value.splice(i, 1);
}

// Cerminan ghb() di apps/transactions/penjualan.py — dual-mode: nilai di (-1,1)
// berarti persen, selebihnya rupiah. HANYA untuk pratinjau; angka yang disimpan
// dihitung ulang di server, dan server yang berwenang.
function ghb(harga, diskon) {
  if (harga <= 0) return harga;
  let v = harga;
  for (const d of diskon) {
    const n = angka(d);
    v = n > -1 && n < 1 ? v * (1 - n) : v - n;
  }
  return v;
}
const ppnbm = ref(0);
const pajak = ref(0);
const subtotal = (b) => ghb(angka(b.harga), [b.diskon1, b.diskon2, b.diskon3, b.diskon4]) * angka(b.qty);
const total = computed(() => {
  const net = baris.value.reduce((s, b) => s + subtotal(b), 0);
  return net * (1 + angka(pajak.value)) * (1 + angka(ppnbm.value));
});

// --- Simpan ----------------------------------------------------------------
const form = useForm({
  kd_pihak: "", kd_jenis: "", kd_kas: "", kd_pegawai: "",
  keterangan: "", pajak: 0, ppnbm: 0, items: [],
});
const KELAS_SEL =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-right tabular-nums";
const KELAS_PILIH =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-sm";

const siap = computed(
  () => Boolean(props.kd_user && props.kd_divisi) && baris.value.length > 0
    && form.kd_pihak && form.kd_jenis && form.kd_kas
    && (!props.pakai_pegawai || form.kd_pegawai),
);
function simpan() {
  form.items = baris.value.map((b) => ({
    kd_barang: b.kd_barang, kd_satuan: b.kd_satuan, qty: angka(b.qty),
    harga: angka(b.harga), diskon1: angka(b.diskon1),
    diskon2: angka(b.diskon2), diskon3: angka(b.diskon3),
    diskon4: angka(b.diskon4),
  }));
  form.pajak = angka(pajak.value);
  form.ppnbm = angka(ppnbm.value);
  form.post(`${props.aksi_url}/save`, {
    preserveScroll: true,
    onSuccess: () => {
      baris.value = [];
      ppnbm.value = 0;
      pajak.value = 0;
      fokusEntri();
    },
  });
}
</script>

<template>
  <AdminLayout :title="label">
    <!-- Akun tanpa tautan legacy tak bisa membuat nota sama sekali (kd_user
         NOT NULL). Dikatakan di awal, bukan setelah kasir mengisi sekeranjang. -->
    <Banner
      v-if="!kd_user || !kd_divisi"
      variant="warning"
      class="mb-4"
      message="Akun Anda belum ditautkan ke user legacy dan divisi, jadi transaksi belum bisa dicatat. Minta pengelola aplikasi mengisinya di Manajemen User."
    />

    <Deferred data="nota">
      <template #fallback>
        <LoadingCard message="Menyiapkan layar nota…" />
      </template>

      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />

      <div class="grid gap-4">
        <Card :title="label">
          <div class="grid gap-3 sm:grid-cols-2">
            <Select v-model="form.kd_pihak" :label="`${label_pihak} *`" :options="opsi.pihak || []" placeholder="Pilih…" />
            <Select v-model="form.kd_jenis" label="Jenis Bayar *" :options="opsi.jenis_bayar || []" placeholder="Pilih…" />
            <Select v-model="form.kd_kas" label="Kas *" :options="opsi.kas || []" placeholder="Pilih…" />
            <Select v-if="pakai_pegawai" v-model="form.kd_pegawai" label="Pegawai *" :options="opsi.pegawai || []" placeholder="Pilih…" />
            <Input v-model="form.keterangan" label="Keterangan" placeholder="-" />
          </div>

          <!-- Cari & isi DI DALAM tabel: baris terakhir kotak pindai/cari,
               hasilnya jadi baris di bawahnya, seluruh sel dijelajahi dengan
               panah + Enter (useGridNav). -->
          <div ref="wadahTabel" class="mt-4 overflow-x-auto" @keydown="navGrid">
            <table class="w-full text-sm">
              <thead class="text-xs text-ink-subtle">
                <tr class="border-b border-border-default">
                  <th class="px-2 py-1 text-left font-medium">Barang</th>
                  <th class="w-32 px-2 py-1 text-left font-medium">Satuan</th>
                  <th class="w-24 px-2 py-1 text-right font-medium">Qty</th>
                  <th class="w-32 px-2 py-1 text-right font-medium">Harga</th>
                  <th class="w-28 px-2 py-1 text-right font-medium">Diskon</th>
                  <th class="px-2 py-1 text-right font-medium">Subtotal</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(b, i) in baris" :key="i" data-baris class="border-b border-border-default">
                  <td class="px-2 py-1">
                    <p class="text-ink">{{ b.nama }}</p>
                    <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</p>
                  </td>
                  <td class="px-2 py-1">
                    <!-- Ganti satuan = ganti harga (lihat useSatuan). -->
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
                    <input v-model="b.harga" data-nav inputmode="decimal" :class="KELAS_SEL" />
                  </td>
                  <td class="px-2 py-1">
                    <input v-model="b.diskon1" data-nav inputmode="decimal" :class="KELAS_SEL" />
                  </td>
                  <td class="px-2 py-1 text-right tabular-nums">{{ formatRupiah(subtotal(b)) }}</td>
                  <td class="px-2 py-1 text-right">
                    <Button size="sm" variant="secondary" @click="hapus(i)">Hapus</Button>
                  </td>
                </tr>

                <tr class="border-b-2 border-border-strong bg-surface-2/50">
                  <td class="px-2 py-2" colspan="5">
                    <input
                      ref="kotakEntri"
                      v-model="entri"
                      class="w-full rounded-control border border-border-strong bg-surface px-3 py-2 font-mono text-lg"
                      placeholder="Pindai / ketik kode atau nama barang…"
                      @keydown="entriKey"
                    />
                  </td>
                  <td class="px-2 py-2 text-right text-xs text-ink-subtle" colspan="2">
                    ↑↓ pilih · Enter masukkan · Ctrl+Del hapus baris
                  </td>
                </tr>

                <tr
                  v-for="(b, i) in hasil"
                  :key="`cari-${b.kd_barang}-${b.kd_satuan}`"
                  :class="['cursor-pointer border-b border-border-default',
                           i === sorot ? 'bg-brand-bg' : 'hover:bg-surface-2']"
                  @click="pilihHasil(i)"
                >
                  <td class="px-2 py-1.5">
                    <p class="truncate text-ink">{{ b.nama }}</p>
                    <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }} · {{ b.satuan }}</p>
                  </td>
                  <td class="px-2 py-1.5 text-right text-xs text-ink-subtle" colspan="6">
                    {{ formatRupiah(b.harga_jual) }}
                  </td>
                </tr>

                <tr v-if="!baris.length && !hasil.length">
                  <td colspan="7" class="px-2 py-4 text-center text-ink-subtle">
                    Belum ada barang.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="pesan" class="mt-2 text-sm text-warning-fg">{{ pesan }}</p>

          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <Input v-model="pajak" type="number" step="any" label="Pajak (fraksi, 0.05 = 5%)" />
            <Input v-model="ppnbm" type="number" step="any" label="PPnBM (fraksi)" />
          </div>

          <div class="mt-4 flex items-center justify-between border-t border-border-default pt-3">
            <div>
              <p class="text-xs text-ink-subtle">Total</p>
              <p class="text-xl font-semibold tabular-nums text-ink">{{ formatRupiah(total) }}</p>
              <p class="text-xs text-ink-subtle">
                Angka ini pratinjau; nilai yang disimpan dihitung ulang di server.
              </p>
            </div>
            <Button :disabled="!siap" :loading="form.processing" @click="simpan">
              Simpan {{ label }}
            </Button>
          </div>
        </Card>
      </div>
    </Deferred>
  </AdminLayout>
</template>

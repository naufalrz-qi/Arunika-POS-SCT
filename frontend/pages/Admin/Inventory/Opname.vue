<script setup>
import { computed, ref, watch } from "vue";
import { useForm } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import Modal from "@/components/ui/Modal.vue";
import Banner from "@/components/ui/Banner.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { useSatuan } from "@/composables/useSatuan.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  // Kosong kalau akun ini belum ditautkan ke user legacy. Dikirim supaya layar
  // bisa mengatakannya SEBELUM operator mengisi sepuluh baris lalu ditolak.
  kd_user: { type: String, default: "" },
});

const URL = "/admin-panel/inventory/opname";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_transaksi", label: "No. Opname" },
  { key: "tanggal", label: "Tanggal", format: "date" },
  { key: "divisi", label: "Divisi" },
  { key: "barang", label: "Barang" },
  // Dulu "Qty Sistem"/"Qty Fisik" — keduanya menyesatkan: t_opname_stok tak
  // menyimpan saldo stok, hanya besar koreksi dan arahnya.
  { key: "koreksi_masuk", label: "Koreksi Masuk", align: "right", format: "number" },
  { key: "koreksi_keluar", label: "Koreksi Keluar", align: "right", format: "number" },
  { key: "diferensi", label: "Diferensi", align: "right", format: "number" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  // Bruto ditampilkan di sebelah neto: "Total Selisih" saja menyembunyikan
  // sesi yang plus dan minusnya saling meniadakan di angka 0.
  return [
    { label: "Jumlah Opname", value: nf.format(s.jml_baris || 0) },
    { label: "Koreksi Masuk", value: nf.format(s.total_masuk || 0) },
    { label: "Koreksi Keluar", value: nf.format(s.total_keluar || 0) },
    { label: "Selisih Neto", value: nf.format(s.total_diferensi || 0) },
  ];
});

// --- Koreksi stok ----------------------------------------------------------
//
// Satu baris koreksi = satu baris t_opname_stok = satu nomor sendiri; tabelnya
// datar, tak ada kepala/detail. `keterangan` dipegang sekali untuk seluruh
// batch karena begitulah data nyatanya dipakai ("BALANCE STOK RETUR" menandai
// seluruh koreksi satu sesi), dan karena satu sebab memang menerangkan semua
// baris yang diisi bersamaan.

const ARAH = [
  { value: "lebih", label: "Lebih (stok bertambah)" },
  { value: "kurang", label: "Kurang (stok berkurang)" },
];

const buka = ref(false);
const cari = ref("");
const hasil = ref([]);
const pesan = ref("");
const koreksi = useForm({ kd_divisi: "", items: [], keterangan: "" });
const satuan = useSatuan(URL);

let timer = null;
watch(cari, (q) => {
  clearTimeout(timer);
  if (!q.trim()) {
    hasil.value = [];
    return;
  }
  timer = setTimeout(async () => {
    const { data } = await axios.get(`${URL}/cari-barang`, { params: { cari: q } });
    hasil.value = data.rows || [];
    pesan.value = data.error || "";
  }, 250);
});

function tambah(b) {
  koreksi.items.push({
    kd_barang: b.kd_barang,
    nama: b.nama,
    kd_satuan: b.kd_satuan,
    satuan: b.satuan || b.kd_satuan,
    qty: 1,
    arah: "kurang",
  });
  cari.value = "";
  hasil.value = [];
}

const hapus = (i) => koreksi.items.splice(i, 1);

function bukaModal() {
  koreksi.reset();
  koreksi.clearErrors();
  cari.value = "";
  hasil.value = [];
  pesan.value = "";
  buka.value = true;
}

function simpan() {
  koreksi.post(`${URL}/save`, {
    preserveScroll: true,
    onSuccess: () => (buka.value = false),
  });
}
</script>

<template>
  <AdminLayout title="Opname Stok">
    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="no_transaksi"
      :page="Number(form.page)"
      :per-page="Number(form.per_page)"
      :sort-key="form.sort"
      :sort-dir="form.sort_dir"
      :export-href="exportHref"
      :summary-items="summaryItems"
      @page-change="onPage"
      @sort-change="onSort"
      @per-page-change="onPerPage"
    >
      <template #filters>
        <!-- Di luar <Deferred> bersama panel filter: tombolnya harus bisa
             diklik tanpa menunggu tabel selesai dimuat. -->
        <Card class="mb-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <p class="text-sm text-ink-muted">
              Stok fisik tidak cocok dengan sistem? Catat selisihnya di sini —
              stok langsung bergeser dan koreksinya tak bisa dibatalkan dari layar mana pun.
            </p>
            <Button @click="bukaModal">Koreksi Stok</Button>
          </div>
        </Card>

        <FilterPanel :form="form" @submit="apply({ page: 1 })" @reset="reset">
          <FilterSection title="Periode & Pencarian">
            <DateRangeField class="sm:col-span-2" v-model:from="form.date_from" v-model:to="form.date_to" />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <Input v-model="form.search" label="Cari" placeholder="no opname / kode / nama barang" />
          </FilterSection>
        </FilterPanel>
      </template>
    </ReportPage>

    <Modal :show="buka" title="Koreksi Stok" size="lg" @close="buka = false">
      <Banner
        v-if="!kd_user"
        variant="warning"
        message="Akun Anda belum ditautkan ke user legacy, jadi koreksi belum bisa disimpan. Minta pengelola aplikasi mengisinya di Manajemen User."
        class="mb-4"
      />
      <Banner v-if="pesan" variant="warning" :message="pesan" class="mb-4" />

      <!-- Divisi WAJIB dipilih, tanpa nilai bawaan. Toko memang berisi satu
           divisi, tapi gudang berisi lima — dan di sana seluruh opname ada di
           PERGUDANGAN, bukan di UMUM yang kebetulan urutan pertama. Divisi juga
           menentukan awalan nomor koreksinya. -->
      <Select
        v-model="koreksi.kd_divisi"
        label="Divisi *"
        placeholder="Pilih divisi…"
        :options="divisiOptions"
        class="mb-3"
      />
      <p v-if="!divisiOptions.length" class="mb-3 text-xs text-ink-subtle">
        Daftar divisi ikut dimuat bersama tabel. Tunggu sebentar lalu buka lagi.
      </p>

      <Input
        v-model="cari"
        label="Cari barang"
        placeholder="kode atau nama barang…"
        autocomplete="off"
      />
      <ul v-if="hasil.length" class="mt-2 max-h-48 overflow-y-auto rounded-control border border-border-default">
        <li v-for="(b, i) in hasil" :key="`${b.kd_barang}-${b.kd_satuan}-${i}`">
          <button
            type="button"
            class="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-surface-3"
            @click="tambah(b)"
          >
            <span class="font-mono text-xs text-ink-muted">{{ b.kd_barang }}</span>
            <span class="flex-1 text-ink">{{ b.nama }}</span>
            <span class="text-xs text-ink-subtle">{{ b.satuan || b.kd_satuan }}</span>
          </button>
        </li>
      </ul>

      <div v-if="koreksi.items.length" class="mt-4 space-y-2">
        <div
          v-for="(b, i) in koreksi.items"
          :key="`${b.kd_barang}-${i}`"
          class="grid items-end gap-2 rounded-control border border-border-default p-2 sm:grid-cols-12"
        >
          <div class="sm:col-span-4">
            <p class="text-sm text-ink">{{ b.nama }}</p>
            <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</p>
          </div>
          <!-- Satuan menentukan BESAR pergeseran stok (1 DUS ≠ 1 PCS), jadi ia
               dapat kotaknya sendiri, bukan sekadar tulisan. -->
          <Select
            class="sm:col-span-3"
            label="Satuan"
            :model-value="b.kd_satuan"
            :options="satuan.opsi(b).map((s) => ({ value: s.kd_satuan, label: satuan.label(s) }))"
            @update:model-value="satuan.ganti(b, $event)"
            @focus="satuan.muat(b)"
            @pointerdown="satuan.muat(b)"
          />
          <Input class="sm:col-span-2" v-model="b.qty" type="number" min="0" step="any" label="Qty" />
          <Select class="sm:col-span-2" v-model="b.arah" label="Arah" :options="ARAH" />
          <div class="sm:col-span-1">
            <Button variant="ghost" size="sm" @click="hapus(i)">Hapus</Button>
          </div>
        </div>
      </div>
      <p v-else class="mt-4 text-sm text-ink-subtle">
        Belum ada baris. Cari barang di atas untuk menambahkannya.
      </p>

      <Input
        v-model="koreksi.keterangan"
        class="mt-4"
        label="Keterangan *"
        placeholder="sebab koreksi, mis. BALANCE STOK RETUR"
        maxlength="50"
      />
      <p class="mt-1 text-xs text-ink-subtle">
        Maksimal 50 karakter. Ini satu-satunya tempat sebab koreksi tercatat, dan
        yang dibaca orang saat membalance selisih di Neraca Opname nanti.
      </p>

      <template #footer>
        <Button variant="secondary" @click="buka = false">Batal</Button>
        <Button
          :loading="koreksi.processing"
          :disabled="!kd_user || !koreksi.kd_divisi || !koreksi.items.length || !koreksi.keterangan.trim()"
          @click="simpan"
        >
          Simpan Koreksi
        </Button>
      </template>
    </Modal>
  </AdminLayout>
</template>

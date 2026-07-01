<script setup>
import { computed, reactive, ref } from "vue";
import { router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import { downloadXlsx, stamp } from "@/utils/xlsx";

const props = defineProps({
  levels: { type: Array, default: () => [] },
  divisi_list: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
  conn_error: { type: String, default: null },
});

const pull = reactive({
  kd_divisi: props.filters.kd_divisi || "",
  tanggal: props.filters.tanggal || new Date().toISOString().slice(0, 10),
});
const pulling = ref(false);

const divisiOptions = computed(() =>
  props.divisi_list.map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

function tarikData() {
  pulling.value = true;
  router.get("/admin-panel/inventory/stock", { ...pull }, {
    preserveState: true,
    preserveScroll: true,
    onFinish: () => (pulling.value = false),
  });
}

const q = ref("");
const catFilter = ref("");

const catOptions = computed(() => {
  const names = [...new Set(props.levels.map((r) => r.kategori).filter(Boolean))].sort();
  return names.map((c) => ({ value: c, label: c }));
});

const displayed = computed(() => {
  const term = q.value.toLowerCase().trim();
  return props.levels.filter((r) => {
    const okQ = !term || r.barang.toLowerCase().includes(term) || r.kd_barang.toLowerCase().includes(term);
    const okCat = !catFilter.value || r.kategori === catFilter.value;
    return okQ && okCat;
  });
});

const num = (n) => (n ?? 0).toLocaleString("id-ID");
const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

function exportXlsx() {
  downloadXlsx(`monitoring-stok-${stamp()}.xlsx`, columns, displayed.value, "Monitoring Stok");
}

const columns = [
  { key: "kd_divisi", label: "Kode Div." },
  { key: "divisi", label: "Divisi", sortable: true },
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "merk", label: "Merk" },
  { key: "model", label: "Model" },
  { key: "warna", label: "Warna" },
  { key: "ukuran", label: "Ukuran" },
  { key: "stok_akhir", label: "Stok Akhir", align: "right", sortable: true },
  { key: "harga_average", label: "Harga Avg", align: "right" },
  { key: "harga_jual", label: "Harga Jual", align: "right" },
  { key: "nominal", label: "Nominal", align: "right", sortable: true },
  { key: "harga_beli_akhir", label: "Harga Beli Akhir", align: "right" },
];
</script>

<template>
  <AdminLayout title="Monitoring Stok">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />

    <Card title="Tarik Data" subtitle="Pilih divisi & tanggal, lalu tarik dari server" class="mb-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Select v-model="pull.kd_divisi" label="Divisi" :options="divisiOptions" placeholder="Semua Divisi" />
        <Input v-model="pull.tanggal" label="Per Tanggal" type="date" />
        <div class="flex items-end">
          <Button class="w-full" :loading="pulling" @click="tarikData">Tarik Data</Button>
        </div>
      </div>
    </Card>

    <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end">
      <div class="sm:max-w-xs sm:flex-1">
        <Input v-model="q" label="Cari (dalam data)" placeholder="kode / nama barang…" />
      </div>
      <div class="sm:w-56">
        <Select v-model="catFilter" label="Kategori" :options="catOptions" placeholder="Semua kategori" />
      </div>
      <p class="text-xs text-ink-subtle sm:pb-2">
        Menampilkan {{ displayed.length.toLocaleString("id-ID") }} dari {{ levels.length.toLocaleString("id-ID") }} baris.
      </p>
      <div class="sm:ml-auto sm:pb-0.5">
        <Button variant="secondary" :disabled="displayed.length === 0" @click="exportXlsx">Export Excel</Button>
      </div>
    </div>

    <DataTable :columns="columns" row-key="kd_barang" :rows="displayed" :per-page="20" empty-message="Tidak ada data stok.">
      <template #cell-stok_akhir="{ value }">
        <span :class="value <= 0 ? 'font-semibold text-danger-600' : 'font-semibold'">{{ num(value) }}</span>
      </template>
      <template #cell-harga_average="{ value }">{{ rupiah(value) }}</template>
      <template #cell-harga_jual="{ value }">{{ rupiah(value) }}</template>
      <template #cell-nominal="{ value }"><span class="font-medium">{{ rupiah(value) }}</span></template>
      <template #cell-harga_beli_akhir="{ value }">{{ rupiah(value) }}</template>
    </DataTable>
  </AdminLayout>
</template>


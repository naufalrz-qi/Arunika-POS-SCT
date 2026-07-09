<script setup>
import { computed, ref } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import DateRangeFilter from "@/components/report/DateRangeFilter.vue";
import { useReportFilters } from "@/composables/useReportFilters";
import { downloadXlsx, stamp } from "@/utils/xlsx";

const props = defineProps({
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const rows = computed(() => props.data?.rows || []);
const connError = computed(() => props.data?.conn_error ?? null);

const { filters: form, loading, apply } = useReportFilters("/admin-panel/inventory/mutasi-stok", {
  kd_divisi: props.filters.kd_divisi || "",
  date_from: props.filters.date_from || "",
  date_to: props.filters.date_to || "",
});

const divisiOptions = computed(() =>
  (props.data?.divisi_list || []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

const q = ref("");
const displayed = computed(() => {
  const term = q.value.toLowerCase().trim();
  return rows.value.filter(
    (r) =>
      !term ||
      (r.barang || "").toLowerCase().includes(term) ||
      (r.kd_barang || "").toLowerCase().includes(term),
  );
});

const num = (n) => (n ?? 0).toLocaleString("id-ID");

function exportXlsx() {
  downloadXlsx(`mutasi-stok-${stamp()}.xlsx`, columns, displayed.value, "Mutasi Stok");
}

const columns = [
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "masuk", label: "Masuk", align: "right", sortable: true },
  { key: "keluar", label: "Keluar", align: "right", sortable: true },
  { key: "stok", label: "Stok (Awal 0)", align: "right", sortable: true },
];
</script>

<template>
  <AdminLayout title="Mutasi Stok">
    <Card class="mb-4">
      <DateRangeFilter
        mode="range"
        :filters="form"
        :divisi-options="divisiOptions"
        :loading="loading"
        :inline-submit="false"
        submit-label="Tampilkan"
        @submit="apply()"
      />
      <p class="mt-2 text-xs text-ink-subtle">
        Stok dihitung dari mutasi (masuk − keluar) dalam rentang tanggal, dengan
        asumsi stok awal = 0. Kosongkan "Dari Tanggal" untuk memakai 1 Januari
        tahun berjalan.
      </p>
    </Card>

    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data mutasi…" /></template>

      <Banner v-if="connError" variant="warning" :message="connError" />

      <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="sm:max-w-xs sm:flex-1">
          <Input v-model="q" label="Cari (dalam data)" placeholder="kode / nama barang…" />
        </div>
        <p class="text-xs text-ink-subtle sm:pb-2">
          Menampilkan {{ displayed.length.toLocaleString("id-ID") }} dari
          {{ rows.length.toLocaleString("id-ID") }} baris.
        </p>
        <div class="sm:ml-auto sm:pb-0.5">
          <Button variant="secondary" :disabled="displayed.length === 0" @click="exportXlsx">Export Excel</Button>
        </div>
      </div>

      <DataTable
        :columns="columns"
        row-key="kd_barang"
        :rows="displayed"
        :per-page="25"
        empty-message="Tidak ada mutasi pada rentang ini."
      >
        <template #cell-masuk="{ value }">{{ value ? num(value) : "—" }}</template>
        <template #cell-keluar="{ value }">{{ value ? num(value) : "—" }}</template>
        <template #cell-stok="{ value }">
          <span :class="value < 0 ? 'font-semibold text-danger-600' : 'font-semibold'">{{ num(value) }}</span>
        </template>
      </DataTable>
    </Deferred>
  </AdminLayout>
</template>

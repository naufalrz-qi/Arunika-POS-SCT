<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import ColumnFilters from "@/components/report/ColumnFilters.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { paramNamesFor } from "@/utils/reportFilters.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/penjualan-hpp";

const filterDefs = [
  { key: "no_transaksi", label: "No. Transaksi", type: "text" },
  { key: "customer", label: "Customer", type: "text" },
  { key: "barang", label: "Barang", type: "text" },
  { key: "kd_barang", label: "Kode Barang", type: "text" },
  { key: "kategori", label: "Kategori", type: "text" },
  { key: "laba", label: "Laba", type: "number_range" },
  { key: "margin", label: "Margin %", type: "number_range" },
  { key: "total_bersih", label: "Total Bersih", type: "number_range" },
];

const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "divisi", label: "Divisi" },
  { key: "customer", label: "Customer" },
  { key: "kd_barang", label: "Kode Barang" },
  { key: "barang", label: "Barang", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "satuan", label: "Satuan" },
  { key: "harga", label: "Harga", align: "right", format: "rupiah" },
  { key: "harga_pokok", label: "Harga Pokok", align: "right", format: "rupiah", sortable: true },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
  { key: "total_harga_pokok", label: "Total HPP", align: "right", format: "rupiah", sortable: true },
  { key: "laba", label: "Laba", align: "right", format: "rupiah", sortable: true },
  { key: "margin", label: "Margin %", align: "right", format: "persen", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Baris", value: nf.format(s.jml_baris || 0) },
    { label: "Total Bersih", value: rp.format(s.total_bersih || 0) },
    { label: "Total HPP", value: rp.format(s.total_harga_pokok || 0) },
    { label: "Total Laba", value: rp.format(s.total_laba || 0) },
    { label: "Margin %", value: `${nf.format(s.margin_total || 0)}%` },
  ];
});
</script>

<template>
  <AdminLayout title="Laba per Barang">
    <ReportPage
      title="Laba per Barang"
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
      :recent="!!filters.recent"
      @page-change="onPage"
      @sort-change="onSort"
      @per-page-change="onPerPage"
    >
      <template #filters>
        <FilterPanel :form="form" @submit="apply({ page: 1 })" @reset="reset">
          <FilterSection title="Periode & Pencarian">
            <DateModeField
              class="sm:col-span-2"
              label="Tanggal"
              :mode="form.date_mode"
              :from="form.date_from"
              :to="form.date_to"
              :date="form.date"
              @update:mode="form.date_mode = $event"
              @update:from="form.date_from = $event"
              @update:to="form.date_to = $event"
              @update:date="form.date = $event"
            />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <Input v-model="form.search" label="Cari" placeholder="no transaksi / barang / customer" />
          </FilterSection>
          <template #lanjutan>
            <FilterSection title="Pencarian Lanjutan">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['text']" />
            </FilterSection>
            <FilterSection title="Rentang Nilai">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['number_range']" />
            </FilterSection>
          </template>
        </FilterPanel>
      </template>
      <template #cell-laba="{ value }">
        <span :class="Number(value) < 0 ? 'text-red-600 font-medium' : ''">
          {{ value == null ? "—" : new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(value) }}
        </span>
      </template>
    </ReportPage>
  </AdminLayout>
</template>

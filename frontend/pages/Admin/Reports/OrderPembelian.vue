<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import ColumnFilters from "@/components/report/ColumnFilters.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Select from "@/components/ui/Select.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { paramNamesFor } from "@/utils/reportFilters.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/order-pembelian";

const filterDefs = [
  { key: "no_order", label: "No. Order", type: "text" },
  { key: "supplier", label: "Supplier", type: "text" },
  { key: "status", label: "Status", type: "category" },
  { key: "total_qty", label: "Total Qty", type: "number_range" },
  { key: "total_bersih", label: "Total Bersih", type: "number_range" },
];

const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

const columns = [
  { key: "no_order", label: "No. Order" },
  { key: "tanggal", label: "Tanggal", format: "date" },
  { key: "tanggal_terima", label: "Tgl. Terima", format: "date" },
  { key: "mitra", label: "Supplier" },
  { key: "divisi", label: "Divisi" },
  { key: "status", label: "Status" },
  { key: "no_transaksi", label: "No. Nota" },
  { key: "jml_item", label: "Jml Item", align: "right", format: "number" },
  { key: "total_qty", label: "Total Qty", align: "right", format: "number" },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const supplierOptions = computed(() => props.report?.options?.supplier || []);
const statusOptions = computed(() => props.report?.options?.status_order || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Order", value: nf.format(s.jml_order || 0) },
    { label: "Masih Terbuka", value: nf.format(s.jml_terbuka || 0) },
    { label: "Total Qty", value: nf.format(s.total_qty || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Order Pembelian">
    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="no_order"
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
            <SelectSearch v-model="form.kd_supplier" :options="supplierOptions" label="Supplier" />
            <Select v-model="form.status_order" :options="statusOptions" label="Status" placeholder="Semua" />
            <Input v-model="form.search" label="Cari" placeholder="no order / supplier" />
          </FilterSection>
          <template #lanjutan>
            <FilterSection title="Pencarian Lanjutan">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['text', 'category']" />
            </FilterSection>
            <FilterSection title="Rentang Nilai">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['number_range']" />
            </FilterSection>
          </template>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>

<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
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
        <FilterPanel :form="form" @submit="apply({ page: 1 })" @reset="reset">
          <FilterSection title="Periode & Pencarian">
            <DateRangeField class="sm:col-span-2" v-model:from="form.date_from" v-model:to="form.date_to" />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <Input v-model="form.search" label="Cari" placeholder="no opname / kode / nama barang" />
          </FilterSection>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>

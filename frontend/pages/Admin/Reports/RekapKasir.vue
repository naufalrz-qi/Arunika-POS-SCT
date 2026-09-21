<script setup>
// Rekap per kasir: satu baris per kd_user, bukan per nota.
//
// Penjualan per User di sebelahnya memang sengaja per-NOTA — grainnya mengikuti
// view legacy `mon_t_penjualan_per_user`. Pertanyaan "siapa menjual berapa"
// cuma bisa dijawab di sana dengan menjumlahkan ratusan baris dengan mata,
// jadi agregatnya berdiri sebagai laporan sendiri.
//
// Tunai/kredit dipecah karena itu yang dicocokkan dengan laci: uang yang masuk
// hari ini bukan total penjualan hari ini. Nota "Lunas" (kredit yang sudah
// dibayar) ikut kolom kredit — lihat `reports.rekap_kasir`.
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/rekap-kasir";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "kasir", label: "Kasir" },
  { key: "kd_user", label: "Kode User" },
  { key: "jml_nota", label: "Jml Nota", align: "right", format: "number" },
  { key: "total_kotor", label: "Total Kotor", align: "right", format: "rupiah" },
  { key: "total_diskon", label: "Total Diskon", align: "right", format: "rupiah" },
  { key: "total", label: "Total Bersih", align: "right", format: "rupiah" },
  { key: "total_tunai", label: "Tunai", align: "right", format: "rupiah" },
  { key: "total_kredit", label: "Kredit", align: "right", format: "rupiah" },
  { key: "rata_nota", label: "Rata per Nota", align: "right", format: "rupiah" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Kasir", value: nf.format(s.jml_kasir || 0) },
    { label: "Total Nota", value: nf.format(s.total_nota || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Rekap Kasir">
    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="kd_user"
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
          <FilterSection title="Periode">
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
          </FilterSection>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>

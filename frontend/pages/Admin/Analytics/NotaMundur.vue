<script setup>
/**
 * Nota Tanggal Mundur — dokumen yang tanggalnya berbeda hari dari cap server.
 *
 * Di aplikasi POS legacy, `tanggal` dokumen dirakit dari jam PC kasir dan bisa
 * diubah operator; `tanggal_server` tidak. Seluruh laporan lain bersumbu
 * `tanggal`, jadi dokumen yang dimundurkan ke periode yang sudah dilaporkan
 * tidak terlihat di mana pun. Layar ini satu-satunya yang membandingkannya.
 *
 * Nada layar ini sengaja NETRAL. Di data nyata 83% pembelian testGudang masuk
 * daftar ini secara sah (faktur pemasok bertanggal mundur itu normal). Layar
 * yang menuduh akan diabaikan dalam seminggu, dan bersamanya ekor yang benar-
 * benar layak diperiksa ikut hilang.
 */
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import Banner from "@/components/ui/Banner.vue";
import Badge from "@/components/ui/Badge.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/analitik/nota-mundur";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "jenis", label: "Jenis Dokumen" },
  { key: "no_dokumen", label: "No. Dokumen" },
  { key: "tanggal", label: "Tanggal", format: "date" },
  { key: "tanggal_server", label: "Tanggal Server", format: "date" },
  { key: "selisih_hari", label: "Selisih (hari)", align: "right", format: "number" },
  { key: "arah", label: "Arah" },
  { key: "divisi", label: "Divisi" },
  { key: "petugas", label: "Petugas" },
  { key: "keterangan", label: "Keterangan" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const jenisOptions = computed(() => props.report?.options?.jenis || []);

const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  return [
    { label: "Dokumen", value: nf.format(s.jml_dokumen || 0) },
    { label: "Bertanggal Mundur", value: nf.format(s.jml_mundur || 0) },
    // Dipisah, bukan digabung: bertanggal MAJU jauh lebih jarang dan jauh lebih
    // aneh — 49 baris dari 3.483 di testGudang. Menjumlahkannya dengan yang
    // mundur akan menguburnya.
    { label: "Bertanggal Maju", value: nf.format(s.jml_maju || 0) },
    { label: "Selisih Terjauh", value: `${nf.format(s.selisih_terjauh || 0)} hari` },
  ];
});
</script>

<template>
  <AdminLayout title="Nota Tanggal Mundur">
    <Banner
      variant="info"
      class="mb-4"
      message="Selisih tanggal BUKAN dengan sendirinya penyimpangan. Faktur pemasok yang bertanggal minggu lalu dan baru diinput hari ini akan selalu muncul di sini — pada data nyata, mayoritas baris pembelian memang begitu. Yang layak diperiksa: selisih besar pada dokumen PENJUALAN (yang seharusnya diinput saat transaksinya terjadi), dan dokumen bertanggal MAJU, yaitu bertanggal masa depan saat ia disimpan."
    />

    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="no_dokumen"
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
            <SelectSearch v-model="form.jenis" :options="jenisOptions" label="Jenis Dokumen" />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <!-- Wajib ada, dan bawaannya 1. Tanpa ambang, pembelian testGudang
                 menyumbang 13.021 baris dan menenggelamkan ekornya. -->
            <Input v-model="form.min_selisih" label="Min. selisih (hari)" type="number" placeholder="1" />
            <Input v-model="form.search" label="Cari" placeholder="no dokumen / keterangan" />
          </FilterSection>
        </FilterPanel>
      </template>

      <template #cell-arah="{ row }">
        <!-- Netral, bukan merah: 'Mundur' mayoritasnya sah. Yang diberi warna
             justru 'Maju', yang jarang dan tak punya penjelasan wajar. -->
        <Badge :variant="row.arah === 'Maju' ? 'warning' : 'neutral'">{{ row.arah }}</Badge>
      </template>
      <template #cell-selisih_hari="{ row }">
        <span :class="Math.abs(row.selisih_hari) > 30 ? 'font-semibold text-warning-fg' : ''">
          {{ row.selisih_hari > 0 ? "+" : "" }}{{ row.selisih_hari }}
        </span>
      </template>
    </ReportPage>
  </AdminLayout>
</template>

<script setup>
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import DetailBarang from "@/components/report/DetailBarang.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import Badge from "@/components/ui/Badge.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { useHiddenData } from "@/composables/useHiddenData.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/analitik/deadstock";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);
const { bisaLihat, saringKolom } = useHiddenData();

const columns = computed(() =>
  saringKolom(
    [
      { key: "kd_barang", label: "Kode" },
      { key: "barang", label: "Barang" },
      { key: "kategori", label: "Kategori" },
      { key: "qty_stok", label: "Stok", align: "right", format: "number" },
      { key: "nilai_stok", label: "Nilai Stok", align: "right", format: "rupiah" },
      { key: "jual_terakhir", label: "Jual Terakhir", format: "date" },
      { key: "hari_tak_laku", label: "Hari Tak Laku", align: "right", format: "number" },
      { key: "beli_terakhir", label: "Beli Terakhir", format: "date" },
    ],
    { nilai_stok: "nominal" },
  ),
);

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Barang", value: nf.format(s.jml_barang || 0) },
    { label: "Total Stok", value: nf.format(s.total_qty || 0) },
    ...(bisaLihat("nominal") ? [{ label: "Total Nilai Stok", value: rp.format(s.total_nilai || 0) }] : []),
    { label: "Belum Pernah Laku", value: nf.format(s.belum_pernah_laku || 0) },
  ];
});

const dipilih = ref(null);
</script>

<template>
  <AdminLayout title="Deadstock">
    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="kd_barang"
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
          <FilterSection title="Aturan & Pencarian">
            <Input
              v-model="form.hari"
              label="Tak terjual minimal (hari)"
              type="number"
              inputmode="numeric"
              step="1"
              min="1"
            />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <Input v-model="form.search" label="Cari" placeholder="kode / nama barang" />
          </FilterSection>
        </FilterPanel>
      </template>
      <!-- Nama jadi tombol pembuka panel detail, bukan seluruh baris (pola
           Klasifikasi Pelanggan): bisa dijangkau keyboard, dan tak merebut klik
           saat orang cuma ingin menyeleksi teks. -->
      <template #cell-barang="{ row }">
        <button
          type="button"
          class="text-left text-brand-fg underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          @click="dipilih = row"
        >
          {{ row.barang || row.kd_barang }}
        </button>
      </template>
      <template #cell-hari_tak_laku="{ row }">
        <span v-if="row.hari_tak_laku === null" class="whitespace-nowrap">
          <Badge variant="danger">Belum pernah laku</Badge>
        </span>
        <span v-else>{{ new Intl.NumberFormat("id-ID").format(row.hari_tak_laku) }}</span>
      </template>
    </ReportPage>

    <DetailBarang :baris="dipilih" @close="dipilih = null" />
  </AdminLayout>
</template>

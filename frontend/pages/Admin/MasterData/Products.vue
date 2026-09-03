<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import Input from "@/components/ui/Input.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Select from "@/components/ui/Select.vue";
import NumberRangeField from "@/components/ui/NumberRangeField.vue";
import { useServerReport } from "@/composables/useServerReport.js";

// Katalog ini ~55.000 barang. Versi sebelumnya mengirim semuanya sekaligus dan
// menyaring di peramban — penyakit yang sama yang dulu membunuh Stok Akhir —
// dan panel filternya `@submit="() => {}"`, jadi tak ada satu pun filter yang
// benar-benar sampai ke server. Sekarang cari/urut/saring semuanya dikerjakan
// server; paginasinya sudah dibawa ServerTable.
const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/master/products";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(
  URL,
  props.filters,
  ["f_harga_jual_min", "f_harga_jual_max"],
);

const opsi = computed(() => props.report?.options || {});

const columns = [
  { key: "kd_barang", label: "Kode" },
  { key: "nama", label: "Nama Produk" },
  { key: "kategori", label: "Kategori" },
  // Nama, bukan kode. Kolom ini dulu berlabel manusiawi tapi terikat ke kunci
  // kd_* sehingga yang tampil MAA003, bukan namanya.
  { key: "jenis_bahan", label: "Jenis Bahan" },
  { key: "departemen", label: "Departemen" },
  { key: "divisi_barang", label: "Divisi Barang" },
  { key: "sub_kategori", label: "Sub Kategori" },
  { key: "ukuran", label: "Ukuran" },
  { key: "pabrik", label: "Pabrik" },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "harga_jual", label: "Harga", align: "right", format: "rupiah" },
  { key: "status", label: "Status", align: "center" },
  { key: "status_pinjam", label: "Status Pinjam", align: "center" },
  { key: "keterangan", label: "Keterangan" },
];

const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  return [
    { label: "Jumlah Produk", value: nf.format(s.jml_baris || 0) },
    { label: "Aktif", value: nf.format(s.jml_aktif || 0) },
    { label: "Nonaktif", value: nf.format(s.jml_nonaktif || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Master Produk">
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
          <FilterSection title="Pencarian">
            <Input v-model="form.search" label="Cari" placeholder="kode / nama / pabrik" />
            <SelectSearch
              v-model="form.kd_kategori"
              label="Kategori"
              :options="opsi.kategori || []"
              placeholder="Semua kategori"
            />
            <Select
              v-model="form.status"
              label="Status"
              :options="[
                { value: '1', label: 'Aktif' },
                { value: '0', label: 'Nonaktif' },
              ]"
              placeholder="Semua status"
            />
          </FilterSection>
          <template #lanjutan>
            <FilterSection title="Filter Lanjutan">
              <SelectSearch
                v-model="form.kd_merk"
                label="Divisi Barang"
                :options="opsi.merk || []"
                placeholder="Semua"
              />
              <SelectSearch
                v-model="form.kd_model"
                label="Departemen"
                :options="opsi.model || []"
                placeholder="Semua"
              />
              <SelectSearch
                v-model="form.kd_warna"
                label="Sub Kategori"
                :options="opsi.warna || []"
                placeholder="Semua"
              />
              <SelectSearch
                v-model="form.kd_jenis_bahan"
                label="Jenis Bahan"
                :options="opsi.jenis_bahan || []"
                placeholder="Semua"
              />
              <SelectSearch
                v-model="form.kd_satuan"
                label="Satuan"
                :options="opsi.satuan || []"
                placeholder="Semua satuan"
              />
              <NumberRangeField
                v-model:min="form.f_harga_jual_min"
                v-model:max="form.f_harga_jual_max"
                label="Harga Jual"
              />
            </FilterSection>
          </template>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>

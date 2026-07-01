<script setup>
import ReportView from "@/components/report/ReportView.vue";
import { stokDivisi } from "@/mock/inventory";

const columns = [
  { key: "kd_divisi", label: "Kode Divisi" },
  { key: "divisi", label: "Divisi", sortable: true },
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "jenis", label: "Jenis" },
  { key: "stok_akhir", label: "Stok Akhir", align: "right", format: "number", sortable: true },
  { key: "supplier", label: "Supplier" },
];
</script>

<template>
  <ReportView
    title="Stok per Divisi"
    :columns="columns"
    :rows="stokDivisi"
    row-key="kd_barang"
    :per-page="25"
    :search-keys="['kd_barang', 'barang', 'kategori', 'divisi', 'supplier']"
    search-placeholder="kode / barang / kategori…"
    export-name="stok-per-divisi"
    sheet-name="Stok per Divisi"
  >
    <template #cell-stok_akhir="{ value }">
      <span :class="value <= 0 ? 'font-semibold text-danger-600' : 'font-semibold'">
        {{ Number(value).toLocaleString("id-ID") }}
      </span>
    </template>
  </ReportView>
</template>

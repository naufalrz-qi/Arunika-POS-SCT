<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { fmiStok } from "@/mock/analitik";

const columns = [
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "kode", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "stok", label: "Stok", align: "right", format: "number", sortable: true },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "klas", label: "Klasifikasi", align: "center" },
  { key: "kosong", label: "Status Stok", align: "center" },
];

const klas = (r) => (r.fmi ? "Fast Moving" : r.smi ? "Slow Moving" : "Medium");
const variant = (r) => (r.fmi ? "success" : r.smi ? "danger" : "neutral");
</script>

<template>
  <ReportView
    title="FMI Stok (Risiko Stok)"
    :columns="columns"
    :rows="fmiStok"
    row-key="kode"
    :search-keys="['kode', 'barang', 'divisi']"
    search-placeholder="kode / barang…"
    export-name="fmi-stok"
    sheet-name="FMI Stok"
  >
    <template #cell-klas="{ row }">
      <Badge :variant="variant(row)">{{ klas(row) }}</Badge>
    </template>
    <template #cell-kosong="{ row }">
      <Badge v-if="row.stok <= 0" variant="danger">Kosong</Badge>
      <Badge v-else variant="success">Tersedia</Badge>
    </template>
  </ReportView>
</template>

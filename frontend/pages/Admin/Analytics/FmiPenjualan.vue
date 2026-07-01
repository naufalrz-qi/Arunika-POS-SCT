<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { fmiPenjualan } from "@/mock/analitik";

const columns = [
  { key: "nomor", label: "#", align: "right" },
  { key: "periode", label: "Periode" },
  { key: "divisi", label: "Divisi" },
  { key: "kode", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "qty", label: "Qty Terjual", align: "right", format: "number", sortable: true },
  { key: "total", label: "Total", align: "right", format: "rupiah", sortable: true },
  { key: "saldo", label: "Saldo Stok", align: "right", format: "number" },
  { key: "klas", label: "Klasifikasi", align: "center" },
];

const klas = (r) => (r.fmi ? "Fast Moving" : r.smi ? "Slow Moving" : "Medium");
const variant = (r) => (r.fmi ? "success" : r.smi ? "danger" : "neutral");
</script>

<template>
  <ReportView
    title="FMI Penjualan (Fast/Slow Moving)"
    :columns="columns"
    :rows="fmiPenjualan"
    row-key="kode"
    :search-keys="['kode', 'barang', 'divisi']"
    search-placeholder="kode / barang…"
    export-name="fmi-penjualan"
    sheet-name="FMI Penjualan"
  >
    <template #cell-klas="{ row }">
      <Badge :variant="variant(row)">{{ klas(row) }}</Badge>
    </template>
  </ReportView>
</template>

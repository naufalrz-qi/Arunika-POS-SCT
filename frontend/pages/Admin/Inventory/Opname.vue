<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { opname } from "@/mock/inventory";

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "barang", label: "Barang", sortable: true },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "status", label: "Status", align: "center" },
  { key: "keterangan", label: "Keterangan" },
  { key: "petugas", label: "Petugas" },
];

const statusVariant = (s) => {
  if (s === "Hilang" || s === "Rusak" || s.includes("(-)")) return "danger";
  if (s.includes("(+)")) return "success";
  return "neutral";
};
</script>

<template>
  <ReportView
    title="Opname Stok"
    :columns="columns"
    :rows="opname"
    row-key="no_transaksi"
    :search-keys="['no_transaksi', 'barang', 'petugas', 'divisi']"
    search-placeholder="no transaksi / barang / petugas…"
    export-name="opname-stok"
    sheet-name="Opname Stok"
  >
    <template #cell-qty="{ value }">
      <span :class="value < 0 ? 'font-semibold text-danger-600' : 'font-semibold text-success-700'">
        {{ value > 0 ? "+" : "" }}{{ Number(value).toLocaleString("id-ID") }}
      </span>
    </template>
    <template #cell-status="{ value }">
      <Badge :variant="statusVariant(value)">{{ value }}</Badge>
    </template>
  </ReportView>
</template>

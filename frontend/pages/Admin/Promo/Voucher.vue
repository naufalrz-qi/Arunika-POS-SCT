<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { voucher } from "@/mock/promo";

const columns = [
  { key: "kode", label: "Kode Voucher", sortable: true },
  { key: "nama", label: "Nama", sortable: true },
  { key: "nilai", label: "Nilai", align: "right", format: "rupiah" },
  { key: "kuota", label: "Kuota", align: "right", format: "number" },
  { key: "terpakai", label: "Terpakai", align: "right", format: "number", sortable: true },
  { key: "sisa", label: "Sisa", align: "right", format: "number" },
  { key: "mulai", label: "Mulai" },
  { key: "selesai", label: "Selesai" },
  { key: "status", label: "Status", align: "center" },
];

const rows = voucher.map((v) => ({ ...v, sisa: v.kuota - v.terpakai }));

const statusVariant = (s) =>
  s === "Aktif" ? "success" : s === "Terjadwal" ? "brand" : s === "Habis" ? "danger" : "neutral";
</script>

<template>
  <ReportView
    title="Voucher"
    :columns="columns"
    :rows="rows"
    row-key="kode"
    :search-keys="['kode', 'nama', 'status']"
    search-placeholder="kode / nama voucher…"
    export-name="voucher"
    sheet-name="Voucher"
  >
    <template #cell-status="{ value }">
      <Badge :variant="statusVariant(value)">{{ value }}</Badge>
    </template>
  </ReportView>
</template>

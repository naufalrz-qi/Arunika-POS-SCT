<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { promo } from "@/mock/promo";

const columns = [
  { key: "kode", label: "Kode Promo", sortable: true },
  { key: "nama", label: "Nama Promo", sortable: true },
  { key: "tipe", label: "Tipe", align: "center" },
  { key: "nilai", label: "Nilai", align: "right" },
  { key: "min_belanja", label: "Min. Belanja", align: "right", format: "rupiah" },
  { key: "mulai", label: "Mulai", sortable: true },
  { key: "selesai", label: "Selesai" },
  { key: "status", label: "Status", align: "center" },
];

const statusVariant = (s) =>
  s === "Aktif" ? "success" : s === "Terjadwal" ? "brand" : "neutral";
</script>

<template>
  <ReportView
    title="Promo & Diskon"
    :columns="columns"
    :rows="promo"
    row-key="kode"
    :search-keys="['kode', 'nama', 'tipe', 'status']"
    search-placeholder="kode / nama promo…"
    export-name="promo-diskon"
    sheet-name="Promo"
  >
    <template #cell-nilai="{ row }">
      {{ row.tipe === "Persen" ? row.nilai + "%" : "Rp " + Number(row.nilai).toLocaleString("id-ID") }}
    </template>
    <template #cell-status="{ value }">
      <Badge :variant="statusVariant(value)">{{ value }}</Badge>
    </template>
  </ReportView>
</template>

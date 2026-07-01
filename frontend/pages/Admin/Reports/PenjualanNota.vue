<script setup>
import ReportView from "@/components/report/ReportView.vue";
import { penjualanNota } from "@/mock/penjualan";

const columns = [
  { key: "no_nota", label: "No. Nota", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "customer", label: "Customer", sortable: true },
  { key: "kota", label: "Kota" },
  { key: "divisi", label: "Divisi" },
  { key: "total_kotor", label: "Total Kotor", align: "right", format: "rupiah" },
  { key: "potongan", label: "Potongan", align: "right", format: "rupiah" },
  { key: "voucher", label: "Voucher", align: "right", format: "rupiah" },
  { key: "pajak", label: "Pajak", align: "right", format: "rupiah" },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
  { key: "petugas", label: "Petugas" },
];
</script>

<template>
  <ReportView
    title="Penjualan per Nota"
    :columns="columns"
    :rows="penjualanNota"
    row-key="no_nota"
    :search-keys="['no_nota', 'customer', 'kota', 'petugas']"
    search-placeholder="no nota / customer / petugas…"
    export-name="penjualan-per-nota"
    sheet-name="Penjualan per Nota"
  />
</template>

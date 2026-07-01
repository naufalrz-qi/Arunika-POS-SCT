<script setup>
import ReportView from "@/components/report/ReportView.vue";
import { returPenjualan } from "@/mock/penjualan";

const columns = [
  { key: "no_retur", label: "No. Retur", sortable: true },
  { key: "tanggal_retur", label: "Tgl Retur", sortable: true },
  { key: "no_bukti", label: "No. Bukti" },
  { key: "divisi", label: "Divisi" },
  { key: "barang", label: "Barang", sortable: true },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "jenis_bayar", label: "Jenis Bayar" },
  { key: "bank", label: "Bank" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "total", label: "Total", align: "right", format: "rupiah", sortable: true },
  { key: "customer", label: "Customer" },
  { key: "sales", label: "Sales" },
];
</script>

<template>
  <ReportView
    title="Retur Penjualan"
    :columns="columns"
    :rows="returPenjualan"
    row-key="no_retur"
    :search-keys="['no_retur', 'no_bukti', 'barang', 'customer', 'sales']"
    search-placeholder="no retur / barang / customer…"
    export-name="retur-penjualan"
    sheet-name="Retur Penjualan"
  />
</template>

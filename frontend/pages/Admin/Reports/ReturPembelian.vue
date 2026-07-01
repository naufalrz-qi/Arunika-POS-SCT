<script setup>
import ReportView from "@/components/report/ReportView.vue";
import { returPembelian } from "@/mock/pembelian";

const columns = [
  { key: "no_retur", label: "No. Retur", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "supplier", label: "Supplier", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "pembayaran", label: "Pembayaran" },
  { key: "bank", label: "Bank" },
  { key: "no_rekening", label: "No. Rekening" },
  { key: "barang", label: "Barang", sortable: true },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "keterangan", label: "Keterangan" },
];
</script>

<template>
  <ReportView
    title="Retur Pembelian"
    :columns="columns"
    :rows="returPembelian"
    row-key="no_retur"
    :search-keys="['no_retur', 'supplier', 'barang', 'divisi']"
    search-placeholder="no retur / supplier / barang…"
    export-name="retur-pembelian"
    sheet-name="Retur Pembelian"
  />
</template>

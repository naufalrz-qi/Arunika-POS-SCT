<script setup>
/**
 * Tabel yang seluruh datanya sudah ada di peramban: pengurutan dan paginasi
 * dikerjakan di sini, tampilannya milik BaseTable — lihat catatan di sana soal
 * kenapa dua salinan tabel disatukan.
 */
import { computed, ref, watch } from "vue";
import BaseTable from "./BaseTable.vue";

const props = defineProps({
  // columns: [{ key, label, sortable?, align?, format? }]
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: "id" },
  loading: { type: Boolean, default: false },
  perPage: { type: Number, default: 100 },
  emptyMessage: { type: String, default: "Tidak ada data untuk filter yang dipilih." },
});

const sortKey = ref("");
const sortDir = ref("asc");
const page = ref(1);
// Prop `perPage` hanya nilai awal; pemilih di footer yang memilikinya setelah itu.
const perPage = ref(props.perPage);

// Kembali ke halaman pertama tiap kali baris (hasil filter) berubah.
watch(
  () => props.rows,
  () => {
    page.value = 1;
  },
);

function onSort({ key, dir }) {
  sortKey.value = key;
  sortDir.value = dir;
}

function onPerPage(n) {
  perPage.value = n;
  page.value = 1;
}

const sortedRows = computed(() => {
  if (!sortKey.value) return props.rows;
  const dir = sortDir.value === "asc" ? 1 : -1;
  return [...props.rows].sort((a, b) => {
    const av = a[sortKey.value];
    const bv = b[sortKey.value];
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
});

const pagedRows = computed(() => {
  const start = (page.value - 1) * perPage.value;
  return sortedRows.value.slice(start, start + perPage.value);
});
</script>

<template>
  <BaseTable
    :columns="columns"
    :rows="pagedRows"
    :row-key="rowKey"
    :loading="loading"
    :total="sortedRows.length"
    :page="page"
    :per-page="perPage"
    :sort-key="sortKey"
    :sort-dir="sortDir"
    :empty-message="emptyMessage"
    @page-change="page = $event"
    @sort-change="onSort"
    @per-page-change="onPerPage"
  >
    <template v-for="(_, name) in $slots" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps" />
    </template>
  </BaseTable>
</template>

<script setup>
/**
 * Tabel yang pengurutan dan paginasinya dikerjakan server: semuanya cuma
 * diteruskan ke BaseTable dan dilaporkan balik ke pemanggil. Tampilannya
 * sepenuhnya milik BaseTable — lihat catatan di sana soal kenapa dua salinan
 * tabel disatukan.
 */
import { onMounted, onUnmounted } from "vue";
import BaseTable from "@/components/ui/BaseTable.vue";

defineProps({
  columns: { type: Array, required: true }, // {key,label,sortable?,align?,format?}
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: "id" },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  perPage: { type: Number, default: 50 },
  sortKey: { type: String, default: "" },
  sortDir: { type: String, default: "desc" },
  emptyMessage: { type: String, default: "Tidak ada data untuk filter yang dipilih." },
});
const emit = defineEmits(["page-change", "sort-change", "per-page-change"]);

// Pintasan "/" untuk melompat ke kolom pencarian halaman.
function onKey(e) {
  if (e.key === "/" && !/input|textarea|select/i.test(e.target.tagName)) {
    e.preventDefault();
    document.querySelector('input[placeholder*="Cari"], input[placeholder*="cari"]')?.focus();
  }
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <BaseTable
    :columns="columns"
    :rows="rows"
    :row-key="rowKey"
    :total="total"
    :page="page"
    :per-page="perPage"
    :sort-key="sortKey"
    :sort-dir="sortDir"
    :empty-message="emptyMessage"
    @page-change="emit('page-change', $event)"
    @sort-change="emit('sort-change', $event)"
    @per-page-change="emit('per-page-change', $event)"
  >
    <template v-for="(_, name) in $slots" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps" />
    </template>
  </BaseTable>
</template>

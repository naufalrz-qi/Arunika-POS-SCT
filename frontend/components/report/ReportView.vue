<script setup>
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import CollapsibleSection from "@/components/ui/CollapsibleSection.vue";
import { downloadXlsx, stamp } from "@/utils/xlsx";

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: "" },
  // columns: [{ key, label, sortable?, align? }]
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: "id" },
  perPage: { type: Number, default: 20 },
  // Keys to match the client-side search box against. Empty hides the box.
  searchKeys: { type: Array, default: () => [] },
  searchPlaceholder: { type: String, default: "Cari di dalam data…" },
  exportName: { type: String, default: "laporan" },
  sheetName: { type: String, default: "Data" },
  emptyMessage: { type: String, default: "Tidak ada data." },
  connError: { type: String, default: null },
});

const q = ref("");

const displayed = computed(() => {
  const term = q.value.toLowerCase().trim();
  if (!term || props.searchKeys.length === 0) return props.rows;
  return props.rows.filter((r) =>
    props.searchKeys.some((k) => String(r[k] ?? "").toLowerCase().includes(term)),
  );
});

const idNum = (n) => Number(n ?? 0).toLocaleString("id-ID");

function exportXlsx() {
  downloadXlsx(`${props.exportName}-${stamp()}.xlsx`, props.columns, displayed.value, props.sheetName);
}
</script>

<template>
  <AdminLayout :title="title">
    <Banner v-if="connError" variant="warning" :message="connError" />

    <!-- Optional filter panel (collapsible). -->
    <CollapsibleSection
      v-if="$slots.filters"
      title="Filter"
      subtitle="Saring data laporan"
      icon="search"
      class="mb-4"
    >
      <slot name="filters" />
    </CollapsibleSection>

    <!-- Optional KPI / summary strip. -->
    <div v-if="$slots.summary" class="mb-4">
      <slot name="summary" />
    </div>

    <!-- Search + export toolbar. -->
    <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end">
      <div v-if="searchKeys.length" class="sm:max-w-xs sm:flex-1">
        <Input v-model="q" label="Cari (dalam data)" :placeholder="searchPlaceholder" />
      </div>
      <p class="text-xs text-neutral-400 sm:pb-2">
        Menampilkan {{ idNum(displayed.length) }} dari {{ idNum(rows.length) }} baris.
      </p>
      <div class="sm:ml-auto sm:pb-0.5">
        <Button variant="secondary" :disabled="displayed.length === 0" @click="exportXlsx">Export Excel</Button>
      </div>
    </div>

    <DataTable
      :columns="columns"
      :row-key="rowKey"
      :rows="displayed"
      :per-page="perPage"
      :empty-message="emptyMessage"
    >
      <!-- Forward any cell-* slots a page provides through to DataTable. -->
      <template v-for="(_, name) in $slots" #[name]="slotProps" :key="name">
        <slot :name="name" v-bind="slotProps" />
      </template>
    </DataTable>
  </AdminLayout>
</template>

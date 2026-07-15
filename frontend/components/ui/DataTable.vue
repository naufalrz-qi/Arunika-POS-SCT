<script setup>
import { computed, ref, watch } from "vue";
import Spinner from "./Spinner.vue";
import EmptyState from "./EmptyState.vue";
import Pagination from "./Pagination.vue";

const props = defineProps({
  // columns: [{ key, label, sortable?, align?: 'left'|'right'|'center' }]
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: "id" },
  loading: { type: Boolean, default: false },
  perPage: { type: Number, default: 10 },
  emptyMessage: { type: String, default: "Tidak ada data." },
});

const sortKey = ref(null);
const sortDir = ref("asc");
const page = ref(1);

// Reset to first page whenever the underlying (filtered) rows change.
watch(
  () => props.rows,
  () => {
    page.value = 1;
  },
);

function toggleSort(col) {
  if (!col.sortable) return;
  if (sortKey.value === col.key) {
    sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
  } else {
    sortKey.value = col.key;
    sortDir.value = "asc";
  }
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
  const start = (page.value - 1) * props.perPage;
  return sortedRows.value.slice(start, start + props.perPage);
});

const alignClass = (a) =>
  a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left";

const rupiahFmt = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

// Default cell rendering when a page does not provide a `cell-<key>` slot.
// `col.format`: 'number' | 'rupiah' formats with id-ID locale.
function formatCell(value, col) {
  if (value === null || value === undefined || value === "") return value;
  if (col.format === "number" && typeof value === "number") return value.toLocaleString("id-ID");
  if (col.format === "rupiah" && typeof value === "number") return rupiahFmt.format(value);
  return value;
}
</script>

<template>
  <div class="panel-cut-frame">
    <div class="overflow-hidden panel-cut bg-surface">
    <div class="overflow-x-auto">
      <table class="min-w-[720px] divide-y divide-border-default text-sm tabular-nums">
        <thead class="bg-surface-2 sticky top-0 z-10">
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              scope="col"
              :role="col.sortable ? 'button' : undefined"
              :tabindex="col.sortable ? 0 : undefined"
              :aria-sort="col.sortable ? (sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none') : undefined"
              :class="[
                'whitespace-nowrap border-b-2 border-border-strong px-3 py-2 text-[11px] font-heading font-semibold uppercase tracking-wider text-ink-muted',
                alignClass(col.align),
                col.sortable ? 'cursor-pointer select-none hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500' : '',
              ]"
              @click="toggleSort(col)"
              @keydown.enter.prevent="col.sortable && toggleSort(col)"
              @keydown.space.prevent="col.sortable && toggleSort(col)"
            >
              <span class="inline-flex items-center gap-1">
                {{ col.label }}
                <span v-if="col.sortable && sortKey === col.key" class="text-brand-600">
                  {{ sortDir === "asc" ? "▲" : "▼" }}
                </span>
              </span>
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border-default">
          <tr v-if="loading">
            <td :colspan="columns.length" class="py-12">
              <div class="flex justify-center"><Spinner /></div>
            </td>
          </tr>
          <tr v-else-if="pagedRows.length === 0">
            <td :colspan="columns.length">
              <EmptyState :message="emptyMessage" />
            </td>
          </tr>
          <tr
            v-for="row in pagedRows"
            :key="row[rowKey]"
            v-show="!loading"
            class="even:bg-surface-2/60 hover:bg-surface-3"
          >
            <td
              v-for="col in columns"
              :key="col.key"
              :class="['px-3 py-1.5 leading-snug text-ink', alignClass(col.align)]"
            >
              <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
                {{ formatCell(row[col.key], col) }}
              </slot>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="!loading && sortedRows.length > perPage" class="border-t border-border-default px-3 bg-surface-2">
      <Pagination v-model:page="page" :total="sortedRows.length" :per-page="perPage" />
    </div>
    </div>
  </div>
</template>

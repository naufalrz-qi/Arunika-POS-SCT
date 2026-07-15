<script setup>
import { onMounted, onUnmounted } from "vue";
import Pagination from "@/components/ui/Pagination.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
const props = defineProps({
  columns: { type: Array, required: true }, // {key,label,sortable?,align?,format?}
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: "id" },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  perPage: { type: Number, default: 50 },
  sortKey: { type: String, default: "" },
  sortDir: { type: String, default: "desc" },
  emptyMessage: { type: String, default: "Tidak ada data." },
});
const emit = defineEmits(["page-change", "sort-change", "per-page-change"]);

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
function fmt(value, col) {
  if (value === null || value === undefined || value === "") return "-";
  if (col.format === "number") return nf.format(value);
  if (col.format === "rupiah") return rp.format(value);
  if (col.format === "date") {
    const d = new Date(value);
    return isNaN(d) ? value : d.toLocaleDateString("id-ID");
  }
  return value;
}
function alignClass(col) {
  return col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left";
}
function toggleSort(col) {
  if (!col.sortable) return;
  const dir = props.sortKey === col.key && props.sortDir === "asc" ? "desc" : "asc";
  emit("sort-change", { key: col.key, dir });
}

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
  <div class="panel-cut-frame">
    <div class="overflow-hidden panel-cut bg-surface">
      <div class="overflow-x-auto scroll-slim">
        <table class="w-full min-w-[720px] text-sm tabular-nums">
          <thead class="sticky top-0 z-10 bg-surface-3">
            <tr>
              <th
                v-for="col in columns"
                :key="col.key"
                scope="col"
                :role="col.sortable ? 'button' : undefined"
                :tabindex="col.sortable ? 0 : undefined"
                :aria-sort="col.sortable ? (sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none') : undefined"
                @click="toggleSort(col)"
                @keydown.enter.prevent="toggleSort(col)"
                @keydown.space.prevent="toggleSort(col)"
                :class="[
                  alignClass(col),
                  col.sortable ? 'cursor-pointer select-none hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500' : '',
                  'whitespace-nowrap border-b-2 border-border-strong px-3 py-2 text-[11px] font-heading font-semibold uppercase tracking-wider text-ink-muted',
                ]"
              >
                {{ col.label }}
                <span v-if="sortKey === col.key" class="text-brand-600">{{ sortDir === "asc" ? "▲" : "▼" }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!rows.length">
              <td :colspan="columns.length">
                <EmptyState :message="emptyMessage" />
              </td>
            </tr>
            <tr
              v-for="row in rows"
              :key="row[rowKey]"
              class="border-t border-border-default even:bg-surface-2/60 hover:bg-surface-3"
            >
              <td v-for="col in columns" :key="col.key" :class="[alignClass(col), 'px-3 py-1.5 leading-snug text-ink']">
                <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
                  {{ fmt(row[col.key], col) }}
                </slot>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        class="flex flex-wrap items-center justify-between gap-2 border-t border-border-default bg-surface-2 px-3 py-1.5"
      >
        <div class="flex items-center gap-2">
          <label class="text-xs text-ink-muted">Per halaman:</label>
          <select
            :value="perPage"
            @change="emit('per-page-change', Number($event.target.value))"
            class="h-8 rounded border border-border-strong bg-surface px-2 text-sm text-ink"
          >
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </div>
        <Pagination
          v-if="total > perPage"
          :page="page"
          :total="total"
          :per-page="perPage"
          @update:page="emit('page-change', $event)"
        />
        <span v-else-if="total" class="text-sm text-ink-muted">Menampilkan semua {{ total }} data</span>
      </div>
    </div>
  </div>
</template>

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
  <div>
    <div class="overflow-x-auto rounded-card border border-border-default scroll-slim">
      <table class="w-full min-w-[720px] text-sm">
        <thead class="sticky top-0 bg-surface-3">
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              @click="toggleSort(col)"
              :class="[alignClass(col), col.sortable ? 'cursor-pointer select-none' : '', 'px-4 py-2 font-semibold text-ink-muted']"
            >
              {{ col.label }}
              <span v-if="sortKey === col.key">{{ sortDir === "asc" ? "▲" : "▼" }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row[rowKey]" class="border-t border-border-default hover:bg-surface-2">
            <td v-for="col in columns" :key="col.key" :class="[alignClass(col), 'px-4 py-2 text-ink']">
              <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
                {{ fmt(row[col.key], col) }}
              </slot>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-if="!rows.length" :message="emptyMessage" class="mt-3" />
    <div class="mt-3 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <label class="text-xs text-ink-muted">Per halaman:</label>
        <select
          :value="perPage"
          @change="emit('per-page-change', Number($event.target.value))"
          class="rounded-card border border-border-default bg-surface px-2 py-1 text-sm text-ink"
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
    </div>
  </div>
</template>

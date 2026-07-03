# Frontend Task Playbook — Arunika POS

> **Audience:** an AI coding model executing tasks one by one (Haiku 4.5 / Gemini Flash 3 level).
> **Companion docs:** `planing/prd.md` (product spec), `planing/frontend_plan.md` (high-level plan). This file is the step-by-step build list.
> **Instructions are in English. All user-facing UI text stays in Indonesian.**

---

## SECTION 0 — RULES (read first, follow every task)

1. Only touch files under `frontend/`. **Do NOT change any Python/Django file.** Backend endpoints are built separately.
2. Do the tasks **in order**. Each task says CREATE or EDIT, gives the exact file path, and gives the **full code**. Paste it as-is.
3. Do NOT invent component props, URLs, or prop names. If a task does not give you something, copy the closest existing pattern from `frontend/pages/Admin/Inventory/BarangHistori.vue`.
4. UI strings (labels, buttons, messages) are **Indonesian**. Code identifiers and comments are English.
5. Colors: use theme classes only (e.g. `bg-surface`, `text-ink`, `border-border-default`, `bg-brand-600`, `text-danger-fg`). **Never write raw hex colors.** The list of classes is in Task reference R1 below.
6. After finishing a task, run `npm run build`. If it fails, fix the file you just wrote before moving on.
7. Each page reads data from a **deferred prop** sent by the backend. The exact shape is written in each task under "PROP CONTRACT". Assume the backend sends it. Guard everything with `|| []` / `|| {}`.
8. Mark each task done: change `- [ ]` to `- [x]`.

### R1 — Theme classes you may use (from `frontend/css/main.css`)
Surfaces: `bg-surface`, `bg-surface-2`, `bg-surface-3`.
Text: `text-ink`, `text-ink-muted`, `text-ink-subtle`.
Borders: `border-border-default`, `border-border-strong`.
Brand: `bg-brand-600`, `text-brand-fg`, `bg-brand-bg`.
Status (bg+fg pairs): `bg-success-bg text-success-fg`, `bg-warning-bg text-warning-fg`, `bg-danger-bg text-danger-fg`.
Radius: `rounded-card`. Scroll area: `scroll-slim`. Accent tick: `vfin`. Strip: `panel-strip`.

### R2 — Existing components you will reuse (do not modify them)
- `@/components/ui/Button.vue` — props `variant` (`primary|secondary|ghost|danger|success|warning`), `size` (`sm|md`), `loading`, `disabled`. Slot = label.
- `@/components/ui/Input.vue` — `v-model`, props `label`, `type`, `placeholder`.
- `@/components/ui/Select.vue` — `v-model`, props `label`, `options` (`[{value,label}]`), `placeholder`.
- `@/components/ui/Card.vue` — props `title`, `subtitle`; slots `header`, default.
- `@/components/ui/Badge.vue` — prop `variant` (`neutral|success|warning|danger|brand`). Slot = text.
- `@/components/ui/Banner.vue` — props `variant` (`danger|warning|info`), `message`.
- `@/components/ui/LoadingCard.vue` — prop `message`.
- `@/components/ui/Pagination.vue` — props `page`, `total`, `perPage`; emits `update:page`.
- `@/components/ui/ToastContainer.vue` — already global in `AdminLayout`. Do not add again.
- `@/components/report/ReportView.vue` — existing CLIENT-side report wrapper (used by small pages).
- `@/utils/xlsx.js` — `downloadXlsx(filename, columns, rows, sheetName)`, `stamp()`.
- `@/stores/ui.js` — `useUiStore()` gives `pushToast(message, type, timeout)`.
- `@/layouts/AdminLayout.vue` — page wrapper, prop `title`.

---

## SECTION 1 — SHARED BUILDING BLOCKS

Build these first. Later pages depend on them.

### - [ ] T1 — CREATE `frontend/components/ui/DateRangeField.vue`
Two date inputs plus quick presets. Emits `update:from` / `update:to`.

```vue
<script setup>
const props = defineProps({
  from: { type: String, default: "" },
  to: { type: String, default: "" },
});
const emit = defineEmits(["update:from", "update:to"]);

function iso(d) {
  return d.toISOString().slice(0, 10);
}
function setPreset(name) {
  const now = new Date();
  let from = new Date(now);
  let to = new Date(now);
  if (name === "hari-ini") {
    // from = to = today
  } else if (name === "kemarin") {
    from.setDate(now.getDate() - 1);
    to.setDate(now.getDate() - 1);
  } else if (name === "7hari") {
    from.setDate(now.getDate() - 6);
  } else if (name === "bulan-ini") {
    from = new Date(now.getFullYear(), now.getMonth(), 1);
  } else if (name === "bulan-lalu") {
    from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    to = new Date(now.getFullYear(), now.getMonth(), 0);
  }
  emit("update:from", iso(from));
  emit("update:to", iso(to));
}
const presets = [
  { key: "hari-ini", label: "Hari ini" },
  { key: "kemarin", label: "Kemarin" },
  { key: "7hari", label: "7 Hari" },
  { key: "bulan-ini", label: "Bulan Ini" },
  { key: "bulan-lalu", label: "Bulan Lalu" },
];
</script>

<template>
  <div class="space-y-2">
    <div class="grid grid-cols-2 gap-2">
      <label class="block">
        <span class="mb-1 block text-xs text-ink-muted">Dari Tanggal</span>
        <input
          type="date"
          :value="from"
          @input="emit('update:from', $event.target.value)"
          class="w-full rounded-card border border-border-default bg-surface px-3 py-2 text-sm text-ink"
        />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs text-ink-muted">Sampai Tanggal</span>
        <input
          type="date"
          :value="to"
          @input="emit('update:to', $event.target.value)"
          class="w-full rounded-card border border-border-default bg-surface px-3 py-2 text-sm text-ink"
        />
      </label>
    </div>
    <div class="flex flex-wrap gap-1">
      <button
        v-for="p in presets"
        :key="p.key"
        type="button"
        @click="setPreset(p.key)"
        class="rounded-card border border-border-default px-2 py-1 text-xs text-ink-muted hover:bg-surface-3"
      >
        {{ p.label }}
      </button>
    </div>
  </div>
</template>
```
**DoD:** file exists, `npm run build` passes.

### - [ ] T2 — CREATE `frontend/components/ui/SelectSearch.vue`
Dropdown with a search box. `v-model` = selected value.

```vue
<script setup>
import { ref, computed } from "vue";
const props = defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  options: { type: Array, default: () => [] }, // [{value,label}]
  label: { type: String, default: "" },
  placeholder: { type: String, default: "Semua" },
});
const emit = defineEmits(["update:modelValue"]);
const open = ref(false);
const q = ref("");
const filtered = computed(() => {
  const t = q.value.toLowerCase().trim();
  if (!t) return props.options;
  return props.options.filter((o) => String(o.label).toLowerCase().includes(t));
});
const currentLabel = computed(() => {
  const hit = props.options.find((o) => String(o.value) === String(props.modelValue));
  return hit ? hit.label : props.placeholder;
});
function pick(v) {
  emit("update:modelValue", v);
  open.value = false;
  q.value = "";
}
</script>

<template>
  <div class="relative">
    <span v-if="label" class="mb-1 block text-xs text-ink-muted">{{ label }}</span>
    <button
      type="button"
      @click="open = !open"
      class="flex w-full items-center justify-between rounded-card border border-border-default bg-surface px-3 py-2 text-left text-sm text-ink"
    >
      <span :class="modelValue === '' || modelValue === null ? 'text-ink-subtle' : ''">{{ currentLabel }}</span>
      <span class="text-ink-subtle">▾</span>
    </button>
    <div
      v-if="open"
      class="absolute z-20 mt-1 w-full rounded-card border border-border-default bg-surface shadow-lg"
    >
      <input
        v-model="q"
        type="text"
        placeholder="Cari…"
        class="w-full border-b border-border-default bg-surface px-3 py-2 text-sm text-ink"
      />
      <div class="max-h-56 overflow-y-auto scroll-slim">
        <button
          type="button"
          @click="pick('')"
          class="block w-full px-3 py-2 text-left text-sm text-ink-muted hover:bg-surface-3"
        >
          {{ placeholder }}
        </button>
        <button
          v-for="o in filtered"
          :key="o.value"
          type="button"
          @click="pick(o.value)"
          class="block w-full px-3 py-2 text-left text-sm text-ink hover:bg-surface-3"
        >
          {{ o.label }}
        </button>
      </div>
    </div>
  </div>
</template>
```
**DoD:** build passes; clicking opens list, typing filters, selecting emits value.

### - [ ] T3 — CREATE `frontend/components/ui/StatusSelect.vue`
Thin wrapper over existing `Select` for the 0/1/2 status enum.

```vue
<script setup>
import Select from "@/components/ui/Select.vue";
defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  label: { type: String, default: "Status" },
});
defineEmits(["update:modelValue"]);
const options = [
  { value: "1", label: "Aktif" },
  { value: "0", label: "Non-aktif" },
  { value: "2", label: "Tidak dijual" },
];
</script>

<template>
  <Select
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    :label="label"
    :options="options"
    placeholder="Semua status"
  />
</template>
```
**DoD:** build passes.

### - [ ] T4 — CREATE `frontend/components/ui/FilterPanel.vue`
Collapsible filter box. Fields go in the default slot. Enter submits (form submit). Buttons: Tampilkan + Reset.

```vue
<script setup>
import { ref } from "vue";
import Button from "@/components/ui/Button.vue";
defineProps({
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(["submit", "reset"]);
const open = ref(true);
</script>

<template>
  <div class="mb-4 rounded-card border border-border-default bg-surface">
    <button
      type="button"
      @click="open = !open"
      class="flex w-full items-center justify-between px-4 py-3 text-left"
    >
      <span class="text-sm font-semibold text-ink">Filter</span>
      <span class="text-ink-subtle">{{ open ? "▾" : "▸" }}</span>
    </button>
    <form v-show="open" @submit.prevent="emit('submit')" class="border-t border-border-default p-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <slot />
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('reset')">Reset</Button>
        <Button type="submit" variant="primary" :loading="loading">Tampilkan</Button>
      </div>
    </form>
  </div>
</template>
```
**DoD:** build passes; pressing Enter inside a field triggers `submit`.

### - [ ] T5 — CREATE `frontend/components/ui/ExportButton.vue`
Two modes. `client` builds the file in the browser; `server` is a download link that carries the active filter.

```vue
<script setup>
import Button from "@/components/ui/Button.vue";
import { downloadXlsx, stamp } from "@/utils/xlsx.js";
const props = defineProps({
  mode: { type: String, default: "client" }, // "client" | "server"
  // client mode:
  filename: { type: String, default: "laporan" },
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
  sheetName: { type: String, default: "Data" },
  // server mode:
  href: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
});
function onClient() {
  downloadXlsx(`${props.filename}-${stamp()}.xlsx`, props.columns, props.rows, props.sheetName);
}
</script>

<template>
  <a
    v-if="mode === 'server'"
    :href="href"
    class="inline-flex items-center gap-2 rounded-card bg-success-bg px-3 py-2 text-sm font-medium text-success-fg hover:opacity-90"
  >
    Export Excel
  </a>
  <Button v-else variant="success" :disabled="disabled" @click="onClient">Export Excel</Button>
</template>
```
**DoD:** build passes.

### - [ ] T5b — CREATE `frontend/components/ui/EmptyState.vue`
```vue
<script setup>
defineProps({
  message: { type: String, default: "Tidak ada data." },
});
</script>
<template>
  <div class="rounded-card border border-dashed border-border-default bg-surface-2 py-12 text-center">
    <p class="text-sm text-ink-muted">{{ message }}</p>
  </div>
</template>
```
**DoD:** build passes.

### - [ ] T5c — CREATE `frontend/components/ui/TableSkeleton.vue`
```vue
<script setup>
defineProps({ rows: { type: Number, default: 8 } });
</script>
<template>
  <div class="overflow-hidden rounded-card border border-border-default">
    <div class="h-10 bg-surface-3"></div>
    <div
      v-for="n in rows"
      :key="n"
      class="flex items-center gap-4 border-t border-border-default px-4 py-3"
    >
      <div class="h-3 flex-1 animate-pulse rounded bg-surface-3"></div>
      <div class="h-3 w-24 animate-pulse rounded bg-surface-3"></div>
      <div class="h-3 w-16 animate-pulse rounded bg-surface-3"></div>
    </div>
  </div>
</template>
```
**DoD:** build passes.

### - [ ] T5d — CREATE `frontend/components/ui/SummaryStrip.vue`
Renders KPI cards from an array. Each item `{label, value}`.
```vue
<script setup>
defineProps({ items: { type: Array, default: () => [] } });
</script>
<template>
  <div v-if="items.length" class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
    <div v-for="it in items" :key="it.label" class="rounded-card border border-border-default bg-surface p-3">
      <p class="text-xs text-ink-muted">{{ it.label }}</p>
      <p class="text-lg font-semibold text-ink">{{ it.value }}</p>
    </div>
  </div>
</template>
```
**DoD:** build passes.

### - [ ] T6 — CREATE `frontend/components/report/ServerTable.vue`
Server-driven table: it renders rows exactly as given (no local sort/paging), emits intent when the user clicks a header or changes page. Formatting for `number`/`rupiah`/`date` is built in.

```vue
<script setup>
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
const emit = defineEmits(["page-change", "sort-change"]);

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
    <div class="mt-3">
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
```
**DoD:** build passes.

### - [ ] T7 — CREATE `frontend/components/report/ReportPage.vue`
The page shell: title bar + export, a slot for the filter panel (rendered instantly), then the deferred data area with skeleton fallback, connection-error banner, summary strip, and the server table.

```vue
<script setup>
import { Deferred } from "@inertiajs/vue3";
import Banner from "@/components/ui/Banner.vue";
import TableSkeleton from "@/components/ui/TableSkeleton.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import ServerTable from "@/components/report/ServerTable.vue";
import ExportButton from "@/components/ui/ExportButton.vue";

const props = defineProps({
  title: { type: String, required: true },
  deferredKey: { type: String, required: true }, // Inertia prop name, e.g. "report"
  data: { type: Object, default: null }, // the deferred payload
  columns: { type: Array, required: true },
  rowKey: { type: String, default: "id" },
  page: { type: Number, default: 1 },
  perPage: { type: Number, default: 50 },
  sortKey: { type: String, default: "" },
  sortDir: { type: String, default: "desc" },
  exportHref: { type: String, default: "" },
  summaryItems: { type: Array, default: () => [] },
});
const emit = defineEmits(["page-change", "sort-change"]);
</script>

<template>
  <div>
    <div class="mb-4 flex items-center justify-between">
      <h1 class="text-xl font-semibold text-ink">{{ title }}</h1>
      <ExportButton v-if="exportHref" mode="server" :href="exportHref" />
    </div>

    <!-- Filter panel lives OUTSIDE Deferred so it shows instantly -->
    <slot name="filters" />

    <Deferred :data="deferredKey">
      <template #fallback><TableSkeleton /></template>

      <Banner v-if="data && data.conn_error" variant="warning" :message="data.conn_error" />
      <SummaryStrip :items="summaryItems" />
      <ServerTable
        :columns="columns"
        :rows="(data && data.rows) || []"
        :row-key="rowKey"
        :total="(data && data.total) || 0"
        :page="page"
        :per-page="perPage"
        :sort-key="sortKey"
        :sort-dir="sortDir"
        @page-change="emit('page-change', $event)"
        @sort-change="emit('sort-change', $event)"
      >
        <template v-for="(_, name) in $slots" #[name]="slotProps">
          <slot :name="name" v-bind="slotProps" />
        </template>
      </ServerTable>
    </Deferred>
  </div>
</template>
```
**DoD:** build passes.

### - [ ] T8 — CREATE `frontend/composables/useServerReport.js`
One helper that every server-driven page uses. It holds the filter form, re-fetches with `router.get`, and builds the export URL.

```js
import { reactive, computed } from "vue";
import { router } from "@inertiajs/vue3";

// url: the page URL, e.g. "/admin-panel/laporan/penjualan"
// initial: values from props.filters (echoed by backend)
export function useServerReport(url, initial = {}) {
  const form = reactive({
    date_from: "",
    date_to: "",
    search: "",
    sort: "tanggal",
    sort_dir: "desc",
    page: 1,
    per_page: 50,
    ...initial,
  });

  function cleanParams() {
    const out = {};
    for (const [k, v] of Object.entries(form)) {
      if (v !== "" && v !== null && v !== undefined) out[k] = v;
    }
    return out;
  }

  function apply(extra = {}) {
    Object.assign(form, extra);
    router.get(url, cleanParams(), { preserveState: true, preserveScroll: true });
  }
  function onPage(p) {
    apply({ page: p });
  }
  function onSort(s) {
    apply({ sort: s.key, sort_dir: s.dir, page: 1 });
  }
  function reset() {
    for (const k of Object.keys(form)) {
      if (k === "page") form[k] = 1;
      else if (k === "sort" || k === "sort_dir" || k === "per_page") continue;
      else form[k] = "";
    }
    apply({ page: 1 });
  }

  const exportHref = computed(() => `${url}/export?` + new URLSearchParams(cleanParams()).toString());

  return { form, apply, onPage, onSort, reset, exportHref };
}
```
**DoD:** build passes.

---

## SECTION 2 — PILOT PAGE (do this before the rest; it is the template)

### - [ ] T9 — EDIT `frontend/pages/Admin/Reports/PenjualanAll.vue`
Replace the whole file. This is the reference every other server-driven page copies.

**PROP CONTRACT (backend sends this deferred prop named `report`):**
```
report = {
  rows: [ { no_transaksi, tanggal, customer, barang, qty, harga, subtotal, ... } ],
  total: <int, total rows for pagination>,
  summary: { total_nilai, total_qty, jml_baris },   // numbers
  options: { divisi: [{value,label}], ... },          // filter dropdown data
  conn_error: <string or null>,
}
filters = { date_from, date_to, kd_divisi, search, sort, sort_dir, page, per_page }  // echo of what user asked
```

```vue
<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/penjualan";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "customer", label: "Customer" },
  { key: "barang", label: "Barang" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "harga", label: "Harga", align: "right", format: "rupiah" },
  { key: "subtotal", label: "Subtotal", align: "right", format: "rupiah", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Baris", value: nf.format(s.jml_baris || 0) },
    { label: "Total Qty", value: nf.format(s.total_qty || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Penjualan (Detail)">
    <ReportPage
      title="Penjualan (Detail)"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="no_transaksi"
      :page="Number(form.page)"
      :per-page="Number(form.per_page)"
      :sort-key="form.sort"
      :sort-dir="form.sort_dir"
      :export-href="exportHref"
      :summary-items="summaryItems"
      @page-change="onPage"
      @sort-change="onSort"
    >
      <template #filters>
        <FilterPanel @submit="apply({ page: 1 })" @reset="reset">
          <DateRangeField v-model:from="form.date_from" v-model:to="form.date_to" />
          <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
          <Input v-model="form.search" label="Cari" placeholder="no transaksi / barang / customer" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
```
**DoD:** build passes. In the browser (Mode B) the skeleton shows first, then the table. Changing a filter and pressing Tampilkan reloads. `@/mock/penjualan` is no longer imported by this file.

---

## SECTION 3 — REMAINING SERVER-SIDE PAGES

Each task: copy the T9 pattern, change only the marked parts (`title`, `URL`, `columns`, filter fields, `deferred-key` stays `report`, `row-key`). Full code given.

### - [ ] T10 — EDIT `frontend/pages/Admin/Reports/PenjualanNota.vue`
URL `/admin-panel/laporan/penjualan-nota`, row-key `no_transaksi`.
Columns:
```js
const columns = [
  { key: "no_transaksi", label: "No. Nota", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "customer", label: "Customer" },
  { key: "total_kotor", label: "Total Kotor", align: "right", format: "rupiah" },
  { key: "potongan", label: "Potongan", align: "right", format: "rupiah" },
  { key: "pajak", label: "Pajak", align: "right", format: "rupiah" },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
];
```
Filters: `DateRangeField`, `SelectSearch` Divisi, `SelectSearch` Customer (`options` = `report.options.customer`), `Input` search. Title "Penjualan per Nota".
**DoD:** build passes; no mock import.

### - [ ] T11 — EDIT `frontend/pages/Admin/Reports/PenjualanCustomer.vue`
URL `/admin-panel/laporan/penjualan-customer`, row-key `kd_customer`.
```js
const columns = [
  { key: "customer", label: "Customer", sortable: true },
  { key: "kota", label: "Kota" },
  { key: "jml_nota", label: "Jml Nota", align: "right", format: "number", sortable: true },
  { key: "total", label: "Total", align: "right", format: "rupiah", sortable: true },
];
```
Filters: `DateRangeField`, `SelectSearch` Divisi, `Input` search. Title "Penjualan per Customer".

### - [ ] T12 — EDIT `frontend/pages/Admin/Reports/PenjualanUser.vue`
URL `/admin-panel/laporan/penjualan-user`, row-key `kd_user`.
```js
const columns = [
  { key: "user", label: "User / Kasir", sortable: true },
  { key: "jml_nota", label: "Jml Nota", align: "right", format: "number", sortable: true },
  { key: "total", label: "Total", align: "right", format: "rupiah", sortable: true },
];
```
Filters: `DateRangeField`, `SelectSearch` Divisi. Title "Penjualan per User".

### - [ ] T13 — EDIT `frontend/pages/Admin/Reports/PenjualanPeriode.vue`
URL `/admin-panel/laporan/penjualan-periode`, row-key `periode`.
```js
const columns = [
  { key: "periode", label: "Periode", sortable: true },
  { key: "jml_nota", label: "Jml Nota", align: "right", format: "number" },
  { key: "total", label: "Total", align: "right", format: "rupiah", sortable: true },
];
```
Filters: `DateRangeField`, a `Select` for granularity (`options`: `[{value:'harian',label:'Harian'},{value:'bulanan',label:'Bulanan'}]`, bind `form.granularitas`), `SelectSearch` Divisi. Title "Penjualan per Periode".

### - [ ] T14 — EDIT `frontend/pages/Admin/Reports/ReturPenjualan.vue`
URL `/admin-panel/laporan/retur-penjualan`, row-key `no_retur`.
```js
const columns = [
  { key: "no_retur", label: "No. Retur", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "customer", label: "Customer" },
  { key: "barang", label: "Barang" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "nilai", label: "Nilai", align: "right", format: "rupiah", sortable: true },
];
```
Filters: `DateRangeField`, `SelectSearch` Divisi, `SelectSearch` Customer, `Input` search. Title "Retur Penjualan".

### - [ ] T15 — EDIT `frontend/pages/Admin/Reports/Pembelian.vue`
URL `/admin-panel/laporan/pembelian`, row-key `no_transaksi`.
```js
const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "supplier", label: "Supplier" },
  { key: "barang", label: "Barang" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "harga_beli", label: "Harga Beli", align: "right", format: "rupiah" },
  { key: "subtotal", label: "Subtotal", align: "right", format: "rupiah", sortable: true },
];
```
Filters: `DateRangeField`, `SelectSearch` Divisi, `SelectSearch` Supplier (`report.options.supplier`), `Input` search. Title "Pembelian".

### - [ ] T16 — EDIT `frontend/pages/Admin/Reports/ReturPembelian.vue`
URL `/admin-panel/laporan/retur-pembelian`, row-key `no_retur`. Columns like T14 but `supplier` instead of `customer`. Title "Retur Pembelian".

### - [ ] T17 — EDIT `frontend/pages/Admin/Inventory/Opname.vue`
URL `/admin-panel/inventory/opname`, row-key `no_transaksi`.
```js
const columns = [
  { key: "no_transaksi", label: "No. Opname", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "divisi", label: "Divisi" },
  { key: "barang", label: "Barang" },
  { key: "qty_sistem", label: "Qty Sistem", align: "right", format: "number" },
  { key: "qty_fisik", label: "Qty Fisik", align: "right", format: "number" },
  { key: "selisih", label: "Selisih", align: "right", format: "number", sortable: true },
];
```
Filters: `DateRangeField`, `SelectSearch` Divisi, `Input` search. Title "Opname Stok".

### - [ ] T18 — EDIT `frontend/pages/Admin/Cash/Kas.vue`
URL `/admin-panel/kas/harian`, row-key `_rid` (backend gives a synthetic id).
```js
const columns = [
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "kas", label: "Kas" },
  { key: "keterangan", label: "Keterangan" },
  { key: "masuk", label: "Masuk", align: "right", format: "rupiah" },
  { key: "keluar", label: "Keluar", align: "right", format: "rupiah" },
  { key: "saldo", label: "Saldo", align: "right", format: "rupiah" },
];
```
Filters: `DateRangeField`, `SelectSearch` Kas (`report.options.kas`). Title "Kas Harian".

### - [ ] T19 — EDIT `frontend/pages/Admin/Cash/Shift.vue`
URL `/admin-panel/kas/shift`, row-key `no_transaksi`.
```js
const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "pegawai", label: "Pegawai" },
  { key: "shift", label: "Shift" },
  { key: "keterangan", label: "Keterangan" },
];
```
Filters: `DateRangeField`, `SelectSearch` Divisi, `Input` search. Title "Shift Kasir".

---

## SECTION 3B — SMALL CLIENT-SIDE PAGES (use existing ReportView)

These datasets are small. The backend still sends ONE deferred prop holding all filtered rows. Keep client-side search/sort/paging via the existing `ReportView`.

**PATTERN (client page):**
```vue
<script setup>
import { computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  data: { type: Object, default: null }, // { rows, conn_error }
});
const rows = computed(() => props.data?.rows || []);
const columns = [ /* per page */ ];
</script>

<template>
  <AdminLayout title="JUDUL">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="JUDUL"
        :columns="columns"
        :rows="rows"
        row-key="ROWKEY"
        :search-keys="[/* keys */]"
        export-name="NAMA-FILE"
        sheet-name="SHEET"
        :conn-error="data && data.conn_error"
      />
    </Deferred>
  </AdminLayout>
</template>
```

### - [ ] T20 — EDIT `frontend/pages/Admin/Inventory/StokAkhir.vue`
Deferred prop `data`. row-key `kd_barang`. Columns: `kd_barang`(Kode), `barang`(Barang), `kategori`, `stok_akhir`(align right, number). search-keys `['kd_barang','barang']`. Title "Stok Akhir per Tanggal". Remove `@/mock/inventory` import.

### - [ ] T21 — EDIT `frontend/pages/Admin/Inventory/StokDivisi.vue`
row-key `kd_barang`. Columns: `kd_barang`, `barang`, `divisi`, `stok`(right,number), `stok_min`(right,number). Add a `cell-stok` slot showing a red `Badge` when `row.stok < row.stok_min`. search-keys `['kd_barang','barang']`. Title "Stok per Divisi".

### - [ ] T22 — EDIT `frontend/pages/Admin/Promo/Promo.vue`
row-key `kd_promo`. Columns: `kd_promo`, `divisi`, `barang`, `harga_promo`(right,rupiah), `tanggal_awal`(date), `tanggal_akhir`(date), `status`. search-keys `['kd_promo','barang']`. Title "Promo & Diskon".

### - [ ] T23 — EDIT `frontend/pages/Admin/Promo/Voucher.vue`
row-key `kd_voucher`. Columns: `kd_voucher`, `nama`, `nominal`(right,rupiah), `dipakai`(right,number), `nilai_dipakai`(right,rupiah), `status`. search-keys `['kd_voucher','nama']`. Title "Voucher".

### - [ ] T24 — EDIT `frontend/pages/Admin/Analytics/FmiPenjualan.vue`
row-key `kd_barang`. Columns: `kd_barang`, `barang`, `kategori`, `qty_terjual`(right,number), `nilai`(right,rupiah), `kelas`(FMI class). Add `cell-kelas` slot: `Badge` variant `success` for "Fast", `warning` for "Medium", `danger` for "Slow". search-keys `['kd_barang','barang']`. Title "FMI Penjualan".

### - [ ] T25 — EDIT `frontend/pages/Admin/Analytics/FmiStok.vue`
row-key `kd_barang`. Columns: `kd_barang`, `barang`, `stok`(right,number), `terjual`(right,number), `rasio`(right,number), `status`. `cell-status` slot: Badge `danger` "Kritis", `warning` "Overstock", `success` "Sehat". Title "FMI Stok".

### - [ ] T26 — EDIT `frontend/pages/Admin/MasterData/Products.vue` (already real — enhance)
Keep server search if present. ADD an `ExportButton` (client mode) above the table using the current `columns` and displayed rows. ADD filter fields for merk/model/warna/status using `SelectSearch`/`StatusSelect` if the page has a filter area; otherwise wrap existing controls. Do not remove working behavior.
**DoD:** export downloads an xlsx; build passes.

### - [ ] T27 — EDIT `frontend/pages/Admin/MasterData/Customers.vue` (already real — enhance)
Add `ExportButton` (client) + `SelectSearch` Kota filter + `StatusSelect`. Keep existing search.

### - [ ] T28 — CREATE `frontend/pages/Admin/MasterData/Supplier.vue` (new page)
Copy the T27 Customers page structure. Deferred prop `data` = `{ rows, conn_error }`. row-key `kd_supplier`. Columns: `kd_supplier`, `nama`, `kota`, `kontak`, `hp`, `status`. search-keys `['kd_supplier','nama','kota']`. Title "Master Supplier".
**NOTE (dependency, not your job):** backend must add the view/URL and a menu key `supplier`. If the page 404s, that backend piece is missing — leave a comment and continue.

### - [ ] T29 — EDIT `frontend/pages/Admin/Dashboard.vue` (already real — tidy)
Replace ad-hoc KPI cards with `SummaryStrip` for consistency. Do not change data source. Keep the existing chart.

### - [ ] T30 — EDIT `frontend/pages/Admin/ActivityLogs.vue` (already real — enhance)
Add a `FilterPanel` with: `Input` (aksi), `SelectSearch` (user, from `report.options.user` if provided), `DateRangeField`. Add `ExportButton`. If the page is currently client-side, keep it client-side (use existing `ReportView`), just wire the filter fields to a `router.get` reload. Title "Log Aktivitas".

---

## SECTION 4 — WRITE PAGES

### - [ ] T31 — EDIT `frontend/pages/Admin/MasterData/UpdateBarang.vue` (add confirm-diff modal)
Do NOT change the existing save logic. ADD a confirmation modal that shows old → new price before calling save. Insert this block and gate the existing `saveHarga()` behind it.

Add to `<script setup>`:
```js
import { ref, computed } from "vue";
import Modal from "@/components/ui/Modal.vue";
import Button from "@/components/ui/Button.vue";

const showConfirm = ref(false);
// `editing` and `priceForm` already exist in this file.
const priceDiff = computed(() => {
  if (!editing.value) return [];
  return editing.value.satuan.map((u) => ({
    kd_satuan: u.kd_satuan,
    lama: u.harga_jual,
    baru: Number(priceForm.prices[u.kd_satuan]) || 0,
  })).filter((d) => d.lama !== d.baru);
});
function askConfirm() {
  showConfirm.value = true;
}
function confirmSave() {
  showConfirm.value = false;
  saveHarga(); // existing function
}
```
In the template, change the existing "Simpan Harga" button `@click` from `saveHarga` to `askConfirm`, and add this modal near the end of the template (inside root):
```vue
<Modal :show="showConfirm" title="Konfirmasi Perubahan Harga" @close="showConfirm = false">
  <table class="w-full text-sm">
    <thead>
      <tr class="text-ink-muted">
        <th class="py-1 text-left">Satuan</th>
        <th class="py-1 text-right">Harga Lama</th>
        <th class="py-1 text-right">Harga Baru</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="d in priceDiff" :key="d.kd_satuan" class="border-t border-border-default">
        <td class="py-1">{{ d.kd_satuan }}</td>
        <td class="py-1 text-right text-ink-muted">{{ d.lama }}</td>
        <td class="py-1 text-right font-semibold text-ink">{{ d.baru }}</td>
      </tr>
    </tbody>
  </table>
  <p v-if="!priceDiff.length" class="text-sm text-ink-muted">Tidak ada perubahan harga.</p>
  <template #footer>
    <Button variant="ghost" @click="showConfirm = false">Batal</Button>
    <Button variant="primary" :disabled="!priceDiff.length" @click="confirmSave">Simpan</Button>
  </template>
</Modal>
```
**DoD:** clicking Simpan opens the modal listing changed prices; Simpan inside modal performs the real save.

### - [ ] T32 — CREATE `frontend/pages/Admin/MasterData/SyncHistory.vue` (new page)
Deferred prop `data` = `{ rows, conn_error }` where each row is a `SyncRun`. Server or client is fine — use `ReportView` (client) for simplicity. Add a details `Modal` opened per row that lists `SyncRunItem` rows (old → new price).

```vue
<script setup>
import { ref, computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import Modal from "@/components/ui/Modal.vue";
import Badge from "@/components/ui/Badge.vue";

const props = defineProps({ data: { type: Object, default: null } });
const rows = computed(() => props.data?.rows || []);
const columns = [
  { key: "created_at", label: "Waktu", sortable: true, format: "date" },
  { key: "user", label: "User" },
  { key: "src", label: "Sumber" },
  { key: "dst", label: "Tujuan" },
  { key: "mode", label: "Mode" },
  { key: "total_items", label: "Baris", align: "right", format: "number" },
  { key: "status", label: "Status" },
];
const detail = ref(null); // holds a SyncRun with .items
</script>

<template>
  <AdminLayout title="Riwayat Sinkronisasi Harga">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil riwayat…" /></template>
      <ReportView
        title="Riwayat Sinkronisasi Harga"
        :columns="columns"
        :rows="rows"
        row-key="id"
        :search-keys="['user', 'src', 'dst']"
        export-name="riwayat-sync"
        sheet-name="Riwayat Sync"
        :conn-error="data && data.conn_error"
      >
        <template #cell-status="{ value }">
          <Badge :variant="value === 'ok' ? 'success' : value === 'gagal' ? 'danger' : 'warning'">{{ value }}</Badge>
        </template>
        <template #cell-total_items="{ row, value }">
          <button class="text-brand-fg underline" @click="detail = row">{{ value }}</button>
        </template>
      </ReportView>
    </Deferred>

    <Modal :show="!!detail" title="Detail Item Sinkronisasi" size="lg" @close="detail = null">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-ink-muted">
            <th class="py-1 text-left">Barang</th>
            <th class="py-1 text-left">Satuan</th>
            <th class="py-1 text-right">Harga Lama</th>
            <th class="py-1 text-right">Harga Baru</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(it, i) in (detail?.items || [])" :key="i" class="border-t border-border-default">
            <td class="py-1">{{ it.nama_barang }}</td>
            <td class="py-1">{{ it.kd_satuan }}</td>
            <td class="py-1 text-right text-ink-muted">{{ it.harga_lama_dst }}</td>
            <td class="py-1 text-right font-semibold text-ink">{{ it.harga_baru }}</td>
          </tr>
        </tbody>
      </table>
    </Modal>
  </AdminLayout>
</template>
```
**NOTE (dependency):** backend must add `SyncRun`/`SyncRunItem`, a view, URL, and menu key `sync_history`. Frontend is ready regardless.

---

## SECTION 5 — NAVIGATION

### - [ ] T33 — EDIT `frontend/composables/useNav.js`
The nav is driven by `allowedMenus` from the backend, so **new menu items appear automatically once the backend adds them**. You only need to make sure the section labels exist. Confirm `SECTION_LABELS` contains `master`. No new group needed — Supplier and Riwayat Sync fall under the existing `master` section.
**Do nothing else here unless a menu label is missing.**
**DoD:** build passes; when backend adds `supplier` / `sync_history` menu keys, they show under "Master Data".

---

## SECTION 6 — COMFORT LAYER (apply after pages work)

Most comfort features are already baked into the shared components (URL-persisted filters via `router.get`, Enter-to-submit via `FilterPanel`'s `<form>`, sticky header + horizontal scroll in `ServerTable`, skeleton loading, id-ID number/rupiah formatting). Remaining explicit tasks:

### - [ ] T34 — Toast on save/sync/export success
In pages that write (`UpdateBarang.vue`, `SyncHarga.vue`), after a successful action add:
```js
import { useUiStore } from "@/stores/ui.js";
const ui = useUiStore();
// inside onSuccess:
ui.pushToast("Berhasil disimpan.", "success");
```
(Backend flash messages already surface as toasts; add this only where there is no flash.)
**DoD:** a toast appears after saving.

### - [ ] T35 — Page-size selector (server pages)
In `ServerTable.vue` add a small select above the table bound to a new emit `per-page-change`, options 25/50/100. Then in each server page handle it: `@per-page-change="apply({ per_page: $event, page: 1 })"`. (Optional but recommended.)
**DoD:** changing page size reloads with new `per_page`.

### - [ ] T36 — Focus search with "/"
Add to `ServerTable.vue` `onMounted`:
```js
import { onMounted, onUnmounted } from "vue";
function onKey(e) {
  if (e.key === "/" && !/input|textarea|select/i.test(e.target.tagName)) {
    e.preventDefault();
    document.querySelector('input[placeholder*="Cari"], input[placeholder*="cari"]')?.focus();
  }
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
```
**DoD:** pressing "/" focuses the search box.

### - [ ] T37 — Dark mode + mobile check
For every page you touched: switch theme to dark (top-nav toggle) and shrink the window to phone width. Confirm no raw colors, text stays readable, tables scroll horizontally. Fix any hardcoded color you find (replace with an R1 class).
**DoD:** all migrated pages readable in dark mode and on mobile.

---

## SECTION 7 — CLEANUP & FINAL VERIFY

### - [ ] T38 — Remove mock data
Only after every page in Sections 2–3B no longer imports from `@/mock`:
1. Search the project: there must be **zero** matches for `@/mock` under `frontend/pages`.
2. Delete the folder `frontend/mock/`.
**DoD:** `frontend/mock/` is gone and build still passes.

### - [ ] T39 — Full verification checklist
Run `npm run build`, then `python manage.py runserver 0.0.0.0:8000` (Mode B, `.env DJANGO_VITE_DEV=0`). For each migrated page:
- [ ] Skeleton/loading shows first, then data appears (deferred works).
- [ ] Changing a filter + Tampilkan reloads the data; the URL shows the query params.
- [ ] Sorting a column and changing pages triggers a new request (server pages).
- [ ] Export Excel downloads a correct file.
- [ ] Works in dark mode and on a phone-width screen.
- [ ] No console errors.
- [ ] `grep -r "@/mock" frontend/pages` returns nothing.

---

## Appendix — Component contract quick reference

```
ReportPage props: title, deferredKey(String), data(Object|null), columns, rowKey,
                  page, perPage, sortKey, sortDir, exportHref, summaryItems
ReportPage emits: page-change(page), sort-change({key,dir})
ReportPage slots: #filters, cell-<key>

ServerTable props: columns, rows, rowKey, total, page, perPage, sortKey, sortDir, emptyMessage
ServerTable emits: page-change(page), sort-change({key,dir})

FilterPanel emits: submit, reset   | slot: default (fields)
DateRangeField: v-model:from, v-model:to
SelectSearch: v-model, props options([{value,label}]), label, placeholder
ExportButton: mode="client"(filename,columns,rows,sheetName) | mode="server"(href)
useServerReport(url, initialFilters) -> { form, apply, onPage, onSort, reset, exportHref }

Column object: { key, label, sortable?, align?('left'|'right'|'center'), format?('number'|'rupiah'|'date') }
Deferred payload (server pages): { rows, total, summary, options, conn_error }
Deferred payload (client pages): { rows, conn_error }
```

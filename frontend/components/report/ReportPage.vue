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
  recent: { type: Boolean, default: false }, // showing the "100 terbaru" first-load snapshot
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
      <Banner
        v-else-if="recent"
        variant="info"
        message="Menampilkan 100 data terbaru. Gunakan filter untuk melihat data lain."
      />
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

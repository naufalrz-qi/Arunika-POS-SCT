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

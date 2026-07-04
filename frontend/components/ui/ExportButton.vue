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
    class="inline-flex items-center justify-center gap-2 font-heading font-bold uppercase tracking-widest rounded transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 active:translate-y-px active:scale-[0.98] border relative overflow-hidden group before:absolute before:inset-0 before:bg-white/10 before:opacity-0 hover:before:opacity-100 before:transition-opacity bg-success-600/90 text-white border-success-500 hover:bg-success-500 hover:border-success-400 hover:shadow-[0_0_15px_rgba(40,167,69,0.4)] backdrop-blur-sm text-[10px] px-3 py-1.5 h-8"
  >
    Export Excel
  </a>
  <Button v-else variant="success" size="sm" :disabled="disabled" @click="onClient">Export Excel</Button>
</template>

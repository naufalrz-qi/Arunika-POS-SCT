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
  label: { type: String, default: "Export Excel" },
});
function onClient() {
  downloadXlsx(`${props.filename}-${stamp()}.xlsx`, props.columns, props.rows, props.sheetName);
}
</script>

<template>
  <Button v-if="mode === 'server'" variant="success" size="sm" :href="href">{{ label }}</Button>
  <Button v-else variant="success" size="sm" :disabled="disabled" @click="onClient">{{ label }}</Button>
</template>

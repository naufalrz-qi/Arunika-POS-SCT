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
  <!-- `secondary`, bukan `success` (hijau pekat). Ekspor bukan tindakan utama
       halaman mana pun — yang utama selalu tombol saring/tarik data. Dengan dua
       tombol berwarna sekaligus, tak ada yang menunjukkan mana yang dituju. -->
  <Button v-if="mode === 'server'" variant="secondary" size="sm" :href="href">{{ label }}</Button>
  <Button v-else variant="secondary" size="sm" :disabled="disabled" @click="onClient">{{ label }}</Button>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ items: { type: Array, default: () => [] } });

// Jumlah kolom mengikuti jumlah kartu, bukan dipatok 4: dengan sm:grid-cols-4
// halaman yang mengirim 3 ringkasan (mis. Penjualan Detail) menyisakan satu sel
// menganga di kanan, dan 5 ringkasan menyisakan satu kartu yatim di baris kedua.
// Kelas ditulis utuh, bukan dirangkai, supaya tidak lolos dari pemindai Tailwind.
const colClass = computed(
  () =>
    ({
      1: "sm:grid-cols-1",
      2: "sm:grid-cols-2",
      3: "sm:grid-cols-3",
      4: "sm:grid-cols-4",
    })[Math.min(props.items.length, 4)] ?? "sm:grid-cols-4",
);
</script>
<template>
  <div v-if="items.length" :class="['mb-4 grid grid-cols-2 gap-3', colClass]">
    <div v-for="it in items" :key="it.label" class="surface-flat flex h-full flex-col justify-between px-3.5 py-3">
      <p class="text-xs text-ink-muted">{{ it.label }}</p>
      <p class="mt-1.5 text-xl font-semibold tabular-nums tracking-tight text-ink">{{ it.value }}</p>
    </div>
  </div>
</template>

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
  <div v-if="items.length" :class="['mb-6 grid grid-cols-2 gap-3', colClass]">
    <div v-for="(it, index) in items" :key="it.label" :class="['panel-cut-frame panel-cut-frame-accent h-full', `stagger-${(index % 4) + 1}`]">
      <div class="mecha-card panel-cut bg-surface p-3.5 h-full flex flex-col justify-between">
        <p class="text-[11px] font-heading font-bold uppercase tracking-wide text-ink-muted mb-2">{{ it.label }}</p>
        <p class="text-xl lg:text-2xl font-semibold text-ink tracking-tight">{{ it.value }}</p>
      </div>
    </div>
  </div>
</template>

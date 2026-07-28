<script setup>
// Pemilih "Rentang" / "Tanggal Tertentu". Metrik chip-nya sengaja sama dengan
// pintasan preset di DateRangeField (rounded-full, py-0.5, text-[11px]) supaya
// keduanya bisa berbagi satu baris tanpa tinggi yang berbeda.
defineProps({ mode: { type: String, default: "range" } });
const emit = defineEmits(["update:mode"]);
const modes = [
  { key: "range", label: "Rentang" },
  { key: "exact", label: "Tanggal Tertentu" },
];
</script>

<template>
  <div class="inline-flex overflow-hidden rounded-full border border-border-default">
    <button
      v-for="m in modes"
      :key="m.key"
      type="button"
      :aria-pressed="mode === m.key"
      @click="emit('update:mode', m.key)"
      :class="[
        'px-2.5 py-0.5 text-[11px] transition-colors',
        mode === m.key ? 'bg-brand-bg font-medium text-brand-fg' : 'text-ink-muted hover:bg-surface-2',
      ]"
    >
      {{ m.label }}
    </button>
  </div>
</template>

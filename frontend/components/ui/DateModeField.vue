<script setup>
import DateRangeField from "@/components/ui/DateRangeField.vue";

const props = defineProps({
  mode: { type: String, default: "range" }, // "range" | "exact"
  from: { type: String, default: "" },
  to: { type: String, default: "" },
  date: { type: String, default: "" },
  label: { type: String, default: "" },
});
const emit = defineEmits(["update:mode", "update:from", "update:to", "update:date"]);

function setMode(m) {
  emit("update:mode", m);
}
</script>

<template>
  <div class="space-y-2">
    <span v-if="label" class="mb-1 block text-xs text-ink-muted">{{ label }}</span>
    <div class="flex gap-1">
      <button
        type="button"
        @click="setMode('range')"
        :class="[
          'rounded-card border px-2 py-1 text-xs',
          mode === 'range' ? 'border-brand-500 bg-brand-bg text-brand-fg' : 'border-border-default text-ink-muted hover:bg-surface-3',
        ]"
      >
        Rentang
      </button>
      <button
        type="button"
        @click="setMode('exact')"
        :class="[
          'rounded-card border px-2 py-1 text-xs',
          mode === 'exact' ? 'border-brand-500 bg-brand-bg text-brand-fg' : 'border-border-default text-ink-muted hover:bg-surface-3',
        ]"
      >
        Tanggal Tertentu
      </button>
    </div>

    <DateRangeField
      v-if="mode === 'range'"
      :from="from"
      :to="to"
      @update:from="emit('update:from', $event)"
      @update:to="emit('update:to', $event)"
    />
    <label v-else class="block">
      <span class="mb-1 block text-xs text-ink-muted">Tanggal</span>
      <input
        type="date"
        :value="date"
        @input="emit('update:date', $event.target.value)"
        class="w-full rounded-card border border-border-default bg-surface px-3 py-2 text-sm text-ink"
      />
    </label>
  </div>
</template>

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
    <div class="flex items-center justify-between gap-2">
      <span
        v-if="label"
        class="text-[10px] font-heading font-bold uppercase tracking-widest text-ink-muted"
      >
        {{ label }}
      </span>
      <div class="inline-flex overflow-hidden rounded border border-border-default">
        <button
          type="button"
          @click="setMode('range')"
          :class="[
            'px-2 py-1 text-[11px] transition-colors',
            mode === 'range' ? 'bg-brand-500 font-semibold text-white' : 'text-ink-muted hover:bg-surface-3',
          ]"
        >
          Rentang
        </button>
        <button
          type="button"
          @click="setMode('exact')"
          :class="[
            'px-2 py-1 text-[11px] transition-colors',
            mode === 'exact' ? 'bg-brand-500 font-semibold text-white' : 'text-ink-muted hover:bg-surface-3',
          ]"
        >
          Tanggal Tertentu
        </button>
      </div>
    </div>

    <DateRangeField
      v-if="mode === 'range'"
      :from="from"
      :to="to"
      @update:from="emit('update:from', $event)"
      @update:to="emit('update:to', $event)"
    />
    <input
      v-else
      type="date"
      :value="date"
      @input="emit('update:date', $event.target.value)"
      class="h-10 w-full rounded border border-border-strong bg-surface/50 px-3 text-sm text-ink transition-all duration-200 hover:border-brand-400 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:outline-none"
    />
  </div>
</template>

<script setup>
defineProps({
  min: { type: [String, Number], default: "" },
  max: { type: [String, Number], default: "" },
  label: { type: String, default: "" },
});
defineEmits(["update:min", "update:max"]);
</script>

<template>
  <div>
    <span v-if="label" class="mb-1.5 block text-[10px] font-heading font-bold uppercase tracking-widest text-ink-muted">{{ label }}</span>
    <div class="flex items-center gap-1.5">
      <input
        type="number"
        :value="min"
        placeholder="Min"
        @input="$emit('update:min', $event.target.value)"
        class="h-10 w-full min-w-0 rounded border border-border-strong bg-surface/50 px-3 text-sm text-ink transition-all duration-200 placeholder:text-ink-subtle hover:border-brand-400 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:outline-none"
      />
      <span class="shrink-0 text-ink-subtle">–</span>
      <input
        type="number"
        :value="max"
        placeholder="Max"
        @input="$emit('update:max', $event.target.value)"
        class="h-10 w-full min-w-0 rounded border border-border-strong bg-surface/50 px-3 text-sm text-ink transition-all duration-200 placeholder:text-ink-subtle hover:border-brand-400 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:outline-none"
      />
    </div>
  </div>
</template>

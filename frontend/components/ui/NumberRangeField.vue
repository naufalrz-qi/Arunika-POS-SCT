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
    <span v-if="label" class="mb-1 block text-xs font-medium text-ink-muted">{{ label }}</span>
    <div class="flex items-center gap-1.5">
      <input
        type="number"
        :value="min"
        placeholder="Min"
        @input="$emit('update:min', $event.target.value)"
        class="h-9 w-full min-w-0 rounded-control border border-border-strong bg-surface px-2.5 text-sm text-ink transition-colors duration-150 placeholder:text-ink-subtle focus:border-brand-500 focus:ring-2 focus:ring-brand-500 focus:outline-none"
      />
      <span class="shrink-0 text-ink-subtle">–</span>
      <input
        type="number"
        :value="max"
        placeholder="Max"
        @input="$emit('update:max', $event.target.value)"
        class="h-9 w-full min-w-0 rounded-control border border-border-strong bg-surface px-2.5 text-sm text-ink transition-colors duration-150 placeholder:text-ink-subtle focus:border-brand-500 focus:ring-2 focus:ring-brand-500 focus:outline-none"
      />
    </div>
  </div>
</template>

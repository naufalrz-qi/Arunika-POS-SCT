<script setup>
defineProps({
  min: { type: [String, Number], default: "" },
  max: { type: [String, Number], default: "" },
  label: { type: String, default: "" },
});
defineEmits(["update:min", "update:max"]);
</script>

<template>
  <div class="grid grid-cols-2 gap-2">
    <label class="block">
      <span class="mb-1 block text-xs text-ink-muted">{{ label }} Min</span>
      <input
        type="number"
        :value="min"
        @input="$emit('update:min', $event.target.value)"
        class="w-full rounded-card border border-border-default bg-surface px-3 py-2 text-sm text-ink"
      />
    </label>
    <label class="block">
      <span class="mb-1 block text-xs text-ink-muted">{{ label }} Max</span>
      <input
        type="number"
        :value="max"
        @input="$emit('update:max', $event.target.value)"
        class="w-full rounded-card border border-border-default bg-surface px-3 py-2 text-sm text-ink"
      />
    </label>
  </div>
</template>

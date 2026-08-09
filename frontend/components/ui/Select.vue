<script setup>
defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  label: { type: String, default: "" },
  // options: [{ value, label }]
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
});
defineEmits(["update:modelValue"]);
</script>

<template>
  <label class="block">
    <span v-if="label" class="mb-1 block text-xs font-medium text-ink-muted">{{ label }}</span>
    <select
      :value="modelValue"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.value)"
      class="h-9 w-full rounded-control border border-border-strong bg-surface px-2.5 text-sm text-ink transition-colors duration-150 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <option v-if="placeholder" value="">{{ placeholder }}</option>
      <option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
    </select>
  </label>
</template>

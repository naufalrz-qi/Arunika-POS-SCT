<script setup>
defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  label: { type: String, default: "" },
  // options: [{ value, label }]
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "" },
});
defineEmits(["update:modelValue"]);
</script>

<template>
  <label class="block">
    <span v-if="label" class="mb-1 block text-sm font-medium text-ink">{{ label }}</span>
    <select
      :value="modelValue"
      @change="$emit('update:modelValue', $event.target.value)"
      class="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-ink shadow-sm transition focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
    >
      <option v-if="placeholder" value="">{{ placeholder }}</option>
      <option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
    </select>
  </label>
</template>

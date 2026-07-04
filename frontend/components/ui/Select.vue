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
    <span v-if="label" class="mb-1.5 block text-[10px] font-heading font-bold uppercase tracking-widest text-ink-muted">{{ label }}</span>
    <select
      :value="modelValue"
      @change="$emit('update:modelValue', $event.target.value)"
      class="h-10 w-full rounded border border-border-strong bg-surface/50 backdrop-blur-sm px-3 py-2 text-sm text-ink transition-all duration-200 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500/50 hover:border-brand-400 focus:shadow-[0_0_10px_rgba(11,61,145,0.2)]"
    >
      <option v-if="placeholder" value="">{{ placeholder }}</option>
      <option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
    </select>
  </label>
</template>

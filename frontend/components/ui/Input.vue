<script setup>
defineProps({
  modelValue: { type: [String, Number], default: "" },
  label: { type: String, default: "" },
  type: { type: String, default: "text" },
  placeholder: { type: String, default: "" },
  error: { type: String, default: "" },
  required: { type: Boolean, default: false },
});
defineEmits(["update:modelValue"]);
</script>

<template>
  <label class="block">
    <span v-if="label" class="mb-1.5 block text-[10px] font-heading font-bold uppercase tracking-widest text-ink-muted">
      {{ label }} <span v-if="required" class="text-danger-500">*</span>
    </span>
    <input
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      @input="$emit('update:modelValue', $event.target.value)"
      :class="[
        'h-10 w-full rounded border bg-surface/50 backdrop-blur-sm px-3 py-2 text-sm text-ink transition-all duration-200 placeholder:text-ink-subtle focus:outline-none focus:ring-1 focus:ring-brand-500/50',
        error ? 'border-danger-500 shadow-[0_0_8px_rgba(230,0,18,0.2)]' : 'border-border-strong focus:border-brand-500 focus:shadow-[0_0_10px_rgba(11,61,145,0.2)] hover:border-brand-400',
      ]"
    />
    <span v-if="error" class="mt-1.5 block text-[10px] font-bold uppercase tracking-widest text-danger-500">{{ error }}</span>
  </label>
</template>

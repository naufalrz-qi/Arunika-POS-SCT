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
    <span v-if="label" class="mb-1 block text-sm font-medium text-ink">
      {{ label }} <span v-if="required" class="text-danger-600">*</span>
    </span>
    <input
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      @input="$emit('update:modelValue', $event.target.value)"
      :class="[
        'w-full rounded-lg border bg-surface px-3 py-2 text-sm text-ink shadow-sm transition placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-brand-500/40',
        error ? 'border-danger-500' : 'border-border-strong focus:border-brand-500',
      ]"
    />
    <span v-if="error" class="mt-1 block text-xs text-danger-600">{{ error }}</span>
  </label>
</template>

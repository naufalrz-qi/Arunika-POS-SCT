<script setup>
defineProps({
  modelValue: { type: [String, Number], default: "" },
  label: { type: String, default: "" },
  type: { type: String, default: "text" },
  placeholder: { type: String, default: "" },
  error: { type: String, default: "" },
  required: { type: Boolean, default: false },
  // Tanpa ini pengelola kata sandi tak punya petunjuk untuk mengisi formulir
  // masuk secara otomatis.
  autocomplete: { type: String, default: undefined },
  autofocus: { type: Boolean, default: false },
});
defineEmits(["update:modelValue"]);
</script>

<template>
  <label class="block">
    <span v-if="label" class="mb-1 block text-xs font-medium text-ink-muted">
      {{ label }} <span v-if="required" class="text-danger-fg">*</span>
    </span>
    <input
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      :autocomplete="autocomplete"
      :autofocus="autofocus || undefined"
      :required="required || undefined"
      :aria-invalid="error ? 'true' : undefined"
      @input="$emit('update:modelValue', $event.target.value)"
      :class="[
        'h-9 w-full rounded-control border bg-surface px-2.5 text-sm text-ink transition-colors duration-150 placeholder:text-ink-subtle focus:outline-none focus:ring-2 focus:ring-brand-500',
        error ? 'border-danger-600' : 'border-border-strong focus:border-brand-500',
      ]"
    />
    <span v-if="error" class="mt-1 block text-xs text-danger-fg">{{ error }}</span>
  </label>
</template>

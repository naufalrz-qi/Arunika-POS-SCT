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
    <span v-if="label" class="mb-1.5 block text-[11px] font-heading font-semibold tracking-wide text-ink-muted">
      {{ label }} <span v-if="required" class="text-danger-500">*</span>
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
        'h-10 w-full rounded-control border bg-surface/50 backdrop-blur-sm px-3 py-2 text-sm text-ink transition-all duration-200 placeholder:text-ink-subtle focus:outline-none focus:ring-1 focus:ring-brand-500/50',
        error ? 'border-danger-500 shadow-[0_0_8px_var(--glow-danger)]' : 'border-border-strong focus:border-brand-500 focus:shadow-[0_0_10px_var(--glow-brand)] hover:border-brand-400',
      ]"
    />
    <span v-if="error" class="mt-1.5 block text-[11px] font-semibold tracking-wide text-danger-500">{{ error }}</span>
  </label>
</template>

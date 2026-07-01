<script setup>
import { computed } from "vue";

const props = defineProps({
  variant: { type: String, default: "primary" }, // primary | secondary | ghost | danger
  size: { type: String, default: "md" }, // sm | md
  type: { type: String, default: "button" },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
});

const base =
  "inline-flex items-center justify-center gap-2 font-medium rounded-md transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 disabled:opacity-50 disabled:cursor-not-allowed active:translate-y-px active:scale-[0.99]";

const variants = {
  primary: "bg-brand-600 text-white hover:bg-brand-700",
  secondary: "bg-surface text-ink border border-border-strong hover:bg-surface-3",
  ghost: "text-ink-muted hover:bg-surface-3",
  danger: "bg-danger-600 text-white hover:bg-danger-700",
  success: "bg-success-600 text-white hover:bg-success-700",
  warning: "bg-warning-600 text-white hover:bg-warning-700",
  info: "bg-blue-600 text-white hover:bg-blue-700",
  yellow: "bg-yellow-500 text-white hover:bg-yellow-600",
  accent: "bg-rx-red text-white hover:brightness-110", // RX-78-2 chest red — special CTAs
};

const sizes = {
  sm: "text-xs px-2.5 py-1.5",
  md: "text-sm px-4 py-2",
};

const classes = computed(() => [base, variants[props.variant], sizes[props.size]]);
</script>

<template>
  <button :type="type" :disabled="disabled || loading" :class="classes">
    <svg
      v-if="loading"
      class="animate-spin h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
    <slot />
  </button>
</template>

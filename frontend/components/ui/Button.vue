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
  "inline-flex items-center justify-center gap-2 font-heading font-bold uppercase tracking-widest panel-cut-sm transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 disabled:opacity-50 disabled:cursor-not-allowed active:translate-y-px active:scale-[0.98] border relative overflow-hidden group before:absolute before:inset-0 before:bg-white/10 before:opacity-0 hover:before:opacity-100 before:transition-opacity";

const variants = {
  primary: "bg-brand-600/90 text-white border-brand-500 hover:bg-brand-500 hover:border-brand-400 hover:shadow-[0_0_15px_rgba(11,61,145,0.6)] backdrop-blur-sm",
  secondary: "bg-surface/80 text-ink border-border-strong hover:bg-surface-2 hover:border-brand-400 hover:text-brand-600 hover:shadow-[0_0_12px_rgba(11,61,145,0.15)] backdrop-blur-sm",
  ghost: "text-ink-muted border-transparent hover:bg-surface-3/50 hover:text-ink",
  danger: "bg-danger-600/90 text-white border-danger-500 hover:bg-danger-500 hover:border-danger-400 hover:shadow-[0_0_15px_rgba(230,0,18,0.4)] backdrop-blur-sm",
  success: "bg-success-600/90 text-white border-success-500 hover:bg-success-500 hover:border-success-400 hover:shadow-[0_0_15px_rgba(40,167,69,0.4)] backdrop-blur-sm",
  warning: "bg-warning-600/90 text-white border-warning-500 hover:bg-warning-500 hover:shadow-[0_0_15px_rgba(255,196,0,0.4)] backdrop-blur-sm",
  info: "bg-blue-600/90 text-white border-blue-500 hover:bg-blue-500 hover:shadow-[0_0_15px_rgba(0,123,255,0.4)] backdrop-blur-sm",
  yellow: "bg-rx-yellow text-ink border-yellow-400 hover:bg-yellow-400 hover:shadow-[0_0_15px_rgba(255,196,0,0.6)] backdrop-blur-sm",
  "yellow-outline": "bg-surface/80 text-ink border-rx-yellow hover:bg-warning-bg hover:text-warning-fg hover:shadow-[0_0_12px_rgba(255,196,0,0.35)] backdrop-blur-sm",
  accent: "bg-rx-red text-white border-red-500 hover:brightness-110 hover:shadow-[0_0_15px_rgba(230,0,18,0.6)] backdrop-blur-sm",
};

const sizes = {
  sm: "text-[10px] px-3 py-1.5 h-8",
  md: "text-xs px-5 py-2.5 h-10",
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

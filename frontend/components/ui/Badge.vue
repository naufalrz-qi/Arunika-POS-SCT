<script setup>
import { computed } from "vue";

const props = defineProps({
  variant: { type: String, default: "neutral" }, // neutral | success | warning | danger | brand
});

const styles = {
  neutral: "bg-surface-3 text-ink-muted",
  success: "bg-success-bg text-success-fg",
  warning: "bg-warning-bg text-warning-fg",
  danger: "bg-danger-bg text-danger-fg",
  brand: "bg-brand-bg text-brand-fg",
};

const cls = computed(() => styles[props.variant] ?? styles.neutral);
</script>

<template>
  <span :class="['inline-flex items-center gap-1 rounded px-2.5 py-0.5 text-xs font-medium', cls]">
    <slot />
  </span>
</template>

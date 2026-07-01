<script setup>
defineProps({
  variant: { type: String, default: "danger" }, // danger | warning | info
  message: { type: String, default: "" },
});

const styles = {
  danger: "bg-danger-bg text-danger-fg border-danger-500/30",
  warning: "bg-warning-bg text-warning-fg border-warning-500/30",
  info: "bg-brand-bg text-brand-fg border-brand-500/30",
};
</script>

<template>
  <div :class="['mb-4 flex items-start gap-2 rounded-lg border px-4 py-3 text-sm', styles[variant]]">
    <svg class="mt-0.5 h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
    </svg>
    <span>{{ message }}</span>
  </div>
</template>

<script setup>
defineProps({
  message: { type: String, default: "Tidak ada data." },
});
</script>
<template>
  <div class="rounded-card border border-dashed border-border-default bg-surface-2 py-12 text-center">
    <p class="text-sm text-ink-muted">{{ message }}</p>
  </div>
</template>

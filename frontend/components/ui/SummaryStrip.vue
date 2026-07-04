<script setup>
defineProps({ items: { type: Array, default: () => [] } });
</script>
<template>
  <div v-if="items.length" class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
    <div v-for="it in items" :key="it.label" class="rounded-card border border-border-default bg-surface p-3">
      <p class="text-xs text-ink-muted">{{ it.label }}</p>
      <p class="text-lg font-semibold text-ink">{{ it.value }}</p>
    </div>
  </div>
</template>

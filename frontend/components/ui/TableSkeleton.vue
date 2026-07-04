<script setup>
defineProps({ rows: { type: Number, default: 8 } });
</script>
<template>
  <div class="panel-cut-frame panel-cut-frame-accent">
    <div class="mecha-card panel-cut bg-surface">
      <div class="h-10 bg-surface-3"></div>
      <div
        v-for="n in rows"
        :key="n"
        class="flex items-center gap-4 border-t border-border-default px-4 py-3"
      >
        <div class="h-3 flex-1 animate-pulse rounded bg-surface-3"></div>
        <div class="h-3 w-24 animate-pulse rounded bg-surface-3"></div>
        <div class="h-3 w-16 animate-pulse rounded bg-surface-3"></div>
      </div>
    </div>
  </div>
</template>

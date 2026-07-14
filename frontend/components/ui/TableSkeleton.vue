<script setup>
import { useLoadingProgress } from "@/composables/useLoadingProgress.js";

defineProps({ rows: { type: Number, default: 8 } });

const { elapsed, hint } = useLoadingProgress();
</script>
<template>
  <div class="panel-cut-frame panel-cut-frame-accent">
    <div class="relative overflow-hidden mecha-card panel-cut bg-surface">
      <div class="absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-surface-3">
        <div class="h-full w-1/3 animate-loading-bar rounded-full bg-brand-500"></div>
      </div>
      <div class="flex items-center justify-between gap-3 border-b border-border-default px-4 py-2 text-xs text-ink-subtle">
        <span>Mengambil data…<span v-if="elapsed >= 2"> ({{ elapsed }} detik)</span></span>
        <span v-if="hint">{{ hint }}</span>
      </div>
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

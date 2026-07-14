<script setup>
import Card from "./Card.vue";
import Spinner from "./Spinner.vue";
import { useLoadingProgress } from "@/composables/useLoadingProgress.js";

defineProps({
  message: { type: String, default: "Mengambil data…" },
});

const { elapsed, hint } = useLoadingProgress();
</script>

<template>
  <Card class="relative overflow-hidden py-16">
    <div class="flex flex-col items-center justify-center gap-2">
      <div class="flex items-center gap-3">
        <Spinner />
        <span class="text-sm text-ink-muted">{{ message }}<span v-if="elapsed >= 2"> ({{ elapsed }} detik)</span></span>
      </div>
      <p v-if="hint" class="text-xs text-ink-subtle">{{ hint }}</p>
    </div>
    <div class="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-surface-3">
      <div class="h-full w-1/3 animate-loading-bar rounded-full bg-brand-500"></div>
    </div>
  </Card>
</template>

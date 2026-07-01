<script setup>
defineProps({
  message: { type: String, default: "Tidak ada data." },
});
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-2 py-12 text-center">
    <div class="rounded-md border border-border-strong bg-surface-2 p-3">
      <svg class="h-6 w-6 text-ink-subtle" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
      </svg>
    </div>
    <p class="text-sm text-ink-subtle">{{ message }}</p>
  </div>
</template>

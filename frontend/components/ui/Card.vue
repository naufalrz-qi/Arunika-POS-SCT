<script setup>
defineProps({
  title: { type: String, default: "" },
  subtitle: { type: String, default: "" },
});
</script>

<template>
  <div class="rounded-card border border-border-default bg-surface shadow-sm">
    <div v-if="title || $slots.header" class="flex items-center justify-between border-b border-border-default px-5 py-3.5">
      <div>
        <h3 v-if="title" class="text-sm font-semibold text-ink">{{ title }}</h3>
        <p v-if="subtitle" class="text-xs text-ink-muted">{{ subtitle }}</p>
      </div>
      <slot name="header" />
    </div>
    <div class="p-5">
      <slot />
    </div>
  </div>
</template>

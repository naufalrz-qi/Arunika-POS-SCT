<script setup>
defineProps({ items: { type: Array, default: () => [] } });
</script>
<template>
  <div v-if="items.length" class="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
    <div v-for="(it, index) in items" :key="it.label" :class="['panel-cut-frame panel-cut-frame-accent h-full', `stagger-${(index % 4) + 1}`]">
      <div class="mecha-card panel-cut bg-surface p-3.5 h-full flex flex-col justify-between">
        <p class="text-[10px] font-heading font-bold uppercase tracking-widest text-ink-muted mb-2">{{ it.label }}</p>
        <p class="text-xl lg:text-2xl font-semibold text-ink tracking-tight">{{ it.value }}</p>
      </div>
    </div>
  </div>
</template>

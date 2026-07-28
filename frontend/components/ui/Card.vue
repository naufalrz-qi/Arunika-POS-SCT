<script setup>
defineProps({
  title: { type: String, default: "" },
  subtitle: { type: String, default: "" },
});
</script>

<template>
  <div class="surface-flat mb-4 last:mb-0">
    <div v-if="title || $slots.header" class="flex items-center justify-between gap-3 border-b border-border-default px-4 py-3">
      <div>
        <h3 v-if="title" class="text-sm font-semibold text-ink">{{ title }}</h3>
        <!-- Subtitle memuat kalimat utuh ("Top 10 qty terjual — barang tanpa
             harga jual dikecualikan"), bukan label pendek. -->
        <p v-if="subtitle" class="mt-0.5 text-xs text-ink-muted">{{ subtitle }}</p>
      </div>
      <slot name="header" />
    </div>
    <div class="p-4">
      <slot />
    </div>
  </div>
</template>

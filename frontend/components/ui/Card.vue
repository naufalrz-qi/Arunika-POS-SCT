<script setup>
defineProps({
  title: { type: String, default: "" },
  subtitle: { type: String, default: "" },
});
</script>

<template>
  <div class="panel-cut-frame panel-cut-frame-accent mb-4 last:mb-0">
    <div class="mecha-card panel-cut bg-surface">
      <div v-if="title || $slots.header" class="flex items-center justify-between border-b border-border-default px-5 py-3.5 bg-surface-3">
        <div class="flex items-center gap-3">
          <!-- Tech accent -->
          <div v-if="title" class="w-1 h-4 bg-brand-500 rounded-full"></div>
          <div>
            <h3 v-if="title" class="text-sm font-heading font-semibold tracking-wide text-ink">{{ title }}</h3>
            <p v-if="subtitle" class="text-[11px] font-medium tracking-widest uppercase text-ink-muted mt-0.5">{{ subtitle }}</p>
          </div>
        </div>
        <slot name="header" />
      </div>
      <div class="p-5">
        <slot />
      </div>
    </div>
  </div>
</template>

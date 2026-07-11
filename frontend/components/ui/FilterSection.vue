<script setup>
defineProps({ title: { type: String, default: "" } });
</script>

<template>
  <section class="col-span-full border-t border-border-default pt-3 first:border-t-0 first:pt-0">
    <h4
      v-if="title"
      class="mb-2.5 flex items-center gap-2 text-[10px] font-heading font-bold uppercase tracking-widest text-ink-subtle"
    >
      <span class="h-3 w-0.5 rounded-full bg-brand-500"></span>
      {{ title }}
    </h4>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <slot />
    </div>
  </section>
</template>

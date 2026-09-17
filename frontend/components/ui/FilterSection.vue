<script setup>
defineProps({ title: { type: String, default: "" } });
</script>

<template>
  <!-- Judul seksi PERTAMA disembunyikan: isinya selalu periode + cari, dan
       label tiap kolom sudah mengatakannya. Seksi berikutnya (di Filter
       lanjutan) tetap berjudul karena di situlah pengelompokan berguna. -->
  <section class="group/seksi col-span-full border-t border-border-default pt-3 first:border-t-0 first:pt-0">
    <h4
      v-if="title"
      class="mb-2 text-xs font-semibold text-ink-muted group-first/seksi:hidden"
    >
      {{ title }}
    </h4>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <slot />
    </div>
  </section>
</template>

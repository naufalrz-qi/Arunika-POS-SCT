<script setup>
import Card from "./Card.vue";
import Spinner from "./Spinner.vue";

defineProps({
  message: { type: String, default: "Mengambil data…" },
});
</script>

<template>
  <Card class="flex items-center justify-center gap-3 py-16">
    <Spinner />
    <span class="text-sm text-ink-muted">{{ message }}</span>
  </Card>
</template>

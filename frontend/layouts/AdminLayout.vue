<script setup>
import Navbar from "@/components/nav/Navbar.vue";
import ToastContainer from "@/components/ui/ToastContainer.vue";

defineProps({
  title: { type: String, default: "" },
});
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-surface-2">
    <Navbar :title="title" />
    <main class="scroll-slim flex-1 overflow-y-auto">
      <div class="page-enter mx-auto max-w-[1600px] p-4 sm:p-6">
        <h1 v-if="title" class="mb-4 text-xl font-semibold text-ink">{{ title }}</h1>
        <slot />
      </div>
    </main>
    <ToastContainer />
  </div>
</template>

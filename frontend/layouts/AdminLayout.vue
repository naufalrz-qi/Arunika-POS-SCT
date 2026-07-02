<script setup>
import TopNav from "@/components/nav/TopNav.vue";
import SideNav from "@/components/nav/SideNav.vue";
import ToastContainer from "@/components/ui/ToastContainer.vue";
import { useNav } from "@/composables/useNav";

defineProps({
  title: { type: String, default: "" },
});

const { activeSection } = useNav();
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-surface-2">
    <TopNav />
    <div class="flex min-h-0 flex-1">
      <SideNav />
      <main class="scroll-slim min-w-0 flex-1 overflow-y-auto">
        <div class="page-enter mx-auto max-w-[1600px] p-4 sm:p-6">
          <div v-if="title" class="mb-4">
            <p v-if="activeSection" class="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
              {{ activeSection.label }}
            </p>
            <h1 class="text-xl font-semibold text-ink">{{ title }}</h1>
          </div>
          <slot />
        </div>
      </main>
    </div>
    <ToastContainer />
  </div>
</template>

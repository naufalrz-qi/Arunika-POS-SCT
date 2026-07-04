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
  <div class="flex h-screen flex-col overflow-hidden bg-transparent">
    <TopNav />
    <div class="flex min-h-0 flex-1 relative z-10 mt-3 lg:mt-4">
      <SideNav />
      <main class="scroll-slim min-w-0 flex-1 overflow-y-auto relative">
        <div class="page-enter mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">
          <div v-if="title" class="mb-6 flex items-end justify-between">
            <div>
              <p v-if="activeSection" class="text-[11px] font-heading font-bold uppercase tracking-widest text-brand-500 mb-1">
                // {{ activeSection.label }}
              </p>
              <h1 class="text-2xl font-heading font-bold text-ink tracking-tight">{{ title }}</h1>
            </div>
            <!-- Optional: decorative mecha element could go here -->
            <div class="hidden sm:flex gap-1 h-6 items-end">
              <div class="w-2 h-2 bg-rx-red animate-pulse-glow"></div>
              <div class="w-2 h-4 bg-rx-yellow"></div>
              <div class="w-8 h-4 bg-brand-600"></div>
            </div>
          </div>
          <slot />
        </div>
      </main>
    </div>
    <ToastContainer />
  </div>
</template>

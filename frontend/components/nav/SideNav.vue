<script setup>
import { Link } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUiStore } from "@/stores/ui";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";

const ui = useUiStore();
const { sidebarCollapsed } = storeToRefs(ui);
const { activeTab, isActive } = useNav();
</script>

<template>
  <aside
    v-if="activeTab"
    :class="[
      'floating-panel hidden shrink-0 flex-col transition-all duration-300 lg:flex relative z-40 ml-3 mb-3 lg:ml-4 lg:mb-4',
      sidebarCollapsed ? 'w-16' : 'w-64',
    ]"
  >
    <!-- Decorative beveled background, kept off the real element — see
         TopNav.vue's header for why (clip-path clips every descendant). -->
    <div class="shoulder-panel bg-sidebar border border-white/5 absolute inset-0 -z-10"></div>
    <p
      v-if="!sidebarCollapsed"
      class="px-5 pb-1 pt-5 text-[10px] font-heading font-bold uppercase tracking-widest text-brand-300/60"
    >
      {{ activeTab.label }}
    </p>
    <div v-else class="pt-5" />

    <nav class="scroll-slim flex-1 overflow-y-auto px-3 pb-4">
      <template v-for="(sub, i) in activeTab.subsections" :key="sub.key">
        <p
          v-if="!sidebarCollapsed && activeTab.subsections.length > 1"
          class="px-2 pb-1.5 pt-4 text-[10px] font-heading font-bold uppercase tracking-widest text-white/50"
        >
          {{ sub.label }}
        </p>
        <div
          v-else-if="sidebarCollapsed && activeTab.subsections.length > 1 && i > 0"
          class="mx-3 my-3 border-t border-white/10"
        />
        <div class="space-y-1">
          <Link
            v-for="item in sub.items"
            :key="item.key"
            :href="item.href"
            :title="sidebarCollapsed ? item.label : undefined"
            :class="[
              'group flex items-center gap-3 rounded-lg py-2 transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60',
              sidebarCollapsed ? 'justify-center px-0' : 'px-3',
              isActive(item.href)
                ? 'bg-brand-600 font-semibold text-white relative overflow-hidden'
                : 'text-white/70 hover:bg-white/10 hover:text-white ' + (sidebarCollapsed ? '' : 'hover:translate-x-1'),
            ]"
          >
            <!-- V-fin accent bar on active state -->
            <div v-if="isActive(item.href)" class="absolute left-0 top-0 bottom-0 w-1 bg-rx-yellow"></div>
            
            <Icon :name="item.icon" size="h-4 w-4" :class="['shrink-0 z-10', isActive(item.href) ? 'text-white' : 'text-white/70 group-hover:text-white/90']" />
            <span v-if="!sidebarCollapsed" class="truncate z-10 text-sm">{{ item.label }}</span>
          </Link>
        </div>
      </template>
    </nav>

    <button
      type="button"
      class="flex items-center gap-3 border-t border-white/10 px-5 py-4 text-xs font-heading font-medium tracking-wide text-white/70 transition-all duration-200 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
      :class="sidebarCollapsed ? 'justify-center px-0' : ''"
      :title="sidebarCollapsed ? 'Perlebar sidebar' : 'Ciutkan sidebar'"
      @click="ui.toggleSidebar()"
    >
      <Icon
        name="chevron"
        size="h-4 w-4"
        :class="['shrink-0 transition-transform duration-300', sidebarCollapsed ? '-rotate-90' : 'rotate-90']"
      />
      <span v-if="!sidebarCollapsed">Ciutkan Panel</span>
    </button>
  </aside>
</template>

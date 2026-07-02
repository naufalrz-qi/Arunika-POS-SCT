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
      'hidden shrink-0 flex-col bg-sidebar transition-all duration-200 lg:flex',
      sidebarCollapsed ? 'w-16' : 'w-60',
    ]"
  >
    <p
      v-if="!sidebarCollapsed"
      class="px-4 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-white/40"
    >
      {{ activeTab.label }}
    </p>
    <div v-else class="pt-4" />

    <nav class="scroll-slim flex-1 overflow-y-auto px-2 pb-3">
      <template v-for="(sub, i) in activeTab.subsections" :key="sub.key">
        <p
          v-if="!sidebarCollapsed && activeTab.subsections.length > 1"
          class="px-3 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wider text-white/30"
        >
          {{ sub.label }}
        </p>
        <div
          v-else-if="sidebarCollapsed && activeTab.subsections.length > 1 && i > 0"
          class="mx-3 my-2 border-t border-white/10"
        />
        <div class="space-y-0.5">
          <Link
            v-for="item in sub.items"
            :key="item.key"
            :href="item.href"
            :title="sidebarCollapsed ? item.label : undefined"
            :class="[
              'flex items-center gap-3 rounded-lg py-2 text-sm transition',
              sidebarCollapsed ? 'justify-center px-0' : 'px-3',
              isActive(item.href)
                ? 'bg-brand-600 font-medium text-white'
                : 'text-white/60 hover:bg-white/10 hover:text-white',
            ]"
          >
            <Icon :name="item.icon" size="h-4 w-4" class="shrink-0" />
            <span v-if="!sidebarCollapsed" class="truncate">{{ item.label }}</span>
          </Link>
        </div>
      </template>
    </nav>

    <button
      type="button"
      class="flex items-center gap-3 border-t border-white/10 px-4 py-3 text-xs text-white/50 transition hover:bg-white/10 hover:text-white"
      :class="sidebarCollapsed ? 'justify-center px-0' : ''"
      :title="sidebarCollapsed ? 'Perlebar sidebar' : 'Ciutkan sidebar'"
      @click="ui.toggleSidebar()"
    >
      <Icon
        name="chevron"
        size="h-4 w-4"
        :class="['shrink-0 transition-transform duration-200', sidebarCollapsed ? '-rotate-90' : 'rotate-90']"
      />
      <span v-if="!sidebarCollapsed">Ciutkan</span>
    </button>
  </aside>
</template>

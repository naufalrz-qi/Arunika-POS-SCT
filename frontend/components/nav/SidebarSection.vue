<script setup>
import { computed } from "vue";
import { usePage } from "@inertiajs/vue3";
import { useUiStore } from "@/stores/ui";
import SidebarItem from "./SidebarItem.vue";
import Icon from "./Icon.vue";

const props = defineProps({
  sectionKey: { type: String, required: true },
  label: { type: String, default: "" },
  items: { type: Array, default: () => [] }, // [{ key, label, href, icon }]
  collapsed: { type: Boolean, default: false }, // sidebar collapsed (icons only)
});

const ui = useUiStore();
const page = usePage();

const hasActive = computed(() => props.items.some((it) => page.url.startsWith(it.href)));

// When the sidebar rail is collapsed we always show the icons. Otherwise honor
// the per-section toggle, but force-open the section holding the active route.
const open = computed(() => props.collapsed || ui.isSectionOpen(props.sectionKey) || hasActive.value);
</script>

<template>
  <div>
    <button
      v-if="!collapsed"
      type="button"
      class="flex w-full items-center justify-between rounded-md px-3 py-1.5 text-[0.7rem] font-semibold uppercase tracking-wider text-white/50 transition hover:text-white/70"
      @click="ui.toggleSection(sectionKey)"
    >
      <span>{{ label }}</span>
      <Icon
        name="chevron"
        size="h-3.5 w-3.5"
        :class="['transition-transform duration-200', open ? '' : '-rotate-90']"
      />
    </button>

    <div v-show="open" class="mt-0.5 space-y-1">
      <SidebarItem
        v-for="item in items"
        :key="item.key"
        :item="item"
        :collapsed="collapsed"
      />
    </div>
  </div>
</template>

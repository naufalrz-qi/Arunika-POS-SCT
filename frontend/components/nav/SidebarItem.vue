<script setup>
import { computed } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import Icon from "./Icon.vue";

const props = defineProps({
  item: { type: Object, required: true }, // { label, href, icon }
  collapsed: { type: Boolean, default: false },
});

const page = usePage();
const active = computed(() => page.url.startsWith(props.item.href));
</script>

<template>
  <Link
    :href="item.href"
    :class="[
      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
      active
        ? 'bg-brand-600 text-white shadow-sm'
        : 'text-white/60 hover:bg-white/10 hover:text-white',
    ]"
    :title="collapsed ? item.label : null"
  >
    <Icon :name="item.icon" />
    <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
  </Link>
</template>

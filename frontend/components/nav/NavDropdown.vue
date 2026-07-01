<script setup>
import { computed, ref } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import Icon from "./Icon.vue";

const props = defineProps({
  label: { type: String, default: "" },
  items: { type: Array, default: () => [] }, // [{ key, label, href, icon }]
});

const page = usePage();
const open = ref(false);
let closeTimer = null;

// Strip query/hash + trailing slash, then match on segment boundaries so a
// short href (e.g. /laporan/penjualan) no longer stays "active" on a sibling
// page (/laporan/penjualan-periode). Fixes the leaking-active-state bug.
const currentPath = computed(() =>
  page.url.split(/[?#]/)[0].replace(/\/+$/, ""),
);
function isActive(href) {
  const h = href.replace(/\/+$/, "");
  return currentPath.value === h || currentPath.value.startsWith(h + "/");
}

const sectionActive = computed(() => props.items.some((it) => isActive(it.href)));

function onEnter() {
  clearTimeout(closeTimer);
  open.value = true;
}
function onLeave() {
  closeTimer = setTimeout(() => (open.value = false), 120);
}
</script>

<template>
  <div class="relative" @mouseenter="onEnter" @mouseleave="onLeave">
    <button
      type="button"
      :class="[
        'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition',
        sectionActive || open
          ? 'bg-white/10 text-white'
          : 'text-white/70 hover:bg-white/10 hover:text-white',
      ]"
      @click="open = !open"
    >
      <span>{{ label }}</span>
      <Icon
        name="chevron"
        size="h-3.5 w-3.5"
        :class="['transition-transform duration-200', open ? 'rotate-180' : '']"
      />
    </button>

    <Transition
      enter-active-class="transition duration-150 ease-out motion-reduce:transition-none"
      enter-from-class="opacity-0 -translate-y-1"
      leave-active-class="transition duration-100 ease-in motion-reduce:transition-none"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <div
        v-if="open"
        class="absolute left-0 z-50 mt-1.5 min-w-56 overflow-hidden rounded-xl border border-border-default bg-surface p-1.5 shadow-xl"
      >
        <Link
          v-for="item in items"
          :key="item.key"
          :href="item.href"
          :class="[
            'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition',
            isActive(item.href)
              ? 'bg-brand-600 text-white'
              : 'text-ink-muted hover:bg-surface-3 hover:text-ink',
          ]"
          @click="open = false"
        >
          <Icon :name="item.icon" size="h-4 w-4" />
          <span class="truncate">{{ item.label }}</span>
        </Link>
      </div>
    </Transition>
  </div>
</template>

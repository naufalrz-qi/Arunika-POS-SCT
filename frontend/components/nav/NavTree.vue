<script setup>
import { reactive, watch } from "vue";
import { Link } from "@inertiajs/vue3";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";

// Satu pohon menu untuk sidebar desktop DAN drawer ponsel. Dulu keduanya
// menulis pohonnya sendiri-sendiri (tab di header + daftar di sidebar, lalu
// salinan lengkapnya di drawer), dan salinan seperti itu cepat menyimpang.
const { tabs, activeTab, lipat, itemAktif } = useNav();

// Grup yang memuat halaman aktif selalu terbuka; yang lain ingat pilihan
// pengguna selama komponen hidup.
const open = reactive({});
watch(
  () => activeTab.value?.key,
  (key) => {
    if (key) open[key] = true;
  },
  { immediate: true },
);
</script>

<template>
  <nav class="space-y-1">
    <div v-for="tab in tabs" :key="tab.key">
      <button
        type="button"
        :aria-expanded="!!open[tab.key]"
        :class="[
          'flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-sm transition-colors hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
          activeTab?.key === tab.key ? 'font-medium text-ink' : 'text-ink-muted hover:text-ink',
        ]"
        @click="open[tab.key] = !open[tab.key]"
      >
        <Icon :name="tab.icon" size="h-4 w-4" class="shrink-0" />
        <span class="flex-1 truncate text-left">{{ tab.label }}</span>
        <Icon
          name="chevron"
          size="h-3.5 w-3.5"
          :class="['shrink-0 text-ink-subtle transition-transform duration-200', open[tab.key] ? '' : '-rotate-90']"
        />
      </button>

      <div v-show="open[tab.key]" class="mb-2 ml-[1.1rem] mt-0.5 border-l border-border-default pl-2.5">
        <template v-for="sub in tab.subsections" :key="sub.key">
          <p
            v-if="tab.subsections.length > 1"
            class="px-2.5 pb-1 pt-2.5 text-[11px] font-medium text-ink-subtle"
          >
            {{ sub.label }}
          </p>
          <Link
            v-for="item in lipat(sub.items)"
            :key="item.key"
            :href="item.href"
            :aria-current="itemAktif(item) ? 'page' : undefined"
            :class="[
              'block truncate rounded-control px-2.5 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
              itemAktif(item)
                ? 'bg-brand-bg font-medium text-brand-fg'
                : 'text-ink-muted hover:bg-surface-3 hover:text-ink',
            ]"
          >
            {{ item.label }}
          </Link>
        </template>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useConnectionStore } from "@/stores/connection";
import Icon from "./Icon.vue";

const store = useConnectionStore();
const { active, list, switching } = storeToRefs(store);
const open = ref(false);

const typeName = { gudang: "Gudang", grosir: "Grosir", retail: "Toko Retail" };

const dot = (status) => (status === "online" ? "bg-success-500" : status === "offline" ? "bg-danger-500" : "bg-neutral-300");

function choose(c) {
  open.value = false;
  if (!c.is_default) store.switchConnection(c.id);
}
</script>

<template>
  <div class="relative">
    <button
      class="flex items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-sm text-white transition hover:bg-white/10"
      @click="open = !open"
      @blur="open = false"
    >
      <span v-if="switching" class="h-2 w-2 animate-pulse rounded-full bg-brand-400" />
      <span v-else :class="['h-2 w-2 rounded-full', dot(active?.status)]" />
      <span class="hidden text-white/60 sm:inline">Koneksi:</span>
      <span class="font-medium">{{ active?.name || "Belum ada" }}</span>
      <Icon name="chevron" size="h-4 w-4" class="text-white/60" />
    </button>

    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="opacity-0 scale-95"
      leave-active-class="transition duration-75 ease-in"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="open"
        class="absolute right-0 z-[60] mt-2 w-72 overflow-hidden rounded-lg border border-border-default bg-surface shadow-lg"
        @mousedown.prevent
      >
        <div class="border-b border-border-default px-4 py-2">
          <p class="text-xs font-semibold text-ink-muted">Ganti Koneksi Server</p>
        </div>

        <div v-if="list.length" class="max-h-96 overflow-y-auto py-1">
          <button
            v-for="c in list"
            :key="c.id"
            class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-surface-3"
            @click="choose(c)"
          >
            <span :class="['h-2 w-2 shrink-0 rounded-full', dot(c.status)]" />
            <span class="min-w-0 flex-1 truncate text-ink">
              {{ c.name }}
              <span class="text-xs text-ink-muted">· {{ typeName[c.db_type] || c.db_type }}</span>
            </span>
            <span v-if="c.is_default" class="shrink-0 rounded bg-brand-bg px-1.5 py-0.5 text-xs font-medium text-brand-fg">
              Aktif
            </span>
          </button>
        </div>
        <p v-else class="px-4 py-4 text-sm text-ink-muted">Belum ada profil koneksi.</p>

        <a
          href="/admin-panel/connections"
          class="flex items-center gap-2 border-t border-border-default px-4 py-2.5 text-sm text-ink-muted hover:bg-surface-3"
        >
          <Icon name="server" size="h-4 w-4" /> Kelola Koneksi…
        </a>
      </div>
    </Transition>
  </div>
</template>

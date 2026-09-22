<script setup>
import { computed } from "vue";
import { DB_TYPE_LABELS, LINGKUNGAN_LABELS } from "@/utils/labels";
import { storeToRefs } from "pinia";
import { useConnectionStore } from "@/stores/connection";
import { useDismissable } from "@/composables/useDismissable";
import Icon from "./Icon.vue";

const store = useConnectionStore();
const { active, list, switching } = storeToRefs(store);
const { open, root, close, toggle } = useDismissable();

const typeName = DB_TYPE_LABELS;

// Lencana untuk semua yang BUKAN produksi. Produksi tetap tanpa lencana dengan
// sengaja: kalau setiap koneksi berlencana, tak ada yang menonjol -- dan yang
// perlu menonjol justru keadaan yang tidak biasa.
const bukanProduksi = (c) => Boolean(c?.lingkungan) && c.lingkungan !== "produksi";
const labelLingkungan = (c) => LINGKUNGAN_LABELS[c?.lingkungan] || c?.lingkungan;

// Dua grup (spec 2026-09-22 K8). Daftarnya sudah disaring server: yang tak
// berhak tak menerima profil non-produksi sama sekali, jadi grup kedua pun
// tak pernah muncul baginya.
const grup = computed(() => [
  { judul: "Produksi", isi: list.value.filter((c) => !bukanProduksi(c)) },
  { judul: "Uji coba & internal", isi: list.value.filter(bukanProduksi) },
].filter((g) => g.isi.length));

const dot = (status) => (status === "online" ? "bg-success-500" : status === "offline" ? "bg-danger-500" : "bg-neutral-300");

function choose(c) {
  close();
  if (c.id !== active.value?.id) store.switchConnection(c.id);
}
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="flex h-9 items-center gap-2 rounded-control border border-border-default px-2.5 text-sm text-ink transition-colors hover:bg-surface-2"
      :aria-expanded="open"
      aria-haspopup="menu"
      @click="toggle"
    >
      <span v-if="switching" class="h-2 w-2 animate-pulse rounded-full bg-brand-400" />
      <span v-else :class="['h-2 w-2 rounded-full', dot(active?.status)]" />
      <span class="hidden text-xs text-ink-muted sm:inline">Koneksi</span>
      <!-- Nama tetap tampil di ponsel, hanya dipotong: koneksi menentukan ke
           cabang MANA nota tertulis, jadi tak boleh disembunyikan di balik
           menu hanya demi ruang. -->
      <span class="max-w-[6.5rem] truncate text-xs font-medium sm:max-w-none">{{ active?.name || "Belum ada" }}</span>
      <span
        v-if="bukanProduksi(active)"
        class="shrink-0 rounded bg-warning-bg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-fg"
      >{{ labelLingkungan(active) }}</span>
      <Icon name="chevron" size="h-4 w-4" class="text-ink-subtle" />
    </button>

    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="opacity-0 scale-95"
      leave-active-class="transition duration-75 ease-in"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="open"
        class="absolute right-0 z-[60] mt-2 w-72 overflow-hidden rounded-control border border-border-default bg-surface shadow-lg"
      >
        <div class="border-b border-border-default px-4 py-2">
          <p class="text-xs font-semibold text-ink-muted">Ganti Koneksi Server</p>
        </div>

        <div v-if="list.length" class="max-h-96 overflow-y-auto py-1">
          <template v-for="g in grup" :key="g.judul">
            <!-- Judul grup hanya kalau memang ada dua grup: satu grup berjudul
                 "Produksi" sendirian cuma menambah baris. -->
            <p
              v-if="grup.length > 1"
              class="px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-ink-subtle"
            >{{ g.judul }}</p>
            <button
              v-for="c in g.isi"
              :key="c.id"
              class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-surface-3"
              @click="choose(c)"
            >
              <span :class="['h-2 w-2 shrink-0 rounded-full', dot(c.status)]" />
              <span class="min-w-0 flex-1 truncate text-ink">
                {{ c.name }}
                <span class="text-xs text-ink-muted">· {{ typeName[c.db_type] || c.db_type }}</span>
              </span>
              <span
                v-if="bukanProduksi(c)"
                class="shrink-0 rounded bg-warning-bg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-fg"
              >{{ labelLingkungan(c) }}</span>
              <span v-if="c.id === active?.id" class="shrink-0 rounded bg-brand-bg px-1.5 py-0.5 text-xs font-medium text-brand-fg">
                Aktif
              </span>
            </button>
          </template>
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

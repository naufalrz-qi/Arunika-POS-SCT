<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { router } from "@inertiajs/vue3";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";

// Lompat ke menu mana pun dengan mengetik namanya (Ctrl+K / ⌘K). Grup Laporan
// saja berisi ±20 menu; membuka grup lalu memindai daftarnya lebih lambat
// daripada mengetik "piutang" lalu Enter. Sumbernya `useNav`, jadi yang
// ditawarkan persis menu yang boleh dibuka akun ini — tak lebih.
const { tabs } = useNav();

const open = ref(false);
const q = ref("");
const aktif = ref(0);
const input = ref(null);
const daftar = ref(null);
let fokusSebelum = null;

const semua = computed(() =>
  tabs.value.flatMap((tab) =>
    tab.subsections.flatMap((sub) =>
      sub.items.map((item) => ({
        key: item.key,
        label: item.label,
        href: item.href,
        konteks: sub.label === tab.label ? tab.label : `${tab.label} · ${sub.label}`,
      })),
    ),
  ),
);

// Semua kata harus cocok (label atau konteks); yang cocok di label didahulukan.
const hasil = computed(() => {
  const kata = q.value.toLowerCase().split(/\s+/).filter(Boolean);
  if (!kata.length) return semua.value;
  const cocok = semua.value.filter((m) => {
    const teks = `${m.label} ${m.konteks}`.toLowerCase();
    return kata.every((k) => teks.includes(k));
  });
  const diLabel = (m) => kata.every((k) => m.label.toLowerCase().includes(k));
  return [...cocok.filter(diLabel), ...cocok.filter((m) => !diLabel(m))];
});

watch(q, () => {
  aktif.value = 0;
});

function buka() {
  fokusSebelum = document.activeElement;
  q.value = "";
  aktif.value = 0;
  open.value = true;
  nextTick(() => input.value?.focus());
}

function tutup() {
  open.value = false;
  fokusSebelum?.focus?.();
  fokusSebelum = null;
}

function pilih(m) {
  if (!m) return;
  open.value = false;
  fokusSebelum = null;
  router.visit(m.href);
}

function geser(arah) {
  const n = hasil.value.length;
  if (!n) return;
  aktif.value = (aktif.value + arah + n) % n;
  nextTick(() => daftar.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" }));
}

function onGlobalKey(e) {
  // `e.key?.`: isi-otomatis Chrome mengirim keydown tanpa `key`.
  if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key?.toLowerCase() === "k") {
    e.preventDefault();
    open.value ? tutup() : buka();
  }
}
onMounted(() => window.addEventListener("keydown", onGlobalKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onGlobalKey));

const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
</script>

<template>
  <button
    type="button"
    class="flex h-9 items-center gap-2 rounded-control px-2.5 text-sm text-ink-muted transition-colors hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 max-md:w-9 max-md:justify-center max-md:px-0 md:w-56 md:border md:border-border-default"
    aria-label="Cari menu"
    title="Cari menu"
    @click="buka"
  >
    <Icon name="search" size="h-4 w-4" class="shrink-0" />
    <span class="hidden flex-1 text-left md:inline">Cari menu…</span>
    <kbd class="hidden rounded border border-border-default px-1 font-sans text-[10px] font-semibold md:inline">
      {{ mac ? "⌘K" : "Ctrl K" }}
    </kbd>
  </button>

  <!-- Tanpa <Transition>, dan itu disengaja: memilih menu menutup palet lalu
       langsung berpindah halaman, sehingga komponen ini dilepas di tengah
       animasi keluar. Pada halaman yang tak sedang menggambar frame (tab latar,
       jendela tertutup) animasi itu tak pernah selesai, dan elemen yang
       di-teleport tertinggal di <body> dengan kelas v-leave-from, opacity 1 —
       lapisan fixed inset-0 yang menutupi seluruh halaman tujuan. Teramati di
       panel pratinjau yang tersembunyi; menutup tanpa animasi menghapus
       kemungkinannya sama sekali. -->
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[80] flex items-start justify-center p-4 pt-[12vh]" @keydown.esc="tutup">
      <div class="absolute inset-0 bg-black/40" @click="tutup" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Cari menu"
        class="surface-raised relative flex max-h-[70vh] w-full max-w-lg flex-col overflow-hidden shadow-lg"
      >
        <div class="flex items-center gap-2.5 border-b border-border-default px-4">
          <Icon name="search" size="h-4 w-4" class="shrink-0 text-ink-subtle" />
          <input
            ref="input"
            v-model="q"
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls="palet-menu"
            :aria-activedescendant="hasil[aktif] ? `palet-${hasil[aktif].key}` : undefined"
            placeholder="Ketik nama menu…"
            autocomplete="off"
            spellcheck="false"
            class="h-12 w-full bg-transparent text-sm text-ink placeholder:text-ink-subtle focus:outline-none"
            @keydown.down.prevent="geser(1)"
            @keydown.up.prevent="geser(-1)"
            @keydown.enter.prevent="pilih(hasil[aktif])"
            @keydown.tab.prevent="geser($event.shiftKey ? -1 : 1)"
          />
          <kbd class="hidden shrink-0 rounded border border-border-default px-1 font-sans text-[10px] font-semibold text-ink-subtle sm:inline">Esc</kbd>
        </div>
        <ul id="palet-menu" ref="daftar" role="listbox" class="scroll-slim min-h-0 flex-1 overflow-y-auto p-1.5">
          <li
            v-for="(m, i) in hasil"
            :id="`palet-${m.key}`"
            :key="m.key"
            role="option"
            :aria-selected="i === aktif"
            :class="[
              'flex cursor-pointer items-center justify-between gap-3 rounded-control px-3 py-2 text-sm',
              i === aktif ? 'bg-brand-bg text-brand-fg' : 'text-ink',
            ]"
            @mousemove="aktif = i"
            @click="pilih(m)"
          >
            <span class="truncate">{{ m.label }}</span>
            <span :class="['shrink-0 text-xs', i === aktif ? 'text-brand-fg' : 'text-ink-subtle']">{{ m.konteks }}</span>
          </li>
          <li v-if="!hasil.length" class="px-3 py-6 text-center text-sm text-ink-muted">
            Tidak ada menu bernama "{{ q }}".
          </li>
        </ul>
      </div>
    </div>
  </Teleport>
</template>

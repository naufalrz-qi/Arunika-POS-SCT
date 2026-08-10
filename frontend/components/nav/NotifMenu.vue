<script setup>
import { computed, ref, watch } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import axios from "axios";
import { storeToRefs } from "pinia";
import { useUserStore } from "@/stores/user";
import { useDismissable } from "@/composables/useDismissable";
import { ACTION_LABELS, labelOf } from "@/utils/labels";
import Icon from "./Icon.vue";

const page = usePage();
const { allowedMenus, user } = storeToRefs(useUserStore());

// Angka lencana disimpan lokal supaya menekan lonceng langsung menol-kannya,
// tanpa menunggu kunjungan Inertia berikutnya. `belumServer` tetap dibaca dari
// prop bersama, jadi notif yang datang di halaman berikutnya tetap muncul.
const dibacaLokal = ref(false);
const belumServer = computed(() => page.props.notif?.belum ?? 0);
const items = computed(() => page.props.notif?.items ?? []);
const belum = computed(() => (dibacaLokal.value ? 0 : belumServer.value));

// Superadmin melihat jejak semua orang (apps/core/models.log_untuk), jadi nama
// pelakunya baru berarti untuk dia.
const tampilkanNama = computed(() => user.value?.role === "superadmin");
const punyaMenuLog = computed(() => allowedMenus.value.some((m) => m.key === "logs"));

const { open, root, toggle } = useDismissable();

function bukaTutup() {
  const akanTerbuka = !open.value;
  toggle();
  if (!akanTerbuka || belum.value === 0) return;
  dibacaLokal.value = true;
  // Di akar, bukan /admin-panel: lonceng ada di navbar layar kasir juga, dan
  // seluruh /admin-panel tertutup penjaga Tailscale dari jaringan toko.
  axios.post("/notif/baca").catch(() => {
    dibacaLokal.value = false; // gagal ditandai → lencana jujur kembali
  });
}

// Angka baru dari server SELALU menang. Tanpa ini, notif yang datang sesudah
// lonceng dibuka akan tertutup topeng lokal dan lencananya tak pernah menyala
// lagi sampai halaman dimuat ulang penuh.
watch(belumServer, () => { dibacaLokal.value = false; });
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="relative flex h-9 w-9 items-center justify-center rounded-control text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
      :aria-expanded="open"
      aria-haspopup="menu"
      :aria-label="belum ? `Notifikasi, ${belum} baru` : 'Notifikasi'"
      title="Notifikasi"
      @click="bukaTutup"
    >
      <Icon name="bell" />
      <span
        v-if="belum"
        class="absolute right-1 top-1 min-w-[1.05rem] rounded-full bg-brand-600 px-1 text-[10px] font-semibold leading-[1.05rem] text-white"
      >
        {{ belum > 99 ? "99+" : belum }}
      </span>
    </button>

    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="opacity-0 scale-95"
      leave-active-class="transition duration-75 ease-in"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="open"
        class="absolute right-0 mt-2 w-80 max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-control border border-border-default bg-surface shadow-lg"
      >
        <div class="border-b border-border-default px-4 py-2.5">
          <p class="text-sm font-medium text-ink">Notifikasi</p>
          <p class="mt-0.5 text-[11px] text-ink-subtle">
            {{ tampilkanNama ? "Aktivitas seluruh akun" : "Aktivitas akun Anda" }}
          </p>
        </div>

        <p v-if="!items.length" class="px-4 py-6 text-center text-sm text-ink-subtle">
          Belum ada aktivitas.
        </p>

        <ul v-else class="scroll-slim max-h-80 overflow-y-auto">
          <li
            v-for="n in items"
            :key="n.id"
            :class="['border-b border-border-default px-4 py-2.5 last:border-b-0', n.baru ? 'bg-brand-bg/40' : '']"
          >
            <div class="flex items-baseline justify-between gap-2">
              <p class="truncate text-sm text-ink">{{ labelOf(ACTION_LABELS, n.action) }}</p>
              <p class="shrink-0 text-[11px] tabular-nums text-ink-subtle">{{ n.waktu }}</p>
            </div>
            <p v-if="n.detail" class="mt-0.5 break-words text-xs text-ink-muted">{{ n.detail }}</p>
            <p v-if="tampilkanNama" class="mt-0.5 text-[11px] text-ink-subtle">{{ n.user }}</p>
          </li>
        </ul>

        <!-- Tautannya cuma muncul kalau menunya memang diberikan: mengantar
             orang ke halaman yang akan menolaknya lebih buruk dari tak
             menawarkan apa-apa. -->
        <Link
          v-if="punyaMenuLog"
          href="/admin-panel/logs"
          class="block border-t border-border-default px-4 py-2.5 text-center text-sm text-brand-fg hover:bg-surface-3"
        >
          Lihat semua aktivitas
        </Link>
      </div>
    </Transition>
  </div>
</template>

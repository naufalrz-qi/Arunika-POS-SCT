<script setup>
/**
 * Layar penolakan akses.
 *
 * Sebelumnya ketiga jalur penolakan (bukan admin, di luar Tailscale, menu tak
 * diberikan) mengembalikan satu baris teks polos di layar putih: tanpa kop,
 * tanpa navigasi, tanpa jalan keluar selain tombol back. Halaman ini menyebut
 * apa yang terjadi, apa yang bisa dilakukan, dan ke mana ia masih boleh pergi.
 *
 * Berdiri di luar AdminLayout: sebagian yang mendarat di sini memang tak berhak
 * membuka panel admin sama sekali, jadi merender sidebar penuh berisi menu yang
 * tak bisa diklik cuma menyesatkan.
 */
import { Link } from "@inertiajs/vue3";
import Button from "@/components/ui/Button.vue";
import Icon from "@/components/nav/Icon.vue";
import ToastContainer from "@/components/ui/ToastContainer.vue";

defineProps({
  judul: { type: String, default: "Halaman ini belum bisa dibuka" },
  saran: { type: String, default: "" },
  // Halaman yang masih boleh dibuka; null bila memang tak ada satu pun.
  tujuan: { type: String, default: null },
});
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-surface-2 px-4 py-12">
    <div class="w-full max-w-md text-center">
      <div class="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-warning-bg">
        <Icon name="key" size="h-6 w-6" class="text-warning-fg" />
      </div>

      <h1 class="text-lg font-semibold text-ink">{{ judul }}</h1>
      <p v-if="saran" class="mt-2 text-sm text-ink-muted">{{ saran }}</p>

      <div class="mt-6 flex flex-col items-center gap-2">
        <Link v-if="tujuan" :href="tujuan" class="w-full">
          <Button class="w-full">Buka halaman saya</Button>
        </Link>
        <a href="/logout" class="text-xs text-ink-muted hover:text-ink hover:underline">
          Keluar, lalu masuk dengan akun lain
        </a>
      </div>
    </div>
  </div>
  <ToastContainer />
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  variant: { type: String, default: "primary" }, // primary | secondary | ghost | danger | success | accent
  size: { type: String, default: "md" }, // sm | md
  type: { type: String, default: "button" },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  // Kalau diisi, dirender sebagai <a> alih-alih <button> — untuk aksi yang
  // sebenarnya navigasi (unduhan server). Tanpa ini pemanggil menyalin seluruh
  // daftar kelas di bawah, lalu menyimpang darinya (dulu terjadi di
  // ExportButton: bevel dan ukuran teksnya sudah beda dari Button).
  href: { type: String, default: "" },
});

// Tombol di sini hanya berpindah warna saat disentuh. Sebelumnya tiap varian
// membawa glow box-shadow berwarna, backdrop-blur, lapisan putih 10% lewat
// ::before, dan skala 0.98 saat ditekan — lima efek untuk satu tindakan. Di
// panel filter yang punya dua tombol dan di modal yang punya dua lagi, itu
// membuat kontrol lebih ramai daripada data yang mereka saring.
const base =
  "inline-flex items-center justify-center gap-2 font-medium rounded-control border transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-1 focus-visible:ring-offset-surface disabled:opacity-50 disabled:cursor-not-allowed";

// Enam varian, semuanya terpakai. Sebelumnya ada sepuluh: `warning`, `info`,
// `yellow`, dan `accent` (merah) nol pemakaian — `variant="warning"` dan
// `variant="info"` yang bertebaran di halaman semuanya milik Banner, bukan
// Button. Nama `yellow-outline` menggambarkan warna, bukan makna, jadi diganti
// `accent`: aksi yang menonjol tapi bukan destruktif (alur saran/ubah harga).
const variants = {
  primary: "bg-brand-600 text-white border-brand-600 hover:bg-brand-700 hover:border-brand-700",
  secondary: "bg-surface text-ink border-border-strong hover:bg-surface-2",
  ghost: "text-ink-muted border-transparent hover:bg-surface-3 hover:text-ink",
  danger: "bg-danger-600 text-white border-danger-600 hover:bg-danger-700 hover:border-danger-700",
  success: "bg-success-600 text-white border-success-600 hover:bg-success-700 hover:border-success-700",
  accent: "bg-warning-bg text-warning-fg border-warning-600/40 hover:bg-warning-bg hover:border-warning-600",
};

const sizes = {
  sm: "text-xs px-2.5 py-1 h-7",
  md: "text-sm px-4 py-2 h-9",
};

// Varian tak dikenal dulu menghasilkan `undefined` di daftar kelas, jadi
// tombolnya terender telanjang tanpa warna sama sekali dan salah ketik lolos
// diam-diam. Sekarang jatuh ke `secondary` dan berisik di konsol dev.
const classes = computed(() => {
  const variant = variants[props.variant];
  if (!variant && import.meta.env.DEV) {
    console.warn(
      `[Button] varian "${props.variant}" tidak dikenal. Pilihan: ${Object.keys(variants).join(", ")}.`,
    );
  }
  return [base, variant ?? variants.secondary, sizes[props.size] ?? sizes.md];
});
</script>

<template>
  <component
    :is="href ? 'a' : 'button'"
    :href="href || undefined"
    :type="href ? undefined : type"
    :disabled="href ? undefined : disabled || loading"
    :class="classes"
  >
    <svg
      v-if="loading"
      class="animate-spin h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
    <slot />
  </component>
</template>

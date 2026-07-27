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

// Tanpa `panel-cut-sm`: clip-path memotong SEMUA yang dilukis elemen ini —
// termasuk `border` (putus di 4 sudut diagonal) dan setiap `box-shadow` (glow
// hover di bawah hilang total, karena shadow dilukis di luar kotak). Lihat
// catatan panjang di main.css .panel-cut-frame. Solusi bevel butuh elemen
// pembungkus, yang tak tersedia untuk satu <button>; jadi kontrol memakai
// radius kecil — bevel tetap milik permukaan (kartu, tabel, panel).
const base =
  "inline-flex items-center justify-center gap-2 font-heading font-bold tracking-wide rounded-control transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 disabled:opacity-50 disabled:cursor-not-allowed active:translate-y-px active:scale-[0.98] border relative overflow-hidden group before:absolute before:inset-0 before:bg-white/10 before:opacity-0 hover:before:opacity-100 before:transition-opacity";

// Enam varian, semuanya terpakai. Sebelumnya ada sepuluh: `warning`, `info`,
// `yellow`, dan `accent` (merah) nol pemakaian — `variant="warning"` dan
// `variant="info"` yang bertebaran di halaman semuanya milik Banner, bukan
// Button. Nama `yellow-outline` menggambarkan warna, bukan makna, jadi diganti
// `accent`: aksi yang menonjol tapi bukan destruktif (alur saran/ubah harga).
const variants = {
  primary: "bg-brand-600/90 text-white border-brand-500 hover:bg-brand-500 hover:border-brand-400 hover:shadow-[0_0_15px_var(--glow-brand)] backdrop-blur-sm",
  secondary: "bg-surface/80 text-ink border-border-strong hover:bg-surface-2 hover:border-brand-400 hover:text-brand-600 hover:shadow-[0_0_12px_var(--glow-brand)] backdrop-blur-sm",
  ghost: "text-ink-muted border-transparent hover:bg-surface-3/50 hover:text-ink",
  danger: "bg-danger-600/90 text-white border-danger-500 hover:bg-danger-500 hover:border-danger-400 hover:shadow-[0_0_15px_var(--glow-danger)] backdrop-blur-sm",
  success: "bg-success-600/90 text-white border-success-500 hover:bg-success-500 hover:border-success-400 hover:shadow-[0_0_15px_var(--glow-success)] backdrop-blur-sm",
  accent: "bg-surface/80 text-ink border-rx-yellow hover:bg-warning-bg hover:text-warning-fg hover:shadow-[0_0_12px_var(--glow-accent)] backdrop-blur-sm",
};

const sizes = {
  sm: "text-[11px] px-3 py-1.5 h-8",
  md: "text-xs px-5 py-2.5 h-10",
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

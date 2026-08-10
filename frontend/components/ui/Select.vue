<script setup>
import { computed } from "vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";

const props = defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  label: { type: String, default: "" },
  // options: [{ value, label }]
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
  // Ambang batas kapan daftar berubah jadi kotak cari. Bisa ditimpa per
  // pemakaian, mis. 0 untuk memaksa selalu bisa diketik.
  ambangCari: { type: Number, default: 20 },
});
defineEmits(["update:modelValue"]);

// Daftar panjang dirender sebagai combobox (SelectSearch), bukan <select> polos:
// m_merk punya 1.474 baris, m_model 1.289, m_kategori 862 di satu server. Menggulung
// seribu <option> untuk mencari satu merk bukan pekerjaan yang bisa diselesaikan
// dengan mouse.
//
// Ambangnya di SINI, bukan di tiap halaman, supaya keputusannya ikut DATA yang
// benar-benar datang dari server — jumlah kota/supplier berbeda di tiap koneksi,
// jadi menebak per kolom akan salah di sebagian server. Daftar pendek tetap
// <select> asli: di ponsel itu memunculkan pemilih bawaan sistem, yang lebih
// enak dipakai daripada daftar buatan sendiri.
const pakaiCari = computed(() => props.options.length >= props.ambangCari);
</script>

<template>
  <SelectSearch
    v-if="pakaiCari"
    :model-value="modelValue"
    :options="options"
    :label="label"
    :placeholder="placeholder || 'Semua'"
    :disabled="disabled"
    @update:model-value="$emit('update:modelValue', $event)"
  />
  <label v-else class="block">
    <span v-if="label" class="mb-1 block text-xs font-medium text-ink-muted">{{ label }}</span>
    <select
      :value="modelValue"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.value)"
      class="h-9 w-full rounded-control border border-border-strong bg-surface px-2.5 text-sm text-ink transition-colors duration-150 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <option v-if="placeholder" value="">{{ placeholder }}</option>
      <option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
    </select>
  </label>
</template>

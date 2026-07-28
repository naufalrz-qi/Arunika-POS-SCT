<script setup>
import { computed } from "vue";
import { Head, useForm } from "@inertiajs/vue3";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Banner from "@/components/ui/Banner.vue";
import Icon from "@/components/nav/Icon.vue";

const form = useForm({ username: "", password: "" });

// Sesi habis diarahkan ke sini oleh auth_required; tanpa ini pengguna cuma
// melihat halaman login muncul tiba-tiba tanpa penjelasan.
const sesiBerakhir = computed(() =>
  typeof window !== "undefined" && new URLSearchParams(window.location.search).has("expired"),
);

function submit() {
  form.post("/login");
}
</script>

<template>
  <Head title="Masuk" />
  <div class="flex min-h-screen items-center justify-center bg-surface-2 p-4">
    <div class="w-full max-w-sm">
      <div class="mb-6 text-center">
        <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-control bg-brand-600 text-white">
          <Icon name="crown" size="h-6 w-6" />
        </div>
        <h1 class="text-lg font-semibold text-ink">Sukses Crown Toys</h1>
        <p class="mt-0.5 text-sm text-ink-muted">Masuk untuk melanjutkan</p>
      </div>

      <!-- Layar pertama yang dilihat pengguna. Kotaknya sama persis dengan
           tabel di dalam aplikasi — satu-satunya permukaan yang terangkat. -->
      <div class="surface-raised overflow-hidden">
        <form class="space-y-4 p-6" @submit.prevent="submit">
          <Banner
            v-if="sesiBerakhir"
            variant="info"
            message="Sesi Anda sudah berakhir. Silakan masuk kembali."
          />
          <!-- Error tingkat-form: password salah tak boleh menyorot kolom Username. -->
          <Banner v-if="form.errors.form" variant="warning" :message="form.errors.form" />
          <Input
            v-model="form.username"
            label="Username"
            placeholder="username"
            autocomplete="username"
            autofocus
            :error="form.errors.username"
            required
          />
          <Input
            v-model="form.password"
            label="Password"
            type="password"
            placeholder="••••••••"
            autocomplete="current-password"
            :error="form.errors.password"
            required
          />
          <Button type="submit" class="w-full" :loading="form.processing">Masuk</Button>
        </form>
      </div>
    </div>
  </div>
</template>

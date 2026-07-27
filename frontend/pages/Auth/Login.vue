<script setup>
import { computed } from "vue";
import { useForm } from "@inertiajs/vue3";
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
  <div class="flex min-h-screen items-center justify-center bg-surface-2 p-4">
    <div class="w-full max-w-sm">
      <div class="mb-6 text-center">
        <div class="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-400 to-brand-700 text-white shadow-lg">
          <Icon name="crown" size="h-7 w-7" />
        </div>
        <h1 class="text-xl font-semibold text-ink">Sukses Crown Toys</h1>
        <p class="text-sm text-ink-muted">Masuk untuk melanjutkan</p>
      </div>

      <div class="overflow-hidden rounded-card border border-border-default bg-surface shadow-sm">
        <div class="panel-strip h-1" />
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
            :error="form.errors.username"
            required
          />
          <Input
            v-model="form.password"
            label="Password"
            type="password"
            placeholder="••••••••"
            :error="form.errors.password"
            required
          />
          <Button type="submit" class="w-full" :loading="form.processing">Masuk</Button>
        </form>
      </div>
    </div>
  </div>
</template>

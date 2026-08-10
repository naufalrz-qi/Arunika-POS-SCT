<script setup>
import { useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Badge from "@/components/ui/Badge.vue";

const props = defineProps({
  profile: { type: Object, default: () => ({}) },
});

const form = useForm({
  username: props.profile.username || "",
  name: props.profile.name || "",
  password_lama: "",
  password: "",
});

function save() {
  form.post("/admin-panel/profile/save", {
    onSuccess: () => {
      form.password = "";
      form.password_lama = "";
    },
  });
}
</script>

<template>
  <AdminLayout title="Profil Saya">
    <Card class="max-w-lg">
      <div class="mb-4 flex items-center gap-3">
        <div class="flex h-12 w-12 items-center justify-center rounded-full bg-brand-bg text-lg font-semibold text-brand-fg">
          {{ (profile.name || profile.username || "?").charAt(0).toUpperCase() }}
        </div>
        <div>
          <p class="font-medium text-ink">{{ profile.username }}</p>
          <Badge variant="brand" class="capitalize">{{ profile.role }}</Badge>
        </div>
      </div>

      <div class="space-y-4">
        <Input v-model="form.username" label="Username" :error="form.errors.username" />
        <Input v-model="form.name" label="Nama Lengkap" :error="form.errors.name" />
        <!-- Kotak password lama berdiri DI ATAS password baru dan hanya muncul
             saat password baru mulai diisi: memintanya di muka pada halaman yang
             lebih sering dipakai untuk mengubah nama membuat orang mengira
             seluruh formulir butuh sandi. -->
        <Input
          v-model="form.password"
          label="Password Baru"
          type="password"
          placeholder="Kosongkan jika tidak diubah"
          :error="form.errors.password"
        />
        <Input
          v-if="form.password"
          v-model="form.password_lama"
          label="Password Saat Ini"
          type="password"
          placeholder="Wajib diisi untuk mengganti password"
          :error="form.errors.password_lama"
        />
        <div class="flex justify-end">
          <Button :loading="form.processing" @click="save">Simpan Perubahan</Button>
        </div>
      </div>
    </Card>
  </AdminLayout>
</template>


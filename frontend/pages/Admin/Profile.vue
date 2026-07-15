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
  password: "",
});

function save() {
  form.post("/admin-panel/profile/save", { onSuccess: () => (form.password = "") });
}
</script>

<template>
  <AdminLayout title="Profil Saya">
    <Card class="max-w-lg">
      <div class="mb-4 flex items-center gap-3">
        <div class="flex h-12 w-12 items-center justify-center rounded-full bg-brand-100 text-lg font-semibold text-brand-700">
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
        <Input
          v-model="form.password"
          label="Password Baru"
          type="password"
          placeholder="Kosongkan jika tidak diubah"
          :error="form.errors.password"
        />
        <div class="flex justify-end">
          <Button :loading="form.processing" @click="save">Simpan Perubahan</Button>
        </div>
      </div>
    </Card>
  </AdminLayout>
</template>


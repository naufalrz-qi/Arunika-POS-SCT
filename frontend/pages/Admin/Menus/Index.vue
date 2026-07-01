<script setup>
import { reactive, ref } from "vue";
import { router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";

const props = defineProps({
  users: { type: Array, default: () => [] }, // {id, username, name, role, allowed_menu_keys}
  menus: { type: Array, default: () => [] }, // assignable menus
});

const selected = ref(null);
const checked = reactive({});
const saving = ref(false);

function select(user) {
  selected.value = user;
  const allowed = user.allowed_menu_keys || [];
  // Empty == full access by default; show everything checked.
  props.menus.forEach((m) => {
    checked[m.key] = allowed.length === 0 ? true : allowed.includes(m.key);
  });
}

function save() {
  if (!selected.value) return;
  const menu_keys = props.menus.filter((m) => checked[m.key]).map((m) => m.key);
  saving.value = true;
  router.post(
    "/admin-panel/menus/save",
    { user_id: selected.value.id, menu_keys },
    {
      preserveScroll: true,
      onSuccess: () => {
        // reflect locally
        const u = props.users.find((x) => x.id === selected.value.id);
        if (u) u.allowed_menu_keys = menu_keys;
      },
      onFinish: () => (saving.value = false),
    },
  );
}

const roleVariant = { admin: "brand", supervisor: "warning", kasir: "neutral" };
</script>

<template>
  <AdminLayout title="Kelola Menu">
    <p class="mb-4 text-sm text-ink-muted">
      Atur menu yang boleh diakses tiap user. <strong>Superadmin</strong> selalu punya akses penuh dan tidak muncul di daftar.
    </p>

    <div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <!-- User list -->
      <Card title="User">
        <ul class="divide-y divide-border-default">
          <li
            v-for="u in users"
            :key="u.id"
            :class="[
              'flex cursor-pointer items-center justify-between px-1 py-2.5 -mx-1 rounded-lg',
              selected?.id === u.id ? 'bg-brand-50' : 'hover:bg-surface-2',
            ]"
            @click="select(u)"
          >
            <div>
              <p class="text-sm font-medium text-ink">{{ u.name }}</p>
              <p class="text-xs text-ink-muted">{{ u.username }}</p>
            </div>
            <Badge :variant="roleVariant[u.role] || 'neutral'" class="capitalize">{{ u.role }}</Badge>
          </li>
          <li v-if="users.length === 0" class="py-6 text-center text-sm text-ink-subtle">Tidak ada user.</li>
        </ul>
      </Card>

      <!-- Menu checkboxes -->
      <Card class="lg:col-span-2" :title="selected ? `Menu untuk ${selected.name}` : 'Pilih user dulu'">
        <template v-if="selected">
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label
              v-for="m in menus"
              :key="m.key"
              class="flex items-center gap-3 rounded-lg border border-border-default px-3 py-2.5 hover:bg-surface-2"
            >
              <input type="checkbox" v-model="checked[m.key]" class="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500" />
              <span class="text-sm text-ink-muted">{{ m.label }}</span>
            </label>
          </div>
          <div class="mt-4 flex items-center justify-between">
            <p class="text-xs text-ink-subtle">Semua tercentang = akses penuh.</p>
            <Button :loading="saving" @click="save">Simpan</Button>
          </div>
        </template>
        <p v-else class="py-8 text-center text-sm text-ink-muted">Pilih user di kiri untuk mengatur menunya.</p>
      </Card>
    </div>
  </AdminLayout>
</template>


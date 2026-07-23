<script setup>
import { computed, reactive, ref } from "vue";
import { router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Input from "@/components/ui/Input.vue";
import Icon from "@/components/nav/Icon.vue";

const props = defineProps({
  users: { type: Array, default: () => [] }, // {id, username, name, role, allowed_menu_keys}
  menus: { type: Array, default: () => [] }, // assignable menus (punya .section + .icon)
  sections: { type: Array, default: () => [] }, // [{key, label}] urut tampil
});

const selected = ref(null);
const checked = reactive({});
const saving = ref(false);
const userSearch = ref("");

const filteredUsers = computed(() => {
  const q = userSearch.value.toLowerCase().trim();
  if (!q) return props.users;
  return props.users.filter(
    (u) => u.name.toLowerCase().includes(q) || u.username.toLowerCase().includes(q),
  );
});

// Menu dikelompokkan per section supaya mudah dipindai (dulu grid flat tanpa pembeda).
const grouped = computed(() =>
  props.sections
    .map((s) => ({ ...s, items: props.menus.filter((m) => m.section === s.key) }))
    .filter((s) => s.items.length),
);

const checkedCount = computed(() => props.menus.filter((m) => checked[m.key]).length);

function sectionState(s) {
  const on = s.items.filter((m) => checked[m.key]).length;
  return { all: on === s.items.length, some: on > 0 && on < s.items.length, on };
}
function toggleSection(s) {
  const target = !sectionState(s).all;
  s.items.forEach((m) => (checked[m.key] = target));
}
function setAll(value) {
  props.menus.forEach((m) => (checked[m.key] = value));
}

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
        <div class="mb-3">
          <Input v-model="userSearch" placeholder="Cari nama / username…" />
        </div>
        <ul class="divide-y divide-border-default">
          <li
            v-for="u in filteredUsers"
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
          <li v-if="filteredUsers.length === 0" class="py-6 text-center text-sm text-ink-subtle">Tidak ada user.</li>
        </ul>
      </Card>

      <!-- Menu checkboxes -->
      <Card class="lg:col-span-2" :title="selected ? `Menu untuk ${selected.name}` : 'Pilih user dulu'">
        <template v-if="selected">
          <!-- Toolbar global -->
          <div class="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-2 px-3 py-2">
            <p class="text-sm text-ink-muted">
              <strong class="text-ink">{{ checkedCount }}</strong> / {{ menus.length }} menu dipilih
            </p>
            <div class="flex gap-2">
              <Button variant="secondary" size="sm" @click="setAll(true)">Pilih Semua</Button>
              <Button variant="secondary" size="sm" @click="setAll(false)">Kosongkan</Button>
            </div>
          </div>

          <!-- Per section: header + pilih semua section + item ber-ikon -->
          <div class="space-y-5">
            <section v-for="s in grouped" :key="s.key">
              <div class="mb-2 flex items-center justify-between border-b border-border-default pb-1.5">
                <h3 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">{{ s.label }}</h3>
                <label class="flex cursor-pointer items-center gap-2 text-xs text-ink-muted hover:text-ink">
                  <input
                    type="checkbox"
                    :checked="sectionState(s).all"
                    :indeterminate.prop="sectionState(s).some"
                    class="h-3.5 w-3.5 rounded border-border-strong text-brand-600 focus:ring-brand-500"
                    @change="toggleSection(s)"
                  />
                  Pilih semua ({{ sectionState(s).on }}/{{ s.items.length }})
                </label>
              </div>
              <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <label
                  v-for="m in s.items"
                  :key="m.key"
                  :class="[
                    'flex items-center gap-3 rounded-lg border px-3 py-2.5 cursor-pointer transition-colors',
                    checked[m.key] ? 'border-brand-500/60 bg-brand-50' : 'border-border-default hover:bg-surface-2',
                  ]"
                >
                  <input type="checkbox" v-model="checked[m.key]" class="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500" />
                  <Icon :name="m.icon" size="h-4 w-4" class="shrink-0 text-ink-subtle" />
                  <span class="text-sm text-ink-muted">{{ m.label }}</span>
                </label>
              </div>
            </section>
          </div>

          <div class="mt-5 flex items-center justify-between">
            <p class="text-xs text-ink-subtle">Semua tercentang = akses penuh.</p>
            <Button :loading="saving" @click="save">Simpan</Button>
          </div>
        </template>
        <p v-else class="py-8 text-center text-sm text-ink-muted">Pilih user di kiri untuk mengatur menunya.</p>
      </Card>
    </div>
  </AdminLayout>
</template>


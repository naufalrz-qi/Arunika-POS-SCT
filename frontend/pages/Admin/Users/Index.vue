<script setup>
import { computed, ref } from "vue";
import { useForm, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import DataTable from "@/components/ui/DataTable.vue";
import Modal from "@/components/ui/Modal.vue";
import Icon from "@/components/nav/Icon.vue";

const props = defineProps({
  users: { type: Array, default: () => [] },
});

const search = ref("");
const filtered = computed(() => {
  const q = search.value.toLowerCase().trim();
  if (!q) return props.users;
  return props.users.filter(
    (u) => u.name.toLowerCase().includes(q) || u.username.toLowerCase().includes(q),
  );
});

const columns = [
  { key: "username", label: "Username", sortable: true },
  { key: "name", label: "Nama", sortable: true },
  { key: "role", label: "Role", sortable: true },
  { key: "is_active", label: "Status", align: "center" },
  { key: "actions", label: "", align: "right" },
];

const roleOptions = [
  { value: "kasir", label: "Kasir" },
  { value: "supervisor", label: "Supervisor" },
];

// --- Create / edit modal ---
const showForm = ref(false);
const form = useForm({ id: null, username: "", name: "", role: "kasir", password: "" });

function openCreate() {
  form.reset();
  form.clearErrors();
  showForm.value = true;
}
function openEdit(u) {
  form.id = u.id;
  form.username = u.username;
  form.name = u.name;
  form.role = u.role;
  form.password = "";
  showForm.value = true;
}
function save() {
  form.post("/admin-panel/users/save", {
    onSuccess: () => (showForm.value = false),
  });
}

// --- Reset password ---
const resetTarget = ref(null);
function confirmReset() {
  router.post(`/admin-panel/users/save`, {}, { onFinish: () => (resetTarget.value = null) });
}

// --- Deactivate ---
const deleteTarget = ref(null);
function confirmDelete() {
  router.delete(`/admin-panel/users/${deleteTarget.value.id}/delete`, {
    onFinish: () => (deleteTarget.value = null),
  });
}
</script>

<template>
  <AdminLayout title="Manajemen User">
    <Card>
      <template #header>
        <Button size="sm" @click="openCreate"><Icon name="plus" size="h-4 w-4" /> Tambah User</Button>
      </template>

      <div class="mb-4 max-w-xs">
        <Input v-model="search" placeholder="Cari nama / username…" />
      </div>

      <DataTable :columns="columns" :rows="filtered" empty-message="Tidak ada user.">
        <template #cell-role="{ value }">
          <Badge :variant="value === 'supervisor' ? 'brand' : 'neutral'" class="capitalize">{{ value }}</Badge>
        </template>
        <template #cell-is_active="{ value }">
          <Badge :variant="value ? 'success' : 'danger'">{{ value ? "Aktif" : "Nonaktif" }}</Badge>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex justify-end gap-1">
            <Button variant="ghost" size="sm" @click="openEdit(row)"><Icon name="pencil" size="h-4 w-4" /></Button>
            <Button variant="ghost" size="sm" @click="resetTarget = row"><Icon name="key" size="h-4 w-4" /></Button>
            <Button variant="ghost" size="sm" @click="deleteTarget = row"><Icon name="power" size="h-4 w-4" /></Button>
          </div>
        </template>
      </DataTable>
    </Card>

    <!-- Create / edit -->
    <Modal :show="showForm" :title="form.id ? 'Edit User' : 'Tambah User'" @close="showForm = false">
      <div class="space-y-4">
        <Input v-model="form.username" label="Username" :error="form.errors.username" required />
        <Input v-model="form.name" label="Nama Lengkap" :error="form.errors.name" required />
        <Select v-model="form.role" label="Role" :options="roleOptions" />
        <Input
          v-model="form.password"
          label="Password"
          type="password"
          :placeholder="form.id ? 'Kosongkan jika tidak diubah' : ''"
          :error="form.errors.password"
        />
      </div>
      <template #footer>
        <Button variant="secondary" @click="showForm = false">Batal</Button>
        <Button :loading="form.processing" @click="save">Simpan</Button>
      </template>
    </Modal>

    <!-- Reset password confirm -->
    <Modal :show="!!resetTarget" title="Reset Password" size="sm" @close="resetTarget = null">
      <p class="text-sm text-ink-muted">
        Reset password untuk <strong>{{ resetTarget?.name }}</strong> ke password default?
      </p>
      <template #footer>
        <Button variant="secondary" @click="resetTarget = null">Batal</Button>
        <Button @click="confirmReset">Reset</Button>
      </template>
    </Modal>

    <!-- Deactivate confirm -->
    <Modal :show="!!deleteTarget" title="Nonaktifkan User" size="sm" @close="deleteTarget = null">
      <p class="text-sm text-ink-muted">
        Nonaktifkan akun <strong>{{ deleteTarget?.name }}</strong>? User tidak akan bisa login.
      </p>
      <template #footer>
        <Button variant="secondary" @click="deleteTarget = null">Batal</Button>
        <Button variant="danger" @click="confirmDelete">Nonaktifkan</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>


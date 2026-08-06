<script setup>
import { computed, ref } from "vue";
import { useForm, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import { ROLE_LABELS } from "@/utils/labels";
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
  assignable_roles: { type: Array, default: () => ["kasir", "supervisor"] },
  me: { type: Number, default: null },
  legacy: { type: Object, default: null },
});

// Pilihan tautan ke akun legacy; datang belakangan lewat deferred prop, jadi
// dropdown-nya kosong sesaat sementara daftar user sudah tampil.
const legacyData = computed(() => props.legacy || {});
const userxOptions = computed(() =>
  (legacyData.value.userx || []).map((u) => ({
    value: u.kd_user,
    label: `${u.nama} (${u.kd_user})${u.aktif ? "" : " — nonaktif"}`,
  })),
);
const divisiOptions = computed(() =>
  (legacyData.value.divisi || []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

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


const roleOptions = computed(() =>
  props.assignable_roles.map((r) => ({ value: r, label: ROLE_LABELS[r] || r })),
);

// --- Create / edit modal ---
const showForm = ref(false);
const form = useForm({
  id: null, username: "", name: "", role: "kasir", password: "",
  kd_user: "", kd_divisi: "",
});

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
  form.kd_user = u.kd_user || "";
  form.kd_divisi = u.kd_divisi || "";
  showForm.value = true;
}
function save() {
  form.post("/admin-panel/users/save", {
    onSuccess: () => (showForm.value = false),
  });
}

// --- Reset password ---
const resetTarget = ref(null);
const resetPassword = ref("");
function openReset(u) {
  resetPassword.value = "";
  resetTarget.value = u;
}
function confirmReset() {
  router.post(
    `/admin-panel/users/${resetTarget.value.id}/reset-password`,
    { password: resetPassword.value },
    { onFinish: () => (resetTarget.value = null) },
  );
}

// --- Activate / deactivate (toggle) ---
const toggleTarget = ref(null);
function confirmToggle() {
  router.post(`/admin-panel/users/${toggleTarget.value.id}/toggle`, {}, {
    onFinish: () => (toggleTarget.value = null),
  });
}

// --- Hapus permanen ---
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
          <Badge :variant="value === 'superadmin' ? 'danger' : value === 'admin' ? 'warning' : value === 'supervisor' ? 'brand' : 'neutral'">{{ ROLE_LABELS[value] || value }}</Badge>
        </template>
        <template #cell-is_active="{ value }">
          <Badge :variant="value ? 'success' : 'danger'">{{ value ? "Aktif" : "Nonaktif" }}</Badge>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex justify-end gap-1">
            <Button variant="ghost" size="sm" aria-label="Edit user" title="Edit user" @click="openEdit(row)"><Icon name="pencil" size="h-4 w-4" /></Button>
            <Button variant="ghost" size="sm" aria-label="Reset password" title="Reset password" @click="openReset(row)"><Icon name="key" size="h-4 w-4" /></Button>
            <!-- Toggle & hapus disembunyikan untuk akun sendiri (backend juga menolak) -->
            <template v-if="row.id !== me">
              <Button variant="ghost" size="sm" :aria-label="row.is_active ? 'Nonaktifkan user' : 'Aktifkan user'" :title="row.is_active ? 'Nonaktifkan user' : 'Aktifkan user'" @click="toggleTarget = row"><Icon name="power" size="h-4 w-4" /></Button>
              <Button variant="ghost" size="sm" aria-label="Hapus user" title="Hapus user (permanen)" @click="deleteTarget = row"><Icon name="trash" size="h-4 w-4" /></Button>
            </template>
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
        <!-- Tautan ke akun legacy. Bukan salinan akun: sandi tetap milik
             Arunika. Yang dipinjam cuma kd_user, karena transaksi menyimpan
             itu dan bukan id user Arunika. -->
        <Select
          v-model="form.kd_user"
          label="Tautan user legacy"
          :options="userxOptions"
          placeholder="Belum ditautkan"
        />
        <Select
          v-model="form.kd_divisi"
          label="Divisi"
          :options="divisiOptions"
          placeholder="Belum dipilih"
        />
        <p v-if="legacyData.conn_error" class="text-xs text-warning-fg">
          {{ legacyData.conn_error }}
        </p>
        <p v-else class="text-xs text-ink-subtle">
          Perlu diisi sebelum akun ini bisa membuat transaksi — nota menyimpan kode
          user legacy, bukan akun Arunika.
        </p>
      </div>
      <template #footer>
        <Button variant="secondary" @click="showForm = false">Batal</Button>
        <Button :loading="form.processing" @click="save">Simpan</Button>
      </template>
    </Modal>

    <!-- Reset password -->
    <Modal :show="!!resetTarget" title="Reset Password" size="sm" @close="resetTarget = null">
      <div class="space-y-3">
        <p class="text-sm text-ink-muted">
          Password baru untuk <strong>{{ resetTarget?.name }}</strong>:
        </p>
        <Input v-model="resetPassword" label="Password Baru" type="password" />
      </div>
      <template #footer>
        <Button variant="secondary" @click="resetTarget = null">Batal</Button>
        <Button :disabled="!resetPassword" @click="confirmReset">Reset</Button>
      </template>
    </Modal>

    <!-- Activate / deactivate -->
    <Modal :show="!!toggleTarget" :title="toggleTarget?.is_active ? 'Nonaktifkan User' : 'Aktifkan User'" size="sm" @close="toggleTarget = null">
      <p class="text-sm text-ink-muted">
        <template v-if="toggleTarget?.is_active">
          Nonaktifkan akun <strong>{{ toggleTarget?.name }}</strong>? User tidak akan bisa login.
        </template>
        <template v-else>
          Aktifkan kembali akun <strong>{{ toggleTarget?.name }}</strong>?
        </template>
      </p>
      <template #footer>
        <Button variant="secondary" @click="toggleTarget = null">Batal</Button>
        <Button :variant="toggleTarget?.is_active ? 'danger' : 'primary'" @click="confirmToggle">
          {{ toggleTarget?.is_active ? "Nonaktifkan" : "Aktifkan" }}
        </Button>
      </template>
    </Modal>

    <!-- Hapus permanen -->
    <Modal :show="!!deleteTarget" title="Hapus User" size="sm" @close="deleteTarget = null">
      <p class="text-sm text-ink-muted">
        Hapus <strong>{{ deleteTarget?.name }}</strong> ({{ deleteTarget?.username }}) secara
        <strong>permanen</strong>? Aksi ini tidak bisa dibatalkan — untuk sekadar memblokir login,
        gunakan Nonaktifkan.
      </p>
      <template #footer>
        <Button variant="secondary" @click="deleteTarget = null">Batal</Button>
        <Button variant="danger" @click="confirmDelete">Hapus Permanen</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>


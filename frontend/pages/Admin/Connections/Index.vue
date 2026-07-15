<script setup>
import { computed, ref } from "vue";
import { useForm, router } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import axios from "axios";
import { useConnectionStore } from "@/stores/connection";
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
  connections: { type: Array, default: () => [] },
  db_types: { type: Array, default: () => ["gudang", "grosir", "retail"] },
});

// Koneksi aktif SESI user ini (per-user, dari shared prop active_connection).
const { active } = storeToRefs(useConnectionStore());

const typeOptions = computed(() =>
  props.db_types.map((t) => ({ value: t, label: t.charAt(0).toUpperCase() + t.slice(1) })),
);

const typeVariant = { gudang: "warning", grosir: "brand", retail: "success" };

// Sumber modal untuk retail: profil grosir/gudang (tak boleh dirinya sendiri).
const costSourceOptions = computed(() =>
  props.connections
    .filter((c) => (c.db_type === "grosir" || c.db_type === "gudang") && c.id !== form.id)
    .map((c) => ({ value: c.id, label: `${c.name} — ${c.db_type === "gudang" ? "Gudang" : "Grosir"}` })),
);

// Replica laporan (CDC): boleh profil tipe apa saja, tak boleh dirinya sendiri.
const reportSourceOptions = computed(() =>
  props.connections
    .filter((c) => c.id !== form.id)
    .map((c) => ({ value: c.id, label: `${c.name} — ${c.db_name} (${c.host})` })),
);

const columns = [
  { key: "name", label: "Nama", sortable: true },
  { key: "db_type", label: "Tipe", sortable: true, align: "center" },
  { key: "host", label: "Host : Port" },
  { key: "db_name", label: "Database", sortable: true },
  { key: "username", label: "User" },
  { key: "is_default", label: "Koneksi", align: "center" },
  { key: "test", label: "Test", align: "center" },
  { key: "indexing", label: "Indexing", align: "center" },
  { key: "actions", label: "", align: "right" },
];

// Test results per connection id: { loading, ok, message }
const testState = ref({});
async function testConnection(conn) {
  testState.value = { ...testState.value, [conn.id]: { loading: true } };
  try {
    const { data } = await axios.post(`/admin-panel/connections/${conn.id}/test`);
    testState.value = { ...testState.value, [conn.id]: { loading: false, ok: data.ok, message: data.message } };
  } catch {
    testState.value = { ...testState.value, [conn.id]: { loading: false, ok: false, message: "Gagal menghubungi server." } };
  }
}

// Index check results per connection id: { loading, ok, results, error }
const indexState = ref({});
const indexDetail = ref(null); // conn row currently showing the results modal
async function checkIndexes(conn) {
  indexState.value = { ...indexState.value, [conn.id]: { loading: true } };
  try {
    const { data } = await axios.post(`/admin-panel/connections/${conn.id}/check-indexes`);
    indexState.value = {
      ...indexState.value,
      [conn.id]: { loading: false, ok: data.ok, results: data.results || [], error: data.error },
    };
  } catch {
    indexState.value = {
      ...indexState.value,
      [conn.id]: { loading: false, ok: false, results: [], error: "Gagal menghubungi server." },
    };
  }
  indexDetail.value = conn;
}
const statusVariant = { exists: "neutral", created: "success", failed: "danger" };
const statusLabel = { exists: "Sudah ada", created: "Dibuat", failed: "Gagal" };

function useConnection(conn) {
  // Pilih koneksi ini untuk SESI user ini (tak mengubah user lain).
  router.post(`/admin-panel/connections/${conn.id}/set-default`, {}, { preserveScroll: true });
}

// --- Create / edit ---
const showForm = ref(false);
const form = useForm({ id: null, name: "", db_type: "grosir", host: "", port: 1433, db_name: "", username: "", password: "", cost_source: null, report_source: null });

function openCreate() {
  // Not form.reset(): Inertia v2 rewrites the form's defaults to the last-submitted
  // values after every successful post, so reset() after an edit would restore that
  // edited row's id instead of a blank form. Assign fields explicitly instead.
  form.id = null;
  form.name = "";
  form.db_type = "grosir";
  form.host = "";
  form.port = 1433;
  form.db_name = "";
  form.username = "";
  form.password = "";
  form.cost_source = null;
  form.report_source = null;
  form.clearErrors();
  showForm.value = true;
}
function openEdit(c) {
  form.id = c.id;
  form.name = c.name;
  form.db_type = c.db_type;
  form.host = c.host;
  form.port = c.port;
  form.db_name = c.db_name;
  form.username = c.username;
  form.password = "";
  form.cost_source = c.cost_source ?? null;
  form.report_source = c.report_source ?? null;
  showForm.value = true;
}
function save() {
  form.post("/admin-panel/connections/save", { onSuccess: () => (showForm.value = false) });
}

const deleteTarget = ref(null);
function confirmDelete() {
  router.delete(`/admin-panel/connections/${deleteTarget.value.id}/delete`, {
    onFinish: () => (deleteTarget.value = null),
  });
}
</script>

<template>
  <AdminLayout title="Koneksi Server">
    <Card>
      <template #header>
        <Button size="sm" @click="openCreate"><Icon name="plus" size="h-4 w-4" /> Tambah Koneksi</Button>
      </template>

      <DataTable :columns="columns" :rows="connections" empty-message="Belum ada profil koneksi.">
        <template #cell-host="{ row }">{{ row.host }}:{{ row.port }}</template>

        <template #cell-db_type="{ value }">
          <Badge :variant="typeVariant[value] || 'neutral'" class="capitalize">{{ value }}</Badge>
        </template>

        <template #cell-is_default="{ row }">
          <div class="flex flex-col items-center gap-1">
            <Badge v-if="row.id === active?.id" variant="success">Aktif (sesi Anda)</Badge>
            <button v-else class="text-xs text-brand-600 hover:underline" @click="useConnection(row)">
              Pakai koneksi ini
            </button>
            <span
              v-if="row.is_default"
              class="text-[10px] text-ink-subtle"
              title="Koneksi default untuk tugas latar (snapshot & sync) saat tidak ada sesi user"
            >
              default sistem
            </span>
          </div>
        </template>

        <template #cell-test="{ row }">
          <div class="flex flex-col items-center justify-center gap-1">
            <div class="flex items-center justify-center gap-2">
              <Button variant="secondary" size="sm" :loading="testState[row.id]?.loading" @click="testConnection(row)">
                Test
              </Button>
              <Badge
                v-if="testState[row.id] && !testState[row.id].loading"
                :variant="testState[row.id].ok ? 'success' : 'danger'"
                :title="testState[row.id].message"
              >
                {{ testState[row.id].ok ? "OK" : "Gagal" }}
              </Badge>
            </div>
            <p
              v-if="testState[row.id] && !testState[row.id].loading && testState[row.id].message"
              class="max-w-xs text-center text-xs"
              :class="testState[row.id].ok ? 'text-ink-subtle' : 'text-danger-fg'"
            >
              {{ testState[row.id].message }}
            </p>
          </div>
        </template>

        <template #cell-indexing="{ row }">
          <div class="flex items-center justify-center gap-2">
            <Button variant="secondary" size="sm" :loading="indexState[row.id]?.loading" @click="checkIndexes(row)">
              Cek Indexing
            </Button>
            <Badge
              v-if="indexState[row.id] && !indexState[row.id].loading"
              :variant="indexState[row.id].ok ? 'success' : 'danger'"
              class="cursor-pointer"
              @click="indexDetail = row"
            >
              {{
                indexState[row.id].error
                  ? "Error"
                  : `${indexState[row.id].results.filter((r) => r.status !== 'failed').length}/${indexState[row.id].results.length} OK`
              }}
            </Badge>
          </div>
        </template>

        <template #cell-actions="{ row }">
          <div class="flex justify-end gap-1">
            <Button variant="ghost" size="sm" aria-label="Edit koneksi" title="Edit koneksi" @click="openEdit(row)"><Icon name="pencil" size="h-4 w-4" /></Button>
            <Button variant="ghost" size="sm" aria-label="Aktif/nonaktif koneksi" title="Aktif/nonaktif koneksi" @click="deleteTarget = row"><Icon name="power" size="h-4 w-4" /></Button>
          </div>
        </template>
      </DataTable>
    </Card>

    <!-- Create / edit -->
    <Modal :show="showForm" :title="form.id ? 'Edit Koneksi' : 'Tambah Koneksi'" @close="showForm = false">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input v-model="form.name" label="Nama Profil" :error="form.errors.name" required />
        <Select v-model="form.db_type" label="Tipe Database" :options="typeOptions" />
        <Input v-model="form.db_name" label="Database" :error="form.errors.db_name" required />
        <Input v-model="form.host" label="Host / IP" :error="form.errors.host" required />
        <Input v-model="form.port" label="Port" type="number" :error="form.errors.port" />
        <Input v-model="form.username" label="Username" :error="form.errors.username" required />
        <Input
          v-model="form.password"
          label="Password"
          type="password"
          :placeholder="form.id ? 'Kosongkan jika tidak diubah' : ''"
          :error="form.errors.password"
        />
        <Select
          v-if="form.db_type === 'retail'"
          v-model="form.cost_source"
          label="Sumber Modal (Grosir/Gudang)"
          :options="costSourceOptions"
          placeholder="Pilih server acuan modal…"
          :error="form.errors.cost_source"
        />
        <Select
          v-model="form.report_source"
          label="Replica Laporan (opsional)"
          :options="reportSourceOptions"
          placeholder="Tidak ada — baca langsung ke server ini"
          :error="form.errors.report_source"
        />
      </div>
      <p v-if="form.db_type === 'retail'" class="mt-3 text-xs text-ink-subtle">
        Server retail wajib punya acuan modal. Margin dihitung dari harga jual server sumber modal.
      </p>
      <p class="mt-3 text-xs text-ink-subtle">
        Replica laporan: kalau diisi, laporan (penjualan/pembelian/dll) baca dari server ini alih-alih server di atas —
        harus sudah disinkron via CDC (<code>manage.py sync_cdc</code>). Kosongkan kalau belum ada replica.
      </p>
      <p class="mt-3 text-xs text-ink-subtle">Password dienkripsi (Fernet) di sisi server sebelum disimpan.</p>
      <template #footer>
        <Button variant="secondary" @click="showForm = false">Batal</Button>
        <Button :loading="form.processing" @click="save">Simpan</Button>
      </template>
    </Modal>

    <!-- Delete confirm -->
    <Modal :show="!!deleteTarget" title="Hapus Koneksi" size="sm" @close="deleteTarget = null">
      <p class="text-sm text-ink-muted">Hapus profil koneksi <strong>{{ deleteTarget?.name }}</strong>?</p>
      <template #footer>
        <Button variant="secondary" @click="deleteTarget = null">Batal</Button>
        <Button variant="danger" @click="confirmDelete">Hapus</Button>
      </template>
    </Modal>

    <!-- Index check results -->
    <Modal :show="!!indexDetail" title="Hasil Cek Indexing" @close="indexDetail = null">
      <p v-if="indexDetail && indexState[indexDetail.id]?.error" class="text-sm text-danger-fg">
        {{ indexState[indexDetail.id].error }}
      </p>
      <ul v-else-if="indexDetail" class="divide-y divide-border-default">
        <li
          v-for="r in indexState[indexDetail.id]?.results"
          :key="r.name"
          class="flex items-center justify-between gap-3 py-2 text-sm"
        >
          <div>
            <p class="font-medium text-ink">{{ r.name }}</p>
            <p v-if="r.detail" class="text-xs text-ink-subtle">{{ r.detail }}</p>
          </div>
          <Badge :variant="statusVariant[r.status] || 'neutral'">{{ statusLabel[r.status] || r.status }}</Badge>
        </li>
      </ul>
      <template #footer>
        <Button variant="secondary" @click="indexDetail = null">Tutup</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>


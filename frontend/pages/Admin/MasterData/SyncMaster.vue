<script setup>
import { computed, reactive, ref } from "vue";
import { router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import Modal from "@/components/ui/Modal.vue";

const props = defineProps({
  profiles: { type: Array, default: () => [] },
  entities: { type: Array, default: () => [] },
  entity: { type: String, default: "m_barang" },
  src: { type: [Number, String], default: null },
  dst: { type: [Number, String], default: null },
  diff: { type: Array, default: () => [] },
  conn_error: { type: String, default: null },
});

// Arah tetap: gudang = sumber data master, tujuan = server aktif/dipilih
// (grosir/retail) — beda dari Sinkronisasi Harga yang punya 2 mode simetris.
const typeName = { gudang: "Gudang", grosir: "Grosir", retail: "Toko Retail" };

const pick = reactive({ entity: props.entity, src: props.src, dst: props.dst });

const srcOptions = computed(() =>
  props.profiles
    .filter((p) => p.db_type === "gudang")
    .map((p) => ({ value: p.id, label: `${p.name} — ${typeName[p.db_type] || p.db_type}` })),
);
const dstOptions = computed(() =>
  props.profiles
    .filter((p) => p.db_type !== "gudang" && String(p.id) !== String(pick.src))
    .map((p) => ({ value: p.id, label: `${p.name} — ${typeName[p.db_type] || p.db_type}` })),
);

const pkCol = computed(() => ({ m_barang: "kd_barang", m_customer: "kd_customer", m_supplier: "kd_supplier" }[pick.entity] || "kd_barang"));
const pkLabel = computed(() => ({ m_barang: "Kode Barang", m_customer: "Kode Pelanggan", m_supplier: "Kode Supplier" }[pick.entity] || "Kode"));

// row-key harus string; diff unik per kode entitas
const rows = computed(() => props.diff.map((r) => ({ ...r, _key: r[pkCol.value] })));

function onEntityChange() {
  pick.src = null;
  pick.dst = null;
}

function bandingkan() {
  router.get("/admin-panel/master/sync-master", { ...pick }, { preserveState: true, preserveScroll: true });
}

// --- selection ---
const selected = ref(new Set());
const allSelected = computed(() => rows.value.length > 0 && selected.value.size === rows.value.length);
function toggle(r) {
  const s = new Set(selected.value);
  s.has(r._key) ? s.delete(r._key) : s.add(r._key);
  selected.value = s;
}
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(rows.value.map((r) => r._key));
}

const syncing = ref(false);
const showConfirm = ref(false);
const dstName = computed(() => {
  const p = props.profiles.find((x) => String(x.id) === String(pick.dst));
  return p ? p.name : "server tujuan";
});
// Aksi menulis lintas server → minta konfirmasi dulu (pola sama dengan modal delete).
function doSync() {
  const keys = rows.value
    .filter((r) => selected.value.has(r._key))
    .map((r) => ({ [pkCol.value]: r[pkCol.value] }));
  if (!keys.length) { showConfirm.value = false; return; }
  syncing.value = true;
  router.post(
    "/admin-panel/master/sync-master/apply",
    { entity: pick.entity, src: pick.src, dst: pick.dst, keys },
    { preserveScroll: true, onFinish: () => { syncing.value = false; selected.value = new Set(); showConfirm.value = false; } },
  );
}

const columns = computed(() => [
  { key: "sel", label: "", align: "center" },
  { key: pkCol.value, label: pkLabel.value, sortable: true },
  { key: "label", label: "Nama", sortable: true },
  { key: "fields_changed", label: "Kolom Berbeda" },
  { key: "flag", label: "", align: "center" },
]);
</script>

<template>
  <AdminLayout title="Sinkronisasi Master Data">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />

    <Card class="mb-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-4 sm:items-end">
        <Select v-model="pick.entity" label="Entitas" :options="entities" @update:modelValue="onEntityChange" />
        <Select v-model="pick.src" label="Server Sumber (Gudang)" :options="srcOptions" placeholder="Pilih sumber…" />
        <Select v-model="pick.dst" label="Server Tujuan" :options="dstOptions" placeholder="Pilih tujuan…" />
        <Button :disabled="!pick.src || !pick.dst" @click="bandingkan">Bandingkan</Button>
      </div>
    </Card>

    <div v-if="diff.length" class="mb-3 flex items-center gap-3">
      <label class="flex items-center gap-2 text-sm text-ink-muted">
        <input type="checkbox" :checked="allSelected" @change="toggleAll" /> Pilih semua
      </label>
      <p class="text-sm text-ink-muted">{{ diff.length.toLocaleString("id-ID") }} baris berbeda</p>
      <p class="text-sm text-ink-subtle">{{ selected.size }} dipilih</p>
      <div class="ml-auto">
        <Button :loading="syncing" :disabled="selected.size === 0" @click="showConfirm = true">
          Sinkronkan Terpilih
        </Button>
      </div>
    </div>

    <Modal :show="showConfirm" title="Konfirmasi Sinkronisasi" size="sm" @close="showConfirm = false">
      <p class="text-sm text-ink">
        Tulis <strong>{{ selected.size }}</strong> perubahan master ke
        <strong>{{ dstName }}</strong>? Aksi ini menimpa data di server tujuan dan tidak bisa dibatalkan.
      </p>
      <template #footer>
        <Button variant="ghost" @click="showConfirm = false">Batal</Button>
        <Button variant="danger" :loading="syncing" @click="doSync">Ya, Sinkronkan</Button>
      </template>
    </Modal>

    <DataTable
      v-if="diff.length || (pick.src && pick.dst)"
      :columns="columns"
      :rows="rows"
      row-key="_key"
      :per-page="30"
      empty-message="Semua data sudah sama."
    >
      <template #cell-sel="{ row }">
        <input type="checkbox" :checked="selected.has(row._key)" @change="toggle(row)" />
      </template>
      <template #cell-fields_changed="{ value }">{{ value && value.length ? value.join(", ") : "—" }}</template>
      <template #cell-flag="{ row }">
        <Badge :variant="row.ada_di_dst ? 'warning' : 'brand'">{{ row.ada_di_dst ? "Data beda" : "Belum ada" }}</Badge>
      </template>
    </DataTable>

    <Card v-else>
      <p class="py-8 text-center text-sm text-ink-muted">Pilih entitas & server, lalu klik "Bandingkan".</p>
    </Card>
  </AdminLayout>
</template>

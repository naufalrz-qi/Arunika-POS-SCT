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
  mode: { type: String, default: "gudang_grosir" },
  src: { type: [Number, String], default: null },
  dst: { type: [Number, String], default: null },
  diff: { type: Array, default: () => [] },
  conn_error: { type: String, default: null },
});

const MODES = {
  gudang_grosir: { src: "gudang", dst: "grosir", withMargin: false },
  retail_retail: { src: "retail", dst: "retail", withMargin: true },
};

const typeName = { gudang: "Gudang", grosir: "Grosir", retail: "Toko Retail" };

const modeOptions = [
  { value: "gudang_grosir", label: "Dari Gudang ke Grosir (harga jual)" },
  { value: "retail_retail", label: "Antar Toko Retail (harga jual + margin)" },
];

const pick = reactive({ mode: props.mode, src: props.src, dst: props.dst });

const srcOptions = computed(() =>
  props.profiles
    .filter((p) => p.db_type === MODES[pick.mode].src)
    .map((p) => ({ value: p.id, label: `${p.name} — ${typeName[p.db_type] || p.db_type}` })),
);
const dstOptions = computed(() =>
  props.profiles
    .filter((p) => p.db_type === MODES[pick.mode].dst && String(p.id) !== String(pick.src))
    .map((p) => ({ value: p.id, label: `${p.name} — ${typeName[p.db_type] || p.db_type}` })),
);

// row-key harus string; diff unik per (kd_barang, kd_satuan)
const rows = computed(() => props.diff.map((r) => ({ ...r, _key: `${r.kd_barang}||${r.kd_satuan}` })));

function onModeChange() {
  pick.src = null;
  pick.dst = null;
}

function bandingkan() {
  router.get("/admin-panel/master/sync-harga", { ...pick }, { preserveState: true, preserveScroll: true });
}

const rupiah = (n) =>
  n == null ? "—" : new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);

// --- selection ---
const selected = ref(new Set());
const keyOf = (r) => `${r.kd_barang}||${r.kd_satuan}`;
const allSelected = computed(() => rows.value.length > 0 && selected.value.size === rows.value.length);
function toggle(r) {
  const k = keyOf(r);
  const s = new Set(selected.value);
  s.has(k) ? s.delete(k) : s.add(k);
  selected.value = s;
}
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(rows.value.map(keyOf));
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
    .filter((r) => selected.value.has(keyOf(r)))
    .map((r) => ({ kd_barang: r.kd_barang, kd_satuan: r.kd_satuan }));
  if (!keys.length) { showConfirm.value = false; return; }
  syncing.value = true;
  router.post(
    "/admin-panel/master/sync-harga/apply",
    { mode: pick.mode, src: pick.src, dst: pick.dst, keys, with_margin: MODES[pick.mode].withMargin },
    { preserveScroll: true, onFinish: () => { syncing.value = false; selected.value = new Set(); showConfirm.value = false; } },
  );
}

const columns = [
  { key: "sel", label: "", align: "center" },
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "nama", label: "Barang", sortable: true },
  { key: "kd_satuan", label: "Satuan", align: "center" },
  { key: "harga_src", label: "Harga Sumber", align: "right" },
  { key: "harga_dst", label: "Harga Tujuan", align: "right" },
  { key: "flag", label: "", align: "center" },
];
</script>

<template>
  <AdminLayout title="Sinkronisasi Harga">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />

    <Card class="mb-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-4 sm:items-end">
        <Select v-model="pick.mode" label="Mode" :options="modeOptions" @update:modelValue="onModeChange" />
        <Select v-model="pick.src" label="Server Sumber" :options="srcOptions" placeholder="Pilih sumber…" />
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

    <Modal :show="showConfirm" title="Konfirmasi Sinkronisasi Harga" size="sm" @close="showConfirm = false">
      <p class="text-sm text-ink">
        Tulis <strong>{{ selected.size }}</strong> perubahan harga ke
        <strong>{{ dstName }}</strong>? Aksi ini menimpa harga di server tujuan dan tidak bisa dibatalkan.
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
      empty-message="Semua harga sudah sama."
    >
      <template #cell-sel="{ row }">
        <input type="checkbox" :checked="selected.has(keyOf(row))" @change="toggle(row)" />
      </template>
      <template #cell-harga_src="{ value }">{{ rupiah(value) }}</template>
      <template #cell-harga_dst="{ value }">{{ rupiah(value) }}</template>
      <template #cell-flag="{ row }">
        <Badge :variant="row.ada_di_dst ? 'warning' : 'brand'">{{ row.ada_di_dst ? "Harga beda" : "Belum ada" }}</Badge>
      </template>
    </DataTable>

    <Card v-else>
      <p class="py-8 text-center text-sm text-ink-muted">Pilih mode & server, lalu klik "Bandingkan".</p>
    </Card>
  </AdminLayout>
</template>


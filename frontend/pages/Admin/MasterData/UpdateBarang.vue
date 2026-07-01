<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useForm, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import Modal from "@/components/ui/Modal.vue";

const props = defineProps({
  active: { type: Object, default: null },
  profile_type: { type: String, default: null },
  items: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
  conn_error: { type: String, default: null },
});

const isRetail = computed(() => props.profile_type === "retail");

const typeName = { gudang: "Gudang", grosir: "Grosir", retail: "Toko Retail" };

const pick = reactive({
  profile: props.active?.id ?? null,
  search: props.filters.search || "",
  status: "", // filter by status
  sort: "nama", // sort: nama, kd_barang, price
});

function reload() {
  router.get("/admin-panel/master/update-barang", { search: pick.search }, { preserveState: true, preserveScroll: true });
}

const num = (n) => (n ?? 0).toLocaleString("id-ID");
const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const statusOptions = [
  { value: "1", label: "Aktif" },
  { value: "0", label: "Non-aktif" },
  { value: "2", label: "Tidak dijual (sembunyikan)" },
];
const statusLabel = (s) => ({ 0: "Non-aktif", 1: "Aktif", 2: "Tidak dijual" }[s] ?? s);
const statusVariant = (s) => ({ 0: "danger", 1: "success", 2: "warning" }[s] ?? "neutral");

// Nama tabel teknis -> label yang dimengerti orang awam.
const statusScopes = [
  { key: "m_barang", label: "Produk (keseluruhan)", hint: "Aktif/nonaktifkan barang di semua toko & satuan." },
  { key: "m_barang_divisi", label: "Ketersediaan per Divisi/Toko", hint: "Status barang di tiap divisi." },
  { key: "m_barang_satuan", label: "Ketersediaan per Satuan", hint: "Status tiap satuan jual (pcs, dus, dll)." },
];

const page = ref(1);
const perPage = 20;

// Filter & sort items
const filtered = computed(() => {
  let result = props.items;

  // Filter by status
  if (pick.status) {
    result = result.filter((i) => i.status === pick.status);
  }

  // Sort
  const sorted = [...result];
  switch (pick.sort) {
    case "kd_barang":
      sorted.sort((a, b) => a.kd_barang.localeCompare(b.kd_barang));
      break;
    case "status":
      sorted.sort((a, b) => a.status.localeCompare(b.status));
      break;
    case "price":
      sorted.sort((a, b) => {
        const pa = a.satuan[0]?.harga_jual ?? 0;
        const pb = b.satuan[0]?.harga_jual ?? 0;
        return pb - pa; // descending
      });
      break;
    case "nama":
    default:
      sorted.sort((a, b) => a.nama.localeCompare(b.nama, "id"));
  }
  return sorted;
});

const pagedItems = computed(() => {
  const start = (page.value - 1) * perPage;
  return filtered.value.slice(start, start + perPage);
});

watch(() => props.items, () => {
  page.value = 1;
});

// --- Edit modal ---
const editing = ref(null);
const priceForm = useForm({ profile: null, kd_barang: "", prices: {} });
const statusSel = reactive({ m_barang: "1", m_barang_divisi: "1", m_barang_satuan: "1" });

function openEdit(item) {
  editing.value = item;
  priceForm.profile = pick.profile;
  priceForm.kd_barang = item.kd_barang;
  priceForm.prices = Object.fromEntries(item.satuan.map((u) => [u.kd_satuan, u.harga_jual]));
  statusSel.m_barang = item.status || "1";
  statusSel.m_barang_divisi = item.divisi[0]?.status || "1";
  statusSel.m_barang_satuan = item.satuan[0]?.status || "1";
}

const liveMargin = (unit) => {
  const harga = Number(priceForm.prices[unit.kd_satuan]) || 0;
  const modal = unit.modal || 0;
  return modal > 0 ? ((harga - modal) / modal) * 100 : 0;
};

function saveHarga() {
  priceForm.post("/admin-panel/master/update-barang/harga", {
    preserveScroll: true,
    onSuccess: () => (editing.value = null),
  });
}

function saveStatus(table) {
  router.post(
    "/admin-panel/master/update-barang/status",
    { profile: pick.profile, kd_barang: editing.value.kd_barang, table, status: statusSel[table] },
    { preserveScroll: true },
  );
}
</script>

<template>
  <AdminLayout title="Update Barang">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />

    <Card class="mb-4">
      <div class="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span class="text-ink-muted">Database aktif:</span>
        <span class="font-semibold text-ink">{{ active?.name || "—" }}</span>
        <Badge v-if="active" variant="brand">{{ typeName[active.db_type] || active.db_type }}</Badge>
        <Badge v-if="isRetail" variant="success">Margin dihitung otomatis</Badge>
        <span class="text-xs text-ink-subtle">Ganti database lewat menu Koneksi di kanan atas.</span>
      </div>
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="flex-1">
          <Input v-model="pick.search" label="Cari Barang" placeholder="kode / nama…" @keyup.enter="reload" />
        </div>
        <Select
          v-model="pick.status"
          label="Status"
          :options="[
            { value: '', label: 'Semua' },
            { value: '1', label: 'Aktif' },
            { value: '0', label: 'Non-aktif' },
            { value: '2', label: 'Tidak dijual' },
          ]"
          class="sm:w-40"
        />
        <Select
          v-model="pick.sort"
          label="Urutkan"
          :options="[
            { value: 'nama', label: 'Nama A-Z' },
            { value: 'kd_barang', label: 'Kode' },
            { value: 'status', label: 'Status' },
            { value: 'price', label: 'Harga (tinggi)' },
          ]"
          class="sm:w-40"
        />
        <Button variant="primary" @click="reload">Cari</Button>
        <span class="text-sm text-ink-muted whitespace-nowrap">{{ filtered.length }} barang</span>
      </div>
    </Card>

    <DataTable
      :columns="[
        { key: 'kd_barang', label: 'Kode', sortable: true },
        { key: 'nama', label: 'Nama Barang', sortable: true },
        { key: 'keterangan', label: 'Keterangan' },
        { key: 'harga', label: 'Harga', align: 'right' },
        ...(isRetail ? [{ key: 'margin', label: 'Margin', align: 'right' }] : []),
        { key: 'status', label: 'Status', align: 'center' },
        { key: 'aksi', label: 'Aksi', align: 'center' },
      ]"
      :rows="pagedItems"
      rowKey="kd_barang"
      :perPage="perPage"
      :total="filtered.length"
      emptyMessage="Tidak ada barang."
      @update:page="page = $event"
    >
      <template #cell-harga="{ row }">
        <span class="font-medium tabular-nums text-brand-600">
          {{ row.satuan.length > 0 ? rupiah(row.satuan[0].harga_jual) : "—" }}
        </span>
      </template>

      <template v-if="isRetail" #cell-margin="{ row }">
        <span
          :class="[
            'font-medium',
            row.satuan.length > 0 && row.satuan[0].modal
              ? ((row.satuan[0].harga_jual - row.satuan[0].modal) / row.satuan[0].modal) * 100 < 0
                ? 'text-danger-600'
                : 'text-success-600'
              : 'text-ink-muted',
          ]"
        >
          {{
            row.satuan.length > 0 && row.satuan[0].modal
              ? (((row.satuan[0].harga_jual - row.satuan[0].modal) / row.satuan[0].modal) * 100).toFixed(1) + "%"
              : "—"
          }}
        </span>
      </template>

      <template #cell-status="{ row }">
        <Badge :variant="statusVariant(row.status)">{{ statusLabel(row.status) }}</Badge>
      </template>

      <template #cell-aksi="{ row }">
        <Button size="sm" variant="secondary" @click="openEdit(row)">Edit</Button>
      </template>
    </DataTable>

    <Modal :show="!!editing" :title="editing ? `${editing.kd_barang} — ${editing.nama}` : ''" size="md" @close="editing = null">
      <div v-if="editing" class="max-h-[70vh] space-y-2 overflow-y-auto scroll-slim">
        <!-- Harga per satuan -->
        <div>
          <h4 class="mb-1 text-xs font-semibold text-ink">Harga Jual per Satuan</h4>
          <div class="space-y-1.5">
            <div
              v-for="u in editing.satuan"
              :key="u.kd_satuan"
              class="flex flex-col gap-1.5 rounded border-l-4 border-l-brand-600 bg-surface-2 p-2 sm:flex-row sm:items-end sm:gap-1.5"
            >
              <div class="min-w-max text-xs font-medium text-ink">
                {{ u.satuan || u.kd_satuan }}
                <span class="text-ink-muted">×{{ num(u.jumlah) }}</span>
              </div>
              <Input v-model="priceForm.prices[u.kd_satuan]" type="number" label="Harga" size="sm" class="sm:w-32" />

              <!-- Margin untuk grosir (locked) -->
              <div v-if="!isRetail" class="text-xs">
                <p class="text-[0.65rem] text-ink-muted">Margin</p>
                <input
                  type="text"
                  disabled
                  :value="u.margin.toFixed(2) + '%'"
                  class="rounded border border-border-default bg-surface-3 px-1.5 py-1 text-xs text-ink-muted cursor-not-allowed"
                />
              </div>

              <!-- Margin untuk retail (editable display) -->
              <template v-if="isRetail">
                <div class="text-xs">
                  <p class="text-[0.65rem] text-ink-muted">Modal</p>
                  <p class="font-medium text-ink text-xs">{{ rupiah(u.modal) }}</p>
                </div>
                <div class="text-xs">
                  <p class="text-[0.65rem] text-ink-muted">Margin</p>
                  <p :class="['font-semibold text-xs', liveMargin(u) < 0 ? 'text-danger-600' : 'text-success-700']">
                    {{ liveMargin(u).toFixed(2) }}%
                  </p>
                </div>
              </template>

              <!-- Save button aligned -->
              <Button
                v-if="editing.satuan.indexOf(u) === editing.satuan.length - 1"
                variant="success"
                size="sm"
                :loading="priceForm.processing"
                @click="saveHarga"
              >
                Simpan
              </Button>
            </div>
          </div>
        </div>

        <!-- Status Ketersediaan -->
        <div>
          <h4 class="mb-1 text-xs font-semibold text-ink">Status Ketersediaan</h4>
          <div class="grid gap-1.5 sm:grid-cols-3">
            <div class="rounded border border-border-default p-2">
              <Select v-model="statusSel.m_barang" label="Barang" :options="statusOptions" />
              <Button variant="danger" size="sm" class="mt-1 w-full" @click="saveStatus('m_barang')">Simpan</Button>
            </div>
            <div class="rounded border border-border-default p-2">
              <Select v-model="statusSel.m_barang_divisi" label="Divisi" :options="statusOptions" />
              <Button variant="danger" size="sm" class="mt-1 w-full" @click="saveStatus('m_barang_divisi')">Simpan</Button>
            </div>
            <div class="rounded border border-border-default p-2">
              <Select v-model="statusSel.m_barang_satuan" label="Satuan" :options="statusOptions" />
              <Button variant="danger" size="sm" class="mt-1 w-full" @click="saveStatus('m_barang_satuan')">Simpan</Button>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <Button variant="ghost" @click="editing = null">Tutup</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>


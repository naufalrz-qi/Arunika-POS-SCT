<script setup>
import { computed, reactive, ref } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import BarangEditModal from "@/components/master/BarangEditModal.vue";
import { useUiStore } from "@/stores/ui.js";

const props = defineProps({
  data: { type: Object, default: null },
  active: { type: Object, default: null },
  profile_type: { type: String, default: null },
  saran_profile: { type: Object, default: null },
  profiles: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
  last_run: { type: Object, default: null },
});

const ui = useUiStore();

const rows = computed(() => props.data?.rows || []);
const saran = computed(() => props.data?.saran || []);

const isRetail = computed(() => props.profile_type === "retail");

const tab = ref("perubahan"); // perubahan | saran

const pick = reactive({
  kd_barang: props.filters.kd_barang || "",
  date_from: props.filters.date_from || "",
  date_to: props.filters.date_to || "",
  profile: props.filters.profile || "",
  scope: props.filters.scope || "hari",
});

const BASE_URL = "/admin-panel/master/pergerakan-harga";

// URL halaman ini + filter aktif — dipakai `redirect_to` supaya simpan dari
// modal edit / terapkan saran kembali ke halaman & filter yang sama.
const currentUrl = computed(() => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(pick)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `${BASE_URL}?${s}` : BASE_URL;
});

function tampilkan() {
  router.get(BASE_URL, { ...pick }, { preserveState: true, preserveScroll: true });
}

function setScope(scope) {
  pick.scope = scope;
  if (scope === "hari") {
    pick.date_from = "";
    pick.date_to = "";
  }
  tampilkan();
}

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const changeColumns = [
  { key: "detected_at", label: "Terdeteksi", sortable: true },
  { key: "kd_barang", label: "Kode Barang", sortable: true },
  { key: "nama_barang", label: "Nama Barang", sortable: true },
  { key: "kd_satuan", label: "Satuan" },
  { key: "harga_lama", label: "Harga Lama", align: "right" },
  { key: "harga_baru", label: "Harga Baru", align: "right" },
  { key: "selisih", label: "Selisih", align: "right" },
  { key: "profile_name", label: "Koneksi" },
  { key: "aksi", label: "", align: "right" },
];

const saranColumns = [
  { key: "kd_barang", label: "Kode Barang", sortable: true },
  { key: "nama", label: "Nama Barang", sortable: true },
  { key: "keterangan", label: "Keterangan" },
  { key: "satuan", label: "Satuan" },
  { key: "harga_lama", label: "Harga Sekarang", align: "right", sortable: true },
  { key: "harga_baru", label: "Saran", align: "right", sortable: true },
  { key: "selisih", label: "Selisih", align: "right", sortable: true },
  { key: "aksi", label: "", align: "right" },
];

// Edit & terapkan hanya untuk koneksi AKTIF (endpoint update menulis ke
// koneksi aktif server-side) — baris dari koneksi lain read-only.
const canEditChange = (row) => !!props.active && row.profile_id === props.active.id;
const saranIsActive = computed(() => !!props.active && !!props.saran_profile && props.saran_profile.id === props.active.id);

// --- Modal edit (sama persis dengan Update Barang) ---
const editItem = ref(null);
const editLoadingKd = ref(null);

async function openEdit(kd_barang) {
  editLoadingKd.value = kd_barang;
  try {
    const { data: res } = await axios.get("/admin-panel/master/update-barang/detail", {
      params: { kd_barang },
    });
    if (res.item) editItem.value = res.item;
    else ui.pushToast(res.error || "Barang tidak ditemukan.", "error");
  } catch {
    ui.pushToast("Gagal memuat detail barang.", "error");
  } finally {
    editLoadingKd.value = null;
  }
}

</script>

<template>
  <AdminLayout title="Pergerakan Harga">
    <p v-if="last_run" class="mb-3 text-xs text-ink-subtle">
      Snapshot terakhir: <span class="font-semibold text-ink-muted">{{ last_run.ran_at }}</span>
      · {{ last_run.profile_name }} · {{ last_run.changes }} perubahan dari {{ last_run.total }} SKU
    </p>
    <p v-else class="mb-3 text-xs text-ink-subtle">
      Belum ada snapshot. Jalankan otomatis saat server hidup, atau manual: <code class="rounded bg-surface-3 px-1">manage.py snapshot_harga</code>.
    </p>

    <!-- Tab: perubahan harga vs saran harga -->
    <div class="mb-4 flex gap-1 rounded-card border border-border-default bg-surface-2 p-1 w-fit">
      <button
        type="button"
        :class="[
          'rounded px-3 py-1.5 text-sm font-semibold transition',
          tab === 'perubahan' ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink',
        ]"
        @click="tab = 'perubahan'"
      >
        Perubahan Harga<span v-if="data" class="ml-1.5 rounded-full bg-surface-3 px-1.5 text-[10px] font-bold text-ink-muted">{{ rows.length }}</span>
      </button>
      <button
        type="button"
        :class="[
          'rounded px-3 py-1.5 text-sm font-semibold transition',
          tab === 'saran' ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink',
        ]"
        @click="tab = 'saran'"
      >
        Saran Harga<span v-if="data" class="ml-1.5 rounded-full bg-rx-yellow px-1.5 text-[10px] font-bold text-ink">{{ saran.length }}</span>
      </button>
    </div>

    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil pergerakan harga…" /></template>

      <!-- Tab 1: perubahan harga (snapshot harian) -->
      <ReportView
        v-if="tab === 'perubahan'"
        title="Perubahan Harga"
        subtitle="Perubahan harga yang terdeteksi snapshot harian, termasuk yang diubah langsung di POS."
        :columns="changeColumns"
        :rows="rows"
        row-key="id"
        :search-keys="['kd_barang', 'nama_barang', 'profile_name']"
        export-name="pergerakan-harga"
        sheet-name="Perubahan Harga"
        :empty-message="pick.scope === 'hari' && !pick.date_from && !pick.date_to
          ? 'Belum ada perubahan harga terdeteksi hari ini. Pilih “Semua Riwayat” untuk melihat keseluruhan.'
          : 'Belum ada perubahan harga terdeteksi.'"
      >
        <template #filters>
          <div class="mb-3 flex gap-1.5">
            <Button :variant="pick.scope === 'hari' && !pick.date_from && !pick.date_to ? 'primary' : 'secondary'" size="sm" @click="setScope('hari')">
              Hari Ini
            </Button>
            <Button :variant="pick.scope === 'semua' || pick.date_from || pick.date_to ? 'primary' : 'secondary'" size="sm" @click="setScope('semua')">
              Semua Riwayat
            </Button>
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Input v-model="pick.kd_barang" label="Kode Barang" placeholder="mis. TOP5026" @keyup.enter="tampilkan" />
            <Input v-model="pick.date_from" type="date" label="Dari Tanggal" />
            <Input v-model="pick.date_to" type="date" label="Sampai Tanggal" />
            <Select
              v-model="pick.profile"
              label="Koneksi"
              :options="[{ value: '', label: 'Semua' }, ...profiles]"
            />
          </div>
          <div class="mt-3 flex justify-end">
            <Button variant="primary" @click="tampilkan">Tampilkan</Button>
          </div>
        </template>

        <template #cell-harga_lama="{ value }">
          <span class="text-ink-muted line-through decoration-danger-500/60">{{ rupiah(value) }}</span>
        </template>
        <template #cell-harga_baru="{ value }">
          <span class="font-semibold text-ink">{{ rupiah(value) }}</span>
        </template>
        <template #cell-selisih="{ value }">
          <span :class="value < 0 ? 'text-danger-600' : 'text-success-700'">
            {{ value > 0 ? "+" : "" }}{{ rupiah(value) }}
          </span>
        </template>
        <template #cell-aksi="{ row }">
          <Button
            size="sm"
            variant="yellow-outline"
            :disabled="!canEditChange(row)"
            :loading="editLoadingKd === row.kd_barang"
            :title="canEditChange(row) ? 'Edit harga & status barang' : 'Hanya untuk koneksi aktif — aktifkan koneksi ini di navbar'"
            @click="openEdit(row.kd_barang)"
          >
            Edit
          </Button>
        </template>
      </ReportView>

      <!-- Tab 2: saran harga menyeluruh dari server terpilih -->
      <div v-else>
        <Banner v-if="data?.saran_error" variant="warning" :message="data.saran_error" class="mb-4" />
        <Banner
          v-else-if="saran_profile && !saranIsActive"
          variant="info"
          :message="`Saran ditampilkan dari server ${saran_profile.name}. Aktifkan koneksi tersebut di navbar untuk menerapkan atau mengedit.`"
          class="mb-4"
        />

        <ReportView
          title="Saran Harga"
          :subtitle="`Seluruh katalog ${saran_profile?.name || '—'} yang harga jualnya beda dari nominal di kolom keterangan (mis. ECER 3.450.000).`"
          :columns="saranColumns"
          :rows="saran"
          row-key="kd_barang"
          :search-keys="['kd_barang', 'nama', 'keterangan']"
          export-name="saran-harga"
          sheet-name="Saran Harga"
          empty-message="Semua harga sudah sesuai nominal di keterangan — tidak ada saran perubahan."
        >
          <template #filters>
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Select
                v-model="pick.profile"
                label="Server Sumber Saran"
                :options="[{ value: '', label: `Koneksi aktif (${active?.name || '—'})` }, ...profiles]"
              />
              <div class="flex items-end">
                <Button variant="primary" @click="tampilkan">Tampilkan</Button>
              </div>
            </div>
          </template>

          <template #cell-harga_lama="{ value }">
            <span class="text-ink-muted tabular-nums">{{ rupiah(value) }}</span>
          </template>
          <template #cell-harga_baru="{ value }">
            <span class="font-semibold text-ink tabular-nums">{{ rupiah(value) }}</span>
          </template>
          <template #cell-selisih="{ value }">
            <span :class="['tabular-nums', value < 0 ? 'text-danger-600' : 'text-success-700']">
              {{ value > 0 ? "+" : "" }}{{ rupiah(value) }}
            </span>
          </template>
          <template #cell-aksi="{ row }">
            <Button
              size="sm"
              variant="yellow-outline"
              :disabled="!saranIsActive"
              :loading="editLoadingKd === row.kd_barang"
              :title="saranIsActive ? 'Edit harga & status barang' : 'Hanya untuk koneksi aktif'"
              @click="openEdit(row.kd_barang)"
            >
              Edit
            </Button>
          </template>
        </ReportView>
      </div>
    </Deferred>

    <!-- Modal edit — komponen yang sama persis dengan Update Barang -->
    <BarangEditModal :item="editItem" :is-retail="isRetail" :redirect-to="currentUrl" @close="editItem = null" />
  </AdminLayout>
</template>

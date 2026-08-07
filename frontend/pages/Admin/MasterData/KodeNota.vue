<script setup>
import { computed, ref } from "vue";
import { useForm } from "@inertiajs/vue3";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import Modal from "@/components/ui/Modal.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({ kode: { type: Object, default: null } });

const data = computed(() => props.kode || {});
const rows = computed(() => data.value.rows || []);

const columns = [
  { key: "kd_divisi", label: "Kode Divisi" },
  { key: "nama", label: "Divisi" },
  { key: "kepala_nota", label: "Kode Nota" },
  { key: "contoh", label: "Contoh nomor berikutnya" },
  { key: "aksi", label: "", align: "right" },
];

// Contoh dihitung di layar supaya perubahan terasa akibatnya sebelum disimpan.
const hariIni = new Date();
const yymmdd =
  String(hariIni.getFullYear() % 100).padStart(2, "0") +
  String(hariIni.getMonth() + 1).padStart(2, "0") +
  String(hariIni.getDate()).padStart(2, "0");

const barisTampil = computed(() =>
  rows.value.map((r) => ({
    ...r,
    contoh: r.kepala_nota ? `${r.kepala_nota}${yymmdd}0001` : "— belum diisi —",
  })),
);

const target = ref(null);
const form = useForm({ kd_divisi: "", kepala_nota: "" });

function openEdit(r) {
  target.value = r;
  form.kd_divisi = r.kd_divisi;
  form.kepala_nota = r.kepala_nota || "";
  form.clearErrors();
}
function simpan() {
  form.post("/admin-panel/master/kode-nota/save", {
    preserveScroll: true,
    onSuccess: () => (target.value = null),
  });
}

const pratinjau = computed(() =>
  form.kepala_nota ? `${form.kepala_nota.toUpperCase()}${yymmdd}0001` : "—",
);
</script>

<template>
  <AdminLayout title="Kelola Kode Nota">
    <Banner
      variant="warning"
      class="mb-4"
      message="Kode ini jadi awalan SETIAP nomor nota yang dibuat sesudahnya. Salah isi berarti nota tercatat atas nama cabang lain, dan nota yang sudah tertulis tidak bisa ditarik lagi."
    />

    <Deferred data="kode">
      <template #fallback>
        <LoadingCard message="Mengambil kode nota…" />
      </template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" class="mb-4" />

      <Card>
        <DataTable :rows="barisTampil" :columns="columns">
          <template #cell-kepala_nota="{ row }">
            <Badge v-if="row.kepala_nota">{{ row.kepala_nota }}</Badge>
            <span v-else class="text-ink-subtle">belum diisi</span>
          </template>
          <template #cell-aksi="{ row }">
            <Button size="sm" variant="secondary" @click="openEdit(row)">Ubah</Button>
          </template>
        </DataTable>
      </Card>
    </Deferred>

    <Modal :open="Boolean(target)" title="Ubah kode nota" @close="target = null">
      <div class="space-y-3">
        <p class="text-sm text-ink-subtle">
          Divisi <strong>{{ target?.nama }}</strong> ({{ target?.kd_divisi }})
        </p>
        <Input
          v-model="form.kepala_nota"
          label="Kode nota"
          placeholder="mis. SC"
          maxlength="5"
          :error="form.errors.kepala_nota"
        />
        <p class="text-sm">
          Nomor berikutnya jadi: <strong>{{ pratinjau }}</strong>
        </p>
        <p class="text-xs text-ink-subtle">
          Huruf dan angka saja, 1–5 karakter. Nota yang sudah ada tidak berubah —
          urutan hariannya dihitung per kode, jadi mengganti kode di tengah hari
          memulai urutan baru dari 0001 dan deretan lama tetap utuh.
        </p>
      </div>
      <template #footer>
        <Button variant="secondary" @click="target = null">Batal</Button>
        <Button :loading="form.processing" @click="simpan">Simpan</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>

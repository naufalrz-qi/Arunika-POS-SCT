<!-- frontend/pages/Admin/MasterData/KelolaInformasiPerusahaan.vue -->
<script setup>
import { computed, watch } from "vue";
import { useForm, Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Banner from "@/components/ui/Banner.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  info: { type: Object, default: null },
});

const data = computed(() => props.info?.info || {});

const form = useForm({
  perusahaan: "",
  alamat: "",
  kota: "",
  telp: "",
  hp: "",
  email: "",
  website: "",
  nama_kontak: "",
});

watch(
  data,
  (val) => {
    if (val && Object.keys(val).length > 0) {
      form.perusahaan = val.perusahaan || "";
      form.alamat = val.alamat || "";
      form.kota = val.kota || "";
      form.telp = val.telp || "";
      form.hp = val.hp || "";
      form.email = val.email || "";
      form.website = val.website || "";
      form.nama_kontak = val.nama_kontak || "";
    }
  },
  { immediate: true },
);

function simpan() {
  form.post("/admin-panel/master-data/informasi-perusahaan", {
    preserveScroll: true,
  });
}
</script>

<template>
  <AdminLayout title="Kelola Informasi Perusahaan">
    <Deferred data="info">
      <template #fallback><LoadingCard message="Memuat informasi perusahaan..." /></template>

      <Banner v-if="props.info?.conn_error" variant="warning" :message="props.info.conn_error" class="mb-4" />

      <Card class="max-w-2xl">
        <!-- Nama, alamat, dan telepon di bawah ini yang tercetak sebagai kop
             struk penjualan (frontend/pages/Kasir/NotaCetak.vue). -->
        <p class="mb-4 text-xs text-ink-muted">
          Nama perusahaan, alamat, dan no. telepon di bawah ini tercetak sebagai kop pada struk penjualan.
        </p>
        <!-- `maxlength` mengikuti max_length di core.InfoPerusahaan. SQLite tidak
             menegakkan panjang VARCHAR, jadi tanpa batas di sini isian yang
             kepanjangan tersimpan utuh dan baru terpotong saat kop dicetak. -->
        <form @submit.prevent="simpan" class="space-y-4">
          <Input v-model="form.perusahaan" label="Nama Perusahaan / Toko" required maxlength="200" :error="form.errors.perusahaan" />

          <label class="block">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Alamat Perusahaan</span>
            <textarea
              v-model="form.alamat"
              rows="3"
              maxlength="300"
              class="w-full rounded-control border border-border-strong bg-surface px-2.5 py-2 text-sm text-ink transition-colors duration-150 placeholder:text-ink-subtle focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500"
            ></textarea>
            <span v-if="form.errors.alamat" class="mt-1 block text-xs text-danger-fg">{{ form.errors.alamat }}</span>
          </label>

          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input v-model="form.kota" label="Kota" maxlength="100" :error="form.errors.kota" />
            <Input v-model="form.telp" label="No. Telepon" type="tel" inputmode="tel" maxlength="60" :error="form.errors.telp" />
          </div>

          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input v-model="form.hp" label="No. HP / WhatsApp" type="tel" inputmode="tel" maxlength="60" :error="form.errors.hp" />
            <Input v-model="form.email" label="Email" type="email" inputmode="email" maxlength="120" :error="form.errors.email" />
          </div>

          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input v-model="form.website" label="Website" type="url" inputmode="url" maxlength="120" placeholder="https://…" :error="form.errors.website" />
            <Input v-model="form.nama_kontak" label="Nama Kontak" maxlength="120" :error="form.errors.nama_kontak" />
          </div>

          <div class="flex justify-end pt-2">
            <Button type="submit" :loading="form.processing">Simpan Perubahan</Button>
          </div>
        </form>
      </Card>
    </Deferred>
  </AdminLayout>
</template>

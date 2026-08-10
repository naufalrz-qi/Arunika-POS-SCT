<script setup>
import { computed, reactive, ref } from "vue";
import { router } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import { ROLE_LABELS } from "@/utils/labels";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import Spinner from "@/components/ui/Spinner.vue";

// Tautan akun Arunika → user legacy, SATU PER KONEKSI. Bentuknya matriks
// (user × koneksi), karena itu ia punya halaman sendiri alih-alih sederet
// isian di Manajemen User — sama alasannya dengan Kelola Menu.
//
// Kenapa per koneksi: kd_user dibuat berurutan (UAA000, UAA001, …) oleh tiap
// server SENDIRI-SENDIRI, jadi kode yang sama menunjuk orang berbeda di server
// berbeda. Terukur antara dua server: 10 dari 11 kode bersama milik orang lain.
const props = defineProps({
  users: { type: Array, default: () => [] },
  profiles: { type: Array, default: () => [] },
});

const cari = ref("");
const terpilih = ref(null);

const daftar = computed(() => {
  const q = cari.value.toLowerCase().trim();
  if (!q) return props.users;
  return props.users.filter(
    (u) => u.name.toLowerCase().includes(q) || u.username.toLowerCase().includes(q),
  );
});

// Kasir/supervisor terkunci ke satu server. Menampilkan 14 baris yang 13 di
// antaranya takkan pernah dipakai cuma mengundang salah isi.
const koneksiUntuk = computed(() => {
  const u = terpilih.value;
  if (!u) return [];
  if (!u.koneksi_terkunci) return props.profiles;
  return props.profiles.filter((p) => p.id === u.server_profile_id);
});

const jumlahTautan = (u) =>
  Object.values(u.tautan || {}).filter((t) => t.kd_user).length;

// --- Pilihan legacy, diambil per koneksi saat barisnya dibuka --------------
//
// Bukan sekaligus untuk semua koneksi: 14 profil berarti 42 query MS SQL lintas
// Tailscale, dan kebanyakan takkan pernah dilihat.
const opsi = reactive({});
const memuat = reactive({});

async function muatOpsi(profileId) {
  if (opsi[profileId] || memuat[profileId]) return;
  memuat[profileId] = true;
  try {
    const { data } = await axios.get(`/admin-panel/tautan-user/opsi/${profileId}`);
    opsi[profileId] = data;
  } catch {
    opsi[profileId] = { userx: [], divisi: [], pegawai: [], error: "Koneksi tak terjangkau." };
  } finally {
    memuat[profileId] = false;
  }
}

const userxOptions = (id) =>
  (opsi[id]?.userx || []).map((u) => ({
    value: u.kd_user,
    label: `${u.nama} (${u.kd_user})${u.aktif ? "" : " — nonaktif"}`,
  }));
const divisiOptions = (id) =>
  (opsi[id]?.divisi || []).map((d) => ({ value: d.kd_divisi, label: d.nama }));
const pegawaiOptions = (id) => opsi[id]?.pegawai || [];

// --- Baris yang sedang disunting ------------------------------------------
const buka = reactive({});
const draft = reactive({});

function toggle(p) {
  buka[p.id] = !buka[p.id];
  if (!buka[p.id]) return;
  muatOpsi(p.id);
  const ada = terpilih.value.tautan?.[p.id] || {};
  draft[p.id] = {
    kd_user: ada.kd_user || "",
    kd_divisi: ada.kd_divisi || "",
    kd_pegawai: ada.kd_pegawai || "",
  };
}

function pilihUser(u) {
  terpilih.value = u;
  Object.keys(buka).forEach((k) => delete buka[k]);
}

const menyimpan = ref(null);
function simpan(p) {
  menyimpan.value = p.id;
  router.post(
    "/admin-panel/tautan-user/save",
    { user_id: terpilih.value.id, profile_id: p.id, ...draft[p.id] },
    {
      preserveScroll: true,
      onSuccess: () => {
        // Prop `users` datang segar dari server; pilihan harus ikut menunjuk
        // objek baru, kalau tidak layar memperlihatkan angka lama.
        const segar = props.users.find((x) => x.id === terpilih.value.id);
        if (segar) terpilih.value = segar;
        buka[p.id] = false;
      },
      onFinish: () => (menyimpan.value = null),
    },
  );
}

const ringkas = (t) =>
  t?.kd_user ? `${t.kd_user} / ${t.kd_divisi || "divisi?"}` : "belum ditautkan";
</script>

<template>
  <AdminLayout title="Kelola Tautan User">
    <Banner
      variant="info"
      class="mb-4"
      message="Tautan dibuat per koneksi. Kode user legacy dibuat berurutan oleh tiap server sendiri-sendiri, jadi kode yang sama menunjuk orang yang berbeda di server yang berbeda — satu tautan untuk semua koneksi akan mencatat transaksi atas nama orang lain."
    />

    <div class="grid gap-4 lg:grid-cols-[20rem_1fr]">
      <Card>
        <Input v-model="cari" label="Cari user" placeholder="nama atau username…" />
        <ul class="mt-3 max-h-[32rem] space-y-1 overflow-y-auto">
          <li v-for="u in daftar" :key="u.id">
            <button
              type="button"
              :class="[
                'flex w-full items-center gap-2 rounded-control border px-3 py-2 text-left transition-colors',
                terpilih?.id === u.id
                  ? 'border-brand-500/60 bg-brand-bg'
                  : 'border-border-default hover:bg-surface-2',
              ]"
              @click="pilihUser(u)"
            >
              <span class="flex-1">
                <span class="block text-sm text-ink">{{ u.name }}</span>
                <span class="block text-xs text-ink-subtle">{{ u.username }}</span>
              </span>
              <Badge variant="neutral" class="shrink-0 text-[10px]">
                {{ ROLE_LABELS[u.role] || u.role }}
              </Badge>
              <Badge
                :variant="jumlahTautan(u) ? 'neutral' : 'warning'"
                class="shrink-0 text-[10px]"
              >
                {{ jumlahTautan(u) || "0" }}
              </Badge>
            </button>
          </li>
        </ul>
      </Card>

      <Card>
        <p v-if="!terpilih" class="text-sm text-ink-subtle">
          Pilih user di sebelah kiri untuk mengatur tautannya per koneksi.
        </p>

        <template v-else>
          <div class="mb-3">
            <h2 class="text-base font-medium text-ink">{{ terpilih.name }}</h2>
            <p class="text-xs text-ink-subtle">
              {{ terpilih.username }} — {{ ROLE_LABELS[terpilih.role] || terpilih.role }}
            </p>
          </div>

          <p v-if="terpilih.koneksi_terkunci && !koneksiUntuk.length"
             class="text-sm text-warning-fg">
            Akun ini terkunci ke satu server, tapi servernya belum ditentukan.
            Isi dulu di Manajemen User.
          </p>
          <p v-else-if="terpilih.koneksi_terkunci" class="mb-3 text-xs text-ink-subtle">
            Kasir &amp; supervisor terkunci ke satu server, jadi hanya koneksi itu
            yang perlu ditautkan.
          </p>

          <ul class="space-y-2">
            <li
              v-for="p in koneksiUntuk"
              :key="p.id"
              class="rounded-control border border-border-default"
            >
              <button
                type="button"
                class="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2"
                @click="toggle(p)"
              >
                <span class="flex-1 text-sm text-ink">{{ p.name }}</span>
                <span
                  :class="[
                    'text-xs',
                    terpilih.tautan?.[p.id]?.kd_user ? 'text-ink-muted' : 'text-ink-subtle',
                  ]"
                >
                  {{ ringkas(terpilih.tautan?.[p.id]) }}
                </span>
              </button>

              <div v-if="buka[p.id]" class="border-t border-border-default p-3">
                <div v-if="memuat[p.id]" class="flex items-center gap-2 text-sm text-ink-subtle">
                  <Spinner /> Membaca user legacy dari {{ p.name }}…
                </div>
                <template v-else>
                  <Banner
                    v-if="opsi[p.id]?.error"
                    variant="warning"
                    :message="opsi[p.id].error"
                    class="mb-3"
                  />
                  <!-- Pilihan, bukan isian bebas: kode dibaca dari server yang
                       bersangkutan, jadi salah ketik jadi mustahil. -->
                  <div class="grid gap-3 sm:grid-cols-3">
                    <Select
                      v-model="draft[p.id].kd_user"
                      label="User legacy *"
                      :options="userxOptions(p.id)"
                      placeholder="Belum ditautkan"
                    />
                    <Select
                      v-model="draft[p.id].kd_divisi"
                      label="Divisi *"
                      :options="divisiOptions(p.id)"
                      placeholder="Belum dipilih"
                    />
                    <Select
                      v-model="draft[p.id].kd_pegawai"
                      label="Pegawai (nota)"
                      :options="pegawaiOptions(p.id)"
                      placeholder="Belum dipilih"
                    />
                  </div>
                  <p class="mt-2 text-xs text-ink-subtle">
                    User legacy dan divisi sama-sama wajib: yang pertama menentukan
                    transaksi tercatat atas nama siapa, yang kedua menentukan awalan
                    nomornya. Kosongkan keduanya untuk mencabut tautan.
                  </p>
                  <div class="mt-3 flex justify-end gap-2">
                    <Button variant="secondary" size="sm" @click="buka[p.id] = false">
                      Batal
                    </Button>
                    <Button size="sm" :loading="menyimpan === p.id" @click="simpan(p)">
                      Simpan
                    </Button>
                  </div>
                </template>
              </div>
            </li>
          </ul>
        </template>
      </Card>
    </div>
  </AdminLayout>
</template>

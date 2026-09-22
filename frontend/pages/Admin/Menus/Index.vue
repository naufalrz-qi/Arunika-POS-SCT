<script setup>
import { computed, reactive, ref } from "vue";
import { router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Input from "@/components/ui/Input.vue";
import Icon from "@/components/nav/Icon.vue";
import { LINGKUNGAN_LABELS } from "@/utils/labels";

const props = defineProps({
  // {id, username, name, role, allowed_menu_keys, allowed_data_keys}
  users: { type: Array, default: () => [] },
  menus: { type: Array, default: () => [] }, // assignable menus (punya .section + .icon)
  sections: { type: Array, default: () => [] }, // [{key, label}] urut tampil
  data_keys: { type: Array, default: () => [] }, // [{key, label}] nilai uang
  role_defaults: { type: Object, default: () => ({}) }, // {peran: [menu_key]}
  // Kunci menu yang boleh DIUBAH pemakai layar ini, per peran target
  // (wewenang_beri di server). Server tetap menegakkannya sendiri.
  boleh_beri: { type: Object, default: () => ({}) },
  boleh_data: { type: Array, default: () => [] }, // kunci nilai uang yang boleh diubah
  saya_superadmin: { type: Boolean, default: false },
  koneksi_nonprod: { type: Array, default: () => [] }, // [{id, name, lingkungan}], superadmin saja
});

const ROLE_LABELS = { kasir: "Kasir", supervisor: "Supervisor", admin: "Admin" };

// Peran mana saja yang mendapat menu ini secara bawaan — dipakai untuk penanda
// di tiap baris, supaya terlihat mana yang memang jatah kasir/supervisor.
function bawaanUntuk(key) {
  return Object.entries(props.role_defaults)
    .filter(([, keys]) => keys.includes(key))
    .map(([role]) => ROLE_LABELS[role] || role);
}

// Centang yang TIDAK boleh diubah pemakai layar ini. Penjagaan sebenarnya di
// server — menu_baru() mempertahankan yang di luar wewenang — jadi ini hanya
// supaya layar tak menjanjikan perubahan yang takkan tersimpan.
const terkunci = (m) =>
  Boolean(selected.value) && !(props.boleh_beri[selected.value.role] || []).includes(m.key);
function alasanKunci(m) {
  if (m.teknis) return "khusus superadmin";
  if (m.tulis_kritis && selected.value?.role !== "admin") return "superadmin saja untuk peran ini";
  return "tidak Anda pegang";
}
const dataTerkunci = (d) => !props.boleh_data.includes(d.key);
const koneksiChecked = reactive({});
const tampilKoneksi = computed(
  () => props.saya_superadmin && selected.value?.role === "admin" && props.koneksi_nonprod.length > 0,
);

// Menu bawaan peran user yang sedang dipilih.
const bawaanTerpilih = computed(() =>
  selected.value ? props.role_defaults[selected.value.role] || [] : [],
);
const memakaiBawaan = computed(
  () => Boolean(selected.value) && (selected.value.allowed_menu_keys || []).length === 0,
);

const selected = ref(null);
const checked = reactive({});
// Terpisah dari `checked` supaya "Pilih Semua"/"Kosongkan" milik menu tak
// diam-diam ikut mencabut akses ke nilai uang.
const dataChecked = reactive({});
const saving = ref(false);
const userSearch = ref("");

const filteredUsers = computed(() => {
  const q = userSearch.value.toLowerCase().trim();
  if (!q) return props.users;
  return props.users.filter(
    (u) => u.name.toLowerCase().includes(q) || u.username.toLowerCase().includes(q),
  );
});

// Menu dikelompokkan per section supaya mudah dipindai (dulu grid flat tanpa pembeda).
const grouped = computed(() =>
  props.sections
    .map((s) => ({ ...s, items: props.menus.filter((m) => m.section === s.key) }))
    .filter((s) => s.items.length),
);

const checkedCount = computed(() => props.menus.filter((m) => checked[m.key]).length);

function sectionState(s) {
  const on = s.items.filter((m) => checked[m.key]).length;
  return { all: on === s.items.length, some: on > 0 && on < s.items.length, on };
}
function toggleSection(s) {
  const bisa = s.items.filter((m) => !terkunci(m));
  const target = !bisa.every((m) => checked[m.key]);
  bisa.forEach((m) => (checked[m.key] = target));
}
// `value` boleh boolean (semua/kosong) atau daftar kunci (mis. bawaan peran).
// Kotak terkunci tak disentuh: tombol massal tak boleh tampak mengubah yang
// memang tak bisa diubah.
function setAll(value) {
  const daftar = Array.isArray(value) ? value : null;
  props.menus.forEach((m) => {
    if (terkunci(m)) return;
    checked[m.key] = daftar ? daftar.includes(m.key) : value;
  });
}

function select(user) {
  selected.value = user;
  const allowed = user.allowed_menu_keys || [];
  // Kosong TIDAK berarti "semua" untuk setiap peran. Admin memang mendapat
  // semuanya, tapi kasir/supervisor hanya mendapat menu bawaan perannya —
  // mencentang semua di sini akan menampilkan akses yang tak ia punya, dan
  // sekali disimpan justru MEMBERIKANNYA.
  const bawaan = props.role_defaults[user.role] || [];
  props.menus.forEach((m) => {
    checked[m.key] = allowed.length === 0 ? bawaan.includes(m.key) : allowed.includes(m.key);
  });
  // Nilai uang TIDAK memakai konvensi "kosong = semua": server mengirim daftar
  // yang boleh dilihat apa adanya, jadi kosong berarti benar-benar tak boleh.
  const bolehData = user.allowed_data_keys || [];
  props.data_keys.forEach((d) => {
    dataChecked[d.key] = bolehData.includes(d.key);
  });
  const khusus = user.koneksi_khusus || [];
  props.koneksi_nonprod.forEach((k) => {
    koneksiChecked[k.id] = khusus.includes(k.id);
  });
}

function save() {
  if (!selected.value) return;
  const menu_keys = props.menus.filter((m) => checked[m.key]).map((m) => m.key);
  const data_keys = props.data_keys.filter((d) => dataChecked[d.key]).map((d) => d.key);
  const payload = { user_id: selected.value.id, menu_keys, data_keys };
  if (tampilKoneksi.value) {
    payload.koneksi_khusus = props.koneksi_nonprod.filter((k) => koneksiChecked[k.id]).map((k) => k.id);
  }
  saving.value = true;
  router.post(
    "/admin-panel/menus/save",
    payload,
    {
      preserveScroll: true,
      onSuccess: () => {
        // reflect locally
        const u = props.users.find((x) => x.id === selected.value.id);
        if (u) {
          u.allowed_menu_keys = menu_keys;
          u.allowed_data_keys = data_keys;
        }
      },
      onFinish: () => (saving.value = false),
    },
  );
}

const roleVariant = { admin: "brand", supervisor: "warning", kasir: "neutral" };
</script>

<template>
  <AdminLayout title="Kelola Menu">
    <p class="mb-4 text-sm text-ink-muted">
      Atur menu yang boleh diakses tiap user. <strong>Superadmin</strong> selalu punya akses penuh dan tidak muncul di daftar.
      <template v-if="!saya_superadmin">
        Anda hanya bisa mengubah menu yang Anda pegang sendiri; menu teknis hanya bisa diberikan superadmin.
      </template>
    </p>

    <div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <!-- User list -->
      <Card title="User">
        <div class="mb-3">
          <Input v-model="userSearch" placeholder="Cari nama / username…" />
        </div>
        <ul class="divide-y divide-border-default">
          <li
            v-for="u in filteredUsers"
            :key="u.id"
            :class="[
              'flex cursor-pointer items-center justify-between px-1 py-2.5 -mx-1 rounded-control',
              selected?.id === u.id ? 'bg-brand-50' : 'hover:bg-surface-2',
            ]"
            @click="select(u)"
          >
            <div>
              <p class="text-sm font-medium text-ink">{{ u.name }}</p>
              <p class="text-xs text-ink-muted">{{ u.username }}</p>
            </div>
            <Badge :variant="roleVariant[u.role] || 'neutral'" class="capitalize">{{ u.role }}</Badge>
          </li>
          <li v-if="filteredUsers.length === 0" class="py-6 text-center text-sm text-ink-subtle">Tidak ada user.</li>
        </ul>
      </Card>

      <!-- Menu checkboxes -->
      <Card class="lg:col-span-2" :title="selected ? `Menu untuk ${selected.name}` : 'Pilih user dulu'">
        <template v-if="selected">
          <!-- Toolbar global -->
          <div class="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-control bg-surface-2 px-3 py-2">
            <p class="text-sm text-ink-muted">
              <strong class="text-ink">{{ checkedCount }}</strong> / {{ menus.length }} menu dipilih
            </p>
            <div class="flex gap-2">
              <Button variant="secondary" size="sm" @click="setAll(bawaanTerpilih)">
                Kembalikan Bawaan
              </Button>
              <Button variant="secondary" size="sm" @click="setAll(true)">Pilih Semua</Button>
              <Button variant="secondary" size="sm" @click="setAll(false)">Kosongkan</Button>
            </div>
          </div>

          <!-- Yang belum pernah diatur memakai bawaan perannya. Tanpa keterangan
               ini, centang yang tampil terbaca seperti pilihan yang pernah
               dibuat seseorang, padahal belum. -->
          <p
            v-if="memakaiBawaan"
            class="mb-4 rounded-control border border-border-default bg-surface-2 px-3 py-2 text-xs text-ink-muted"
          >
            Akun ini belum pernah diatur, jadi yang tercentang adalah
            <strong class="text-ink">menu bawaan {{ ROLE_LABELS[selected.role] || selected.role }}</strong
            >. Menyimpan akan mengunci pilihan ini, dan sejak itu perubahan menu bawaan
            tidak lagi ikut terbawa.
          </p>

          <!-- Nilai uang: berdiri sendiri di atas daftar menu, bukan sebagai
               salah satu section, karena cakupannya berbeda — ini menyaring ISI
               halaman, bukan menentukan halaman mana yang terbuka. -->
          <section class="mb-5 rounded-control border border-border-default p-3">
            <div class="mb-2 border-b border-border-default pb-1.5">
              <h3 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Nilai Uang</h3>
              <p class="mt-1 text-xs text-ink-subtle">
                Yang tidak dicentang benar-benar disembunyikan, termasuk saat diunduh ke Excel.
                Berlaku di <strong>Stok Akhir</strong>, <strong>Barang Histori</strong>, dan
                <strong>Dashboard</strong>. Halaman laporan lain masih menampilkan angka uang —
                kalau perlu, cabut juga menunya di daftar bawah.
              </p>
            </div>
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <label
                v-for="d in data_keys"
                :key="d.key"
                :class="[
                  'flex items-center gap-3 rounded-control border px-3 py-2.5 transition-colors',
                  dataTerkunci(d) ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
                  dataChecked[d.key] ? 'border-brand-500/60 bg-brand-bg' : 'border-border-default hover:bg-surface-2',
                ]"
              >
                <input
                  type="checkbox"
                  v-model="dataChecked[d.key]"
                  :disabled="dataTerkunci(d)"
                  class="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500"
                />
                <span class="text-sm text-ink-muted">{{ d.label }}</span>
              </label>
            </div>
          </section>

          <!-- Koneksi non-produksi: superadmin saja, dan hanya untuk admin —
               kasir/supervisor dikunci ke satu server lewat Manajemen User. -->
          <section v-if="tampilKoneksi" class="mb-5 rounded-control border border-border-default p-3">
            <div class="mb-2 border-b border-border-default pb-1.5">
              <h3 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Akses Koneksi Non-Produksi</h3>
              <p class="mt-1 text-xs text-ink-subtle">
                Koneksi uji coba dan internal (mis. AMPHOREUS) hanya muncul di pemilih koneksi
                superadmin, kecuali dicentang di sini. Koneksi produksi selalu tersedia.
              </p>
            </div>
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <label
                v-for="k in koneksi_nonprod"
                :key="k.id"
                :class="[
                  'flex cursor-pointer items-center gap-3 rounded-control border px-3 py-2.5 transition-colors',
                  koneksiChecked[k.id] ? 'border-brand-500/60 bg-brand-bg' : 'border-border-default hover:bg-surface-2',
                ]"
              >
                <input
                  type="checkbox"
                  v-model="koneksiChecked[k.id]"
                  class="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500"
                />
                <span class="flex-1 text-sm text-ink-muted">{{ k.name }}</span>
                <Badge variant="neutral" class="shrink-0 text-[10px]">{{ LINGKUNGAN_LABELS[k.lingkungan] || k.lingkungan }}</Badge>
              </label>
            </div>
          </section>

          <!-- Per section: header + pilih semua section + item ber-ikon -->
          <div class="space-y-5">
            <section v-for="s in grouped" :key="s.key">
              <div class="mb-2 flex items-center justify-between border-b border-border-default pb-1.5">
                <h3 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">{{ s.label }}</h3>
                <label class="flex cursor-pointer items-center gap-2 text-xs text-ink-muted hover:text-ink">
                  <input
                    type="checkbox"
                    :checked="sectionState(s).all"
                    :indeterminate.prop="sectionState(s).some"
                    class="h-3.5 w-3.5 rounded border-border-strong text-brand-600 focus:ring-brand-500"
                    @change="toggleSection(s)"
                  />
                  Pilih semua ({{ sectionState(s).on }}/{{ s.items.length }})
                </label>
              </div>
              <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <label
                  v-for="m in s.items"
                  :key="m.key"
                  :title="terkunci(m) ? `${m.label}: ${alasanKunci(m)}.` : undefined"
                  :class="[
                    'flex items-center gap-3 rounded-control border px-3 py-2.5 transition-colors',
                    terkunci(m) ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
                    checked[m.key] ? 'border-brand-500/60 bg-brand-bg' : 'border-border-default hover:bg-surface-2',
                  ]"
                >
                  <input type="checkbox" v-model="checked[m.key]" :disabled="terkunci(m)" class="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-500" />
                  <Icon :name="m.icon" size="h-4 w-4" class="shrink-0 text-ink-subtle" />
                  <span class="flex-1 text-sm text-ink-muted">{{ m.label }}</span>
                  <Badge v-if="terkunci(m)" variant="neutral" class="shrink-0 text-[10px]">{{ alasanKunci(m) }}</Badge>
                  <!-- Penanda jatah peran: tanpa ini tak ada cara membedakan
                       menu yang memang bawaan kasir/supervisor dari menu admin
                       yang kebetulan sedang diberikan kepada mereka. -->
                  <Badge
                    v-for="peran in bawaanUntuk(m.key)"
                    :key="peran"
                    variant="neutral"
                    class="shrink-0 text-[10px]"
                    >{{ peran }}</Badge
                  >
                </label>
              </div>
            </section>
          </div>

          <div class="mt-5 flex items-center justify-between">
            <p class="text-xs text-ink-subtle">
              Menyimpan tanpa satu centang pun akan mengembalikan akun ini ke menu
              bawaan perannya — bukan mencabut semuanya.
            </p>
            <Button :loading="saving" @click="save">Simpan</Button>
          </div>
        </template>
        <p v-else class="py-8 text-center text-sm text-ink-muted">Pilih user di kiri untuk mengatur menunya.</p>
      </Card>
    </div>
  </AdminLayout>
</template>


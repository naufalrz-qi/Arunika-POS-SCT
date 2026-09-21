<script setup>
import { computed } from "vue";
import { Deferred, Link, usePage } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Banner from "@/components/ui/Banner.vue";
import BarChart from "@/components/charts/BarChart.vue";
import Icon from "@/components/nav/Icon.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import { useHiddenData } from "@/composables/useHiddenData";

const props = defineProps({
  dashboard: { type: Object, default: null },
});

const data = computed(() => props.dashboard || {});

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const { bisaLihat } = useHiddenData();

// Peran dibaca di dalam computed: Inertia mengganti objek props tiap kunjungan,
// jadi salinan yang diambil saat setup akan basi setelah berpindah halaman.
const inertiaPage = usePage();
const bolehLihatServer = computed(() => inertiaPage.props.auth_user?.role === "superadmin");

const summaryItems = computed(() => {
  const s = data.value.stats || {};
  const items = [
    { label: "Transaksi Hari Ini", value: s.total_transactions ?? 0 },
    { label: "Item Terjual", value: s.total_items ?? 0 },
  ];
  // `revenue` memang tak dikirim server bila izinnya dicabut; tanpa penjagaan
  // ini kartunya tetap muncul bertuliskan "Rp 0" — angka yang salah, bukan
  // sekadar kosong.
  if (bisaLihat("nominal")) {
    items.push({ label: "Omzet", value: rupiah(s.revenue) });
  }
  // Status server hanya dikirim untuk superadmin; tanpa penjagaan ini kartunya
  // tetap muncul bertuliskan "0 / 0" — terbaca seperti semua server mati.
  if (bolehLihatServer.value) {
    items.push({
      label: "Server Online",
      value: `${s.servers_online ?? 0} / ${s.servers_total ?? 0}`,
    });
  }
  return items;
});

// Yang offline di depan: dari 14 server, yang perlu dicari mata hanya yang mati.
const servers = computed(() =>
  [...(data.value.servers || [])].sort((a, b) => (a.status === "online") - (b.status === "online")),
);
const jumlahOffline = computed(() => servers.value.filter((s) => s.status !== "online").length);

const chartData = computed(() =>
  (data.value.hourly_transactions || []).map((h) => ({ label: h.hour, value: h.count })),
);
</script>

<template>
  <AdminLayout title="Dashboard">
    <Deferred data="dashboard">
      <template #fallback>
        <LoadingCard message="Mengambil data dashboard…" />
      </template>

    <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

    <SummaryStrip :items="summaryItems" />

    <div class="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
      <!-- Chart. Tanpa kartu Status Server di sebelahnya ia melebar penuh,
           bukan menyisakan sepertiga halaman kosong. -->
      <div :class="bolehLihatServer ? 'lg:col-span-2' : 'lg:col-span-3'">
        <Card title="Transaksi per Jam" subtitle="Hari ini">
          <BarChart :data="chartData" />
        </Card>
      </div>

      <!-- Status server: khusus superadmin. Daftarnya membuka nama host dan
           port tiap server MS SQL, dan datanya memang tak dikirim ke yang lain
           (lihat dashboard() di apps/monitoring/views.py) — `v-if` di sini
           hanya merapikan tata letak. -->
      <!-- Grid ringkas, bukan daftar: 14 server bertumpuk dengan host di bawah
           namanya membuat kartu ini dua kali lebih tinggi dari grafik di
           sebelahnya. Host pindah ke tooltip. -->
      <Card
        v-if="bolehLihatServer"
        title="Status Server"
        :subtitle="`${servers.length - jumlahOffline} online · ${jumlahOffline} offline`"
      >
        <ul class="grid grid-cols-2 gap-2">
          <li
            v-for="s in servers"
            :key="s.id"
            :title="s.host"
            :class="[
              'flex min-w-0 items-center gap-2 rounded-control border px-2.5 py-2',
              s.status === 'online' ? 'border-border-default' : 'border-danger-500/40 bg-danger-bg',
            ]"
          >
            <span :class="['h-2 w-2 shrink-0 rounded-full', s.status === 'online' ? 'bg-success-500' : 'bg-danger-500']" />
            <span class="min-w-0">
              <span class="block truncate text-xs font-medium text-ink">{{ s.name }}</span>
              <span v-if="s.status !== 'online'" class="block text-[11px] text-danger-fg">Offline</span>
              <span v-else class="sr-only">Online</span>
            </span>
          </li>
        </ul>
      </Card>
    </div>

    <!-- Fast moving + recent activity -->
    <div class="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Card title="Fast Moving Bulan Ini" subtitle="Top 10 qty terjual — barang tanpa harga jual dikecualikan">
        <table v-if="(data.fast_movers || []).length" class="w-full text-sm">
          <thead>
            <tr class="text-left">
              <th class="py-1.5 text-[11px] font-semibold text-ink-muted">Barang</th>
              <th class="py-1.5 text-right text-[11px] font-semibold text-ink-muted">Qty</th>
              <th v-if="bisaLihat('nominal')" class="py-1.5 text-right text-[11px] font-semibold text-ink-muted">
                Nilai
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border-default">
            <tr v-for="m in data.fast_movers" :key="m.kd_barang">
              <td class="py-1.5 pr-2 text-ink">{{ m.nama }}</td>
              <td class="py-1.5 text-right text-ink">{{ (m.qty ?? 0).toLocaleString("id-ID") }}</td>
              <td v-if="bisaLihat('nominal')" class="py-1.5 text-right text-ink">{{ rupiah(m.nilai) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="text-sm text-ink-muted">Belum ada penjualan bulan ini.</p>
        <Link
          href="/admin-panel/analitik/fmi-penjualan"
          class="mt-3 inline-block text-xs font-medium text-brand-fg hover:underline"
        >
          Lihat semua (analisis Pareto) →
        </Link>
      </Card>

      <Card title="Aktivitas Terbaru">
        <!-- Kartu sebelahnya ("Fast Moving") punya kalimat pengganti saat kosong,
             kartu ini tidak — jadi <ul>-nya hanya kosong melompong dan terbaca
             seperti gagal memuat, bukan "belum ada aktivitas". -->
        <p v-if="!(data.recent_activity || []).length" class="text-sm text-ink-muted">
          Belum ada aktivitas tercatat.
        </p>
        <ul v-else class="divide-y divide-border-default">
          <!-- `min-w-0` di kedua tingkat flex, dan `[overflow-wrap:anywhere]`
               pada detailnya. Tanpa itu satu baris log bisa melebarkan seluruh
               halaman: detail "Set menu <user>: dashboard,penjualan_all,…"
               berisi 40+ kunci menu dipisah koma TANPA spasi, jadi peramban tak
               menemukan satu pun titik putus. `break-words` tak cukup di sini —
               ia hanya memutus di spasi, yang memang tak ada. -->
          <li v-for="a in data.recent_activity || []" :key="a.id" class="flex items-start justify-between gap-3 py-3">
            <div class="flex min-w-0 items-start gap-3">
              <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-3 text-xs font-semibold text-ink-muted">
                {{ a.user.charAt(0).toUpperCase() }}
              </div>
              <div class="min-w-0">
                <p class="text-sm text-ink"><span class="font-medium">{{ a.user }}</span> — {{ a.action }}</p>
                <p class="text-xs text-ink-muted [overflow-wrap:anywhere]">{{ a.detail }}</p>
              </div>
            </div>
            <span class="shrink-0 whitespace-nowrap text-xs text-ink-subtle">{{ a.time }}</span>
          </li>
        </ul>
      </Card>
    </div>
    </Deferred>
  </AdminLayout>
</template>

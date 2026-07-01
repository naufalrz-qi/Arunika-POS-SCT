<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import BarChart from "@/components/charts/BarChart.vue";
import Icon from "@/components/nav/Icon.vue";

const props = defineProps({
  servers: { type: Array, default: () => [] },
  stats: { type: Object, default: () => ({}) },
  hourly_transactions: { type: Array, default: () => [] },
  recent_activity: { type: Array, default: () => [] },
  conn_error: { type: String, default: null },
});

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

// RX-78-2 tricolor: blue (primary), yellow (V-fin), red (chest), navy.
const kpis = computed(() => [
  { label: "Transaksi Hari Ini", value: props.stats.total_transactions ?? 0, icon: "cart", tone: "blue" },
  { label: "Item Terjual", value: props.stats.total_items ?? 0, icon: "box", tone: "yellow" },
  { label: "Omzet", value: rupiah(props.stats.revenue), icon: "cash", tone: "red" },
  { label: "Server Online", value: `${props.stats.servers_online ?? 0} / ${props.stats.servers_total ?? 0}`, icon: "server", tone: "navy" },
]);

// Tricolor top panel-line (flush bar) + mode-aware icon chip (kept semantic for contrast).
const tones = {
  blue: { bar: "bg-brand-600", chip: "bg-brand-bg text-brand-fg" },
  yellow: { bar: "bg-rx-yellow", chip: "bg-warning-bg text-warning-fg" },
  red: { bar: "bg-rx-red", chip: "bg-danger-bg text-danger-fg" },
  navy: { bar: "bg-brand-900", chip: "bg-surface-3 text-ink-muted" },
};

const chartData = computed(() =>
  props.hourly_transactions.map((h) => ({ label: h.hour, value: h.count })),
);
</script>

<template>
  <AdminLayout title="Dashboard">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />

    <!-- KPI cards -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div
        v-for="kpi in kpis"
        :key="kpi.label"
        class="overflow-hidden rounded-card border border-border-default bg-surface shadow-sm transition hover:shadow-md"
      >
        <div :class="['h-1', tones[kpi.tone].bar]" />
        <div class="flex items-center gap-4 p-5">
          <span :class="['flex h-12 w-12 shrink-0 items-center justify-center rounded-md', tones[kpi.tone].chip]">
            <Icon :name="kpi.icon" size="h-6 w-6" />
          </span>
          <div class="min-w-0">
            <p class="truncate text-sm text-ink-muted">{{ kpi.label }}</p>
            <p class="mt-0.5 text-2xl font-semibold tabular-nums text-ink">{{ kpi.value }}</p>
          </div>
        </div>
      </div>
    </div>

    <div class="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
      <!-- Chart -->
      <div class="lg:col-span-2">
        <Card title="Transaksi per Jam" subtitle="Hari ini">
          <BarChart :data="chartData" />
        </Card>
      </div>

      <!-- Server status -->
      <Card title="Status Server">
        <ul class="space-y-3">
          <li v-for="s in servers" :key="s.id" class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium text-ink">{{ s.name }}</p>
              <p class="text-xs text-ink-muted">{{ s.host }}</p>
            </div>
            <Badge :variant="s.status === 'online' ? 'success' : 'danger'">
              <span :class="['h-1.5 w-1.5 rounded-full', s.status === 'online' ? 'bg-success-600' : 'bg-danger-600']" />
              {{ s.status === "online" ? "Online" : "Offline" }}
            </Badge>
          </li>
        </ul>
      </Card>
    </div>

    <!-- Recent activity -->
    <div class="mt-6">
      <Card title="Aktivitas Terbaru">
        <ul class="divide-y divide-border-default">
          <li v-for="a in recent_activity" :key="a.id" class="flex items-center justify-between py-3">
            <div class="flex items-center gap-3">
              <div class="flex h-8 w-8 items-center justify-center rounded-full bg-surface-3 text-xs font-semibold text-ink-muted">
                {{ a.user.charAt(0).toUpperCase() }}
              </div>
              <div>
                <p class="text-sm text-ink"><span class="font-medium">{{ a.user }}</span> — {{ a.action }}</p>
                <p class="text-xs text-ink-muted">{{ a.detail }}</p>
              </div>
            </div>
            <span class="text-xs text-ink-subtle">{{ a.time }}</span>
          </li>
        </ul>
      </Card>
    </div>
  </AdminLayout>
</template>

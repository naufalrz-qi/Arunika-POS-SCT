<script setup>
import { computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import BarChart from "@/components/charts/BarChart.vue";
import Icon from "@/components/nav/Icon.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";

const props = defineProps({
  dashboard: { type: Object, default: null },
});

const data = computed(() => props.dashboard || {});

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const summaryItems = computed(() => [
  { label: "Transaksi Hari Ini", value: data.value.stats?.total_transactions ?? 0 },
  { label: "Item Terjual", value: data.value.stats?.total_items ?? 0 },
  { label: "Omzet", value: rupiah(data.value.stats?.revenue) },
  { label: "Server Online", value: `${data.value.stats?.servers_online ?? 0} / ${data.value.stats?.servers_total ?? 0}` },
]);

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
      <!-- Chart -->
      <div class="lg:col-span-2">
        <Card title="Transaksi per Jam" subtitle="Hari ini">
          <BarChart :data="chartData" />
        </Card>
      </div>

      <!-- Server status -->
      <Card title="Status Server">
        <ul class="space-y-3">
          <li v-for="s in data.servers || []" :key="s.id" class="flex items-center justify-between">
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
          <li v-for="a in data.recent_activity || []" :key="a.id" class="flex items-center justify-between py-3">
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
    </Deferred>
  </AdminLayout>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  // data: [{ label, value }]
  data: { type: Array, default: () => [] },
  height: { type: Number, default: 220 },
});

const W = 720;
const PAD = { top: 16, right: 12, bottom: 28, left: 32 };

const maxValue = computed(() => Math.max(1, ...props.data.map((d) => d.value)));

const innerW = computed(() => W - PAD.left - PAD.right);
const innerH = computed(() => props.height - PAD.top - PAD.bottom);
const bandW = computed(() => innerW.value / Math.max(1, props.data.length));

function barHeight(v) {
  return (v / maxValue.value) * innerH.value;
}

// y gridlines (4 segments)
const ticks = computed(() => {
  const out = [];
  for (let i = 0; i <= 4; i++) {
    const v = Math.round((maxValue.value / 4) * i);
    out.push({ v, y: PAD.top + innerH.value - (i / 4) * innerH.value });
  }
  return out;
});
</script>

<template>
  <svg :viewBox="`0 0 ${W} ${height}`" class="w-full" role="img" aria-label="Grafik transaksi per jam">
    <!-- gridlines + y labels -->
    <g>
      <line
        v-for="t in ticks"
        :key="`g${t.v}`"
        :x1="PAD.left"
        :x2="W - PAD.right"
        :y1="t.y"
        :y2="t.y"
        stroke="currentColor"
        class="text-border-default"
        stroke-width="1"
      />
      <text
        v-for="t in ticks"
        :key="`l${t.v}`"
        :x="PAD.left - 6"
        :y="t.y + 3"
        text-anchor="end"
        class="fill-ink-subtle text-[10px]"
      >
        {{ t.v }}
      </text>
    </g>

    <!-- bars -->
    <g>
      <template v-for="(d, i) in data" :key="d.label">
        <rect
          :x="PAD.left + i * bandW + bandW * 0.18"
          :y="PAD.top + innerH - barHeight(d.value)"
          :width="bandW * 0.64"
          :height="barHeight(d.value)"
          rx="3"
          class="fill-brand-500 transition-all hover:fill-brand-600"
        >
          <title>{{ d.label }}: {{ d.value }}</title>
        </rect>
        <text
          :x="PAD.left + i * bandW + bandW / 2"
          :y="height - 10"
          text-anchor="middle"
          class="fill-ink-subtle text-[10px]"
        >
          {{ d.label }}
        </text>
      </template>
    </g>
  </svg>
</template>

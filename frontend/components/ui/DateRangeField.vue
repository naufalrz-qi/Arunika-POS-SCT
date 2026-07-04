<script setup>
const props = defineProps({
  from: { type: String, default: "" },
  to: { type: String, default: "" },
});
const emit = defineEmits(["update:from", "update:to"]);

function iso(d) {
  return d.toISOString().slice(0, 10);
}
function setPreset(name) {
  const now = new Date();
  let from = new Date(now);
  let to = new Date(now);
  if (name === "hari-ini") {
    // from = to = today
  } else if (name === "kemarin") {
    from.setDate(now.getDate() - 1);
    to.setDate(now.getDate() - 1);
  } else if (name === "7hari") {
    from.setDate(now.getDate() - 6);
  } else if (name === "bulan-ini") {
    from = new Date(now.getFullYear(), now.getMonth(), 1);
  } else if (name === "bulan-lalu") {
    from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    to = new Date(now.getFullYear(), now.getMonth(), 0);
  }
  emit("update:from", iso(from));
  emit("update:to", iso(to));
}
const presets = [
  { key: "hari-ini", label: "Hari ini" },
  { key: "kemarin", label: "Kemarin" },
  { key: "7hari", label: "7 Hari" },
  { key: "bulan-ini", label: "Bulan Ini" },
  { key: "bulan-lalu", label: "Bulan Lalu" },
];
</script>

<template>
  <div class="space-y-2">
    <div class="grid grid-cols-2 gap-2">
      <label class="block">
        <span class="mb-1 block text-xs text-ink-muted">Dari Tanggal</span>
        <input
          type="date"
          :value="from"
          @input="emit('update:from', $event.target.value)"
          class="w-full rounded-card border border-border-default bg-surface px-3 py-2 text-sm text-ink"
        />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs text-ink-muted">Sampai Tanggal</span>
        <input
          type="date"
          :value="to"
          @input="emit('update:to', $event.target.value)"
          class="w-full rounded-card border border-border-default bg-surface px-3 py-2 text-sm text-ink"
        />
      </label>
    </div>
    <div class="flex flex-wrap gap-1">
      <button
        v-for="p in presets"
        :key="p.key"
        type="button"
        @click="setPreset(p.key)"
        class="rounded-card border border-border-default px-2 py-1 text-xs text-ink-muted hover:bg-surface-3"
      >
        {{ p.label }}
      </button>
    </div>
  </div>
</template>

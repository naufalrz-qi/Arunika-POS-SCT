<script setup>
const props = defineProps({
  from: { type: String, default: "" },
  to: { type: String, default: "" },
  // Disisipkan ke label kedua kolom ("Dari Tanggal" / "Sampai Jth. Tempo").
  // Kolom tanggal tak punya baris judul sendiri — kalau ada, isian tanggal
  // turun satu baris dan tak lagi sejajar dengan filter di sebelahnya.
  label: { type: String, default: "Tanggal" },
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
        <span class="mb-1.5 block text-[11px] font-heading font-semibold tracking-wide text-ink-muted">Dari {{ label }}</span>
        <input
          type="date"
          :value="from"
          @input="emit('update:from', $event.target.value)"
          class="h-10 w-full rounded border border-border-strong bg-surface/50 px-3 text-sm text-ink transition-all duration-200 hover:border-brand-400 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:outline-none"
        />
      </label>
      <label class="block">
        <span class="mb-1.5 block text-[11px] font-heading font-semibold tracking-wide text-ink-muted">Sampai {{ label }}</span>
        <input
          type="date"
          :value="to"
          @input="emit('update:to', $event.target.value)"
          class="h-10 w-full rounded border border-border-strong bg-surface/50 px-3 text-sm text-ink transition-all duration-200 hover:border-brand-400 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:outline-none"
        />
      </label>
    </div>
    <!-- `leading`: tempat pemanggil menitipkan kontrol sebaris dengan pintasan
         preset (DateModeField menaruh pemilih Rentang/Tanggal Tertentu di sini)
         alih-alih menumpuk baris sendiri di atas kolom tanggal — baris ekstra
         di atas membuat kolom tanggal turun sendirian dan tak lagi sejajar
         dengan Divisi/Cari di sebelahnya. -->
    <div class="flex flex-wrap items-center gap-1.5">
      <slot name="leading" />
      <span v-if="$slots.leading" class="mx-0.5 h-4 w-px bg-border-default" aria-hidden="true"></span>
      <button
        v-for="p in presets"
        :key="p.key"
        type="button"
        @click="setPreset(p.key)"
        class="rounded-full border border-border-default px-2.5 py-0.5 text-[11px] text-ink-muted transition-colors hover:border-brand-400 hover:text-brand-fg"
      >
        {{ p.label }}
      </button>
    </div>
  </div>
</template>

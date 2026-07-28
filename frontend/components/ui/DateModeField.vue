<script setup>
import DateRangeField from "@/components/ui/DateRangeField.vue";
import DateModeToggle from "@/components/ui/DateModeToggle.vue";

defineProps({
  mode: { type: String, default: "range" }, // "range" | "exact"
  from: { type: String, default: "" },
  to: { type: String, default: "" },
  date: { type: String, default: "" },
  // Diteruskan ke label kolom: "Tanggal" jadi "Dari Tanggal"/"Sampai Tanggal",
  // filter kolom seperti "Jth. Tempo" jadi "Dari Jth. Tempo"/"Sampai Jth. Tempo".
  label: { type: String, default: "Tanggal" },
});
const emit = defineEmits(["update:mode", "update:from", "update:to", "update:date"]);
</script>

<template>
  <!-- Pemilih mode dulu duduk di baris sendiri DI ATAS kolom tanggal. Baris itu
       mendorong seluruh isi sel ~26px ke bawah, jadi label + kotak isian tanggal
       tak pernah sejajar dengan Divisi/Cari di sel sebelahnya — padahal ketiganya
       satu baris grid. Sekarang barisan teratas sel ini adalah label kolom, sama
       seperti tetangganya, dan pemilih mode ikut baris pintasan preset di bawah. -->
  <div class="space-y-2">
    <DateRangeField
      v-if="mode === 'range'"
      :label="label"
      :from="from"
      :to="to"
      @update:from="emit('update:from', $event)"
      @update:to="emit('update:to', $event)"
    >
      <template #leading>
        <DateModeToggle :mode="mode" @update:mode="emit('update:mode', $event)" />
      </template>
    </DateRangeField>

    <template v-else>
      <label class="block">
        <span class="mb-1.5 block text-[11px] font-heading font-semibold tracking-wide text-ink-muted">
          {{ label }}
        </span>
        <input
          type="date"
          :value="date"
          @input="emit('update:date', $event.target.value)"
          class="h-10 w-full rounded border border-border-strong bg-surface/50 px-3 text-sm text-ink transition-all duration-200 hover:border-brand-400 focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:outline-none"
        />
      </label>
      <div class="flex flex-wrap items-center gap-1.5">
        <DateModeToggle :mode="mode" @update:mode="emit('update:mode', $event)" />
      </div>
    </template>
  </div>
</template>
